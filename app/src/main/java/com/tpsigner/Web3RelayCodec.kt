package com.smartcard.signer

import android.util.Base64
import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.zip.DeflaterOutputStream
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

enum class RelayWallet(
    val displayName: String,
    val shortName: String
) {
    TOKENPOCKET("TokenPocket", "TP"),
    OKX("OKX Wallet", "OKX"),
    BITGET("Bitget Wallet", "Bitget")
}

data class Web3RelayRequest(
    val wallet: RelayWallet,
    val rawPayload: String,
    val detectedFormat: String,
    val qrType: String,
    val actionHint: String,
    val chainHint: String,
    val detailText: String
)

object Web3RelayCodec {
    private const val PREFIX = "w3r1:"
    private const val CHUNK_CHARS = 56

    fun parse(wallet: RelayWallet, raw: String): Web3RelayRequest {
        val payload = raw.trim()
        require(payload.isNotBlank()) { "二维码内容为空" }

        val lowered = payload.lowercase(Locale.US)
        if (lowered.startsWith("wc:")) {
            throw IllegalArgumentException(
                "这是 WalletConnect 二维码，需要联网中继；请在 ${wallet.displayName} 里选择 Keystone/二维码硬件钱包模式。"
            )
        }

        val urType = extractUrType(lowered)
        val detectedFormat = when {
            urType != null -> "Keystone / AirGap UR"
            lowered.startsWith("ethereum:") -> "Ethereum URI"
            lowered.startsWith("okx://") || lowered.startsWith("okex://") -> "OKX DeepLink"
            lowered.startsWith("bitkeep://") || lowered.startsWith("bitget://") -> "Bitget DeepLink"
            payload.startsWith("{") -> "JSON Web3 请求"
            else -> "Web3 原始二维码"
        }

        val actionHint = when (urType) {
            "eth-sign-request" -> "EVM 签名请求"
            "eth-signature" -> "EVM 签名结果"
            "crypto-psbt" -> "BTC PSBT"
            "crypto-hdkey", "crypto-account" -> "账户导入/同步"
            else -> inferAction(payload)
        }

        val chainHint = inferChain(payload)
        val detail = buildString {
            appendLine("wallet: ${wallet.displayName}")
            appendLine("format: $detectedFormat")
            appendLine("qrType: ${urType ?: "-"}")
            appendLine("action: $actionHint")
            appendLine("chain: $chainHint")
            appendLine("chars: ${payload.length}")
            appendLine("internet: disabled")
            append("note: 手机只做低密度中转，不保存私钥。")
        }

        return Web3RelayRequest(
            wallet = wallet,
            rawPayload = payload,
            detectedFormat = detectedFormat,
            qrType = urType ?: "-",
            actionHint = actionHint,
            chainHint = chainHint,
            detailText = detail
        )
    }

    fun buildRelayPayloads(request: Web3RelayRequest): RelayQrBundle {
        val envelope = buildJsonObject {
            put("version", JsonPrimitive(1))
            put("wallet", JsonPrimitive(request.wallet.shortName))
            put("wallet_name", JsonPrimitive(request.wallet.displayName))
            put("format", JsonPrimitive(request.detectedFormat))
            put("qr_type", JsonPrimitive(request.qrType))
            put("action", JsonPrimitive(request.actionHint))
            put("chain", JsonPrimitive(request.chainHint))
            put("payload", JsonPrimitive(request.rawPayload))
        }.toString()

        val encoded = Base64.encodeToString(
            deflateUtf8(envelope),
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
        val crc = TpQrCodec.crc32Decimal(encoded)
        val chunks = encoded.chunked(CHUNK_CHARS)
        val pages = chunks.mapIndexed { index, chunk ->
            "$PREFIX${index + 1}/${chunks.size}.$crc.$chunk"
        }
        return RelayQrBundle(payloads = pages, isFragmented = pages.size > 1)
    }

    private fun extractUrType(lowered: String): String? {
        if (!lowered.startsWith("ur:")) return null
        val body = lowered.removePrefix("ur:")
        val slash = body.indexOf('/')
        if (slash <= 0) return null
        return body.substring(0, slash).takeIf { it.isNotBlank() }
    }

    private fun inferAction(payload: String): String {
        val lowered = payload.lowercase(Locale.US)
        return when {
            "signtypeddata" in lowered || "sign_typed_data" in lowered -> "TypedData 签名"
            "personalsign" in lowered || "personal_sign" in lowered -> "消息签名"
            "signtransaction" in lowered || "eth_sendtransaction" in lowered -> "交易签名"
            "approve" in lowered -> "授权/approve"
            "transfer" in lowered -> "转账/transfer"
            else -> "待树莓派解析"
        }
    }

    private fun inferChain(payload: String): String {
        val lowered = payload.lowercase(Locale.US)
        return when {
            "42161" in lowered || "arbitrum" in lowered -> "Arbitrum One"
            "8453" in lowered || "base" in lowered -> "Base"
            "137" in lowered || "polygon" in lowered -> "Polygon"
            "56" in lowered || "bsc" in lowered || "bnb" in lowered -> "BNB Chain"
            "chain_id=1" in lowered || "\"chainid\":1" in lowered || "\"chainid\":\"1\"" in lowered || "ethereum" in lowered || "eth-" in lowered -> "Ethereum/EVM"
            else -> "Web3"
        }
    }

    private fun deflateUtf8(value: String): ByteArray {
        val out = ByteArrayOutputStream()
        DeflaterOutputStream(out).use { deflater ->
            deflater.write(value.toByteArray(StandardCharsets.UTF_8))
        }
        return out.toByteArray()
    }
}
