package com.smartcard.signer

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import org.satochip.io.CardChannel

data class MainUiState(
    val selectedWallet: RelayWallet = RelayWallet.TOKENPOCKET,
    val inputPayload: String = "",
    val parseMessage: String = "",
    val fragmentMessage: String = "",
    val parsedSummary: String = "",
    val transferInfo: String = "",
    val dappInfo: String = "",
    val relayHint: String = "",
    val relayPayloadPages: List<String> = emptyList(),
    val relayPageIndex: Int = 0,
    val relayQr: Bitmap? = null,
    val reviewRequired: Boolean = false,
    val reviewConfirmed: Boolean = false,
    val parsedRequest: TpSignRequest? = null,
    val web3RelayRequest: Web3RelayRequest? = null,
    val derivationPath: String = "m/44'/60'/0'/0/0",
    val pin: String = "",
    val isUnlocked: Boolean = false,
    val unlockedAddress: String = "",
    val waitingForUnlockCard: Boolean = false,
    val unlockInProgress: Boolean = false,
    val waitingForSignCard: Boolean = false,
    val signingInProgress: Boolean = false,
    val responsePayload: String = "",
    val responseQr: Bitmap? = null,
    val digestHex: String = "",
    val digestLabel: String = "摘要哈希",
    val signedResult: String = "",
    val resultLabel: String = "签名结果",
    val signerAddress: String = "",
    val errorMessage: String = ""
)

enum class ScanHandleResult {
    Done,
    NeedMoreFragments
}

class MainViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()

    private val assembler = MultiFragmentAssembler()
    private val signer = SatochipSigner()
    private val cardOpMutex = Mutex()

    fun onWalletChanged(wallet: RelayWallet) {
        _uiState.update {
            resetUnlockState(it).copy(
                selectedWallet = wallet,
                inputPayload = "",
                parsedRequest = null,
                web3RelayRequest = null,
                parsedSummary = "",
                transferInfo = "",
                dappInfo = "",
                relayHint = "",
                relayPayloadPages = emptyList(),
                relayPageIndex = 0,
                relayQr = null,
                reviewRequired = false,
                reviewConfirmed = false,
                responsePayload = "",
                responseQr = null,
                signerAddress = "",
                digestHex = "",
                signedResult = "",
                parseMessage = when (wallet) {
                    RelayWallet.TOKENPOCKET -> "已切换到 TP 签名/中转模式"
                    RelayWallet.OKX -> "已切换到 OKX Wallet 中转模式"
                    RelayWallet.BITGET -> "已切换到 Bitget Wallet 中转模式"
                },
                fragmentMessage = "",
                errorMessage = ""
            )
        }
    }

    fun onInputChanged(value: String) {
        _uiState.update {
            it.copy(
                inputPayload = value,
                parsedRequest = null,
                web3RelayRequest = null,
                parsedSummary = "",
                transferInfo = "",
                dappInfo = "",
                relayHint = "",
                relayPayloadPages = emptyList(),
                relayPageIndex = 0,
                relayQr = null,
                reviewRequired = false,
                reviewConfirmed = false,
                parseMessage = "",
                errorMessage = ""
            )
        }
    }

    fun onPinChanged(value: String) {
        _uiState.update {
            resetUnlockState(it).copy(
                pin = value,
                parseMessage = "PIN 已变更，请重新解锁",
                errorMessage = ""
            )
        }
    }

    fun onPathChanged(value: String) {
        _uiState.update {
            resetUnlockState(it).copy(
                derivationPath = value,
                parseMessage = "路径已变更，请重新解锁",
                errorMessage = ""
            )
        }
    }

    fun parseCurrentPayload() {
        val payload = _uiState.value.inputPayload.trim()
        if (payload.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请先扫码或粘贴请求二维码内容") }
            return
        }
        parseAndApply(payload)
    }

    fun onScanResult(rawContent: String): ScanHandleResult {
        if (rawContent.isBlank()) return ScanHandleResult.Done
        return parseAndApply(rawContent.trim())
    }

    fun onRuntimeError(message: String) {
        _uiState.update { it.copy(errorMessage = message) }
    }

    fun confirmReview() {
        val request = _uiState.value.parsedRequest ?: return
        _uiState.update {
            it.copy(
                reviewRequired = true,
                reviewConfirmed = true,
                parseMessage = when (request) {
                    is TpSignTransactionRequest -> "已确认交易与 DApp 信息，可贴卡签名"
                    is TpSignPersonalMessageRequest -> "已确认消息与 DApp 信息，可贴卡签名"
                    is TpSignTypedDataRequest -> "已确认 TypedData 与 DApp 信息，可贴卡签名"
                },
                errorMessage = ""
            )
        }
    }

    fun armUnlock() {
        val state = _uiState.value
        if (state.pin.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请输入 PIN") }
            return
        }

        _uiState.update {
            it.copy(
                waitingForUnlockCard = true,
                waitingForSignCard = false,
                unlockInProgress = false,
                signingInProgress = false,
                parseMessage = "请贴卡，检测到后将自动解锁并显示地址",
                errorMessage = ""
            )
        }
    }

    fun armSigning() {
        val state = _uiState.value
        if (!state.isUnlocked) {
            _uiState.update { it.copy(errorMessage = "请先解锁并显示钱包地址") }
            return
        }

        if (state.parsedRequest == null) {
            if (state.web3RelayRequest != null) {
                _uiState.update {
                    it.copy(errorMessage = "OKX/Bitget 中转请求请交给树莓派签名，手机只负责低密度二维码中转。")
                }
                return
            }
            parseCurrentPayload()
        }

        val latest = _uiState.value
        val request = latest.parsedRequest
        if (request == null) {
            _uiState.update { it.copy(errorMessage = "请先扫码或粘贴 TP 请求") }
            return
        }

        if (latest.reviewRequired && !latest.reviewConfirmed) {
            _uiState.update { it.copy(errorMessage = "请先核对转账/合约和 DApp 信息，再点击“已核对，允许签名”") }
            return
        }

        _uiState.update {
            it.copy(
                waitingForUnlockCard = false,
                waitingForSignCard = true,
                unlockInProgress = false,
                signingInProgress = false,
                parseMessage = when (request) {
                    is TpSignTransactionRequest -> {
                        if (request.chainId == 42161L) "Arbitrum One 交易已就绪，请贴卡签名"
                        else "交易请求已就绪，请贴卡签名"
                    }

                    is TpSignPersonalMessageRequest -> "Personal Message 请求已就绪，请贴卡签名"
                    is TpSignTypedDataRequest -> "TypedData 请求已就绪，请贴卡签名"
                },
                errorMessage = ""
            )
        }
    }

    fun cancelPendingAction() {
        _uiState.update {
            it.copy(
                waitingForUnlockCard = false,
                waitingForSignCard = false,
                unlockInProgress = false,
                signingInProgress = false,
                parseMessage = ""
            )
        }
    }

    fun showPreviousRelayPage() {
        val state = _uiState.value
        if (state.relayPayloadPages.isEmpty()) return
        val nextIndex = if (state.relayPageIndex <= 0) {
            state.relayPayloadPages.lastIndex
        } else {
            state.relayPageIndex - 1
        }
        _uiState.update {
            it.copy(
                relayPageIndex = nextIndex,
                relayQr = generateQrBitmap(state.relayPayloadPages[nextIndex])
            )
        }
    }

    fun showNextRelayPage() {
        val state = _uiState.value
        if (state.relayPayloadPages.isEmpty()) return
        val nextIndex = if (state.relayPageIndex >= state.relayPayloadPages.lastIndex) {
            0
        } else {
            state.relayPageIndex + 1
        }
        _uiState.update {
            it.copy(
                relayPageIndex = nextIndex,
                relayQr = generateQrBitmap(state.relayPayloadPages[nextIndex])
            )
        }
    }

    fun onCardConnected(channel: CardChannel) {
        val snapshot = _uiState.value
        when {
            snapshot.waitingForUnlockCard && !snapshot.unlockInProgress -> runUnlockFlow(channel)
            snapshot.waitingForSignCard && !snapshot.signingInProgress && snapshot.parsedRequest != null -> runSignFlow(channel)
        }
    }

    private fun runUnlockFlow(channel: CardChannel) {
        viewModelScope.launch(Dispatchers.IO) {
            cardOpMutex.withLock {
                val state = _uiState.value
                if (!state.waitingForUnlockCard || state.unlockInProgress) {
                    return@withLock
                }

                _uiState.update {
                    it.copy(
                        unlockInProgress = true,
                        parseMessage = "检测到卡片，正在解锁...",
                        errorMessage = ""
                    )
                }

                runCatching {
                    signer.unlockCard(
                        channel = channel,
                        derivationPath = state.derivationPath,
                        pin = state.pin
                    )
                }.onSuccess { outcome ->
                    _uiState.update {
                        it.copy(
                            isUnlocked = true,
                            unlockedAddress = outcome.address,
                            waitingForUnlockCard = false,
                            unlockInProgress = false,
                            waitingForSignCard = false,
                            signingInProgress = false,
                            responsePayload = "",
                            responseQr = null,
                            digestHex = "",
                            signedResult = "",
                            signerAddress = "",
                            parseMessage = if (it.parsedRequest == null) {
                                "解锁成功，钱包地址已显示。现在请扫码签名请求"
                            } else {
                                "解锁成功，已保留当前 TP 请求，可直接贴卡签名"
                            },
                            errorMessage = ""
                        )
                    }
                }.onFailure { error ->
                    _uiState.update {
                        it.copy(
                            isUnlocked = false,
                            unlockedAddress = "",
                            waitingForUnlockCard = false,
                            unlockInProgress = false,
                            errorMessage = error.message ?: "解锁失败",
                            parseMessage = ""
                        )
                    }
                }
            }
        }
    }

    private fun runSignFlow(channel: CardChannel) {
        viewModelScope.launch(Dispatchers.IO) {
            cardOpMutex.withLock {
                val state = _uiState.value
                val request = state.parsedRequest ?: return@withLock
                if (!state.waitingForSignCard || state.signingInProgress) {
                    return@withLock
                }

                _uiState.update {
                    it.copy(
                        signingInProgress = true,
                        parseMessage = "检测到卡片，正在签名...",
                        errorMessage = ""
                    )
                }

                runCatching {
                    signer.signWithCard(
                        channel = channel,
                        request = request,
                        derivationPath = state.derivationPath,
                        pin = state.pin
                    )
                }.onSuccess { outcome ->
                    val unlockedAddress = state.unlockedAddress.lowercase()
                    val signerAddress = outcome.signerAddress.lowercase()
                    if (unlockedAddress.isNotBlank() && unlockedAddress != signerAddress) {
                        _uiState.update {
                            it.copy(
                                waitingForSignCard = false,
                                signingInProgress = false,
                                errorMessage = "签名地址与当前解锁地址不一致，已拒绝结果",
                                parseMessage = ""
                            )
                        }
                        return@onSuccess
                    }

                    val qr = generateQrBitmap(outcome.responsePayload)
                    _uiState.update {
                        it.copy(
                            waitingForSignCard = false,
                            signingInProgress = false,
                            responsePayload = outcome.responsePayload,
                            responseQr = qr,
                            digestHex = outcome.digestHex,
                            digestLabel = outcome.digestLabel,
                            signedResult = outcome.resultHex,
                            resultLabel = outcome.resultLabel,
                            signerAddress = outcome.signerAddress,
                            parseMessage = "签名成功，请用 TP 扫描下方二维码",
                            errorMessage = ""
                        )
                    }
                }.onFailure { error ->
                    _uiState.update {
                        it.copy(
                            waitingForSignCard = false,
                            signingInProgress = false,
                            errorMessage = error.message ?: "签名失败",
                            parseMessage = ""
                        )
                    }
                }
            }
        }
    }

    private fun parseAndApply(payload: String): ScanHandleResult {
        if (_uiState.value.selectedWallet != RelayWallet.TOKENPOCKET) {
            return parseAndApplyWeb3Relay(payload)
        }

        runCatching {
            TpQrCodec.parseInput(payload)
        }.onSuccess { parsed ->
            when (parsed) {
                is ParseResult.SignRequest -> {
                    val summary = buildSummary(parsed.request)
                    val transferInfo = buildTransferInfo(parsed.request)
                    val dappInfo = buildDappInfo(parsed.request)
                    val relay = RelayQrCodec.buildRelayPayloads(parsed.request)
                    val relayHint = if (relay.isFragmented) {
                        "已转成 ${relay.payloads.size} 张静态二维码，默认每 1 秒自动循环切换。"
                    } else {
                        "已生成 1 张静态二维码，可直接给树莓派扫描。"
                    }
                    _uiState.update {
                        it.copy(
                            inputPayload = payload,
                            parsedRequest = parsed.request,
                            web3RelayRequest = null,
                            parsedSummary = summary,
                            transferInfo = transferInfo,
                            dappInfo = dappInfo,
                            relayHint = relayHint,
                            relayPayloadPages = relay.payloads,
                            relayPageIndex = 0,
                            relayQr = generateQrBitmap(relay.payloads.first()),
                            reviewRequired = true,
                            reviewConfirmed = false,
                            parseMessage = "请求解析成功。请先核对转账/合约和 DApp 信息；下方已生成树莓派静态中转二维码。",
                            fragmentMessage = "",
                            errorMessage = ""
                        )
                    }
                    return ScanHandleResult.Done
                }

                is ParseResult.Fragment -> {
                    when (val result = assembler.accept(parsed.fragment)) {
                        is AssemblyResult.Progress -> {
                            _uiState.update {
                                it.copy(
                                    fragmentMessage = "已接收分片 ${result.received}/${result.total}",
                                    parseMessage = "",
                                    errorMessage = ""
                                )
                            }
                            return ScanHandleResult.NeedMoreFragments
                        }

                        is AssemblyResult.Complete -> {
                            _uiState.update {
                                it.copy(
                                    inputPayload = result.payload,
                                    fragmentMessage = "分片拼接完成",
                                    errorMessage = ""
                                )
                            }
                            return parseAndApply(result.payload)
                        }

                        is AssemblyResult.Error -> {
                            _uiState.update {
                                it.copy(
                                    fragmentMessage = "",
                                    parseMessage = "",
                                    errorMessage = result.reason
                                )
                            }
                            return ScanHandleResult.Done
                        }
                    }
                }
            }
        }.onFailure { error ->
            _uiState.update {
                it.copy(
                    parseMessage = "",
                    parsedRequest = null,
                    web3RelayRequest = null,
                    parsedSummary = "",
                    transferInfo = "",
                    dappInfo = "",
                    relayHint = "",
                    relayPayloadPages = emptyList(),
                    relayPageIndex = 0,
                    relayQr = null,
                    reviewRequired = false,
                    reviewConfirmed = false,
                    errorMessage = error.message ?: "解析失败"
                )
            }
            return ScanHandleResult.Done
        }
        return ScanHandleResult.Done
    }

    private fun parseAndApplyWeb3Relay(payload: String): ScanHandleResult {
        val wallet = _uiState.value.selectedWallet
        runCatching {
            Web3RelayCodec.parse(wallet, payload)
        }.onSuccess { request ->
            val relay = Web3RelayCodec.buildRelayPayloads(request)
            val relayHint = if (relay.isFragmented) {
                "已转成 ${relay.payloads.size} 张 ${request.wallet.shortName} 静态中转二维码，默认每 1 秒自动循环切换。"
            } else {
                "已生成 1 张 ${request.wallet.shortName} 静态中转二维码，可直接给树莓派扫描。"
            }
            _uiState.update {
                it.copy(
                    inputPayload = payload,
                    parsedRequest = null,
                    web3RelayRequest = request,
                    parsedSummary = "wallet: ${request.wallet.displayName}\nformat: ${request.detectedFormat}\naction: ${request.actionHint}\nqrType: ${request.qrType}",
                    transferInfo = request.detailText,
                    dappInfo = "source: ${request.wallet.displayName}\nmode: offline relay\ninternet: disabled",
                    relayHint = relayHint,
                    relayPayloadPages = relay.payloads,
                    relayPageIndex = 0,
                    relayQr = generateQrBitmap(relay.payloads.first()),
                    reviewRequired = false,
                    reviewConfirmed = false,
                    parseMessage = "${request.wallet.displayName} 二维码解析成功。下方已生成树莓派低密度中转二维码。",
                    fragmentMessage = "",
                    errorMessage = ""
                )
            }
        }.onFailure { error ->
            _uiState.update {
                it.copy(
                    parseMessage = "",
                    parsedRequest = null,
                    web3RelayRequest = null,
                    parsedSummary = "",
                    transferInfo = "",
                    dappInfo = "",
                    relayHint = "",
                    relayPayloadPages = emptyList(),
                    relayPageIndex = 0,
                    relayQr = null,
                    reviewRequired = false,
                    reviewConfirmed = false,
                    errorMessage = error.message ?: "Web3 中转解析失败"
                )
            }
        }
        return ScanHandleResult.Done
    }

    private fun ensureUnlocked(): Boolean {
        if (_uiState.value.isUnlocked) {
            return true
        }
        _uiState.update {
            it.copy(errorMessage = "请先输入 PIN 并贴卡解锁，显示钱包地址后再扫码")
        }
        return false
    }

    private fun buildSummary(request: TpSignRequest): String {
        return when (request) {
            is TpSignTransactionRequest -> buildTransactionSummary(request)
            is TpSignPersonalMessageRequest -> buildPersonalSummary(request)
            is TpSignTypedDataRequest -> buildTypedDataSummary(request)
        }
    }

    private fun buildTransferInfo(request: TpSignRequest): String {
        return when (request) {
            is TpSignTransactionRequest -> {
                val tx = request.txData
                val to = tx["to"]?.jsonPrimitive?.contentOrNull ?: "-"
                val address = request.address ?: tx["from"]?.jsonPrimitive?.contentOrNull ?: "-"
                val valueRaw = tx["value"]?.jsonPrimitive?.contentOrNull ?: "0x0"
                val valueWei = parseQuantity(valueRaw)
                val valueEth = formatEth(valueWei)
                val dataHex = tx["data"]?.jsonPrimitive?.contentOrNull
                    ?: tx["input"]?.jsonPrimitive?.contentOrNull
                    ?: "0x"
                val hasCallData = cleanHexPrefix(dataHex).isNotBlank()
                val methodId = if (cleanHexPrefix(dataHex).length >= 8) {
                    "0x" + cleanHexPrefix(dataHex).substring(0, 8)
                } else {
                    "-"
                }
                val gas = tx["gas"]?.jsonPrimitive?.contentOrNull
                    ?: tx["gasLimit"]?.jsonPrimitive?.contentOrNull
                    ?: "-"
                val nonce = tx["nonce"]?.jsonPrimitive?.contentOrNull ?: "-"

                buildString {
                    appendLine("address: $address")
                    appendLine("to: $to")
                    appendLine("value: $valueRaw wei (~$valueEth ETH)")
                    appendLine("nonce: $nonce")
                    appendLine("gas: $gas")
                    appendLine("contractCall: ${if (hasCallData) "yes" else "no"}")
                    appendLine("methodId: $methodId")
                    appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
                }.trim()
            }

            is TpSignPersonalMessageRequest -> buildString {
                appendLine("type: personalSign")
                appendLine("address: ${request.address ?: "-"}")
                appendLine("messagePreview: ${preview(request.message)}")
                appendLine("messageBytes: ${decodeMessageBytesForPreview(request.message).size}")
            }.trim()

            is TpSignTypedDataRequest -> buildString {
                appendLine("type: signTypedData")
                appendLine("address: ${request.address ?: "-"}")
                appendLine("primaryType: ${request.primaryType ?: "-"}")
                appendLine("typedDataBytes: ${request.typedDataJson.toByteArray().size}")
                appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            }.trim()
        }
    }

    private fun buildDappInfo(request: TpSignRequest): String {
        val name = request.dappName ?: "-"
        val url = request.dappUrl ?: "-"
        val source = request.dappSource ?: "-"
        return buildString {
            appendLine("dappName: $name")
            appendLine("dappUrl: $url")
            appendLine("source/origin: $source")
        }.trim()
    }

    private fun buildTransactionSummary(request: TpSignTransactionRequest): String {
        val tx = request.txData
        val nonce = tx["nonce"]?.toString() ?: ""
        val to = tx["to"]?.toString() ?: ""
        val value = tx["value"]?.toString() ?: ""
        val type = tx["type"]?.toString() ?: "0x0"
        val address = request.address ?: tx["from"]?.toString() ?: "-"

        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            appendLine("address: $address")
            appendLine("type: $type")
            appendLine("nonce: $nonce")
            appendLine("to: $to")
            appendLine("value: $value")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildPersonalSummary(request: TpSignPersonalMessageRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("message: ${preview(request.message)}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildTypedDataSummary(request: TpSignTypedDataRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${request.network}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("primaryType: ${request.primaryType ?: "-"}")
            appendLine("legacy: ${if (request.isLegacy) "yes" else "no"}")
            appendLine("typedDataBytes: ${request.typedDataJson.toByteArray().size}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun preview(value: String, max: Int = 120): String {
        val line = value.replace('\n', ' ')
        if (line.length <= max) return line
        return line.take(max) + "..."
    }

    private fun formatEth(wei: BigInteger): String {
        return try {
            BigDecimal(wei)
                .divide(BigDecimal.TEN.pow(18), 8, RoundingMode.DOWN)
                .stripTrailingZeros()
                .toPlainString()
        } catch (_: Exception) {
            "?"
        }
    }

    private fun decodeMessageBytesForPreview(message: String): ByteArray {
        if (message.startsWith("0x") || message.startsWith("0X")) {
            return runCatching { hexToBytes(message) }.getOrDefault(message.toByteArray())
        }
        return message.toByteArray()
    }

    private fun chainName(chainId: Long): String {
        return when (chainId) {
            1L -> "Ethereum Mainnet"
            42161L -> "Arbitrum One"
            else -> "EVM"
        }
    }

    private fun resetUnlockState(state: MainUiState): MainUiState {
        return state.copy(
            isUnlocked = false,
            unlockedAddress = "",
            waitingForUnlockCard = false,
            waitingForSignCard = false,
            unlockInProgress = false,
            signingInProgress = false
        )
    }
}
