package io.arbitrum.wallet

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory
import kotlinx.coroutines.launch

class QrScanActivity : BiometricGateActivity() {
    companion object {
        const val EXTRA_QR_RESULT = "qr_result"
        const val EXTRA_STATUS_TEXT = "status_text"
    }

    private lateinit var barcodeView: DecoratedBarcodeView
    private lateinit var titleView: TextView
    private lateinit var statusView: TextView
    private var hasReturned = false
    private var lastText = ""
    private var lastReadAt = 0L

    private val galleryLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val decoded = QrImageDecoder.decodeFromUri(this@QrScanActivity, uri)
            if (decoded.isNullOrBlank()) {
                updateStatus("相册图片未识别到二维码，请重试")
                Toast.makeText(this@QrScanActivity, "相册图片未识别到二维码", Toast.LENGTH_SHORT).show()
                return@launch
            }
            returnResult(decoded)
        }
    }

    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) startScan() else {
                setResult(Activity.RESULT_CANCELED)
                finish()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_qr_scan)
        barcodeView = findViewById(R.id.barcode_scanner)
        titleView = findViewById(R.id.tv_scan_title)
        statusView = findViewById(R.id.tv_scan_status)
        barcodeView.decoderFactory = DefaultDecoderFactory(listOf(BarcodeFormat.QR_CODE))
        titleView.text = getString(R.string.scan_title_response)
        updateStatus(intent.getStringExtra(EXTRA_STATUS_TEXT) ?: getString(R.string.scan_status_response))
        findViewById<Button>(R.id.btn_pick_qr_from_gallery).setOnClickListener {
            galleryLauncher.launch("image/*")
        }
        findViewById<Button>(R.id.btn_toggle_torch).apply {
            isEnabled = false
            alpha = 0.45f
        }
        findViewById<Button>(R.id.btn_cancel_scan).setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startScan()
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onPause() {
        barcodeView.pause()
        super.onPause()
    }

    private fun startScan() {
        barcodeView.decodeContinuous { result ->
            if (hasReturned) return@decodeContinuous
            val text = result.text?.trim().orEmpty()
            if (text.isBlank()) return@decodeContinuous
            val now = SystemClock.elapsedRealtime()
            if (text == lastText && now - lastReadAt < 500L) return@decodeContinuous
            lastText = text
            lastReadAt = now
            returnResult(text)
        }
        barcodeView.resume()
    }

    private fun updateStatus(text: String) {
        statusView.text = text
        barcodeView.setStatusText("")
    }

    private fun returnResult(payload: String) {
        if (hasReturned) return
        hasReturned = true
        setResult(Activity.RESULT_OK, Intent().putExtra(EXTRA_QR_RESULT, payload))
        finish()
    }
}
