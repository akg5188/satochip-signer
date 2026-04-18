package com.smartcard.signer

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory

class ContinuousQrScanActivity : ComponentActivity() {
    companion object {
        const val EXTRA_QR_RESULT = "qr_result"
        const val EXTRA_SCAN_WALLET = "scan_wallet"
    }

    private lateinit var barcodeView: DecoratedBarcodeView
    private val assembler = MultiFragmentAssembler()
    private var hasReturned = false
    private var scanWallet = RelayWallet.TOKENPOCKET
    private var lastText = ""
    private var lastReadAt = 0L
    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startContinuousScan()
            } else {
                setResult(Activity.RESULT_CANCELED)
                finish()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_continuous_qr_scan)
        scanWallet = runCatching {
            RelayWallet.valueOf(intent.getStringExtra(EXTRA_SCAN_WALLET).orEmpty())
        }.getOrDefault(RelayWallet.TOKENPOCKET)

        barcodeView = findViewById(R.id.barcode_scanner)
        barcodeView.decoderFactory = DefaultDecoderFactory(listOf(BarcodeFormat.QR_CODE))
        barcodeView.setStatusText(
            if (scanWallet == RelayWallet.TOKENPOCKET) {
                "请连续扫描 TP 动态二维码"
            } else {
                "请扫描 ${scanWallet.displayName} 的 Keystone/硬件钱包二维码"
            }
        )
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

        handleScanText(text)
    }

    private fun handleScanText(text: String) {
        if (scanWallet != RelayWallet.TOKENPOCKET) {
            runCatching { Web3RelayCodec.parse(scanWallet, text) }
                .onSuccess { returnPayload(text) }
                .onFailure { error ->
                    val reason = error.message ?: "Web3 二维码解析失败"
                    barcodeView.setStatusText("$reason，请继续扫描")
                }
            return
        }

        runCatching { TpQrCodec.parseInput(text) }
            .onSuccess { parsed ->
                when (parsed) {
                    is ParseResult.SignRequest -> {
                        returnPayload(text)
                    }

                    is ParseResult.Fragment -> {
                        when (val assembly = assembler.accept(parsed.fragment)) {
                            is AssemblyResult.Progress -> {
                                barcodeView.setStatusText("已接收分片 ${assembly.received}/${assembly.total}，请继续扫描")
                            }

                            is AssemblyResult.Complete -> {
                                returnPayload(assembly.payload)
                            }

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
        val data = Intent().putExtra(EXTRA_QR_RESULT, payload)
        setResult(Activity.RESULT_OK, data)
        finish()
    }
}
