package io.arbitrum.wallet

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private enum class GalleryImportTarget {
        REQUEST,
        RESPONSE,
    }

    private val viewModel: MainViewModel by viewModels()
    private var galleryImportTarget = GalleryImportTarget.REQUEST

    private val requestQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(ContinuousQrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.onRequestScanResult(text)
    }

    private val responseQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(QrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.onResponseScanResult(text)
    }

    private val galleryQrLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val payload = QrImageDecoder.decodeFromUri(this@MainActivity, uri)
            if (payload.isNullOrBlank()) {
                Toast.makeText(this@MainActivity, "相册图片未识别到二维码", Toast.LENGTH_SHORT).show()
                return@launch
            }
            when (galleryImportTarget) {
                GalleryImportTarget.REQUEST -> viewModel.onRequestScanResult(payload)
                GalleryImportTarget.RESPONSE -> viewModel.onResponseScanResult(payload)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val state by viewModel.uiState.collectAsStateWithLifecycle()
            MaterialTheme {
                WalletScreen(
                    state = state,
                    onSelectTab = viewModel::setActiveTab,
                    onNewAddressChange = viewModel::setNewAddressInput,
                    onAddAddress = viewModel::addAddressFromInput,
                    onSelectAddress = viewModel::selectAddress,
                    onRemoveAddress = viewModel::removeAddress,
                    onRefreshBalances = { viewModel.loadBalances() },
                    onTransferToChange = viewModel::setTransferTo,
                    onTransferAmountChange = viewModel::setTransferAmount,
                    onTransferTokenChange = viewModel::setTransferToken,
                    onPrepareTransferEth = viewModel::prepareTransferEth,
                    onPrepareTransferToken = viewModel::prepareTransferToken,
                    onRequestInputChange = viewModel::setRequestInput,
                    onImportRawRequest = viewModel::importRawRequest,
                    onImportRequestFromClipboard = ::importRequestFromClipboard,
                    onPersonalMessageChange = viewModel::setPersonalMessageInput,
                    onPreparePersonalSign = viewModel::preparePersonalSign,
                    onTypedDataChange = viewModel::setTypedDataInput,
                    onPrepareTypedDataSign = viewModel::prepareTypedDataSign,
                    onApproveWalletConnectProposal = viewModel::approveWalletConnectProposal,
                    onRejectWalletConnectProposal = viewModel::rejectWalletConnectProposal,
                    onPrevRelayPage = viewModel::prevSignQrPage,
                    onNextRelayPage = viewModel::nextSignQrPage,
                    onAutoAdvanceRelayPage = viewModel::nextSignQrPage,
                    onScanRequest = ::startRequestScan,
                    onPickRequestFromGallery = ::startRequestGalleryImport,
                    onScanResponse = ::startResponseScan,
                    onPickResponseFromGallery = ::startResponseGalleryImport,
                    onClearPreparedRequest = viewModel::clearPreparedRequest,
                    onClearError = viewModel::clearError,
                    onClearInfo = viewModel::clearInfo,
                    onClearTxHash = viewModel::clearTxHash,
                    onClearSignature = viewModel::clearSignature,
                )
            }
        }
    }

    private fun startRequestScan() {
        val intent = Intent(this, ContinuousQrScanActivity::class.java)
            .putExtra(ContinuousQrScanActivity.EXTRA_SCAN_MODE, ContinuousQrScanActivity.MODE_REQUEST)
        requestQrLauncher.launch(intent)
    }

    private fun startResponseScan() {
        val intent = Intent(this, QrScanActivity::class.java)
            .putExtra(QrScanActivity.EXTRA_STATUS_TEXT, "请扫描树莓派签名结果二维码")
        responseQrLauncher.launch(intent)
    }

    private fun startRequestGalleryImport() {
        galleryImportTarget = GalleryImportTarget.REQUEST
        galleryQrLauncher.launch("image/*")
    }

    private fun startResponseGalleryImport() {
        galleryImportTarget = GalleryImportTarget.RESPONSE
        galleryQrLauncher.launch("image/*")
    }

    private fun importRequestFromClipboard() {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val text = clipboard.primaryClip?.getItemAt(0)?.coerceToText(this)?.toString()?.trim().orEmpty()
        if (text.isBlank()) {
            Toast.makeText(this, "剪贴板没有可用链接", Toast.LENGTH_SHORT).show()
            return
        }
        viewModel.onRequestScanResult(text)
    }
}

@Composable
private fun WalletScreen(
    state: WalletUiState,
    onSelectTab: (WalletTab) -> Unit,
    onNewAddressChange: (String) -> Unit,
    onAddAddress: () -> Unit,
    onSelectAddress: (String) -> Unit,
    onRemoveAddress: (String) -> Unit,
    onRefreshBalances: () -> Unit,
    onTransferToChange: (String) -> Unit,
    onTransferAmountChange: (String) -> Unit,
    onTransferTokenChange: (String) -> Unit,
    onPrepareTransferEth: () -> Unit,
    onPrepareTransferToken: () -> Unit,
    onRequestInputChange: (String) -> Unit,
    onImportRawRequest: () -> Unit,
    onImportRequestFromClipboard: () -> Unit,
    onPersonalMessageChange: (String) -> Unit,
    onPreparePersonalSign: () -> Unit,
    onTypedDataChange: (String) -> Unit,
    onPrepareTypedDataSign: () -> Unit,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
    onPrevRelayPage: () -> Unit,
    onNextRelayPage: () -> Unit,
    onAutoAdvanceRelayPage: () -> Unit,
    onScanRequest: () -> Unit,
    onPickRequestFromGallery: () -> Unit,
    onScanResponse: () -> Unit,
    onPickResponseFromGallery: () -> Unit,
    onClearPreparedRequest: () -> Unit,
    onClearError: () -> Unit,
    onClearInfo: () -> Unit,
    onClearTxHash: () -> Unit,
    onClearSignature: () -> Unit,
) {
    val context = LocalContext.current

    if (state.signQrPages.size > 1 && state.signQrBitmap != null) {
        LaunchedEffect(state.signQrPages) {
            while (true) {
                delay(1000)
                onAutoAdvanceRelayPage()
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF6F7FB))
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Arbitrum One 观察钱包", fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Text(
            "当前版先走二维码中转：转账可直接广播，消息/TypedData 可交给树莓派签名。",
            color = Color(0xFF667085),
            fontSize = 12.sp,
        )

        TabRow(selectedTabIndex = if (state.activeTab == WalletTab.ASSETS) 0 else 1) {
            Tab(selected = state.activeTab == WalletTab.ASSETS, onClick = { onSelectTab(WalletTab.ASSETS) }, text = { Text("资产") })
            Tab(selected = state.activeTab == WalletTab.SIGN, onClick = { onSelectTab(WalletTab.SIGN) }, text = { Text("签名") })
        }

        if (state.error.isNotBlank()) {
            MessageCard(
                title = "错误",
                message = state.error,
                background = Color(0xFFFFEBEE),
                onDismiss = onClearError,
            )
        }
        if (state.info.isNotBlank()) {
            MessageCard(
                title = "提示",
                message = state.info,
                background = Color(0xFFE8F5E9),
                onDismiss = onClearInfo,
            )
        }

        if (state.signQrBitmap != null) {
            PreparedRequestSection(
                state = state,
                onPrevRelayPage = onPrevRelayPage,
                onNextRelayPage = onNextRelayPage,
                onScanResponse = onScanResponse,
                onPickResponseFromGallery = onPickResponseFromGallery,
                onClearPreparedRequest = onClearPreparedRequest,
            )
        }

        AddressSection(
            state = state,
            onNewAddressChange = onNewAddressChange,
            onAddAddress = onAddAddress,
            onSelectAddress = onSelectAddress,
            onRemoveAddress = onRemoveAddress,
            onRefreshBalances = onRefreshBalances,
        )

        if (state.activeTab == WalletTab.ASSETS) {
            BalancesSection(state)
            TransferSection(
                state = state,
                onTransferToChange = onTransferToChange,
                onTransferAmountChange = onTransferAmountChange,
                onTransferTokenChange = onTransferTokenChange,
                onPrepareTransferEth = onPrepareTransferEth,
                onPrepareTransferToken = onPrepareTransferToken,
            )
        } else {
            SignSection(
                state = state,
                onRequestInputChange = onRequestInputChange,
                onImportRawRequest = onImportRawRequest,
                onImportRequestFromClipboard = onImportRequestFromClipboard,
                onPersonalMessageChange = onPersonalMessageChange,
                onPreparePersonalSign = onPreparePersonalSign,
                onTypedDataChange = onTypedDataChange,
                onPrepareTypedDataSign = onPrepareTypedDataSign,
                onScanRequest = onScanRequest,
                onPickRequestFromGallery = onPickRequestFromGallery,
                onApproveWalletConnectProposal = onApproveWalletConnectProposal,
                onRejectWalletConnectProposal = onRejectWalletConnectProposal,
            )
        }

        if (state.txHash.isNotBlank()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("交易已广播", fontWeight = FontWeight.Bold, color = Color(0xFF2E7D32))
                    SelectionContainer {
                        Text("${ArbitrumConfig.EXPLORER}/tx/0x${state.txHash}", fontSize = 12.sp)
                    }
                    TextButton(onClick = onClearTxHash) { Text("关闭") }
                }
            }
        }

        if (state.lastSignature.isNotBlank()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("签名结果", fontWeight = FontWeight.Bold)
                    if (state.lastSignatureAddress.isNotBlank()) {
                        Text("地址: ${state.lastSignatureAddress}", fontSize = 12.sp, color = Color(0xFF667085))
                    }
                    SelectionContainer {
                        Text(state.lastSignature, fontSize = 12.sp)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("signature", state.lastSignature))
                        }) {
                            Text("复制签名")
                        }
                        TextButton(onClick = onClearSignature) { Text("关闭") }
                    }
                }
            }
        }
    }
}

@Composable
private fun AddressSection(
    state: WalletUiState,
    onNewAddressChange: (String) -> Unit,
    onAddAddress: () -> Unit,
    onSelectAddress: (String) -> Unit,
    onRemoveAddress: (String) -> Unit,
    onRefreshBalances: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("观察地址", fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = state.newAddressInput,
                onValueChange = onNewAddressChange,
                label = { Text("添加地址 (0x...)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onAddAddress) { Text("添加") }
                if (state.selectedAddress.isNotBlank()) {
                    TextButton(onClick = onRefreshBalances) { Text(if (state.loading) "刷新中..." else "刷新余额") }
                }
            }
            state.addresses.forEach { address ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                address,
                                fontSize = 12.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                fontWeight = if (state.selectedAddress == address) FontWeight.Bold else FontWeight.Normal,
                            )
                            if (state.selectedAddress == address) {
                                Text("当前地址", color = Color(0xFF2E7D32), fontSize = 11.sp)
                            }
                        }
                        Row {
                            TextButton(onClick = { onSelectAddress(address) }) { Text("选择") }
                            TextButton(onClick = { onRemoveAddress(address) }) { Text("删除") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun BalancesSection(state: WalletUiState) {
    if (state.selectedAddress.isBlank()) return
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Arbitrum One 余额", fontWeight = FontWeight.Bold)
            if (state.loading) {
                Text("加载中...")
            } else {
                state.balances.forEach { (symbol, balance) ->
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(symbol, fontWeight = FontWeight.Medium)
                        Text(balance)
                    }
                }
            }
        }
    }
}

@Composable
private fun TransferSection(
    state: WalletUiState,
    onTransferToChange: (String) -> Unit,
    onTransferAmountChange: (String) -> Unit,
    onTransferTokenChange: (String) -> Unit,
    onPrepareTransferEth: () -> Unit,
    onPrepareTransferToken: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("转账", fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = state.transferTo,
                onValueChange = onTransferToChange,
                label = { Text("接收地址") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = state.transferAmount,
                onValueChange = onTransferAmountChange,
                label = { Text("数量") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf("USDC", "USDT").forEach { token ->
                    TextButton(onClick = { onTransferTokenChange(token) }) {
                        Text(if (state.transferToken == token) "[$token]" else token)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPrepareTransferEth) { Text("转 ETH") }
                Button(onClick = onPrepareTransferToken) { Text("转 ${state.transferToken}") }
            }
        }
    }
}

@Composable
private fun SignSection(
    state: WalletUiState,
    onRequestInputChange: (String) -> Unit,
    onImportRawRequest: () -> Unit,
    onImportRequestFromClipboard: () -> Unit,
    onPersonalMessageChange: (String) -> Unit,
    onPreparePersonalSign: () -> Unit,
    onTypedDataChange: (String) -> Unit,
    onPrepareTypedDataSign: () -> Unit,
    onScanRequest: () -> Unit,
    onPickRequestFromGallery: () -> Unit,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("DApp / 消息签名", fontWeight = FontWeight.Bold)
            Text("支持两条线：直接扫码 WalletConnect 配对码，或手动粘贴 / 扫码离线签名请求。", color = Color(0xFF667085), fontSize = 12.sp)

            WalletConnectSection(
                state = state,
                onApproveWalletConnectProposal = onApproveWalletConnectProposal,
                onRejectWalletConnectProposal = onRejectWalletConnectProposal,
            )

            OutlinedTextField(
                value = state.requestInput,
                onValueChange = onRequestInputChange,
                label = { Text("粘贴 WalletConnect / DApp 原始请求") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 4,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onImportRawRequest, modifier = Modifier.weight(1f)) { Text("解析原始请求") }
                Button(onClick = onScanRequest, modifier = Modifier.weight(1f)) { Text("扫码请求 / 配对二维码") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onPickRequestFromGallery, modifier = Modifier.weight(1f)) { Text("相册导入二维码") }
                Button(onClick = onImportRequestFromClipboard, modifier = Modifier.weight(1f)) { Text("剪贴板导入链接") }
            }

            OutlinedTextField(
                value = state.personalMessageInput,
                onValueChange = onPersonalMessageChange,
                label = { Text("personal_sign 消息") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
            )
            Button(onClick = onPreparePersonalSign) { Text("生成消息签名请求") }

            OutlinedTextField(
                value = state.typedDataInput,
                onValueChange = onTypedDataChange,
                label = { Text("signTypedDataV4 JSON") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 6,
            )
            Button(onClick = onPrepareTypedDataSign) { Text("生成 TypedData 签名请求") }
        }
    }
}

@Composable
private fun WalletConnectSection(
    state: WalletUiState,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF8FAFC)),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("WalletConnect", fontWeight = FontWeight.Medium)
            Text(
                state.walletConnectStatus.ifBlank { "尚未建立 WalletConnect 会话" },
                fontSize = 12.sp,
                color = Color(0xFF475467),
            )
            state.walletConnectProposal?.let { proposal ->
                SectionLabel("待批准会话")
                Text("DApp: ${proposal.peerName.ifBlank { "-" }}", fontSize = 12.sp)
                if (proposal.peerUrl.isNotBlank()) {
                    Text("URL: ${proposal.peerUrl}", fontSize = 12.sp)
                }
                if (proposal.requiredChains.isNotEmpty()) {
                    Text("链: ${proposal.requiredChains.joinToString()}", fontSize = 12.sp)
                }
                if (proposal.requiredMethods.isNotEmpty()) {
                    Text("方法: ${proposal.requiredMethods.joinToString()}", fontSize = 12.sp)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onApproveWalletConnectProposal) { Text("批准连接") }
                    TextButton(onClick = onRejectWalletConnectProposal) { Text("拒绝") }
                }
            }
            state.walletConnectPendingRequest?.let { request ->
                SectionLabel("当前请求")
                Text("DApp: ${request.peerName.ifBlank { "-" }}", fontSize = 12.sp)
                Text("方法: ${request.method}", fontSize = 12.sp)
                request.chainId?.takeIf { it.isNotBlank() }?.let {
                    Text("链: $it", fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun PreparedRequestSection(
    state: WalletUiState,
    onPrevRelayPage: () -> Unit,
    onNextRelayPage: () -> Unit,
    onScanResponse: () -> Unit,
    onPickResponseFromGallery: () -> Unit,
    onClearPreparedRequest: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(state.requestTitle.ifBlank { "树莓派签名请求" }, fontWeight = FontWeight.Bold)
            if (state.requestSummary.isNotBlank()) {
                SelectionContainer {
                    Text(state.requestSummary, modifier = Modifier.fillMaxWidth(), fontSize = 12.sp)
                }
            }
            if (state.transferInfo.isNotBlank()) {
                SectionLabel("转账信息")
                SelectionContainer {
                    Text(state.transferInfo, modifier = Modifier.fillMaxWidth(), fontSize = 12.sp)
                }
            }
            if (state.dappInfo.isNotBlank()) {
                SectionLabel("DApp 信息")
                SelectionContainer {
                    Text(state.dappInfo, modifier = Modifier.fillMaxWidth(), fontSize = 12.sp)
                }
            }
            if (state.relayHint.isNotBlank()) {
                Text(state.relayHint, fontSize = 12.sp, color = Color(0xFF667085))
            }
            if (state.signQrPages.size > 1) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = onPrevRelayPage) { Text("上一张") }
                    Text("${state.signQrPageIndex + 1}/${state.signQrPages.size}")
                    TextButton(onClick = onNextRelayPage) { Text("下一张") }
                }
            }
            RelayQrFrame(
                bitmap = state.signQrBitmap!!,
                pageIndex = state.signQrPageIndex,
                pageCount = state.signQrPages.size,
                qrSize = if (state.signQrPages.size > 1) 344.dp else 352.dp,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onScanResponse, modifier = Modifier.weight(1f)) { Text("扫码树莓派结果") }
                Button(onClick = onPickResponseFromGallery, modifier = Modifier.weight(1f)) { Text("相册导入结果") }
            }
            TextButton(onClick = onClearPreparedRequest) { Text("取消") }
        }
    }
}

@Composable
private fun MessageCard(title: String, message: String, background: Color, onDismiss: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(background)
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(message, fontSize = 12.sp)
            TextButton(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) { Text("关闭") }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text, modifier = Modifier.fillMaxWidth(), fontWeight = FontWeight.Medium)
}

@Composable
private fun RelayQrFrame(bitmap: Bitmap, pageIndex: Int, pageCount: Int, qrSize: Dp) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF0F172A)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (pageCount > 1) {
                Surface(
                    color = Color(0xFF1D4ED8),
                    shape = RectangleShape,
                ) {
                    Text(
                        text = "动态中转 ${pageIndex + 1}/$pageCount · 1 秒轮播",
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        color = Color.White,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            Box(
                modifier = Modifier
                    .background(Color.White)
                    .border(2.dp, Color(0xFFE5E7EB))
                    .padding(12.dp),
            ) {
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "relay qr",
                    modifier = Modifier.size(qrSize),
                )
            }
        }
    }
}
