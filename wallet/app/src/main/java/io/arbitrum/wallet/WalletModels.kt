package io.arbitrum.wallet

import android.graphics.Bitmap

enum class WalletTab {
    HOME,
    ACTIVITY,
    DISCOVER,
}

enum class PendingResponseType {
    BROADCAST_TX,
    BROADCAST_BTC_TX,
    SHOW_SIGNATURE,
    RETURN_RAW_TRANSACTION,
    IMPORT_WATCH_ADDRESS,
}

const val DEFAULT_EVM_DERIVATION_PATH = "m/44'/60'/0'/0/0"

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
    val priceUsd: Double? = null,
    val usdAmount: Double? = null,
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

data class TrustedDappEntry(
    val host: String,
    val chainId: Long,
    val address: String,
    val trustedAt: Long = 0L,
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

data class BitcoinDerivedAddressPreview(
    val branch: Int,
    val branchLabel: String,
    val index: Int,
    val path: String,
    val address: String,
)

data class BitcoinWatchAccount(
    val id: String,
    val label: String,
    val xpub: String,
    val prefix: String,
    val networkLabel: String,
    val scriptTypeLabel: String,
    val accountPathHint: String,
    val sourceLabel: String = "Imported from offline-signer get-xpub",
    val importedAt: Long,
    val accountFingerprintHex: String = "",
    val receivePreview: List<BitcoinDerivedAddressPreview> = emptyList(),
    val changePreview: List<BitcoinDerivedAddressPreview> = emptyList(),
    val derivationError: String = "",
    val balanceSats: Long = 0,
    val priceUsd: Double? = null,
    val utxoCount: Int = 0,
    val nextReceiveAddress: String = "",
    val nextChangeAddress: String = "",
    val lastSyncStatus: String = "",
    val lastSyncAt: Long = 0,
    val syncing: Boolean = false,
    val recentActivity: List<WalletActivityItem> = emptyList(),
)

data class WalletUiState(
    val activeTab: WalletTab = WalletTab.HOME,
    val newAddressInput: String = "",
    val addresses: List<String> = emptyList(),
    val selectedAddress: String = "",
    val evmDerivationPath: String = DEFAULT_EVM_DERIVATION_PATH,
    val bitcoinImportInput: String = "",
    val bitcoinWatchAccounts: List<BitcoinWatchAccount> = emptyList(),
    val bitcoinPrototypeStatus: String = defaultBitcoinPrototypeStatus(0),
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
    val trustedDappEntries: List<TrustedDappEntry> = emptyList(),
    val walletConnectProposal: WalletConnectProposalUi? = null,
    val walletConnectPendingRequest: WalletConnectPendingRequest? = null,
    val preparingRequest: Boolean = false,
    val signQrPages: List<String> = emptyList(),
    val signQrPageIndex: Int = 0,
    val signQrBitmap: Bitmap? = null,
    val pendingResponseType: PendingResponseType? = null,
    val preparedBitcoinAccountId: String? = null,
    val pendingBroadcastRawTransaction: String = "",
    val pendingBroadcastBitcoinTxHex: String = "",
    val txHash: String = "",
    val txHashChainId: Long? = null,
    val txHashExplorerUrl: String = "",
    val lastSignature: String = "",
    val lastSignatureAddress: String = "",
    val activityItems: List<WalletActivityItem> = emptyList(),
)
