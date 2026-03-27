package io.arbitrum.wallet

import android.app.Application
import android.graphics.Bitmap
import android.net.Uri
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import com.journeyapps.barcodescanner.BarcodeEncoder
import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

private val typedDataJson = Json { ignoreUnknownKeys = true; isLenient = true }

class MainViewModel(application: Application) : AndroidViewModel(application) {
    companion object {
        private const val AUTO_APPROVE_WALLETCONNECT = false
        private const val ADDRESS_DISCOVERY_MESSAGE_PREFIX = "tp-watch-address-discovery:"
        private val ALLOWED_INJECTED_BROWSER_ORIGINS = setOf("https://app.hyperliquid.xyz")
    }

    private val prefs = WalletStorage.openSecurePreferences(application)
    private val _uiState = MutableStateFlow(WalletUiState())
    val uiState: StateFlow<WalletUiState> = _uiState.asStateFlow()
    private val _browserCommands = MutableSharedFlow<InjectedBrowserCommand>(extraBufferCapacity = 32)
    val browserCommands: SharedFlow<InjectedBrowserCommand> = _browserCommands.asSharedFlow()

    private val localActivityItems = mutableListOf<WalletActivityItem>()
    private val syncedActivityByChain = linkedMapOf<Long, List<WalletActivityItem>>()
    private val hyperliquidAgentsByAccount = linkedMapOf<String, HyperliquidAgentRecord>()
    private val hyperliquidMarketMeta = linkedMapOf<String, HyperliquidMarketMeta>()
    private var pendingHyperliquidApproval: HyperliquidApprovalRequest? = null
    private var pendingInjectedBrowserRequest: InjectedBrowserPendingRequest? = null
    private val sessionSecurityObserver = object : DefaultLifecycleObserver {
        override fun onStop(owner: LifecycleOwner) {
            clearSensitiveSessionState()
        }
    }

    init {
        ProcessLifecycleOwner.get().lifecycle.addObserver(sessionSecurityObserver)
        restorePersistedState()
        runCatching {
            WalletConnectBridge.ensureInitialized(application)
        }.onFailure { error ->
            _uiState.update {
                it.copy(walletConnectStatus = "WalletConnect 初始化异常: ${error.message ?: "未知错误"}")
            }
        }
        bindWalletConnectState()
    }

    override fun onCleared() {
        ProcessLifecycleOwner.get().lifecycle.removeObserver(sessionSecurityObserver)
        super.onCleared()
    }

    fun setActiveTab(tab: WalletTab) = _uiState.update { it.copy(activeTab = tab) }
    fun setNewAddressInput(value: String) = _uiState.update { it.copy(newAddressInput = value) }
    fun setEvmDerivationPath(value: String) {
        _uiState.update { it.copy(evmDerivationPath = value) }
        WalletStorage.writeEvmDerivationPath(prefs, value)
    }
    fun setBitcoinImportInput(value: String) = _uiState.update { it.copy(bitcoinImportInput = value) }
    fun importBitcoinWatchAccountFromPayload(value: String) {
        _uiState.update { it.copy(bitcoinImportInput = value) }
        importBitcoinWatchAccountInternal(value)
    }
    fun setTransferTo(value: String) = _uiState.update { it.copy(transferTo = value) }
    fun setTransferAmount(value: String) = _uiState.update { it.copy(transferAmount = value) }
    fun setTransferToken(value: String) = _uiState.update { it.copy(transferToken = value) }

    fun transferAllTokens() {
        val state = _uiState.value
        val amount = state.chainPortfolios[state.selectedChainId]?.assets
            ?.firstOrNull { it.symbol.equals(state.transferToken, ignoreCase = true) }
            ?.amount ?: return
        _uiState.update { it.copy(transferAmount = amount) }
    }
    fun setRequestInput(value: String) = _uiState.update { it.copy(requestInput = value) }
    fun setContactNameInput(value: String) = _uiState.update { it.copy(contactNameInput = value) }
    fun setContactAddressInput(value: String) = _uiState.update { it.copy(contactAddressInput = value) }
    fun setContactNoteInput(value: String) = _uiState.update { it.copy(contactNoteInput = value) }
    fun setHyperliquidSelectedMarket(value: String) {
        val market = value.trim().uppercase()
        if (market.isBlank()) return
        val marketMeta = hyperliquidMarketMeta[market]
        _uiState.update {
            it.copy(
                hyperliquidSelectedMarket = market,
                hyperliquidOrderPriceInput = if (
                    it.hyperliquidOrderMode == HyperliquidOrderMode.LIMIT &&
                    marketMeta != null &&
                    it.hyperliquidOrderPriceInput.isBlank()
                ) {
                    marketMeta.midPrice
                } else {
                    it.hyperliquidOrderPriceInput
                },
            )
        }
    }
    fun setHyperliquidOrderMode(mode: HyperliquidOrderMode) {
        val marketMeta = hyperliquidMarketMeta[_uiState.value.hyperliquidSelectedMarket.uppercase()]
        _uiState.update {
            it.copy(
                hyperliquidOrderMode = mode,
                hyperliquidOrderPriceInput = if (
                    mode == HyperliquidOrderMode.LIMIT &&
                    marketMeta != null &&
                    it.hyperliquidOrderPriceInput.isBlank()
                ) {
                    marketMeta.midPrice
                } else {
                    it.hyperliquidOrderPriceInput
                },
            )
        }
    }
    fun setHyperliquidOrderSide(isBuy: Boolean) = _uiState.update { it.copy(hyperliquidOrderSideBuy = isBuy) }
    fun setHyperliquidOrderSizeInput(value: String) = _uiState.update { it.copy(hyperliquidOrderSizeInput = value) }
    fun setHyperliquidOrderPriceInput(value: String) = _uiState.update { it.copy(hyperliquidOrderPriceInput = value) }
    fun toggleHyperliquidReduceOnly() = _uiState.update { it.copy(hyperliquidReduceOnly = !it.hyperliquidReduceOnly) }
    fun clearError() = _uiState.update { it.copy(error = "") }
    fun clearInfo() = _uiState.update { it.copy(info = "") }
    fun clearTxHash() = _uiState.update { it.copy(txHash = "", txHashChainId = null) }
    fun clearSignature() = _uiState.update { it.copy(lastSignature = "", lastSignatureAddress = "") }

    fun syncInjectedBrowserContext() {
        emitBrowserAccountsChanged()
        emitBrowserChainChanged()
    }

    fun handleInjectedBrowserRequest(
        requestId: String,
        method: String,
        paramsJson: String,
        origin: String,
    ) {
        val normalizedOrigin = normalizeInjectedBrowserOrigin(origin)
        if (!isAllowedInjectedBrowserOrigin(normalizedOrigin)) {
            emitBrowserReject(requestId, 4001, "未授权的网页来源")
            reportBrowserRuntimeIssue("blocked browser origin · ${origin.ifBlank { "<blank>" }}")
            return
        }
        val normalizedMethod = method.trim()
        if (normalizedMethod.isBlank()) {
            emitBrowserReject(requestId, 4001, "缺少方法名")
            return
        }

        viewModelScope.launch {
            try {
                when (normalizedMethod.lowercase()) {
                    "eth_accounts" -> {
                        emitBrowserResolve(requestId, org.json.JSONArray(currentAuthorizedBrowserAccounts()).toString())
                    }

                    "eth_requestaccounts" -> {
                        val address = _uiState.value.selectedAddress
                        if (address.isBlank()) {
                            emitBrowserReject(requestId, 4001, "请先选择观察地址")
                        } else {
                            authorizeInjectedBrowser(normalizedOrigin)
                            emitBrowserAccountsChanged()
                            emitBrowserChainChanged()
                            emitBrowserResolve(requestId, org.json.JSONArray(listOf(address)).toString())
                        }
                    }

                    "wallet_getpermissions" -> {
                        emitBrowserResolve(requestId, currentBrowserPermissionsJson(normalizedOrigin))
                    }

                    "wallet_requestpermissions", "wallet_grantpermissions" -> {
                        val address = _uiState.value.selectedAddress
                        if (address.isBlank()) {
                            emitBrowserReject(requestId, 4001, "请先选择观察地址")
                        } else {
                            authorizeInjectedBrowser(normalizedOrigin)
                            emitBrowserAccountsChanged()
                            emitBrowserChainChanged()
                            emitBrowserResolve(requestId, currentBrowserRequestPermissionsJson())
                        }
                    }

                    "wallet_revokepermissions" -> {
                        revokeInjectedBrowserAuthorization()
                        emitBrowserResolve(requestId, "null")
                    }

                    "eth_chainid" -> emitBrowserChainChanged(requestId)
                    "net_version" -> emitBrowserResolve(requestId, org.json.JSONObject.quote(_uiState.value.selectedChainId.toString()))
                    "wallet_registeronboarding" -> emitBrowserResolve(requestId, "false")
                    "wallet_watchasset" -> emitBrowserResolve(requestId, "true")
                    "wallet_getcapabilities" -> emitBrowserResolve(requestId, currentBrowserCapabilitiesJson())
                    "eth_coinbase" -> {
                        val address = currentAuthorizedBrowserAccounts().firstOrNull().orEmpty()
                        emitBrowserResolve(
                            requestId,
                            if (address.isBlank()) "null" else org.json.JSONObject.quote(address),
                        )
                    }

                    else -> {
                        if (pendingInjectedBrowserRequest != null) {
                            emitBrowserReject(requestId, -32002, "已有待处理签名请求")
                            return@launch
                        }
                        if (currentAuthorizedBrowserAccounts().isEmpty()) {
                            emitBrowserReject(requestId, 4100, "当前网页尚未获得钱包授权")
                            return@launch
                        }

                        val address = _uiState.value.selectedAddress
                        if (address.isBlank()) {
                            emitBrowserReject(requestId, 4001, "请先选择观察地址")
                            return@launch
                        }

                        val request = WalletConnectPendingRequest(
                            topic = "hyperliquid-webview",
                            requestId = System.currentTimeMillis(),
                            method = normalizedMethod,
                            chainId = "eip155:${_uiState.value.selectedChainId}",
                            params = paramsJson.ifBlank { "[]" },
                            peerName = "Hyperliquid",
                            peerUrl = normalizedOrigin,
                        )
                        when (
                            val prepared = WalletConnectRequestCodec.prepare(
                                request = request,
                                selectedAddress = address,
                                activeChainId = _uiState.value.selectedChainId,
                                derivationPath = _uiState.value.evmDerivationPath,
                            )
                        ) {
                            is WalletConnectPreparedRequest.ImmediateResult -> {
                                prepared.switchToChainId?.let { targetChainId ->
                                    WalletChains.byId(targetChainId)?.let { chain ->
                                        selectChainInternal(
                                            chain = chain,
                                            persist = true,
                                            triggerReload = true,
                                            message = "已切换到 ${chain.shortName}",
                                        )
                                    }
                                }
                                emitBrowserResolve(requestId, prepared.result ?: "null")
                            }

                            is WalletConnectPreparedRequest.RelayToPi -> {
                                val ok = prepareRelayRequestNow(
                                    payload = prepared.payload,
                                    explicitResponseType = prepared.responseType,
                                    explicitTitle = prepared.title,
                                    focusTab = WalletTab.DISCOVER,
                                )
                                if (!ok) {
                                    emitBrowserReject(requestId, 4001, "未能生成树莓派签名二维码")
                                } else {
                                    pendingInjectedBrowserRequest = InjectedBrowserPendingRequest(
                                        browserRequestId = requestId,
                                        method = normalizedMethod,
                                        origin = normalizedOrigin,
                                    )
                                    recordLocalActivity(
                                        WalletActivityItem(
                                            id = "browser-relay-${request.requestId}",
                                            chainId = prepared.chainId,
                                            kind = WalletActivityKind.DAPP,
                                            title = "Hyperliquid 页面发起 ${normalizedMethod}",
                                            subtitle = normalizedOrigin.ifBlank { "app.hyperliquid.xyz" },
                                            detail = WalletChains.require(prepared.chainId).displayName,
                                            statusLabel = "待树莓派签名",
                                            timestamp = System.currentTimeMillis(),
                                        )
                                    )
                                }
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                emitBrowserReject(requestId, 4001, e.message ?: "请求处理失败")
                setError("Hyperliquid 页面请求失败: ${e.message}")
            }
        }
    }

    fun selectChain(chainId: Long) {
        val chain = WalletChains.byId(chainId) ?: return
        selectChainInternal(chain, persist = true, triggerReload = true, message = "")
    }

    fun addAddressFromInput() {
        addAddress(_uiState.value.newAddressInput)
    }

    fun addAddress(addr: String) {
        val normalized = normalizeAddress(addr)
            ?: return setError("地址格式错误")

        _uiState.update {
            if (it.addresses.contains(normalized)) {
                it.copy(
                    selectedAddress = normalized,
                    newAddressInput = "",
                    error = "",
                    info = "已切换到该观察地址",
                )
            } else {
                it.copy(
                    addresses = it.addresses + normalized,
                    selectedAddress = normalized,
                    newAddressInput = "",
                    error = "",
                    info = "已添加观察地址",
                )
            }
        }
        persistAddresses()
        loadBalances()
        refreshHyperliquid(silent = true)
        emitBrowserAccountsChanged()
    }

    fun prepareDerivedAddressImport() {
        val state = _uiState.value
        val path = normalizeDerivationPath(state.evmDerivationPath)
            ?: return setError("派生路径格式错误，请使用 m/44'/60'/0'/0/0 这种格式")
        val chain = WalletChains.require(state.selectedChainId)
        val payload = TpRequestBuilder.buildPersonalSignRequest(
            address = null,
            message = "$ADDRESS_DISCOVERY_MESSAGE_PREFIX${System.currentTimeMillis()}",
            chain = chain,
            requestId = "discover-address-${System.currentTimeMillis()}",
            derivationPath = path,
        )
        prepareRelayRequest(
            payload = payload,
            explicitResponseType = PendingResponseType.IMPORT_WATCH_ADDRESS,
            explicitTitle = "${chain.shortName} 派生地址导入",
        )
        _uiState.update {
            it.copy(
                evmDerivationPath = path,
                info = "已生成派生地址导入二维码，请让树莓派扫描后再把结果扫回手机。",
                error = "",
            )
        }
        WalletStorage.writeEvmDerivationPath(prefs, path)
    }

    fun selectAddress(address: String) {
        if (_uiState.value.selectedAddress != address) {
            clearSensitiveSessionState()
        }
        _uiState.update { it.copy(selectedAddress = address, error = "", info = "") }
        persistAddresses()
        loadBalances()
        refreshHyperliquid(silent = true)
        emitBrowserAccountsChanged()
    }

    fun importBitcoinWatchAccount() = importBitcoinWatchAccountInternal(_uiState.value.bitcoinImportInput)

    private fun importBitcoinWatchAccountInternal(rawInput: String) {
        val parsed = parseBitcoinWatchAccountImport(rawInput)
            ?: return setError("请输入有效的 xpub / ypub / zpub / tpub / upub / vpub，或直接粘贴 get-xpub 输出")

        val now = System.currentTimeMillis()
        var importedAccountId: String? = null
        _uiState.update { state ->
            val existing = state.bitcoinWatchAccounts.firstOrNull { it.xpub == parsed.xpub }
            if (existing != null) {
                state.copy(
                    bitcoinImportInput = "",
                    bitcoinPrototypeStatus = defaultBitcoinPrototypeStatus(state.bitcoinWatchAccounts.size),
                    info = "BTC 观察账户已存在：${existing.label}",
                    error = "",
                )
            } else {
                val account = enrichBitcoinWatchAccount(
                    BitcoinWatchAccount(
                        id = UUID.randomUUID().toString(),
                        label = parsed.defaultLabel,
                        xpub = parsed.xpub,
                        prefix = parsed.prefix,
                        networkLabel = parsed.networkLabel,
                        scriptTypeLabel = parsed.scriptTypeLabel,
                        accountPathHint = parsed.accountPathHint,
                        importedAt = now,
                    )
                )
                if (account.derivationError.isNotBlank()) {
                    return@update state.copy(
                        error = account.derivationError,
                        info = "",
                    )
                }
                importedAccountId = account.id
                val accounts = listOf(account) + state.bitcoinWatchAccounts
                state.copy(
                    bitcoinImportInput = "",
                    bitcoinWatchAccounts = accounts,
                    bitcoinPrototypeStatus = defaultBitcoinPrototypeStatus(accounts.size),
                    info = "已导入 BTC 观察账户：${account.label}",
                    error = "",
                )
            }
        }
        persistBitcoinWatchAccounts()
        importedAccountId?.let(::syncBitcoinWatchAccount)
    }

    fun removeBitcoinWatchAccount(accountId: String) {
        _uiState.update { state ->
            val accounts = state.bitcoinWatchAccounts.filterNot { it.id == accountId }
            state.copy(
                bitcoinWatchAccounts = accounts,
                bitcoinPrototypeStatus = defaultBitcoinPrototypeStatus(accounts.size),
                info = "BTC 观察账户原型已删除",
                error = "",
            )
        }
        persistBitcoinWatchAccounts()
    }

    fun syncBitcoinWatchAccount(accountId: String) {
        val current = _uiState.value.bitcoinWatchAccounts.firstOrNull { it.id == accountId }
            ?: return setError("未找到 BTC 观察账户")
        _uiState.update { state ->
            state.copy(
                bitcoinWatchAccounts = state.bitcoinWatchAccounts.map { account ->
                    if (account.id == accountId) account.copy(syncing = true, lastSyncStatus = "正在同步链上状态...") else account
                },
                error = "",
            )
        }
        viewModelScope.launch {
            runCatching { BitcoinTransferService.syncAccount(current) }
                .onSuccess { snapshot ->
                    updateBitcoinWatchAccount(accountId) { account ->
                        account.copy(
                            balanceSats = snapshot.balanceSats,
                            priceUsd = snapshot.priceUsd,
                            utxoCount = snapshot.utxoCount,
                            nextReceiveAddress = snapshot.nextReceiveAddress,
                            nextChangeAddress = snapshot.nextChangeAddress,
                            lastSyncStatus = snapshot.status,
                            lastSyncAt = System.currentTimeMillis(),
                            syncing = false,
                            recentActivity = snapshot.recentActivity,
                        )
                    }
                    _uiState.update {
                        it.copy(
                            info = "BTC 账户已同步：${current.label}",
                            error = "",
                        )
                    }
                }
                .onFailure { error ->
                    updateBitcoinWatchAccount(accountId) { account ->
                        account.copy(
                            syncing = false,
                            lastSyncStatus = "同步失败：${error.message ?: "未知错误"}",
                        )
                    }
                    setError("BTC 账户同步失败: ${error.message}")
                }
        }
    }

    fun prepareBitcoinTransfer(
        accountId: String,
        destinationAddress: String,
        amountText: String,
        feeRateText: String?,
    ) {
        val account = _uiState.value.bitcoinWatchAccounts.firstOrNull { it.id == accountId }
            ?: return setError("未找到 BTC 观察账户")
        viewModelScope.launch {
            runCatching {
                BitcoinTransferService.prepareTransfer(
                    account = account,
                    destinationAddress = destinationAddress,
                    amountText = amountText,
                    feeRateText = feeRateText,
                )
            }.onSuccess { prepared ->
                val bundle = RelayQrCodec.buildRelayPayloads(prepared.requestPayload)
                val qr = generateQrBitmap(bundle.payloads.first())
                updateBitcoinWatchAccount(accountId) {
                    it.copy(
                        balanceSats = prepared.snapshot.balanceSats,
                        priceUsd = prepared.snapshot.priceUsd,
                        utxoCount = prepared.snapshot.utxoCount,
                        nextReceiveAddress = prepared.snapshot.nextReceiveAddress,
                        nextChangeAddress = prepared.snapshot.nextChangeAddress,
                        lastSyncStatus = prepared.snapshot.status,
                        lastSyncAt = System.currentTimeMillis(),
                        syncing = false,
                    )
                }
                _uiState.update {
                    it.copy(
                        requestTitle = "BTC 转账待树莓派签名",
                        requestSummary = buildString {
                            appendLine("账户: ${account.label}")
                            appendLine("收款地址: ${prepared.destinationAddress}")
                            appendLine("发送金额: ${formatBitcoinSats(prepared.amountSats)}")
                            appendLine("矿工费: ${formatBitcoinSats(prepared.feeSats)}")
                            appendLine("输入数: ${prepared.inputCount}")
                            if (prepared.changeSats > 0 && prepared.changeAddress != null) {
                                appendLine("找零: ${formatBitcoinSats(prepared.changeSats)}")
                                appendLine("找零地址: ${prepared.changeAddress}")
                            }
                        }.trim(),
                        transferInfo = buildString {
                            appendLine("BTC 账户: ${account.label}")
                            appendLine("to: ${prepared.destinationAddress}")
                            appendLine("amount: ${formatBitcoinSats(prepared.amountSats)}")
                            appendLine("fee: ${formatBitcoinSats(prepared.feeSats)}")
                            appendLine("inputs: ${prepared.inputCount}")
                        }.trim(),
                        dappInfo = "BTC 观察账户 -> 树莓派 PSBT 冷签 -> 手机广播",
                        relayHint = if (bundle.payloads.size > 1) {
                            "已生成 ${bundle.payloads.size} 张 BTC PSBT 二维码，将自动轮播给树莓派扫描。签名完成后，再把树莓派回显的 tx 二维码扫回手机广播。"
                        } else {
                            "已生成 1 张 BTC PSBT 二维码。让树莓派扫描签名后，再把它回显的 tx 二维码扫回手机广播。"
                        },
                        signQrPages = bundle.payloads,
                        signQrPageIndex = 0,
                        signQrBitmap = qr,
                        pendingResponseType = PendingResponseType.BROADCAST_BTC_TX,
                        preparedBitcoinAccountId = accountId,
                        preparedRequestChainId = null,
                        txHash = "",
                        txHashChainId = null,
                        lastSignature = "",
                        lastSignatureAddress = "",
                        error = "",
                        info = "BTC 转账请求已准备好，请让树莓派扫描当前二维码。",
                        activeTab = WalletTab.HOME,
                    )
                }
            }.onFailure { error ->
                setError("BTC 转账准备失败: ${error.message}")
            }
        }
    }

    fun removeAddress(address: String) {
        _uiState.update { state ->
            val updated = state.addresses.filterNot { it.equals(address, ignoreCase = true) }
            val selected = when {
                updated.isEmpty() -> ""
                state.selectedAddress.equals(address, ignoreCase = true) -> updated.first()
                else -> state.selectedAddress
            }
            state.copy(
                addresses = updated,
                selectedAddress = selected,
                chainPortfolios = if (selected.isBlank()) emptyMap() else state.chainPortfolios,
                info = "已删除观察地址",
                error = "",
            )
        }
        persistAddresses()
        if (_uiState.value.selectedAddress.isNotBlank()) {
            loadBalances()
            refreshHyperliquid(silent = true)
        } else {
            clearHyperliquidState()
        }
        emitBrowserAccountsChanged()
    }

    fun loadBalances(
        chainId: Long = _uiState.value.selectedChainId,
        address: String = _uiState.value.selectedAddress,
        silent: Boolean = false,
    ) {
        if (address.isBlank()) return
        val chain = WalletChains.require(chainId)
        viewModelScope.launch {
            if (!silent) {
                _uiState.update { it.copy(loadingBalances = true, error = "") }
            }
            try {
                val balances = mutableListOf<AssetBalanceUi>()
                val nativeToken = chain.tokens.first()
                val nativeBalance = EvmRpc.getBalance(chain, address)
                val nativeAmount = formatUnits(nativeBalance, nativeToken.decimals)
                val nativePrice = EvmRpc.getUsdPrice(chain, null)
                balances += AssetBalanceUi(
                    symbol = nativeToken.symbol,
                    name = nativeToken.name,
                    amount = nativeAmount,
                    isNative = true,
                    priceUsd = nativePrice,
                    usdAmount = calculateUsd(nativeAmount, nativePrice),
                )
                chain.tokens.filter { it.address != null }.forEach { token ->
                    val amount = EvmRpc.getTokenBalance(chain, token.address!!, address)
                    val formatted = formatUnits(amount, token.decimals)
                    val price = EvmRpc.getUsdPrice(chain, token.address)
                balances += AssetBalanceUi(
                    symbol = token.symbol,
                    name = token.name,
                    amount = formatted,
                    contractAddress = token.address,
                    priceUsd = price,
                    usdAmount = calculateUsd(formatted, price),
                )
            }
                val finalBalances = enrichMissingPrices(balances)
                _uiState.update { state ->
                    state.copy(
                        loadingBalances = false,
                        chainPortfolios = state.chainPortfolios + (
                            chain.chainId to ChainPortfolioUi(
                                chainId = chain.chainId,
                                assets = finalBalances,
                                lastUpdatedAt = System.currentTimeMillis(),
                                status = "已同步 ${chain.shortName}",
                            )
                        ),
                        error = "",
                    )
                }
                syncRecentActivity(chain, address)
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        loadingBalances = false,
                        error = "加载 ${chain.shortName} 资产失败: ${e.message}",
                    )
                }
            }
        }
    }

    fun refreshSelectedActivity() {
        val state = _uiState.value
        if (state.selectedAddress.isBlank()) return
        loadBalances(state.selectedChainId, state.selectedAddress)
    }

    fun refreshHyperliquid(silent: Boolean = false) {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) return
        viewModelScope.launch {
            if (!silent) {
                _uiState.update {
                    it.copy(
                        hyperliquidLoading = true,
                        hyperliquidStatus = "正在同步 Hyperliquid...",
                        error = "",
                    )
                }
            }
            try {
                val storedAgent = currentHyperliquidAgent(address)
                val snapshot = HyperliquidApi.loadSnapshot(address, storedAgent)
                hyperliquidMarketMeta.clear()
                hyperliquidMarketMeta.putAll(snapshot.marketMeta)

                val updatedAgent = storedAgent?.copy(validUntil = snapshot.storedAgentValidUntil)
                if (updatedAgent != null) {
                    hyperliquidAgentsByAccount[updatedAgent.accountAddress.lowercase()] = updatedAgent
                }

                val selectedMarket = when {
                    snapshot.marketMeta.containsKey(_uiState.value.hyperliquidSelectedMarket.uppercase()) ->
                        _uiState.value.hyperliquidSelectedMarket.uppercase()
                    snapshot.markets.isNotEmpty() -> snapshot.markets.first().name.uppercase()
                    else -> _uiState.value.hyperliquidSelectedMarket
                }
                val defaultPrice = snapshot.marketMeta[selectedMarket]?.midPrice.orEmpty()
                _uiState.update { state ->
                    state.copy(
                        hyperliquidLoading = false,
                        hyperliquidStatus = snapshot.status,
                        hyperliquidAccount = snapshot.account,
                        hyperliquidMarkets = snapshot.markets,
                        hyperliquidOpenOrders = snapshot.openOrders,
                        hyperliquidFills = snapshot.fills,
                        hyperliquidAgent = updatedAgent?.toUi(),
                        hyperliquidSelectedMarket = selectedMarket,
                        hyperliquidOrderPriceInput = if (
                            state.hyperliquidOrderMode == HyperliquidOrderMode.LIMIT &&
                            state.hyperliquidOrderPriceInput.isBlank()
                        ) {
                            defaultPrice
                        } else {
                            state.hyperliquidOrderPriceInput
                        },
                        error = if (silent) state.error else "",
                    )
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        hyperliquidLoading = false,
                        hyperliquidStatus = "Hyperliquid 同步失败",
                    )
                }
                if (!silent) {
                    setError("Hyperliquid 同步失败: ${e.message}")
                }
            }
        }
    }

    fun beginHyperliquidAgentApproval() {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) return setError("请先添加或选择观察地址")
        val approval = runCatching { HyperliquidApi.buildApprovalRequest(address) }
            .getOrElse { return setError("生成 Hyperliquid 代理失败: ${it.message}") }
        pendingHyperliquidApproval = approval
        val payload = TpRequestBuilder.buildSignTypedDataRequest(
            address = address,
            typedDataJson = approval.typedDataJson,
            chain = WalletChains.ARBITRUM,
            requestId = "hyperliquid-approve-${approval.nonce}",
            derivationPath = _uiState.value.evmDerivationPath,
            dappName = "Hyperliquid",
            dappUrl = "https://app.hyperliquid.xyz",
            dappSource = "Hyperliquid native trade panel",
        )
        prepareRelayRequest(
            payload = payload,
            explicitResponseType = PendingResponseType.SHOW_SIGNATURE,
            explicitTitle = "Hyperliquid 启用交易",
            focusTab = WalletTab.DISCOVER,
        )
        _uiState.update {
            it.copy(
                hyperliquidPendingApproval = true,
                hyperliquidStatus = "请让树莓派签名 Hyperliquid 授权请求",
                activeTab = WalletTab.DISCOVER,
                error = "",
                info = "代理钱包 ${shortAddress(approval.agent.agentAddress)} 已生成，签名后即可在 app 内直接下单。",
            )
        }
        recordLocalActivity(
            WalletActivityItem(
                id = "hyperliquid-approve-${approval.nonce}",
                chainId = WalletChains.ARBITRUM.chainId,
                kind = WalletActivityKind.DAPP,
                title = "Hyperliquid 请求授权代理",
                subtitle = shortAddress(approval.agent.agentAddress),
                detail = approval.agent.agentName,
                statusLabel = "待树莓派签名",
                timestamp = System.currentTimeMillis(),
            )
        )
    }

    fun placeHyperliquidOrder() {
        val state = _uiState.value
        val address = state.selectedAddress
        if (address.isBlank()) return setError("请先选择观察地址")
        val agent = currentHyperliquidAgent(address)
            ?: return setError("请先授权 Hyperliquid 代理钱包")
        val market = hyperliquidMarketMeta[state.hyperliquidSelectedMarket.uppercase()]
            ?: return setError("当前市场不可用，请先刷新 Hyperliquid")

        viewModelScope.launch {
            _uiState.update { it.copy(hyperliquidLoading = true, error = "") }
            try {
                val result = HyperliquidApi.placeOrder(
                    agent = agent,
                    market = market,
                    isBuy = state.hyperliquidOrderSideBuy,
                    sizeText = state.hyperliquidOrderSizeInput,
                    orderMode = state.hyperliquidOrderMode,
                    priceText = state.hyperliquidOrderPriceInput,
                    reduceOnly = state.hyperliquidReduceOnly,
                )
                ensureHyperliquidSuccess(result, "下单")
                recordLocalActivity(
                    WalletActivityItem(
                        id = "hyperliquid-order-${System.currentTimeMillis()}",
                        chainId = WalletChains.ARBITRUM.chainId,
                        kind = WalletActivityKind.DAPP,
                        title = "Hyperliquid ${if (state.hyperliquidOrderSideBuy) "买入" else "卖出"} ${market.name}",
                        subtitle = "${state.hyperliquidOrderSizeInput} @ ${if (state.hyperliquidOrderMode == HyperliquidOrderMode.MARKET) "市价" else state.hyperliquidOrderPriceInput}",
                        detail = result.toString(),
                        statusLabel = "已提交",
                        timestamp = System.currentTimeMillis(),
                    )
                )
                _uiState.update {
                    it.copy(
                        hyperliquidLoading = false,
                        info = "Hyperliquid 订单已提交",
                        hyperliquidStatus = "订单已提交，正在刷新",
                    )
                }
                refreshHyperliquid(silent = true)
            } catch (e: Exception) {
                _uiState.update { it.copy(hyperliquidLoading = false) }
                setError("Hyperliquid 下单失败: ${e.message}")
            }
        }
    }

    fun cancelHyperliquidOrder(coin: String, oid: Long) {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) return setError("请先选择观察地址")
        val agent = currentHyperliquidAgent(address)
            ?: return setError("请先授权 Hyperliquid 代理钱包")
        val market = hyperliquidMarketMeta[coin.uppercase()]
            ?: return setError("未找到 $coin 的市场元数据")
        viewModelScope.launch {
            _uiState.update { it.copy(hyperliquidLoading = true, error = "") }
            try {
                val result = HyperliquidApi.cancelOrder(agent, market, oid)
                ensureHyperliquidSuccess(result, "撤单")
                recordLocalActivity(
                    WalletActivityItem(
                        id = "hyperliquid-cancel-$oid",
                        chainId = WalletChains.ARBITRUM.chainId,
                        kind = WalletActivityKind.DAPP,
                        title = "Hyperliquid 已撤单",
                        subtitle = "$coin / OID $oid",
                        detail = result.toString(),
                        statusLabel = "已提交",
                        timestamp = System.currentTimeMillis(),
                    )
                )
                _uiState.update {
                    it.copy(
                        hyperliquidLoading = false,
                        info = "Hyperliquid 撤单已提交",
                        hyperliquidStatus = "撤单已提交，正在刷新",
                    )
                }
                refreshHyperliquid(silent = true)
            } catch (e: Exception) {
                _uiState.update { it.copy(hyperliquidLoading = false) }
                setError("Hyperliquid 撤单失败: ${e.message}")
            }
        }
    }

    fun prepareTransfer() {
        prepareTransferRequest(
            toInput = _uiState.value.transferTo,
            amountInput = _uiState.value.transferAmount,
            tokenSymbol = _uiState.value.transferToken,
        )
    }

    fun prepareTransferRequest(
        toInput: String,
        amountInput: String,
        tokenSymbol: String,
    ) {
        val state = _uiState.value
        val chain = WalletChains.require(state.selectedChainId)
        val from = state.selectedAddress
        val to = normalizeAddress(toInput)
        val amount = amountInput.trim()
        val token = chain.tokens.firstOrNull { it.symbol.equals(tokenSymbol, ignoreCase = true) }
            ?: return setError("当前链不支持 $tokenSymbol")

        if (from.isBlank()) return setError("请先添加观察地址")
        if (to == null) return setError("接收地址格式错误")
        if (amount.isBlank()) return setError("请输入数量")

        _uiState.update {
            it.copy(
                transferTo = toInput,
                transferAmount = amountInput,
                transferToken = token.symbol,
            )
        }

        viewModelScope.launch {
            try {
                val request = if (token.address == null) {
                    buildNativeTransferRequest(chain, from, to, amount, state.evmDerivationPath)
                } else {
                    buildTokenTransferRequest(chain, from, to, amount, token, state.evmDerivationPath)
                }
                prepareRelayRequest(
                    payload = request,
                    explicitResponseType = PendingResponseType.BROADCAST_TX,
                    explicitTitle = "${chain.shortName} ${token.symbol} 转账",
                )
                _uiState.update {
                    it.copy(
                        info = "${chain.shortName} ${token.symbol} 转账请求已生成",
                        error = "",
                    )
                }
            } catch (e: Exception) {
                setError("构建交易失败: ${e.message}")
            }
        }
    }

    fun prepareTransferEth() {
        val chain = WalletChains.require(_uiState.value.selectedChainId)
        _uiState.update { it.copy(transferToken = chain.nativeSymbol) }
        prepareTransfer()
    }

    fun prepareTransferToken() {
        prepareTransfer()
    }

    fun addContact() {
        val state = _uiState.value
        val name = state.contactNameInput.trim()
        val address = normalizeAddress(state.contactAddressInput)
            ?: return setError("联系人地址格式错误")
        if (name.isBlank()) return setError("请输入联系人名称")

        val existing = state.contacts.firstOrNull { it.address.equals(address, ignoreCase = true) }
        if (existing != null) {
            _uiState.update {
                it.copy(
                    transferTo = existing.address,
                    contactNameInput = "",
                    contactAddressInput = "",
                    contactNoteInput = "",
                    info = "联系人已存在，已填入转账地址",
                    error = "",
                )
            }
            return
        }

        val contact = TransferContact(
            id = UUID.randomUUID().toString(),
            name = name,
            address = address,
            note = state.contactNoteInput.trim(),
            chainId = state.selectedChainId,
        )
        _uiState.update {
            it.copy(
                contacts = listOf(contact) + it.contacts,
                transferTo = address,
                contactNameInput = "",
                contactAddressInput = "",
                contactNoteInput = "",
                info = "联系人已保存",
                error = "",
            )
        }
        persistContacts()
    }

    fun useContact(contactId: String) {
        val contact = _uiState.value.contacts.firstOrNull { it.id == contactId } ?: return
        _uiState.update { it.copy(transferTo = contact.address, error = "", info = "已填入联系人地址") }
        contact.chainId?.let { chainId ->
            WalletChains.byId(chainId)?.let { selectChainInternal(it, persist = true, triggerReload = true, message = "") }
        }
    }

    fun removeContact(contactId: String) {
        _uiState.update {
            it.copy(
                contacts = it.contacts.filterNot { contact -> contact.id == contactId },
                info = "联系人已删除",
                error = "",
            )
        }
        persistContacts()
    }

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

    fun importRawRequest() {
        val payload = _uiState.value.requestInput.trim()
        if (payload.isBlank()) return setError("请输入或扫码 DApp 请求")
        handleIncomingPayload(payload, WalletTab.HOME)
    }

    fun onRequestScanResult(payload: String) {
        _uiState.update { it.copy(requestInput = payload, activeTab = WalletTab.HOME, error = "") }
        handleIncomingPayload(payload, WalletTab.HOME)
    }

    fun onResponseScanResult(payload: String) {
        val parsed = TpResponseParser.parse(payload)
        if (parsed.isError || (parsed.rawTransaction == null && parsed.signature == null && parsed.bitcoinTxHex == null)) {
            return setError("无法解析树莓派结果")
        }

        viewModelScope.launch {
            when {
                parsed.bitcoinTxHex != null -> {
                    val accountId = _uiState.value.preparedBitcoinAccountId
                        ?: return@launch setError("当前没有待广播的 BTC 请求")
                    val account = _uiState.value.bitcoinWatchAccounts.firstOrNull { it.id == accountId }
                        ?: return@launch setError("未找到对应的 BTC 账户")
                    try {
                        val txid = BitcoinTransferService.broadcastTransaction(account.prefix, parsed.bitcoinTxHex)
                        _uiState.update {
                            it.copy(
                                signQrBitmap = null,
                                signQrPages = emptyList(),
                                signQrPageIndex = 0,
                                pendingResponseType = null,
                                preparedBitcoinAccountId = null,
                                requestTitle = "",
                                requestSummary = "",
                                transferInfo = "",
                                dappInfo = "",
                                relayHint = "",
                                error = "",
                                info = "BTC 交易已广播：$txid",
                                requestInput = "",
                            )
                        }
                        recordLocalActivity(
                            WalletActivityItem(
                                id = "btc-$txid",
                                chainId = WalletChains.DEFAULT.chainId,
                                kind = WalletActivityKind.OUTGOING_TX,
                                title = "BTC 交易已广播",
                                subtitle = account.label,
                                detail = _uiState.value.requestSummary,
                                amountLabel = extractAmountLabel(_uiState.value.requestSummary).ifBlank { "BTC" },
                                statusLabel = "已广播",
                                timestamp = System.currentTimeMillis(),
                                txHash = txid,
                            )
                        )
                        syncBitcoinWatchAccount(accountId)
                    } catch (e: Exception) {
                        setError("BTC 广播失败: ${e.message}")
                    }
                }

                parsed.rawTransaction != null -> {
                    val browserRequest = pendingInjectedBrowserRequest
                    if (browserRequest != null && browserRequest.method.equals("eth_signTransaction", ignoreCase = true)) {
                        emitBrowserResolve(
                            browserRequest.browserRequestId,
                            org.json.JSONObject.quote(parsed.rawTransaction),
                        )
                        pendingInjectedBrowserRequest = null
                        recordLocalActivity(
                            WalletActivityItem(
                                id = "browser-signed-tx-${System.currentTimeMillis()}",
                                chainId = _uiState.value.preparedRequestChainId ?: _uiState.value.selectedChainId,
                                kind = WalletActivityKind.DAPP,
                                title = "Hyperliquid 页面已拿到签名交易",
                                subtitle = browserRequest.origin.ifBlank { "app.hyperliquid.xyz" },
                                detail = _uiState.value.requestSummary,
                                statusLabel = "已回传页面",
                                timestamp = System.currentTimeMillis(),
                            )
                        )
                        _uiState.update {
                            it.copy(
                                signQrBitmap = null,
                                signQrPages = emptyList(),
                                signQrPageIndex = 0,
                                pendingResponseType = null,
                                preparedBitcoinAccountId = null,
                                preparedRequestChainId = null,
                                requestTitle = "",
                                requestSummary = "",
                                transferInfo = "",
                                dappInfo = "",
                                relayHint = "",
                                error = "",
                                info = "签名交易已返回给 Hyperliquid 页面",
                                requestInput = "",
                            )
                        }
                        return@launch
                    }

                    val chain = WalletChains.require(_uiState.value.preparedRequestChainId ?: _uiState.value.selectedChainId)
                    try {
                        val hash = EvmRpc.sendRawTransaction(chain, parsed.rawTransaction)
                        val pendingRequest = _uiState.value.walletConnectPendingRequest
                        val pendingBrowserRequest = pendingInjectedBrowserRequest
                        if (pendingRequest != null) {
                            WalletConnectBridge.respondCurrentRequestResult("0x$hash") { result ->
                                result.onFailure { setError("WalletConnect 返回交易哈希失败: ${it.message}") }
                            }
                        }
                        if (pendingBrowserRequest != null) {
                            emitBrowserResolve(
                                pendingBrowserRequest.browserRequestId,
                                org.json.JSONObject.quote("0x$hash"),
                            )
                            pendingInjectedBrowserRequest = null
                        }
                        val explorerUrl = chain.txUrl(hash)
                        recordLocalActivity(
                            WalletActivityItem(
                                id = "tx-$hash",
                                chainId = chain.chainId,
                                kind = WalletActivityKind.OUTGOING_TX,
                                title = "${chain.shortName} 交易已广播",
                                subtitle = _uiState.value.transferInfo.lineSequence().firstOrNull().orEmpty(),
                                detail = _uiState.value.requestSummary,
                                amountLabel = extractAmountLabel(_uiState.value.transferInfo),
                                statusLabel = when {
                                    pendingRequest != null -> "已返回 DApp"
                                    browserRequest != null -> "已返回页面"
                                    else -> "已广播"
                                },
                                timestamp = System.currentTimeMillis(),
                                txHash = "0x$hash",
                                externalUrl = explorerUrl,
                            )
                        )
                        _uiState.update {
                            it.copy(
                                txHash = hash,
                                txHashChainId = chain.chainId,
                                signQrBitmap = null,
                                signQrPages = emptyList(),
                                signQrPageIndex = 0,
                                pendingResponseType = null,
                                preparedBitcoinAccountId = null,
                                preparedRequestChainId = null,
                                requestTitle = "",
                                requestSummary = "",
                                transferInfo = "",
                                dappInfo = "",
                                relayHint = "",
                                error = "",
                                info = when {
                                    pendingRequest != null -> "交易已广播，并已返回给 WalletConnect"
                                    browserRequest != null -> "交易已广播，并已返回给 Hyperliquid 页面"
                                    else -> "交易已广播"
                                },
                                requestInput = "",
                            )
                        }
                        loadBalances(chain.chainId, _uiState.value.selectedAddress, silent = true)
                    } catch (e: Exception) {
                        setError("广播失败: ${e.message}")
                    }
                }

                parsed.signature != null -> {
                    if (pendingHyperliquidApproval != null) {
                        handleHyperliquidApprovalResult(parsed.signature)
                        return@launch
                    }
                    val currentResponseType = _uiState.value.pendingResponseType
                    val browserRequest = pendingInjectedBrowserRequest
                    if (browserRequest != null) {
                        emitBrowserResolve(
                            browserRequest.browserRequestId,
                            org.json.JSONObject.quote(parsed.signature),
                        )
                        pendingInjectedBrowserRequest = null
                    }
                    val chainId = _uiState.value.preparedRequestChainId ?: _uiState.value.selectedChainId
                    val pendingRequest = _uiState.value.walletConnectPendingRequest
                    if (pendingRequest != null) {
                        WalletConnectBridge.respondCurrentRequestResult(parsed.signature) { result ->
                            result.onFailure { setError("WalletConnect 返回签名失败: ${it.message}") }
                        }
                    }
                    recordLocalActivity(
                        WalletActivityItem(
                            id = "sig-${System.currentTimeMillis()}",
                            chainId = chainId,
                            kind = WalletActivityKind.SIGNATURE,
                            title = "签名结果已返回",
                            subtitle = parsed.address.orEmpty().ifBlank { _uiState.value.selectedAddress },
                            detail = _uiState.value.requestSummary,
                            statusLabel = when {
                                pendingRequest != null -> "已回传 DApp"
                                browserRequest != null -> "已回传页面"
                                else -> "待复制"
                            },
                            timestamp = System.currentTimeMillis(),
                        )
                    )
                    _uiState.update {
                        it.copy(
                            lastSignature = if (browserRequest != null || currentResponseType == PendingResponseType.IMPORT_WATCH_ADDRESS) "" else parsed.signature,
                            lastSignatureAddress = if (browserRequest != null || currentResponseType == PendingResponseType.IMPORT_WATCH_ADDRESS) "" else parsed.address.orEmpty(),
                            signQrBitmap = null,
                            signQrPages = emptyList(),
                            signQrPageIndex = 0,
                            pendingResponseType = null,
                            preparedBitcoinAccountId = null,
                            preparedRequestChainId = null,
                            error = "",
                            info = when {
                                currentResponseType == PendingResponseType.IMPORT_WATCH_ADDRESS -> "树莓派地址已返回"
                                pendingRequest != null -> "签名结果已返回给 WalletConnect"
                                browserRequest != null -> "签名结果已返回给 Hyperliquid 页面"
                                else -> "签名结果已返回"
                            },
                        )
                    }
                    if (currentResponseType == PendingResponseType.IMPORT_WATCH_ADDRESS) {
                        val imported = normalizeAddress(parsed.address)
                            ?: return@launch setError("树莓派未返回有效地址")
                        addAddress(imported)
                        _uiState.update {
                            it.copy(
                                info = "已从树莓派导入观察地址: ${shortAddress(imported)}",
                                error = "",
                            )
                        }
                    }
                }
            }
        }
    }

    fun nextSignQrPage() {
        val pages = _uiState.value.signQrPages
        if (pages.size <= 1) return
        updateQrPage((_uiState.value.signQrPageIndex + 1) % pages.size)
    }

    fun prevSignQrPage() {
        val pages = _uiState.value.signQrPages
        if (pages.size <= 1) return
        updateQrPage(if (_uiState.value.signQrPageIndex <= 0) pages.lastIndex else _uiState.value.signQrPageIndex - 1)
    }

    fun clearPreparedRequest() {
        pendingInjectedBrowserRequest?.let {
            emitBrowserReject(it.browserRequestId, 4001, "用户取消了签名请求")
        }
        pendingInjectedBrowserRequest = null
        pendingHyperliquidApproval = null
        _uiState.update {
            it.copy(
                requestTitle = "",
                requestSummary = "",
                transferInfo = "",
                dappInfo = "",
                relayHint = "",
                preparedRequestChainId = null,
                preparedBitcoinAccountId = null,
                signQrPages = emptyList(),
                signQrPageIndex = 0,
                signQrBitmap = null,
                pendingResponseType = null,
                hyperliquidPendingApproval = false,
                error = "",
                info = "",
            )
        }
    }

    private fun bindWalletConnectState() {
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
                                recordLocalActivity(
                                    WalletActivityItem(
                                        id = "dapp-proposal-${System.currentTimeMillis()}",
                                        chainId = _uiState.value.selectedChainId,
                                        kind = WalletActivityKind.DAPP,
                                        title = "WalletConnect 已连接",
                                        subtitle = proposal.peerName.ifBlank { proposal.peerUrl.ifBlank { "未知 DApp" } },
                                        detail = proposal.requiredChains.joinToString(),
                                        statusLabel = "会话已批准",
                                        timestamp = System.currentTimeMillis(),
                                    )
                                )
                                _uiState.update {
                                    it.copy(
                                        info = "WalletConnect 会话已自动批准，可继续在 DApp 中操作",
                                        error = "",
                                    )
                                }
                            }
                            result.onFailure {
                                setError("WalletConnect 自动批准失败: ${it.message}")
                            }
                        }
                    }
                } else if (proposal != null) {
                    _uiState.update {
                        it.copy(
                            info = "收到新的 WalletConnect 连接请求，请手动批准后再继续。",
                            error = "",
                        )
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

    private fun restorePersistedState() {
        val addresses = WalletStorage.readAddresses(prefs, ::normalizeAddress)
        val selected = WalletStorage.readSelectedAddress(prefs, ::normalizeAddress)
        val effectiveSelected = when {
            selected.isNotBlank() && addresses.contains(selected) -> selected
            addresses.isNotEmpty() -> addresses.first()
            else -> ""
        }
        val selectedChain = WalletChains.byId(WalletStorage.readSelectedChainId(prefs))?.chainId
            ?: WalletChains.DEFAULT.chainId
        val contacts = WalletStorage.readContacts(prefs, ::normalizeAddress)
        val evmDerivationPath = WalletStorage.readEvmDerivationPath(prefs)
        val bitcoinWatchAccounts = WalletStorage.readBitcoinWatchAccounts(prefs).map(::enrichBitcoinWatchAccount)
        hyperliquidAgentsByAccount.clear()
        localActivityItems.clear()
        localActivityItems += WalletStorage.readActivity(prefs)
        _uiState.update {
            it.copy(
                addresses = addresses,
                selectedAddress = effectiveSelected,
                evmDerivationPath = evmDerivationPath,
                bitcoinWatchAccounts = bitcoinWatchAccounts,
                bitcoinPrototypeStatus = defaultBitcoinPrototypeStatus(bitcoinWatchAccounts.size),
                selectedChainId = selectedChain,
                transferToken = WalletChains.require(selectedChain).preferredTransferSymbol(),
                contacts = contacts,
                hyperliquidAgent = null,
                hyperliquidStatus = if (effectiveSelected.isBlank()) {
                    "先添加观察地址，再启用 Hyperliquid"
                } else {
                    "为保障安全，Hyperliquid 代理不会保存在本机。每次解锁后需重新授权。"
                },
            )
        }
        emitBrowserAccountsChanged()
        emitBrowserChainChanged()
        publishActivity()
        if (effectiveSelected.isNotBlank()) {
            loadBalances(selectedChain, effectiveSelected)
            refreshHyperliquid(silent = true)
        }
    }

    private fun persistAddresses() {
        val state = _uiState.value
        WalletStorage.writeAddresses(prefs, state.addresses, state.selectedAddress)
    }

    private fun persistContacts() {
        WalletStorage.writeContacts(prefs, _uiState.value.contacts)
    }

    private fun persistBitcoinWatchAccounts() {
        WalletStorage.writeBitcoinWatchAccounts(prefs, _uiState.value.bitcoinWatchAccounts)
    }

    private fun updateBitcoinWatchAccount(
        accountId: String,
        transform: (BitcoinWatchAccount) -> BitcoinWatchAccount,
    ) {
        _uiState.update { state ->
            state.copy(
                bitcoinWatchAccounts = state.bitcoinWatchAccounts.map { account ->
                    if (account.id == accountId) transform(account) else account
                }
            )
        }
        persistBitcoinWatchAccounts()
    }

    private fun persistActivity() {
        WalletStorage.writeActivity(prefs, localActivityItems)
    }

    private fun persistHyperliquidAgents() {
        // Hyperliquid agent private keys are session-only and never persisted.
    }

    private fun syncRecentActivity(chain: WalletChain, address: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(syncingActivity = true) }
            runCatching {
                EvmRpc.getRecentAddressActivity(chain, address)
            }.onSuccess { items ->
                syncedActivityByChain[chain.chainId] = items
                publishActivity()
            }.onFailure {
                syncedActivityByChain.remove(chain.chainId)
                publishActivity()
            }
            _uiState.update { it.copy(syncingActivity = false) }
        }
    }

    private suspend fun buildNativeTransferRequest(
        chain: WalletChain,
        from: String,
        to: String,
        amount: String,
        derivationPath: String,
    ): String {
        val (maxPriority, maxFee) = EvmRpc.getBlockGasParams(chain)
        val nonce = EvmRpc.getNonce(chain, from)
        val valueWei = amountToWei(amount, chain.tokens.first().decimals)
        val gasLimit = EvmRpc.estimateGas(
            chain,
            mapOf(
                "from" to from,
                "to" to to,
                "value" to "0x${valueWei.toString(16)}",
                "data" to "0x",
            )
        )
        return TpRequestBuilder.buildSignTransactionRequest(
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
            ),
            chain = chain,
            derivationPath = derivationPath,
        )
    }

    private suspend fun buildTokenTransferRequest(
        chain: WalletChain,
        from: String,
        to: String,
        amount: String,
        token: TokenInfo,
        derivationPath: String,
    ): String {
        val tokenAddress = token.address ?: error("该资产不是 ERC20")
        val (maxPriority, maxFee) = EvmRpc.getBlockGasParams(chain)
        val nonce = EvmRpc.getNonce(chain, from)
        val amountWei = amountToWei(amount, token.decimals)
        val data = "a9059cbb" +
            "0".repeat(24) + to.removePrefix("0x").lowercase() +
            amountWei.toString(16).padStart(64, '0')
        val gasLimit = EvmRpc.estimateGas(
            chain,
            mapOf(
                "from" to from,
                "to" to tokenAddress,
                "data" to "0x$data",
            )
        )
        return TpRequestBuilder.buildSignTransactionRequest(
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
            ),
            chain = chain,
            derivationPath = derivationPath,
        )
    }

    private fun selectChainInternal(
        chain: WalletChain,
        persist: Boolean,
        triggerReload: Boolean,
        message: String,
    ) {
        _uiState.update {
            it.copy(
                selectedChainId = chain.chainId,
                transferToken = if (chain.supportsSymbol(it.transferToken)) it.transferToken else chain.preferredTransferSymbol(),
                info = if (message.isBlank()) it.info else message,
                error = "",
            )
        }
        if (persist) {
            WalletStorage.writeSelectedChainId(prefs, chain.chainId)
        }
        if (triggerReload && _uiState.value.selectedAddress.isNotBlank()) {
            loadBalances(chain.chainId, _uiState.value.selectedAddress)
        }
        emitBrowserChainChanged()
    }

    private fun prepareRelayRequest(
        payload: String,
        explicitResponseType: PendingResponseType?,
        explicitTitle: String?,
        focusTab: WalletTab = WalletTab.HOME,
    ) {
        viewModelScope.launch {
            prepareRelayRequestNow(payload, explicitResponseType, explicitTitle, focusTab)
        }
    }

    private suspend fun prepareRelayRequestNow(
        payload: String,
        explicitResponseType: PendingResponseType?,
        explicitTitle: String?,
        focusTab: WalletTab = WalletTab.HOME,
    ): Boolean {
        return try {
            val request = TpQrCodec.parseSignRequest(payload)
            val chain = WalletChains.byId(request.chainId)
                ?: throw IllegalArgumentException("当前不支持链 ${request.chainId}")
            val bundle = RelayQrCodec.buildRelayPayloads(payload)
            val qr = generateQrBitmap(bundle.payloads.first())
            _uiState.update { state ->
                state.copy(
                    selectedChainId = chain.chainId,
                    transferToken = if (chain.supportsSymbol(state.transferToken)) state.transferToken else chain.preferredTransferSymbol(),
                    requestTitle = explicitTitle ?: "${chain.shortName} ${requestTitle(request)}",
                    requestSummary = buildRequestSummary(request),
                    transferInfo = buildTransferInfo(request),
                    dappInfo = buildDappInfo(request),
                    relayHint = if (bundle.payloads.size > 1) {
                        "已生成 ${bundle.payloads.size} 张静态二维码，将自动轮播给离线签名器扫描。"
                    } else {
                        "已生成 1 张静态二维码，可直接给树莓派扫描。"
                    },
                    preparedRequestChainId = chain.chainId,
                    preparedBitcoinAccountId = null,
                    signQrPages = bundle.payloads,
                    signQrPageIndex = 0,
                    signQrBitmap = qr,
                    pendingResponseType = explicitResponseType ?: inferResponseType(request),
                    error = "",
                    info = "请求已准备好，请让树莓派扫描本页二维码。",
                    activeTab = focusTab,
                    txHash = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.BROADCAST_TX) "" else state.txHash,
                    txHashChainId = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.BROADCAST_TX) null else state.txHashChainId,
                    lastSignature = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.SHOW_SIGNATURE) "" else state.lastSignature,
                    lastSignatureAddress = if ((explicitResponseType ?: inferResponseType(request)) == PendingResponseType.SHOW_SIGNATURE) "" else state.lastSignatureAddress,
                )
            }
            true
        } catch (e: Exception) {
            setError("解析请求失败: ${e.message}")
            false
        }
    }

    private fun handleIncomingPayload(payload: String, focusTab: WalletTab) {
        val normalizedPayload = WalletConnectUriParser.extract(payload) ?: payload.trim()
        if (normalizedPayload.startsWith("wc:", ignoreCase = true)) {
            try {
                WalletConnectBridge.pair(normalizedPayload)
                recordLocalActivity(
                    WalletActivityItem(
                        id = "wc-pair-${System.currentTimeMillis()}",
                        chainId = _uiState.value.selectedChainId,
                        kind = WalletActivityKind.DAPP,
                        title = "收到 WalletConnect 配对链接",
                        subtitle = "等待 DApp 发起会话提案",
                        statusLabel = "连接中",
                        timestamp = System.currentTimeMillis(),
                    )
                )
                _uiState.update {
                    it.copy(
                        info = "已接收 WalletConnect 配对链接。收到提案后请在钱包内手动批准。",
                        error = "",
                        activeTab = focusTab,
                    )
                }
            } catch (e: Exception) {
                setError("WalletConnect 配对失败: ${e.message}")
            }
            return
        }
        prepareRelayRequest(normalizedPayload, null, null, focusTab)
    }

    private suspend fun handleWalletConnectRequest(request: WalletConnectPendingRequest) {
        val address = _uiState.value.selectedAddress
        if (address.isBlank()) {
            WalletConnectBridge.respondCurrentRequestError("请先在钱包里选择观察地址", 4001)
            setError("请先选择观察地址，再处理 WalletConnect 请求")
            return
        }
        try {
            when (
                val prepared = WalletConnectRequestCodec.prepare(
                    request = request,
                    selectedAddress = address,
                    activeChainId = _uiState.value.selectedChainId,
                    derivationPath = _uiState.value.evmDerivationPath,
                )
            ) {
                is WalletConnectPreparedRequest.ImmediateResult -> {
                    prepared.switchToChainId?.let { targetChainId ->
                        WalletChains.byId(targetChainId)?.let { chain ->
                            selectChainInternal(
                                chain = chain,
                                persist = true,
                                triggerReload = true,
                                message = "已切换到 ${chain.shortName}",
                            )
                        }
                    }
                    WalletConnectBridge.respondCurrentRequestResult(prepared.result) { result ->
                        result.onFailure { setError("WalletConnect 返回结果失败: ${it.message}") }
                    }
                    recordLocalActivity(
                        WalletActivityItem(
                            id = "wc-immediate-${request.requestId}",
                            chainId = prepared.switchToChainId ?: _uiState.value.selectedChainId,
                            kind = WalletActivityKind.DAPP,
                            title = "DApp 请求已处理",
                            subtitle = request.method,
                            detail = request.peerName.ifBlank { request.peerUrl },
                            statusLabel = "已即时返回",
                            timestamp = System.currentTimeMillis(),
                        )
                    )
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
                        focusTab = WalletTab.HOME,
                    )
                    recordLocalActivity(
                        WalletActivityItem(
                            id = "wc-relay-${request.requestId}",
                            chainId = prepared.chainId,
                            kind = WalletActivityKind.DAPP,
                            title = "DApp 发起 ${request.method}",
                            subtitle = request.peerName.ifBlank { request.peerUrl.ifBlank { "未知 DApp" } },
                            detail = WalletChains.require(prepared.chainId).displayName,
                            statusLabel = if (ok) "待树莓派签名" else "生成二维码失败",
                            timestamp = System.currentTimeMillis(),
                        )
                    )
                    if (!ok) {
                        _uiState.update {
                            it.copy(
                                info = "已收到 WalletConnect 请求 ${request.method}，但未成功生成树莓派二维码。",
                                activeTab = WalletTab.HOME,
                            )
                        }
                    } else {
                        _uiState.update {
                            it.copy(
                                info = "已收到 WalletConnect 请求 ${request.method}，请直接扫描页面上的签名二维码。",
                                error = "",
                                activeTab = WalletTab.HOME,
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
                _uiState.update {
                    it.copy(error = "中转二维码第 ${index + 1} 张生成失败: ${error.message}")
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
        val chain = WalletChains.require(request.chainId)
        val tx = request.txData
        val to = tx.string("to") ?: "-"
        val from = request.address ?: tx.string("from") ?: "-"
        val valueWei = parseQuantity(tx.string("value") ?: "0x0")
        val dataHex = tx.string("data") ?: tx.string("input") ?: "0x"
        val cleanData = cleanHex(dataHex)
        val token = chain.findTokenByAddress(to)

        if (cleanData.startsWith("a9059cbb") && cleanData.length >= 136 && token != null) {
            val recipient = "0x" + cleanData.substring(32, 72)
            val amount = BigInteger(cleanData.substring(72, 136), 16)
            return buildString {
                appendLine("from: $from")
                appendLine("token: ${token.symbol}")
                appendLine("to: $recipient")
                appendLine("amount: ${formatUnits(amount, token.decimals)}")
                appendLine("chainId: ${request.chainId} (${chain.displayName})")
            }.trim()
        }

        return buildString {
            appendLine("from: $from")
            appendLine("to: $to")
            appendLine("value: ${formatUnits(valueWei, chain.tokens.first().decimals)} ${chain.nativeSymbol}")
            appendLine("contractCall: ${if (cleanData.isNotBlank()) "yes" else "no"}")
            if (cleanData.length >= 8) appendLine("methodId: 0x${cleanData.take(8)}")
            appendLine("chainId: ${request.chainId} (${chain.displayName})")
        }.trim()
    }

    private fun buildDappInfo(request: TpSignRequest): String {
        return buildString {
            appendLine("network: ${WalletChains.require(request.chainId).displayName}")
            appendLine("dappName: ${request.dappName ?: "-"}")
            appendLine("dappUrl: ${request.dappUrl ?: "-"}")
            appendLine("source/origin: ${request.dappSource ?: "-"}")
        }.trim()
    }

    private fun buildTransactionSummary(request: TpSignTransactionRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${WalletChains.require(request.chainId).displayName}")
            appendLine("address: ${request.address ?: request.txData.string("from") ?: "-"}")
            appendLine("nonce: ${request.txData.string("nonce") ?: "-"}")
            appendLine("gasLimit: ${request.txData.string("gasLimit") ?: request.txData.string("gas") ?: "-"}")
            appendLine("type: ${request.txData.string("type") ?: "-"}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildPersonalSignSummary(request: TpSignPersonalMessageRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${WalletChains.require(request.chainId).displayName}")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("message: ${preview(request.message)}")
            appendLine("bytes: ${request.message.toByteArray().size}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun buildTypedDataSummary(request: TpSignTypedDataRequest): String {
        return buildString {
            appendLine("action: ${request.action}")
            appendLine("network: ${WalletChains.require(request.chainId).displayName}")
            appendLine("address: ${request.address ?: "-"}")
            appendLine("primaryType: ${request.primaryType ?: "-"}")
            appendLine("chainId: ${request.chainId} (${chainName(request.chainId)})")
            appendLine("bytes: ${request.typedDataJson.toByteArray().size}")
            appendLine("requestId: ${request.requestId ?: "-"}")
        }.trim()
    }

    private fun emitBrowserResolve(requestId: String, resultJsonLiteral: String) {
        _browserCommands.tryEmit(
            InjectedBrowserCommand.Resolve(
                requestId = requestId,
                resultJsonLiteral = resultJsonLiteral,
            )
        )
    }

    private fun emitBrowserReject(requestId: String, code: Int, message: String) {
        _browserCommands.tryEmit(
            InjectedBrowserCommand.Reject(
                requestId = requestId,
                code = code,
                message = message,
            )
        )
    }

    private fun emitBrowserAccountsChanged() {
        val accounts = currentAuthorizedBrowserAccounts()
        _browserCommands.tryEmit(
            InjectedBrowserCommand.AccountsChanged(
                accounts = accounts,
            )
        )
    }

    private fun emitBrowserChainChanged() {
        _browserCommands.tryEmit(
            InjectedBrowserCommand.ChainChanged(
                chainIdHex = WalletChains.require(_uiState.value.selectedChainId).chainIdHex,
            )
        )
    }

    private fun emitBrowserChainChanged(requestId: String) {
        emitBrowserResolve(
            requestId = requestId,
            resultJsonLiteral = org.json.JSONObject.quote(WalletChains.require(_uiState.value.selectedChainId).chainIdHex),
        )
        emitBrowserChainChanged()
    }

    private fun currentAuthorizedBrowserAccounts(): List<String> {
        val state = _uiState.value
        return if (state.browserAuthorized && state.selectedAddress.isNotBlank()) {
            listOf(state.selectedAddress)
        } else {
            emptyList()
        }
    }

    private fun currentBrowserPermissionsJson(origin: String): String {
        val accounts = currentAuthorizedBrowserAccounts()
        if (accounts.isEmpty()) return "[]"
        val effectiveOrigin = origin.ifBlank { _uiState.value.browserAuthorizedOrigin.ifBlank { "https://app.hyperliquid.xyz" } }

        val permission = org.json.JSONObject().apply {
            put("id", "satochip_eth_accounts")
            put("invoker", effectiveOrigin)
            put("parentCapability", "eth_accounts")
            put("date", System.currentTimeMillis())
            put(
                "caveats",
                org.json.JSONArray().put(
                    org.json.JSONObject().apply {
                        put("type", "restrictReturnedAccounts")
                        put("value", org.json.JSONArray(accounts))
                    }
                ),
            )
        }
        return org.json.JSONArray().put(permission).toString()
    }

    private fun currentBrowserRequestPermissionsJson(): String {
        val accounts = currentAuthorizedBrowserAccounts()
        if (accounts.isEmpty()) return "[]"

        val granted = org.json.JSONObject().apply {
            put("parentCapability", "eth_accounts")
            put(
                "caveats",
                org.json.JSONArray().put(
                    org.json.JSONObject().apply {
                        put("type", "restrictReturnedAccounts")
                        put("value", org.json.JSONArray(accounts))
                    }
                ),
            )
        }
        return org.json.JSONArray().put(granted).toString()
    }

    private fun currentBrowserCapabilitiesJson(): String {
        val chainIdHex = WalletChains.require(_uiState.value.selectedChainId).chainIdHex
        return org.json.JSONObject().put(
            chainIdHex,
            org.json.JSONObject().put(
                "atomic",
                org.json.JSONObject().put("status", "unsupported"),
            ),
        ).toString()
    }

    private fun authorizeInjectedBrowser(origin: String) {
        if (_uiState.value.browserAuthorized) return
        _uiState.update {
            it.copy(
                browserAuthorized = true,
                browserAuthorizedOrigin = origin,
                error = "",
            )
        }
    }

    private fun revokeInjectedBrowserAuthorization() {
        if (!_uiState.value.browserAuthorized) return
        _uiState.update { it.copy(browserAuthorized = false, browserAuthorizedOrigin = "", error = "") }
        emitBrowserAccountsChanged()
    }

    fun reportBrowserRuntimeIssue(message: String) {
        val normalized = message.trim()
        if (normalized.isBlank()) return
        if (shouldIgnoreBrowserRuntimeIssue(normalized)) {
            return
        }
        _uiState.update { state ->
            val next = "Hyperliquid 页面异常: ${preview(normalized, 220)}"
            if (state.error == next) state else state.copy(error = next, info = "")
        }
    }

    private fun shouldIgnoreBrowserRuntimeIssue(message: String): Boolean {
        if (message.contains("ResizeObserver loop completed with undelivered notifications", ignoreCase = true)) {
            return true
        }
        if (message.contains("Uncaught (in promise) #<Object>", ignoreCase = true)) {
            return true
        }
        if (
            message.contains("static/js/main", ignoreCase = true) &&
            message.contains("#<Object>", ignoreCase = true)
        ) {
            return true
        }
        val isChartingLibraryNoise = message.contains("charting_library", ignoreCase = true) &&
            (
                message.contains("CommonDelegate:Error: Value is null", ignoreCase = true) ||
                    message.contains("Value is null", ignoreCase = true)
                )
        val isCorsNoise = message.contains("blocked by CORS policy", ignoreCase = true) ||
            (
                message.contains("Access to fetch at", ignoreCase = true) &&
                    message.contains("Response to preflight request", ignoreCase = true)
                ) ||
            (
                message.contains("app.hyperliquid.xyz", ignoreCase = true) &&
                    message.contains("preflight request", ignoreCase = true)
                )
        val isStubNoise = message.contains("__satochipWalletSet", ignoreCase = true)
        return isChartingLibraryNoise || isCorsNoise || isStubNoise
    }

    private suspend fun handleHyperliquidApprovalResult(signatureHex: String) {
        val approval = pendingHyperliquidApproval ?: return
        try {
            val result = HyperliquidApi.approveAgent(approval, signatureHex)
            ensureHyperliquidSuccess(result, "代理授权")
            val savedAgent = approval.agent
            hyperliquidAgentsByAccount[savedAgent.accountAddress.lowercase()] = savedAgent
            persistHyperliquidAgents()
            pendingHyperliquidApproval = null
            recordLocalActivity(
                WalletActivityItem(
                    id = "hyperliquid-approved-${approval.nonce}",
                    chainId = WalletChains.ARBITRUM.chainId,
                    kind = WalletActivityKind.DAPP,
                    title = "Hyperliquid 代理已授权",
                    subtitle = shortAddress(savedAgent.agentAddress),
                    detail = savedAgent.agentName,
                    statusLabel = "可直接交易",
                    timestamp = System.currentTimeMillis(),
                )
            )
            _uiState.update {
                it.copy(
                    hyperliquidPendingApproval = false,
                    hyperliquidAgent = savedAgent.toUi(),
                    hyperliquidStatus = "Hyperliquid 代理已在本次会话授权，锁屏或退到后台后需重新授权。",
                    signQrBitmap = null,
                    signQrPages = emptyList(),
                    signQrPageIndex = 0,
                    pendingResponseType = null,
                    preparedRequestChainId = null,
                    requestTitle = "",
                    requestSummary = "",
                    transferInfo = "",
                    dappInfo = "",
                    relayHint = "",
                    requestInput = "",
                    info = "Hyperliquid 代理授权成功。本次会话内可直接交易，离开应用后需重新授权。",
                    error = "",
                )
            }
            refreshHyperliquid(silent = true)
        } catch (e: Exception) {
            setError("Hyperliquid 授权失败: ${e.message}")
        }
    }

    private fun ensureHyperliquidSuccess(result: org.json.JSONObject, action: String) {
        if (!result.optString("status").equals("ok", ignoreCase = true)) {
            error("Hyperliquid $action 未成功: $result")
        }
    }

    private fun currentHyperliquidAgent(address: String): HyperliquidAgentRecord? {
        val normalized = normalizeAddress(address) ?: return null
        return hyperliquidAgentsByAccount[normalized.lowercase()]
    }

    private fun clearHyperliquidState() {
        pendingHyperliquidApproval = null
        hyperliquidMarketMeta.clear()
        _uiState.update {
            it.copy(
                hyperliquidStatus = "先添加观察地址，再启用 Hyperliquid",
                hyperliquidLoading = false,
                hyperliquidPendingApproval = false,
                hyperliquidAgent = null,
                hyperliquidAccount = null,
                hyperliquidMarkets = emptyList(),
                hyperliquidOpenOrders = emptyList(),
                hyperliquidFills = emptyList(),
            )
        }
    }

    private fun clearSensitiveSessionState() {
        val selectedAddress = _uiState.value.selectedAddress
        pendingHyperliquidApproval = null
        pendingInjectedBrowserRequest = null
        hyperliquidAgentsByAccount.clear()
        _uiState.update {
            it.copy(
                browserAuthorized = false,
                browserAuthorizedOrigin = "",
                hyperliquidPendingApproval = false,
                hyperliquidAgent = null,
                signQrPages = emptyList(),
                signQrPageIndex = 0,
                signQrBitmap = null,
                pendingResponseType = null,
                preparedRequestChainId = null,
                requestTitle = "",
                requestSummary = "",
                transferInfo = "",
                dappInfo = "",
                relayHint = "",
                requestInput = "",
                hyperliquidStatus = if (selectedAddress.isBlank()) {
                    "先添加观察地址，再启用 Hyperliquid"
                } else {
                    "已锁定。为保障安全，请重新授权 Hyperliquid 代理。"
                },
            )
        }
        emitBrowserAccountsChanged()
    }

    private fun normalizeInjectedBrowserOrigin(origin: String): String {
        val parsed = runCatching { Uri.parse(origin.trim()) }.getOrNull() ?: return ""
        val scheme = parsed.scheme?.lowercase() ?: return ""
        val host = parsed.host?.lowercase() ?: return ""
        if (scheme != "https") return ""
        return "$scheme://$host"
    }

    private fun isAllowedInjectedBrowserOrigin(origin: String): Boolean {
        return origin in ALLOWED_INJECTED_BROWSER_ORIGINS
    }

    private fun recordLocalActivity(item: WalletActivityItem) {
        localActivityItems.removeAll { it.id == item.id }
        localActivityItems += item
        localActivityItems.sortByDescending { it.timestamp }
        persistActivity()
        publishActivity()
    }

    private fun publishActivity() {
        val merged = (localActivityItems + syncedActivityByChain.values.flatten())
            .sortedByDescending { it.timestamp }
            .distinctBy {
                if (it.txHash.isNotBlank()) "${it.kind}-${it.chainId}-${it.txHash}-${it.amountLabel}"
                else it.id
            }
        _uiState.update { it.copy(activityItems = merged) }
    }

    private fun normalizeAddress(raw: String?): String? {
        val value = raw.orEmpty().trim().removePrefix("ethereum:")
        if (value.isBlank()) return null
        val address = if (value.startsWith("0x")) value else "0x$value"
        if (address.length != 42) return null
        if (!address.removePrefix("0x").all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) return null
        return address
    }

    private fun normalizeDerivationPath(raw: String?): String? {
        val value = raw.orEmpty().trim()
        if (value.isBlank()) return DEFAULT_EVM_DERIVATION_PATH
        if (!value.startsWith("m")) return null
        if (value == "m") return value
        val segments = value.split("/")
        if (segments.first() != "m") return null
        val valid = segments.drop(1).all { segment ->
            val cleaned = segment.removeSuffix("'").removeSuffix("h").removeSuffix("H")
            cleaned.isNotBlank() && cleaned.all(Char::isDigit)
        }
        return value.takeIf { valid }
    }

    private fun shortAddress(address: String): String {
        return if (address.length <= 14) address else "${address.take(8)}...${address.takeLast(6)}"
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

    private fun calculateUsd(amount: String, priceUsd: Double?): Double? {
        val decimal = amount.toBigDecimalOrNull() ?: return null
        return priceUsd?.let { decimal.multiply(BigDecimal.valueOf(it)).toDouble() }
    }

    private suspend fun enrichMissingPrices(balances: List<AssetBalanceUi>): List<AssetBalanceUi> {
        val needed = balances.filter { it.priceUsd == null }
        if (needed.isEmpty()) return balances
        val symbols = needed.map { it.symbol.uppercase() }.distinct()
        val priceMap = mutableMapOf<String, Double>()
        symbols.forEach { symbol ->
            val price = EvmRpc.fetchCoingeckoPriceForSymbol(symbol)
            if (price != null) priceMap[symbol] = price
        }
        return balances.map { asset ->
            val symbolKey = asset.symbol.uppercase()
            val price = asset.priceUsd ?: priceMap[symbolKey]
            if (price == null) asset else asset.copy(priceUsd = price, usdAmount = calculateUsd(asset.amount, price))
        }
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
        return WalletChains.byId(chainId)?.displayName ?: "Chain $chainId"
    }

    private fun shortAddress(address: String, head: Int = 6, tail: Int = 4): String {
        val normalized = normalizeAddress(address) ?: return address
        return "${normalized.take(head)}...${normalized.takeLast(tail)}"
    }

    private fun HyperliquidAgentRecord.toUi(): HyperliquidAgentUi {
        return HyperliquidAgentUi(
            agentAddress = agentAddress,
            agentName = agentName,
            approvedAt = approvedAt,
            validUntil = validUntil,
        )
    }

    private fun extractAmountLabel(transferInfo: String): String {
        return transferInfo.lineSequence()
            .firstOrNull { it.startsWith("amount:", ignoreCase = true) || it.startsWith("value:", ignoreCase = true) }
            ?.substringAfter(':')
            ?.trim()
            .orEmpty()
    }
}

private fun kotlinx.serialization.json.JsonObject.string(key: String): String? =
    this[key]?.jsonPrimitive?.contentOrNull
