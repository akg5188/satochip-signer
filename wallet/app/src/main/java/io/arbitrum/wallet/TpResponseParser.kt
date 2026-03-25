package io.arbitrum.wallet

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.URLDecoder

private val json = Json { ignoreUnknownKeys = true }

data class ParsedResponse(
    val rawTransaction: String?,
    val bitcoinTxHex: String?,
    val signature: String?,
    val address: String?,
    val isError: Boolean = false,
)

object TpResponseParser {
    fun parse(responsePayload: String): ParsedResponse {
        val raw = responsePayload.trim()
        if (raw.isBlank()) return ParsedResponse(null, null, null, null, isError = true)

        if (raw.startsWith("btctx:", ignoreCase = true)) {
            val txHex = raw.substringAfter(':').trim()
            return if (txHex.isBlank()) {
                ParsedResponse(null, null, null, null, isError = true)
            } else {
                ParsedResponse(rawTransaction = null, bitcoinTxHex = txHex, signature = null, address = null)
            }
        }

        val dash = raw.indexOf('-')
        if (dash <= 0) return ParsedResponse(null, null, null, null, isError = true)

        val queryPart = raw.substring(dash + 1).removePrefix("?")
        val dataRaw = parseQuery(queryPart)["data"] ?: return ParsedResponse(null, null, null, null, isError = true)
        val dataObj = try {
            json.parseToJsonElement(dataRaw).jsonObject
        } catch (e: Throwable) {
            return ParsedResponse(null, null, null, null, isError = true)
        }

        val rawTx = dataObj["rawTransaction"]?.jsonPrimitive?.content
        val sig = dataObj["signature"]?.jsonPrimitive?.content
        val addr = dataObj["address"]?.jsonPrimitive?.content

        return ParsedResponse(rawTransaction = rawTx, bitcoinTxHex = null, signature = sig, address = addr)
    }

    private fun parseQuery(queryRaw: String): Map<String, String> {
        val result = mutableMapOf<String, String>()
        val marker = queryRaw.indexOf("data=")
        if (marker >= 0) {
            queryRaw.substring(0, marker).split('&').forEach { piece ->
                val eq = piece.indexOf('=')
                if (eq > 0) result[piece.substring(0, eq)] = URLDecoder.decode(piece.substring(eq + 1), "UTF-8")
            }
            result["data"] = URLDecoder.decode(queryRaw.substring(marker + 5), "UTF-8")
            return result
        }
        queryRaw.split('&').forEach { piece ->
            val eq = piece.indexOf('=')
            if (eq > 0) result[piece.substring(0, eq)] = URLDecoder.decode(piece.substring(eq + 1), "UTF-8")
        }
        return result
    }
}
