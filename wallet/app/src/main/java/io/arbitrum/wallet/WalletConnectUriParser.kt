package io.arbitrum.wallet

import java.net.URLDecoder
import java.nio.charset.StandardCharsets

object WalletConnectUriParser {
    private val wcRegex = Regex("""wc:[^\s"'<>]+""", RegexOption.IGNORE_CASE)

    fun extract(input: String): String? {
        if (input.isBlank()) return null
        val candidates = mutableListOf(input.trim())
        var decoded = input.trim()
        repeat(3) {
            val next = runCatching {
                URLDecoder.decode(decoded, StandardCharsets.UTF_8.name())
            }.getOrNull() ?: return@repeat
            if (next == decoded) return@repeat
            decoded = next
            candidates += decoded
        }
        for (candidate in candidates) {
            val direct = candidate.trim()
            if (direct.startsWith("wc:", ignoreCase = true)) return direct
            wcRegex.find(direct)?.value?.let { return it.trim() }
        }
        return null
    }
}

