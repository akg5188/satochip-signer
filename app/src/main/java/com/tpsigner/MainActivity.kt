package com.smartcard.signer

import android.app.Activity
import android.content.Intent
import android.nfc.NfcAdapter
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import org.satochip.io.CardChannel
import org.satochip.io.CardListener

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    private lateinit var nfcCardManager: NfcCardManager
    private var nfcCardManagerStarted = false
    private lateinit var usbCardManager: UsbCcidCardManager
    private var nfcAdapter: NfcAdapter? = null

    private val qrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(ContinuousQrScanActivity.EXTRA_QR_RESULT)
            ?: return@registerForActivityResult
        when (viewModel.onScanResult(text)) {
            ScanHandleResult.Done -> Unit
            ScanHandleResult.NeedMoreFragments -> {
                window.decorView.postDelayed(
                    {
                        if (!isFinishing && !isDestroyed) {
                            startScan()
                        }
                    },
                    120L
                )
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val sharedListener = object : CardListener {
            override fun onConnected(channel: CardChannel) {
                viewModel.onCardConnected(channel)
            }

            override fun onDisconnected() {
                // No-op
            }
        }

        nfcCardManager = NfcCardManager().apply {
            setCardListener(sharedListener)
        }
        usbCardManager = UsbCcidCardManager(
            context = applicationContext,
            onError = viewModel::onRuntimeError
        ).apply {
            setCardListener(sharedListener)
        }

        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        setContent {
            val state by viewModel.uiState.collectAsStateWithLifecycle()

            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    SignerScreen(
                        state = state,
                        onWalletChanged = viewModel::onWalletChanged,
                        onInputChanged = viewModel::onInputChanged,
                        onPinChanged = viewModel::onPinChanged,
                        onPathChanged = viewModel::onPathChanged,
                        onParse = viewModel::parseCurrentPayload,
                        onScan = ::startScan,
                        onOpenTp = ::openTp,
                        onPrevRelay = viewModel::showPreviousRelayPage,
                        onNextRelay = viewModel::showNextRelayPage,
                        onConfirmReview = viewModel::confirmReview,
                        onArmUnlock = ::armUnlock,
                        onArmSign = ::armSign,
                        onCancel = viewModel::cancelPendingAction
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (!nfcCardManagerStarted) {
            runCatching {
                nfcCardManager.start()
                nfcCardManagerStarted = true
            }.onFailure { error ->
                viewModel.onRuntimeError("启动读卡线程失败: ${error.message ?: error.javaClass.simpleName}")
            }
        }
        if (nfcAdapter != null) {
            runCatching {
                nfcAdapter?.enableReaderMode(
                    this,
                    nfcCardManager,
                    NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B,
                    null
                )
            }.onFailure { error ->
                viewModel.onRuntimeError("启用 NFC 失败，请确认手机已打开 NFC: ${error.message ?: error.javaClass.simpleName}")
            }
        }
        runCatching {
            usbCardManager.startManager()
            usbCardManager.probeNow(forceOpenAttempt = true)
        }.onFailure { error ->
            viewModel.onRuntimeError("启动 USB 读卡器失败: ${error.message ?: error.javaClass.simpleName}")
        }
    }

    override fun onPause() {
        runCatching { nfcAdapter?.disableReaderMode(this) }
        super.onPause()
    }

    override fun onDestroy() {
        if (this::nfcCardManager.isInitialized && nfcCardManagerStarted) {
            nfcCardManager.interrupt()
        }
        if (this::usbCardManager.isInitialized) {
            usbCardManager.stopManager()
        }
        super.onDestroy()
    }

    private fun startScan() {
        val intent = Intent(this, ContinuousQrScanActivity::class.java)
            .putExtra(ContinuousQrScanActivity.EXTRA_SCAN_WALLET, viewModel.uiState.value.selectedWallet.name)
        qrLauncher.launch(intent)
    }

    private fun openTp() {
        val payload = viewModel.uiState.value.responsePayload.trim()
        if (payload.isBlank()) {
            viewModel.onRuntimeError("还没有树莓派签名结果")
            return
        }
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(payload)))
        }.onFailure { error ->
            viewModel.onRuntimeError("未能打开 TP: ${error.message ?: error.javaClass.simpleName}")
        }
    }

    private fun armUnlock() {
        viewModel.armUnlock()
        if (this::nfcCardManager.isInitialized) {
            nfcCardManager.withConnectedChannel { channel ->
                viewModel.onCardConnected(channel)
            }
        }
        if (this::usbCardManager.isInitialized) {
            usbCardManager.withConnectedChannel { channel ->
                viewModel.onCardConnected(channel)
            }
        }
    }

    private fun armSign() {
        viewModel.armSigning()
        if (this::nfcCardManager.isInitialized) {
            nfcCardManager.withConnectedChannel { channel ->
                viewModel.onCardConnected(channel)
            }
        }
        if (this::usbCardManager.isInitialized) {
            usbCardManager.withConnectedChannel { channel ->
                viewModel.onCardConnected(channel)
            }
        }
    }
}

@Composable
private fun SignerScreen(
    state: MainUiState,
    onWalletChanged: (RelayWallet) -> Unit,
    onInputChanged: (String) -> Unit,
    onPinChanged: (String) -> Unit,
    onPathChanged: (String) -> Unit,
    onParse: () -> Unit,
    onScan: () -> Unit,
    onOpenTp: () -> Unit,
    onPrevRelay: () -> Unit,
    onNextRelay: () -> Unit,
    onConfirmReview: () -> Unit,
    onArmUnlock: () -> Unit,
    onArmSign: () -> Unit,
    onCancel: () -> Unit
) {
    val busy = state.waitingForUnlockCard || state.unlockInProgress || state.waitingForSignCard || state.signingInProgress

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF3F6F9))
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("智能卡", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("离线冷签：应用不申请 INTERNET 权限", color = Color(0xFF0F5132))
        Text("可扫 TP/OKX/Bitget 高密度码，转成静态二维码给树莓派慢慢扫", color = Color(0xFF4A5568))
        Text("支持 NFC 贴卡 或 USB-OTG 读卡器（ACR39U）签名", color = Color(0xFF4A5568))
        Text("助记词导入请在离线 Tails 电脑完成，手机仅做扫码中转/签名", color = Color(0xFF4A5568))

        Text("中转来源", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RelayWallet.values().forEach { wallet ->
                Button(
                    onClick = { onWalletChanged(wallet) },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (state.selectedWallet == wallet) Color(0xFF1565C0) else Color(0xFF64748B)
                    ),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
                ) {
                    Text(wallet.shortName)
                }
            }
        }

        OutlinedTextField(
            value = state.derivationPath,
            onValueChange = onPathChanged,
            label = { Text("BIP32 路径") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )

        OutlinedTextField(
            value = state.pin,
            onValueChange = onPinChanged,
            label = { Text("卡 PIN") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            visualTransformation = PasswordVisualTransformation()
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = onArmUnlock,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1565C0))
            ) {
                Text("解锁")
            }
            if (busy) {
                TextButton(onClick = onCancel) { Text("取消") }
            }
        }

        if (state.unlockedAddress.isNotBlank()) {
            InfoCard("当前钱包地址", state.unlockedAddress)
        }

        OutlinedTextField(
            value = state.inputPayload,
            onValueChange = onInputChanged,
            label = {
                Text(
                    when (state.selectedWallet) {
                        RelayWallet.TOKENPOCKET -> "TP 请求字符串"
                        RelayWallet.OKX -> "OKX/Keystone 二维码内容"
                        RelayWallet.BITGET -> "Bitget/Keystone 二维码内容"
                    }
                )
            },
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onScan) { Text("扫码") }
            Button(onClick = onParse) { Text("解析") }
            Button(
                onClick = onArmSign,
                enabled = state.selectedWallet == RelayWallet.TOKENPOCKET && state.isUnlocked && (!state.reviewRequired || state.reviewConfirmed),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1E8C5C))
            ) {
                Text("贴卡/插卡签名")
            }
        }

        if (state.fragmentMessage.isNotBlank()) {
            StatusTag(state.fragmentMessage, Color(0xFFE6FFFA), Color(0xFF0C4A6E))
        }

        if (state.parseMessage.isNotBlank()) {
            StatusTag(state.parseMessage, Color(0xFFDCFCE7), Color(0xFF14532D))
        }

        if (state.errorMessage.isNotBlank()) {
            StatusTag(state.errorMessage, Color(0xFFFEE2E2), Color(0xFF991B1B))
        }

        if (state.parsedSummary.isNotBlank()) {
            InfoCard("请求摘要", state.parsedSummary)
        }
        if (state.transferInfo.isNotBlank()) {
            InfoCard("转账/合约信息", state.transferInfo)
        }
        if (state.dappInfo.isNotBlank()) {
            InfoCard("DApp 信息", state.dappInfo)
        }
        if (state.relayHint.isNotBlank()) {
            StatusTag(state.relayHint, Color(0xFFE8F1FF), Color(0xFF1D4ED8))
        }

        val relayQr = state.relayQr
        if (relayQr != null) {
            if (state.relayPayloadPages.size > 1) {
                LaunchedEffect(state.relayPageIndex, state.relayPayloadPages.size) {
                    delay(1000)
                    onNextRelay()
                }
            }
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    if (state.selectedWallet == RelayWallet.TOKENPOCKET) "树莓派静态中转二维码" else "${state.selectedWallet.shortName} 树莓派中转二维码",
                    style = MaterialTheme.typography.titleMedium
                )
                if (state.relayPayloadPages.size > 1) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        TextButton(
                            onClick = onPrevRelay,
                            enabled = true
                        ) { Text("上一张") }
                        Text("第 ${state.relayPageIndex + 1}/${state.relayPayloadPages.size} 张")
                        TextButton(
                            onClick = onNextRelay,
                            enabled = true
                        ) { Text("下一张") }
                    }
                }
                Image(
                    bitmap = relayQr.asImageBitmap(),
                    contentDescription = "relay qr",
                    modifier = Modifier
                        .fillMaxWidth(0.92f)
                        .aspectRatio(1f)
                )
            }
        }

        if (state.reviewRequired) {
            Button(
                onClick = onConfirmReview,
                enabled = !state.reviewConfirmed,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF3D7B59))
            ) {
                Text(if (state.reviewConfirmed) "已核对" else "已核对，允许签名")
            }
        }

        if (state.signerAddress.isNotBlank()) {
            InfoCard("签名地址", state.signerAddress)
            if (state.digestHex.isNotBlank()) {
                InfoCard(state.digestLabel, state.digestHex)
            }
            if (state.signedResult.isNotBlank()) {
                InfoCard(state.resultLabel, state.signedResult)
            }
            InfoCard("回传字符串", state.responsePayload)
        }

        if (state.responsePayload.isNotBlank()) {
            Button(
                onClick = onOpenTp,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF3D7B59))
            ) {
                Text("打开 TP")
            }
        }

        val qr = state.responseQr
        if (qr != null) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("回扫二维码", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Image(
                    bitmap = qr.asImageBitmap(),
                    contentDescription = "response qr",
                    modifier = Modifier.size(300.dp)
                )
            }
        }

        Spacer(modifier = Modifier.height(24.dp))
    }
}

@Composable
private fun StatusTag(text: String, bg: Color, fg: Color) {
    Text(
        text = text,
        color = fg,
        modifier = Modifier
            .fillMaxWidth()
            .background(bg, RoundedCornerShape(10.dp))
            .padding(10.dp)
    )
}

@Composable
private fun InfoCard(title: String, content: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.White, RoundedCornerShape(12.dp))
            .padding(PaddingValues(12.dp)),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Text(title, fontWeight = FontWeight.SemiBold)
        SelectionContainer {
            Text(content, color = Color(0xFF1F2937))
        }
    }
}
