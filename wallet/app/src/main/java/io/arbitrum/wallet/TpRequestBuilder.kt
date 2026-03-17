package io.arbitrum.wallet

import org.json.JSONObject
import java.math.BigInteger
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * 构建与 pi-signer 兼容的离线签名请求字符串。
 * 内部仍使用历史前缀以保持与现有树莓派固件兼容。
 */
object TpRequestBuilder {
    private const val NAMESPACE = "tp"
    private const val VERSION = "1.0"
    private const val PROTOCOL = "ArbitrumWallet"
    // Compatibility for older Pi signer builds:
    // use signTypeDataV4 (single 'd' after Type) instead of signTypedDataV4.
    private const val TYPED_DATA_ACTION = "signTypeDataV4"

    fun buildSignTransactionRequest(
        fromAddress: String,
        txData: TxData,
        chain: WalletChain = WalletChains.DEFAULT,
        requestId: String = java.util.UUID.randomUUID().toString(),
    ): String {
        val txJson = JSONObject().apply {
            put("from", txData.from ?: fromAddress)
            put("to", txData.to)
            put("value", txData.value.toString())
            put("data", txData.data)
            put("gasLimit", txData.gasLimit.toString())
            put("chainId", chain.chainIdHex)
            txData.gasPrice?.let { put("gasPrice", it.toString()) }
            txData.maxFeePerGas?.let { put("maxFeePerGas", it.toString()) }
            txData.maxPriorityFeePerGas?.let { put("maxPriorityFeePerGas", it.toString()) }
            txData.nonce?.let { put("nonce", it.toString()) }
            put("type", txData.type)
        }
        val dataJson = JSONObject().apply {
            put("address", fromAddress)
            put("txData", txJson)
        }
        val query = buildQuery(
            "version" to VERSION,
            "protocol" to PROTOCOL,
            "network" to chain.slug,
            "chain_id" to chain.chainId.toString(),
            "requestId" to requestId,
            "data" to dataJson.toString(),
        )
        return "$NAMESPACE:signTransaction-$query"
    }

    fun buildPersonalSignRequest(
        address: String,
        message: String,
        chain: WalletChain = WalletChains.DEFAULT,
        requestId: String = java.util.UUID.randomUUID().toString(),
    ): String {
        val dataJson = JSONObject().apply {
            put("address", address)
            put("message", message)
        }
        val query = buildQuery(
            "version" to VERSION,
            "protocol" to PROTOCOL,
            "network" to chain.slug,
            "chain_id" to chain.chainId.toString(),
            "requestId" to requestId,
            "data" to dataJson.toString(),
        )
        return "$NAMESPACE:personalSign-$query"
    }

    fun buildSignTypedDataRequest(
        address: String,
        typedDataJson: String,
        chain: WalletChain = WalletChains.DEFAULT,
        requestId: String = java.util.UUID.randomUUID().toString(),
        dappName: String? = null,
        dappUrl: String? = null,
        dappSource: String? = null,
    ): String {
        val messageObj = JSONObject(typedDataJson)
        val dataJson = JSONObject().apply {
            put("address", address)
            put("message", messageObj)
            dappName?.takeIf { it.isNotBlank() }?.let { put("dappName", it) }
            dappUrl?.takeIf { it.isNotBlank() }?.let { put("dappUrl", it) }
            dappSource?.takeIf { it.isNotBlank() }?.let { put("source", it) }
        }
        val dataStr = dataJson.toString()
        val query = buildQuery(
            "version" to VERSION,
            "protocol" to PROTOCOL,
            "network" to chain.slug,
            "chain_id" to chain.chainId.toString(),
            "requestId" to requestId,
            "dappName" to dappName.orEmpty(),
            "dappUrl" to dappUrl.orEmpty(),
            "source" to dappSource.orEmpty(),
            "data" to dataStr,
        )
        return "$NAMESPACE:$TYPED_DATA_ACTION-$query"
    }

    private fun buildQuery(vararg pairs: Pair<String, String>): String =
        pairs.filter { it.second.isNotBlank() }.joinToString("&") { (k, v) ->
            "$k=${URLEncoder.encode(v, StandardCharsets.UTF_8.name())}"
        }
}

data class TxData(
    val from: String?,
    val to: String,
    val value: BigInteger,
    val data: String,
    val gasLimit: BigInteger,
    val nonce: BigInteger? = null,
    val gasPrice: BigInteger? = null,
    val maxFeePerGas: BigInteger? = null,
    val maxPriorityFeePerGas: BigInteger? = null,
    val type: Int = 2,
)
