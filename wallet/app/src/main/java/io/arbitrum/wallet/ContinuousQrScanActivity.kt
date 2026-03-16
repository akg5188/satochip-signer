package io.arbitrum.wallet

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import android.view.KeyEvent
import android.view.View
import android.widget.Button
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.zxing.BarcodeFormat
import com.google.zxing.DecodeHintType
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory
import com.journeyapps.barcodescanner.camera.CameraSettings
import com.journeyapps.barcodescanner.camera.CenterCropStrategy
import kotlinx.coroutines.launch

class ContinuousQrScanActivity : ComponentActivity() {
    companion object {
        const val EXTRA_QR_RESULT = "qr_result"
        const val EXTRA_SCAN_MODE = "scan_mode"
        const val MODE_REQUEST = "request"
        const val MODE_RESPONSE = "response"
    }

    private lateinit var barcodeView: DecoratedBarcodeView
    private lateinit var torchButton: Button
    private val assembler = MultiFragmentAssembler()
    private var hasReturned = false
    private var lastText = ""
    private var lastReadAt = 0L
    private var torchEnabled = false
    private val hasFlash by lazy {
        packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_FLASH)
    }

    private val galleryLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val decoded = QrImageDecoder.decodeFromUri(this@ContinuousQrScanActivity, uri)
            if (decoded.isNullOrBlank()) {
                barcodeView.setStatusText("相册图片未识别到二维码，请重试")
                Toast.makeText(this@ContinuousQrScanActivity, "相册图片未识别到二维码", Toast.LENGTH_SHORT).show()
                return@launch
            }
            if (scanMode == MODE_RESPONSE) {
                returnPayload(decoded)
            } else {
                handleRequestScanText(decoded)
            }
        }
    }

    private val scanMode: String
        get() = intent.getStringExtra(EXTRA_SCAN_MODE) ?: MODE_REQUEST

    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) startContinuousScan() else {
                setResult(Activity.RESULT_CANCELED)
                finish()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_qr_scan)

        barcodeView = findViewById(R.id.barcode_scanner)
        torchButton = findViewById(R.id.btn_toggle_torch)
        configureScanner()
        barcodeView.setTorchListener(object : DecoratedBarcodeView.TorchListener {
            override fun onTorchOn() {
                torchEnabled = true
                updateTorchButton()
            }

            override fun onTorchOff() {
                torchEnabled = false
                updateTorchButton()
            }
        })
        torchButton.setOnClickListener { toggleTorch() }
        torchButton.visibility = if (hasFlash) View.VISIBLE else View.GONE
        updateTorchButton()
        findViewById<Button>(R.id.btn_pick_qr_from_gallery).setOnClickListener {
            galleryLauncher.launch("image/*")
        }
        findViewById<Button>(R.id.btn_cancel_scan).setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startContinuousScan()
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onPause() {
        barcodeView.pause()
        super.onPause()
    }

    override fun onDestroy() {
        runCatching { barcodeView.pauseAndWait() }
        super.onDestroy()
    }

    private fun startContinuousScan() {
        barcodeView.decodeContinuous(scanCallback)
        barcodeView.resume()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> {
                if (hasFlash) {
                    setTorchEnabled(true)
                    true
                } else {
                    super.onKeyDown(keyCode, event)
                }
            }

            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                if (hasFlash) {
                    setTorchEnabled(false)
                    true
                } else {
                    super.onKeyDown(keyCode, event)
                }
            }

            else -> super.onKeyDown(keyCode, event)
        }
    }

    private val scanCallback = BarcodeCallback { scanResult ->
        if (hasReturned) return@BarcodeCallback
        val text = scanResult.text?.trim().orEmpty()
        if (text.isBlank()) return@BarcodeCallback

        val now = SystemClock.elapsedRealtime()
        if (text == lastText && now - lastReadAt < 600L) {
            return@BarcodeCallback
        }
        lastText = text
        lastReadAt = now

        if (scanMode == MODE_RESPONSE) {
            returnPayload(text)
        } else {
            handleRequestScanText(text)
        }
    }

    private fun handleRequestScanText(text: String) {
        WalletConnectUriParser.extract(text)?.let { wcUri ->
            returnPayload(wcUri)
            return
        }
        runCatching { TpQrCodec.parseInput(text) }
            .onSuccess { parsed ->
                when (parsed) {
                    is ParseResult.SignRequest -> returnPayload(text)
                    is ParseResult.Fragment -> {
                        when (val assembly = assembler.accept(parsed.fragment)) {
                            is AssemblyResult.Progress -> {
                                barcodeView.setStatusText("已接收分片 ${assembly.received}/${assembly.total}，请继续扫描")
                            }
                            is AssemblyResult.Complete -> returnPayload(assembly.payload)
                            is AssemblyResult.Error -> {
                                barcodeView.setStatusText("${assembly.reason}，请继续扫描")
                            }
                        }
                    }
                }
            }
            .onFailure { error ->
                val reason = error.message ?: "二维码解析失败"
                barcodeView.setStatusText("$reason，请继续扫描")
            }
    }

    private fun returnPayload(payload: String) {
        if (hasReturned) return
        hasReturned = true
        setResult(Activity.RESULT_OK, Intent().putExtra(EXTRA_QR_RESULT, payload))
        finish()
    }

    private fun configureScanner() {
        val hints = mapOf(
            DecodeHintType.TRY_HARDER to true,
            DecodeHintType.CHARACTER_SET to Charsets.UTF_8.name()
        )
        barcodeView.decoderFactory = DefaultDecoderFactory(
            listOf(BarcodeFormat.QR_CODE),
            hints,
            Charsets.UTF_8.name(),
            0
        )
        barcodeView.setCameraSettings(
            CameraSettings().apply {
                setAutoFocusEnabled(true)
                setContinuousFocusEnabled(true)
                setMeteringEnabled(true)
                setExposureEnabled(true)
                setBarcodeSceneModeEnabled(true)
                setAutoTorchEnabled(hasFlash)
            }
        )
        barcodeView.barcodeView.setPreviewScalingStrategy(CenterCropStrategy())
        barcodeView.barcodeView.setMarginFraction(0.08)
        barcodeView.setStatusText(
            if (scanMode == MODE_RESPONSE) getString(R.string.scan_status_response)
            else getString(R.string.scan_status_request)
        )
    }

    private fun toggleTorch() {
        setTorchEnabled(!torchEnabled)
    }

    private fun setTorchEnabled(enabled: Boolean) {
        if (!hasFlash || torchEnabled == enabled) return
        if (enabled) {
            barcodeView.setTorchOn()
        } else {
            barcodeView.setTorchOff()
        }
    }

    private fun updateTorchButton() {
        if (!::torchButton.isInitialized) return
        torchButton.text = getString(
            if (torchEnabled) R.string.scan_torch_off
            else R.string.scan_torch_on
        )
    }
}
