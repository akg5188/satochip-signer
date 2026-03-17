package io.arbitrum.wallet

data class InjectedBrowserPendingRequest(
    val browserRequestId: String,
    val method: String,
    val origin: String,
)

sealed interface InjectedBrowserCommand {
    data class Resolve(
        val requestId: String,
        val resultJsonLiteral: String,
    ) : InjectedBrowserCommand

    data class Reject(
        val requestId: String,
        val code: Int,
        val message: String,
    ) : InjectedBrowserCommand

    data class AccountsChanged(
        val accounts: List<String>,
    ) : InjectedBrowserCommand

    data class ChainChanged(
        val chainIdHex: String,
    ) : InjectedBrowserCommand
}
