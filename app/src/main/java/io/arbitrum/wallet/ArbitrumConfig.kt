package io.arbitrum.wallet

object ArbitrumConfig {
    const val CHAIN_ID = 42161L
    const val CHAIN_ID_HEX = "0xa4b1"
    const val RPC_URL = "https://arb1.arbitrum.io/rpc"
    const val EXPLORER = "https://arbiscan.io"

    val TOKENS = linkedMapOf(
        "ETH" to TokenInfo("ETH", "Ether", 18, null),
        "USDC" to TokenInfo("USDC", "USD Coin", 6, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"),
        "USDT" to TokenInfo("USDT", "Tether USD", 6, "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"),
    )

    fun findTokenByAddress(address: String?): TokenInfo? {
        if (address.isNullOrBlank()) return null
        return TOKENS.values.firstOrNull { it.address.equals(address, ignoreCase = true) }
    }
}

data class TokenInfo(val symbol: String, val name: String, val decimals: Int, val address: String?)
