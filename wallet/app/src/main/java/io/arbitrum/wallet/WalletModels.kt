package io.arbitrum.wallet

import android.graphics.Bitmap

enum class WalletTab {
    HOME,
    ACTIVITY,
    DISCOVER,
}

enum class HyperliquidOrderMode {
    MARKET,
    LIMIT,
}

enum class PendingResponseType {
    BROADCAST_TX,
    SHOW_SIGNATURE,
    RETURN_RAW_TRANSACTION,
}

enum class WalletActivityKind {
    OUTGOING_TX,
    SIGNATURE,
    DAPP,
    SYSTEM,
    ONCHAIN,
}

data class AssetBalanceUi(
    val symbol: String,
    val name: String,
    val amount: String,
    val contractAddress: String? = null,
    val isNative: Boolean = false,
)

data class ChainPortfolioUi(
    val chainId: Long,
    val assets: List<AssetBalanceUi> = emptyList(),
    val lastUpdatedAt: Long = 0L,
    val status: String = "",
)

data class TransferContact(
    val id: String,
    val name: String,
    val address: String,
    val note: String = "",
    val chainId: Long? = null,
)

data class WalletActivityItem(
    val id: String,
    val chainId: Long,
    val kind: WalletActivityKind,
    val title: String,
    val subtitle: String,
    val detail: String = "",
    val amountLabel: String = "",
    val statusLabel: String = "",
    val timestamp: Long,
    val txHash: String = "",
    val externalUrl: String = "",
)

data class HyperliquidAgentUi(
    val agentAddress: String,
    val agentName: String,
    val approvedAt: Long,
    val validUntil: Long? = null,
)

data class HyperliquidAccountUi(
    val accountValue: String = "",
    val marginUsed: String = "",
    val withdrawable: String = "",
    val notionalPosition: String = "",
)

data class HyperliquidMarketUi(
    val name: String,
    val midPrice: String,
    val dayVolume: String,
    val fundingRate: String,
    val openInterest: String,
    val szDecimals: Int,
    val maxLeverage: Int,
)

data class HyperliquidOpenOrderUi(
    val oid: Long,
    val coin: String,
    val sideLabel: String,
    val limitPrice: String,
    val size: String,
    val timestamp: Long,
)

data class HyperliquidFillUi(
    val id: String,
    val coin: String,
    val sideLabel: String,
    val price: String,
    val size: String,
    val pnl: String,
    val timestamp: Long,
)

data class WalletUiState(
    val activeTab: WalletTab = WalletTab.HOME,
    val newAddressInput: String = "",
    val addresses: List<String> = emptyList(),
    val selectedAddress: String = "",
    val browserAuthorized: Boolean = false,
    val selectedChainId: Long = WalletChains.DEFAULT.chainId,
    val chainPortfolios: Map<Long, ChainPortfolioUi> = emptyMap(),
    val loadingBalances: Boolean = false,
    val syncingActivity: Boolean = false,
    val error: String = "",
    val info: String = "",
    val transferTo: String = "",
    val transferAmount: String = "",
    val transferToken: String = WalletChains.DEFAULT.preferredTransferSymbol(),
    val contacts: List<TransferContact> = emptyList(),
    val contactNameInput: String = "",
    val contactAddressInput: String = "",
    val contactNoteInput: String = "",
    val requestInput: String = "",
    val requestTitle: String = "",
    val requestSummary: String = "",
    val transferInfo: String = "",
    val dappInfo: String = "",
    val relayHint: String = "",
    val preparedRequestChainId: Long? = null,
    val walletConnectStatus: String = "",
    val walletConnectProposal: WalletConnectProposalUi? = null,
    val walletConnectPendingRequest: WalletConnectPendingRequest? = null,
    val signQrPages: List<String> = emptyList(),
    val signQrPageIndex: Int = 0,
    val signQrBitmap: Bitmap? = null,
    val pendingResponseType: PendingResponseType? = null,
    val txHash: String = "",
    val txHashChainId: Long? = null,
    val lastSignature: String = "",
    val lastSignatureAddress: String = "",
    val activityItems: List<WalletActivityItem> = emptyList(),
    val hyperliquidStatus: String = "",
    val hyperliquidLoading: Boolean = false,
    val hyperliquidPendingApproval: Boolean = false,
    val hyperliquidAgent: HyperliquidAgentUi? = null,
    val hyperliquidAccount: HyperliquidAccountUi? = null,
    val hyperliquidMarkets: List<HyperliquidMarketUi> = emptyList(),
    val hyperliquidSelectedMarket: String = "BTC",
    val hyperliquidOrderMode: HyperliquidOrderMode = HyperliquidOrderMode.MARKET,
    val hyperliquidOrderSideBuy: Boolean = true,
    val hyperliquidOrderSizeInput: String = "",
    val hyperliquidOrderPriceInput: String = "",
    val hyperliquidReduceOnly: Boolean = false,
    val hyperliquidOpenOrders: List<HyperliquidOpenOrderUi> = emptyList(),
    val hyperliquidFills: List<HyperliquidFillUi> = emptyList(),
)
