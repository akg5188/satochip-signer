package io.arbitrum.wallet

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.zxing.EncodeHintType
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import com.journeyapps.barcodescanner.BarcodeEncoder
import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.json.JSONArray

private val typedDataJson = Json { ignoreUnknownKeys = true; isLenient = true }

enum class WalletTab {
    ASSETS,
    SIGN
}

enum class PendingResponseType {
    BROADCAST_TX,
    SHOW_SIGNATURE
}

data class WalletUiState(
    val activeTab: WalletTab = WalletTab.ASSETS,
    val newAddressInput: String = "",
    val addresses: List<String> = emptyList(),
    val selectedAddress: String = "",
    val balances: Map<String, String> = emptyMap(),
    val loading: Boolean = false,
    val error: String = "",
    val info: String = "",
    val transferTo: String = "",
    val transferAmount: String = "",
    val transferToken: String = "USDC",
    val requestInput: String = "",
    val personalMessageInput: String = "",
    val typedDataInput: String = "",
    val requestTitle: String = "",
    val requestSummary: String = "",
    val transferInfo: String = "",
    val dappInfo: String = "",
    val relayHint: String = "",
    val walletConnectStatus: String = "",
    val walletConnectProposal: WalletConnectProposalUi? = null,
    val walletConnectPendingRequest: WalletConnectPendingRequest? = null,
    val signQrPages: List<String> = emptyList(),
    val signQrPageIndex: Int = 0,
    val signQrBitmap: Bitmap? = null,
    val pendingResponseType: PendingResponseType? = null,
    val txHash: String = "",
    val lastSignature: String = "",
    val lastSignatureAddress: String = "",
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    companion object {
        private const val PREFS_NAME = "arb_watch_wallet"
        private const val KEY_ADDRESSES = "addresses"
        private const val KEY_SELECTED = "selected"
        private const val AUTO_APPROVE_WALLETCONNECT = true
    }

    private val prefs = application.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val _uiState = MutableStateFlow(WalletUiState())
    val uiState: StateFlow<WalletUiState> = _uiState.asStateFlow()

    init {
        restoreAddresses()
        runCatching {
            WalletConnectBridge.ensureInitialized(application)
        }.onFailure { error ->
            _uiState.update {
                it.copy(walletConnectStatus = "WalletConnect 初始化异常: ${error.message ?: "未知错误"}")
            }
        }
        viewModelScope.launch {
            WalletConnectBridge.status.collectLatest { status ->
                _uiState.update { it.copy(walletConnectStatus = status) }
            }
        }
        viewModelScope.launch {
            WalletConnectBridge.proposal.collectLatest { proposal ->
                _uiState.update { it.copy(walletConnectProposal = proposal) }
                if (AUTO_APPROVE_WALLETCONNECT && proposal != null) {
                    val currentAddress = _uiState.value.selectedAddress
                    if (currentAddress.isBlank()) {
                        setError("收到 WalletConnect 会话提案，但当前未选择观察地址，无法自动批准")
                    } else {
                        WalletConnectBridge.approveCurrentProposal(currentAddress) { result ->
                            result.onSuccess {
                                _uiState.update {
                                    it.copy(
                                        info = "WalletConnect 会话已自动批准，可在 DApp 继续下一步操作",
                                        error = "",
                                    )
                                }
                            }
                            result.onFailure {
                                setError("WalletConnect 自动批准失败: ${it.message}")
                            }
                        }
                    }
                }
            }
        }
        viewModelScope.launch {
            WalletConnectBridge.request.collectLatest { request ->
                _uiState.update { it.copy(walletConnectPendingRequest = request) }
                if (request != null) {
                    handleWalletConnectRequest(request)
                }
            }
        }
    }

    fun setActiveTab(tab: WalletTab) = _uiState.update { it.copy(activeTab = tab) }
    fun setNewAddressInput(v: String) = _uiState.update { it.copy(newAddressInput = v) }
    fun setTransferTo(v: String) = _uiState.update { it.copy(transferTo = v) }
    fun setTransferAmount(v: String) = _uiState.update { it.copy(transferAmount = v) }
    fun setTransferToken(v: String) = _uiState.update { it.copy(transferToken = v) }
    fun setRequestInput(v: String) = _uiState.update { it.copy(requestInput = v) }
    fun setPersonalMessageInput(v: String) = _uiState.update { it.copy(personalMessageInput = v) }
    fun setTypedDataInput(v: String) = _uiState.update { it.copy(typedDataInput = v) }
    fun clearError() = _uiState.update { it.copy(error = "") }
    fun clearInfo() = _uiState.update { it.copy(info = "") }
    fun clearTxHash() = _uiState.update { it.copy(txHash = "") }
    fun clearSignature() = _uiState.update { it.copy(lastSignature = "", lastSignatureAddress = "") }

    fun approveWalletConnectProposal() {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) return setError("请先选择观察地址，再批准 WalletConnect 会话")
        WalletConnectBridge.approveCurrentProposal(address) { result ->
            result.onFailure { setError("WalletConnect 批准失败: ${it.message}") }
        }
    }

    fun rejectWalletConnectProposal() {
        WalletConnectBridge.rejectCurrentProposal { result ->
            result.onFailure { setError("WalletConnect 拒绝失败: ${it.message}") }
        }
    }

    fun addAddressFromInput() {
        val input = _uiState.value.newAddressInput
        addAddress(input)
    }

    fun addAddress(addr: String) {
        val normalized = normalizeAddress(addr)
            ?: run {
                _uiState.update { it.copy(error = "地址格式错误") }
                return
            }
        _uiState.update {
            if (it.addresses.contains(normalized)) {
                it.copy(selectedAddress = normalized, newAddressInput = "", error = "")
            } else {
                it.copy(
                    addresses = it.addresses + normalized,
                    selectedAddress = normalized,
                    newAddressInput = "",
                    error = "",
                    info = "已添加观察地址"
                )
            }
        }
        persistAddresses()
        loadBalances(normalized)
    }

    fun selectAddress(address: String) {
        _uiState.update { it.copy(selectedAddress = address, error = "") }
        persistAddresses()
        loadBalances(address)
    }

    fun removeAddress(address: String) {
        _uiState.update { state ->
            val updated = state.addresses.filterNot { it.equals(address, ignoreCase = true) }
            state.copy(
                addresses = updated,
                selectedAddress = when {
                    updated.isEmpty() -> ""
                    state.selectedAddress.equals(address, ignoreCase = true) -> updated.first()
                    else -> state.selectedAddress
                },
                balances = if (updated.isEmpty()) emptyMap() else state.balances,
                info = "已删除观察地址",
                error = ""
            )
        }
        persistAddresses()
        _uiState.value.selectedAddress.takeIf { it.isNotBlank() }?.let(::loadBalances)
    }

    fun loadBalances(address: String = _uiState.value.selectedAddress) {
        if (address.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = "") }
            try {
                val ethBal = ArbitrumRpc.getBalance(address)
                val usdc = ArbitrumConfig.TOKENS["USDC"]!!.address?.let { ArbitrumRpc.getTokenBalance(it, address) } ?: BigInteger.ZERO
                val usdt = ArbitrumConfig.TOKENS["USDT"]!!.address?.let { ArbitrumRpc.getTokenBalance(it, address) } ?: BigInteger.ZERO
                _uiState.update {
                    it.copy(
                        loading = false,
                        balances = linkedMapOf(
                            "ETH" to formatUnits(ethBal, 18),
                            "USDC" to formatUnits(usdc, 6),
                            "USDT" to formatUnits(usdt, 6),
                        ),
                        error = ""
                    )
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(loading = false, error = "加载余额失败: ${e.message}") }
            }
        }
    }

    fun prepareTransferEth() {
        val from = _uiState.value.selectedAddress
        val to = normalizeAddress(_uiState.value.transferTo)
        val amount = _uiState.value.transferAmount.trim()
        if (from.isBlank()) return setError("请先添加观察地址")
        if (to == null) return setError("接收地址格式错误")
        if (amount.isBlank()) return setError("请输入 ETH 数量")

        viewModelScope.launch {
            try {
                val (maxPriority, maxFee) = ArbitrumRpc.getBlockGasParams()
                val nonce = ArbitrumRpc.getNonce(from)
                val valueWei = amountToWei(amount, 18)
                val gasLimit = ArbitrumRpc.estimateGas(
                    mapOf(
                        "from" to from,
                        "to" to to,
                        "value" to "0x${valueWei.toString(16)}",
                        "data" to "0x",
                    )
                )
                val request = TpRequestBuilder.buildSignTransactionRequest(
                    fromAddress = from,
                    txData = TxData(
                        from = from,
                        to = to,
                        value = valueWei,
                        data = "0x",
                        gasLimit = gasLimit,
                        nonce = nonce,
                        maxFeePerGas = maxFee,
                        maxPriorityFeePerGas = maxPriority,
                        type = 2,
                    )
                )
                prepareRelayRequest(request, PendingResponseType.BROADCAST_TX, "ETH 转账")
            } catch (e: Exception) {
                setError("构建交易失败: ${e.message}")
            }
        }
    }

    fun prepareTransferToken() {
        val from = _uiState.value.selectedAddress
        val to = normalizeAddress(_uiState.value.transferTo)
        val amount = _uiState.value.transferAmount.trim()
        val tokenKey = _uiState.value.transferToken
        if (from.isBlank()) return setError("请先添加观察地址")
        if (to == null) return setError("接收地址格式错误")
        if (amount.isBlank()) return setError("请输入数量")

        val token = ArbitrumConfig.TOKENS[tokenKey] ?: return setError("不支持的代币")
        val tokenAddress = token.address ?: return setError("该资产不是 ERC20")

        viewModelScope.launch {
            try {
                val (maxPriority, maxFee) = ArbitrumRpc.getBlockGasParams()
                val nonce = ArbitrumRpc.getNonce(from)
                val amountWei = amountToWei(amount, token.decimals)
                val data = "a9059cbb" +
                    "0".repeat(24) + to.removePrefix("0x").lowercase() +
                    amountWei.toString(16).padStart(64, '0')
                val gasLimit = ArbitrumRpc.estimateGas(
                    mapOf(
                        "from" to from,
                        "to" to tokenAddress,
                        "data" to "0x$data",
                    )
                )
                val request = TpRequestBuilder.buildSignTransactionRequest(
                    fromAddress = from,
                    txData = TxData(
                        from = from,
                        to = tokenAddress,
                        value = BigInteger.ZERO,
                        data = "0x$data",
                        gasLimit = gasLimit,
                        nonce = nonce,
                        maxFeePerGas = maxFee,
                        maxPriorityFeePerGas = maxPriority,
                        type = 2,
                    )
                )
                prepareRelayRequest(request, PendingResponseType.BROADCAST_TX, "$tokenKey 转账")
            } catch (e: Exception) {
                setError("构建交易失败: ${e.message}")
            }
        }
    }

    fun preparePersonalSign() {
        val address = _uiState.value.selectedAddress
        val message = _uiState.value.personalMessageInput.trim()
        if (address.isBlank()) return setError("请先选择观察地址")
        if (message.isBlank()) return setError("请输入要签名的消息")
        val request = TpRequestBuilder.buildPersonalSignRequest(address, message)
        prepareRelayRequest(request, PendingResponseType.SHOW_SIGNATURE, "personal_sign")
    }

    fun prepareTypedDataSign() {
        val address = _uiState.value.selectedAddress
        val typedData = _uiState.value.typedDataInput.trim()
        if (address.isBlank()) return setError("请先选择观察地址")
        if (typedData.isBlank()) return setError("请输入 TypedData JSON")
        try {
            typedDataJson.parseToJsonElement(typedData)
        } catch (e: Exception) {
            return setError("TypedData JSON 不合法: ${e.message}")
        }
        val request = TpRequestBuilder.buildSignTypedDataRequest(address, typedData)
        prepareRelayRequest(request, PendingResponseType.SHOW_SIGNATURE, "signTypedDataV4")
    }

    fun importRawRequest() {
        val payload = _uiState.value.requestInput.trim()
        if (payload.isBlank()) return setError("请输入或扫码 DApp 请求")
        handleIncomingPayload(payload)
    }

    fun onRequestScanResult(payload: String) {
        _uiState.update { it.copy(requestInput = payload, activeTab = WalletTab.SIGN, error = "") }
        handleIncomingPayload(payload)
    }

    fun onResponseScanResult(payload: String) {
        val parsed = TpResponseParser.parse(payload)
        if (parsed.isError || (parsed.rawTransaction == null && parsed.signature == null)) {
            return setError("无法解析树莓派结果")
        }

        viewModelScope.launch {
            when {
                parsed.rawTransaction != null -> {
                    try {
                        val hash = ArbitrumRpc.sendRawTransaction(parsed.rawTransaction)
                        val pendingRequest = _uiState.value.walletConnectPendingRequest
                        if (pendingRequest != null) {
                            WalletConnectBridge.respondCurrentRequestResult("0x$hash") { result ->
                                result.onFailure { setError("WalletConnect 返回交易哈希失败: ${it.message}") }
                            }
                        }
                        _uiState.update {
                            it.copy(
                                txHash = hash,
                                signQrBitmap = null,
                                signQrPages = emptyList(),
                                signQrPageIndex = 0,
                                pendingResponseType = null,
                                requestTitle = "",
                                requestSummary = "",
                                transferInfo = "",
                                dappInfo = "",
                                relayHint = "",
                                error = "",
                                info = if (pendingRequest != null) "交易已广播，并已返回给 WalletConnect" else "交易已广播",
                                requestInput = "",
                            )
                        }
                    } catch (e: Exception) {
                        setError("广播失败: ${e.message}")
                    }
                }
                parsed.signature != null -> {
                    val pendingRequest = _uiState.value.walletConnectPendingRequest
                    if (pendingRequest != null) {
                        WalletConnectBridge.respondCurrentRequestResult(parsed.signature) { result ->
                            result.onFailure { setError("WalletConnect 返回签名失败: ${it.message}") }
                        }
                    }
                    _uiState.update {
                        it.copy(
                            lastSignature = parsed.signature,
                            lastSignatureAddress = parsed.address.orEmpty(),
                            signQrBitmap = null,
                            signQrPages = emptyList(),
                            signQrPageIndex = 0,
                            pendingResponseType = null,
                            error = "",
                            info = if (pendingRequest != null) "签名结果已返回给 WalletConnect" else "签名结果已返回",
                        )
                    }
                }
            }
        }
    }

    fun nextSignQrPage() {
        val pages = _uiState.value.signQrPages
        if (pages.size <= 1) return
        val nextIndex = (_uiState.value.signQrPageIndex + 1) % pages.size
        updateQrPage(nextIndex)
    }

    fun prevSignQrPage() {
        val pages = _uiState.value.signQrPages
        if (pages.size <= 1) return
        val nextIndex = if (_uiState.value.signQrPageIndex <= 0) pages.lastIndex else _uiState.value.signQrPageIndex - 1
        updateQrPage(nextIndex)
    }

    fun clearPreparedRequest() {
        _uiState.update {
            it.copy(
                requestTitle = "",
                requestSummary = "",
                transferInfo = "",
                dappInfo = "",
                relayHint = "",
                signQrPages = emptyList(),
                signQrPageIndex = 0,
                signQrBitmap = null,
                pendingResponseType = null,
                error = "",
                info = "",
            )
        }
    }

    private fun prepareRelayRequest(
        payload: String,
        explicitResponseType: PendingResponseType?,
        explicitTitle: String?
    ) {
        viewModelScope.launch {
            prepareRelayRequestNow(payload, explicitResponseType, explicitTitle)
        }
    }

    private suspend fun prepareRelayRequestNow(
        payload: String,
        explicitResponseType: PendingResponseType?,
        explicitTitle: String?
    ): Boolean {
        return try {
            val request = TpQrCodec.parseSignRequest(payload)
            val bundle = RelayQrCodec.buildRelayPayloads(payload)
            val qr = generateQrBitmap(bundle.payloads.first())
            _uiState.update {
                it.copy(
                    requestTitle = explicitTitle ?: requestTitle(request),
                    requestSummary = buildRequestSummary(request),
                    transferInfo = buildTransferInfo(request),
                    dappInfo = buildDappInfo(request),
                    relayHint = if (bundle.payloads.size > 1) {
                        "已生成 ${bundle.payloads.size} 张静态二维码，将自动循环切换。"
                    } else {
                        "已生成 1 张静态二维码，可直接给树莓派扫描。"
                    },
                    signQrPages = bundle.payloads,
                    signQrPageIndex = 0,
                    signQrBitmap = qr,
                    pendingResponseType = explicitResponseType ?: inferResponseType(request),
                    error = "",
                    info = "请求已准备好，下一步让树莓派扫描。",
                    activeTab = WalletTab.SIGN,
                    txHash = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.BROADCAST_TX) "" else it.txHash,
                    lastSignature = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.SHOW_SIGNATURE) "" else it.lastSignature,
                    lastSignatureAddress = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.SHOW_SIGNATURE) "" else it.lastSignatureAddress,
                )
            }
            true
        } catch (e: Exception) {
            setError("解析请求失败: ${e.message}")
            false
        }
    }

    private fun handleIncomingPayload(payload: String) {
        val normalizedPayload = WalletConnectUriParser.extract(payload) ?: payload.trim()
        if (normalizedPayload.startsWith("wc:", ignoreCase = true)) {
            try {
                WalletConnectBridge.pair(normalizedPayload)
                _uiState.update {
                    it.copy(
                        info = "已接收 WalletConnect 配对链接。请回 DApp 点击连接/签名，收到请求后会自动生成给树莓派的二维码。",
                        error = "",
                        activeTab = WalletTab.SIGN,
                    )
                }
            } catch (e: Exception) {
                setError("WalletConnect 配对失败: ${e.message}")
            }
            return
        }
        prepareRelayRequest(normalizedPayload, null, null)
    }

    private suspend fun handleWalletConnectRequest(request: WalletConnectPendingRequest) {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) {
            WalletConnectBridge.respondCurrentRequestError("请先在钱包里选择观察地址", 4001)
            setError("请先选择观察地址，再处理 WalletConnect 请求")
            return
        }
        try {
            when (val prepared = WalletConnectRequestCodec.prepare(request, address)) {
                is WalletConnectPreparedRequest.ImmediateResult -> {
                    WalletConnectBridge.respondCurrentRequestResult(prepared.result) { result ->
                        result.onFailure { setError("WalletConnect 返回结果失败: ${it.message}") }
                    }
                    _uiState.update {
                        it.copy(
                            info = "WalletConnect 请求已直接返回: ${request.method}",
                            error = "",
                        )
                    }
                }

                is WalletConnectPreparedRequest.RelayToPi -> {
                    val ok = prepareRelayRequestNow(
                        payload = prepared.payload,
                        explicitResponseType = prepared.responseType,
                        explicitTitle = prepared.title,
                    )
                    if (!ok) {
                        _uiState.update {
                            it.copy(
                                info = "已收到 WalletConnect 请求 ${request.method}，但当前未成功生成树莓派签名二维码，请检查错误提示后重试。",
                                activeTab = WalletTab.SIGN,
                            )
                        }
                    } else {
                        _uiState.update {
                            it.copy(
                                info = "已收到 WalletConnect 请求 ${request.method}，树莓派签名二维码已生成，请直接扫描页面上的“树莓派签名请求”卡片。",
                                error = "",
                                activeTab = WalletTab.SIGN,
                            )
                        }
                    }
                }
            }
        } catch (e: Exception) {
            WalletConnectBridge.respondCurrentRequestError(e.message ?: "请求处理失败", 5000)
            setError("WalletConnect 请求处理失败: ${e.message}")
        }
    }

    private fun updateQrPage(index: Int) {
        val pages = _uiState.value.signQrPages
        if (pages.isEmpty() || index !in pages.indices) return
        runCatching { generateQrBitmapSync(pages[index]) }
            .onSuccess { bitmap ->
                _uiState.update { it.copy(signQrPageIndex = index, signQrBitmap = bitmap) }
            }
            .onFailure { error ->
                // Keep current visible QR instead of clearing it when one page fails.
                _uiState.update {
                    it.copy(
                        error = "中转二维码第 ${index + 1} 张生成失败: ${error.message}",
                    )
                }
            }
    }

    private suspend fun generateQrBitmap(payload: String): Bitmap = withContext(Dispatchers.Default) {
        generateQrBitmapSync(payload)
    }

    private fun generateQrBitmapSync(payload: String): Bitmap {
        val matrix = QRCodeWriter().encode(
            payload,
            BarcodeFormat.QR_CODE,
            900,
            900,
            mapOf(
                EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.L,
                EncodeHintType.MARGIN to 1,
                EncodeHintType.CHARACTER_SET to "UTF-8",
            )
        )
        return BarcodeEncoder().createBitmap(matrix)
    }

    private fun inferResponseType(request: TpSignRequest): PendingResponseType {
        return if (request is TpSignTransactionRequest) PendingResponseType.BROADCAST_TX else PendingResponseType.SHOW_SIGNATURE
    }

    private fun requestTitle(request: TpSignRequest): String {
        return when (request) {
            is TpSignTransactionRequest -> "待签交易"
            is TpSignPersonalMessageRequest -> "待签消息"
            is TpSignTypedDataRequest -> "待签 TypedData"
        }
    }

    private fun buildRequestSummary(request: TpSignRequest): String {
        return when (request) {
            is TpSignTransactionRequest -> buildTransactionSummary(request)
            is TpSignPersonalMessageRequest -> buildPersonalSignSummary(request)
            is TpSignTypedDataRequest -> buildTypedDataSummary(request)
        }
    }

    private fun buildTransferInfo(request: TpSignRequest): String {
        if (request !is TpSignTransactionRequest) return ""
        val tx = request.txData
        val to = tx.string("to") ?: "-"
        val from = request.address ?: tx.string("from") ?: "-"
        val valueWei = parseQuantity(tx.string("value") ?: "0x0")
        val dataHex = tx.string("data") ?: tx.string("input") ?: "0x"
        val cleanData = cleanHex(dataHex)
        val token = ArbitrumConfig.findTokenByAddress(to)

        if (cleanData.startsWith("a9059cbb") && cleanData.length >= 136 && token != null) {
            val recipient = "0x" + cleanData.substring(32, 72)
            val amount = BigInteger(cleanData.substring(72, 136), 16)
            return buildString {
                appendLine("from: $from")
                appendLine("token: ${token.symbol}")
                appendLine("to: $recipient")
                appendLine("amount: ${formatUnits(amount, token.decimals)}")
                appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            }.trim()
        }

        return buildString {
            appendLine("from: $from")
            appendLine("to: $to")
            appendLine("value: ${formatUnits(valueWei, 18)} ETH")
            appendLine("contractCall: ${if (cleanData.isNotBlank()) "yes" else "no"}")
            if (cleanData.length >= 8) appendLine("methodId: 0x${cleanData.take(8)}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
        }.trim()
    }

    private fun buildDappInfo(request: TpSignRequest): String {
        return buildString {
            appendLine("dappName: ${request.dappName ?: "-"}")
            appendLine("dappUrl: ${request.dappUrl ?: "-"}")
            appendLine("source/origin: ${request.dappSource ?: "-"}")
        }.trim()
    }

    private fun buildTransactionSummary(request: TpSignTransactionRequest): String {
        val tx = request.txData
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("address: ${request.address ?: tx.string("from") ?: "-"}")
            appendLine("nonce: ${tx.string("nonce") ?: "-"}")
            appendLine("gasLimit: ${tx.string("gasLimit") ?: tx.string("gas") ?: "-"}")
            appendLine("type: ${tx.string("type") ?: "-"}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildPersonalSignSummary(request: TpSignPersonalMessageRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("message: ${preview(request.message)}")
            appendLine("bytes: ${request.message.toByteArray().size}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildTypedDataSummary(request: TpSignTypedDataRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("primaryType: ${request.primaryType ?: "-"}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            appendLine("bytes: ${request.typedDataJson.toByteArray().size}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun restoreAddresses() {
        val raw = prefs.getString(KEY_ADDRESSES, null)
        val addresses = mutableListOf<String>()
        if (!raw.isNullOrBlank()) {
            runCatching {
                val array = JSONArray(raw)
                for (i in 0 until array.length()) {
                    val value = normalizeAddress(array.optString(i))
                    if (value != null) addresses += value
                }
            }
        }
        val selected = normalizeAddress(prefs.getString(KEY_SELECTED, "") ?: "")
        val effectiveSelected = when {
            selected != null && addresses.contains(selected) -> selected
            addresses.isNotEmpty() -> addresses.first()
            else -> ""
        }
        _uiState.update { it.copy(addresses = addresses, selectedAddress = effectiveSelected) }
        if (effectiveSelected.isNotBlank()) loadBalances(effectiveSelected)
    }

    private fun persistAddresses() {
        val state = _uiState.value
        val array = JSONArray()
        state.addresses.forEach(array::put)
        prefs.edit()
            .putString(KEY_ADDRESSES, array.toString())
            .putString(KEY_SELECTED, state.selectedAddress)
            .apply()
    }

    private fun normalizeAddress(raw: String): String? {
        val value = raw.trim().removePrefix("ethereum:")
        val address = if (value.startsWith("0x")) value else "0x$value"
        if (address.length != 42) return null
        if (!address.removePrefix("0x").all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) return null
        return address
    }

    private fun setError(message: String) {
        _uiState.update { it.copy(error = message, info = "") }
    }

    private fun preview(value: String, max: Int = 100): String {
        val singleLine = value.replace('\n', ' ')
        return if (singleLine.length <= max) singleLine else singleLine.take(max) + "..."
    }

    private fun parseQuantity(raw: String): BigInteger {
        val value = raw.trim()
        if (value.isBlank()) return BigInteger.ZERO
        return if (value.startsWith("0x") || value.startsWith("0X")) {
            BigInteger(value.removePrefix("0x").removePrefix("0X").ifBlank { "0" }, 16)
        } else {
            value.toBigIntegerOrNull() ?: BigInteger.ZERO
        }
    }

    private fun cleanHex(value: String): String = value.removePrefix("0x").removePrefix("0X").lowercase()

    private fun formatUnits(value: BigInteger, decimals: Int): String {
        if (value == BigInteger.ZERO) return "0"
        val divisor = BigDecimal.TEN.pow(decimals)
        return BigDecimal(value)
            .divide(divisor, decimals.coerceAtMost(8), RoundingMode.DOWN)
            .stripTrailingZeros()
            .toPlainString()
    }

    private fun amountToWei(amount: String, decimals: Int): BigInteger {
        val cleaned = amount.trim()
        val parts = cleaned.split('.')
        val intPart = parts.firstOrNull().orEmpty().ifBlank { "0" }.toBigIntegerOrNull() ?: BigInteger.ZERO
        val fraction = (parts.getOrNull(1) ?: "").padEnd(decimals, '0').take(decimals)
        val frac = if (fraction.isBlank()) BigInteger.ZERO else fraction.toBigIntegerOrNull() ?: BigInteger.ZERO
        return intPart * BigInteger.TEN.pow(decimals) + frac
    }

    private fun chainName(chainId: Long): String {
        return if (chainId == ArbitrumConfig.CHAIN_ID) "Arbitrum One" else "Chain $chainId"
    }
}

private fun kotlinx.serialization.json.JsonObject.string(key: String): String? =
    this[key]?.jsonPrimitive?.contentOrNull
