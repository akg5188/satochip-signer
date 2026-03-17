package io.arbitrum.wallet

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.util.concurrent.TimeUnit

data class TokenTransferActivity(
    val chainId: Long,
    val token: TokenInfo,
    val txHash: String,
    val blockNumber: Long,
    val timestamp: Long,
    val from: String,
    val to: String,
    val amount: BigInteger,
    val incoming: Boolean,
)

object EvmRpc {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private const val JSON_MEDIA = "application/json"
    private const val TRANSFER_TOPIC =
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    private val fallbackGasPrice = BigInteger("1000000000")

    suspend fun getBalance(chain: WalletChain, address: String): BigInteger = withContext(Dispatchers.IO) {
        val resp = post(chain, buildRequest("eth_getBalance", JSONArray().put(address).put("latest")))
        parseHexResult(resp)
    }

    suspend fun getTokenBalance(chain: WalletChain, tokenAddress: String, walletAddress: String): BigInteger = withContext(Dispatchers.IO) {
        val data = "0x70a08231" + "0".repeat(24) + walletAddress.removePrefix("0x").lowercase()
        val params = JSONArray().put(JSONObject().put("to", tokenAddress).put("data", data)).put("latest")
        val resp = post(chain, buildRequest("eth_call", params))
        parseHexResult(resp)
    }

    suspend fun getNonce(chain: WalletChain, address: String): BigInteger = withContext(Dispatchers.IO) {
        val resp = post(chain, buildRequest("eth_getTransactionCount", JSONArray().put(address).put("pending")))
        parseHexResult(resp)
    }

    suspend fun sendRawTransaction(chain: WalletChain, rawTxHex: String): String = withContext(Dispatchers.IO) {
        val raw = rawTxHex.ensureHexPrefix()
        val resp = post(chain, buildRequest("eth_sendRawTransaction", JSONArray().put(raw)))
        val obj = JSONObject(resp)
        throwIfError(obj)
        obj.optString("result", "").removePrefix("0x")
    }

    suspend fun estimateGas(chain: WalletChain, tx: Map<String, String>): BigInteger = withContext(Dispatchers.IO) {
        val params = JSONObject().apply {
            tx["from"]?.let { put("from", it) }
            tx["to"]?.let { put("to", it) }
            tx["value"]?.let { put("value", it) }
            tx["data"]?.let { put("data", it) }
        }
        val resp = post(chain, buildRequest("eth_estimateGas", JSONArray().put(params)))
        parseHexResult(resp, "0x5208")
    }

    suspend fun getGasPrice(chain: WalletChain): BigInteger = withContext(Dispatchers.IO) {
        val resp = post(chain, buildRequest("eth_gasPrice", JSONArray()))
        parseHexResult(resp)
    }

    suspend fun getBlockGasParams(chain: WalletChain): Pair<BigInteger, BigInteger> = withContext(Dispatchers.IO) {
        val resp = post(chain, buildRequest("eth_getBlockByNumber", JSONArray().put("latest").put(false)))
        val obj = JSONObject(resp)
        throwIfError(obj)
        val block = obj.optJSONObject("result")
        val baseFee = block?.optString("baseFeePerGas", "0x0")
            ?.takeIf { it.isNotBlank() }
            ?.let { parseHex(it) }
            ?: fallbackGasPrice
        val maxPriority = baseFee.divide(BigInteger.TEN).coerceAtLeast(fallbackGasPrice)
        val maxFee = baseFee.multiply(BigInteger.valueOf(2)).coerceAtLeast(fallbackGasPrice.multiply(BigInteger.TWO))
        maxPriority to maxFee
    }

    suspend fun getRecentTokenTransfers(
        chain: WalletChain,
        walletAddress: String,
        limit: Int = 10,
    ): List<TokenTransferActivity> = withContext(Dispatchers.IO) {
        val tokens = chain.tokens.filter { it.address != null }
        if (tokens.isEmpty()) return@withContext emptyList()

        val latestBlock = getBlockNumber(chain)
        val fromBlock = (latestBlock - chain.historyLookbackBlocks).coerceAtLeast(0)
        val encodedAddress = "0x" + walletAddress.removePrefix("0x").lowercase().padStart(64, '0')
        val transfers = linkedMapOf<String, TokenTransferActivity>()

        tokens.forEach { token ->
            val contract = token.address ?: return@forEach
            fetchTokenLogs(chain, contract, fromBlock, latestBlock, JSONArray().put(TRANSFER_TOPIC).put(encodedAddress))
                .forEach { log ->
                    val txHash = log.optString("transactionHash")
                    val blockNumber = parseHex(log.optString("blockNumber", "0x0")).toLong()
                    val amount = parseHex(log.optString("data", "0x0"))
                    val to = topicToAddress(log.optJSONArray("topics")?.optString(2))
                    transfers["$txHash-out-$contract"] = TokenTransferActivity(
                        chainId = chain.chainId,
                        token = token,
                        txHash = txHash,
                        blockNumber = blockNumber,
                        timestamp = 0L,
                        from = walletAddress,
                        to = to,
                        amount = amount,
                        incoming = false,
                    )
                }
            fetchTokenLogs(chain, contract, fromBlock, latestBlock, JSONArray().put(TRANSFER_TOPIC).put(JSONObject.NULL).put(encodedAddress))
                .forEach { log ->
                    val txHash = log.optString("transactionHash")
                    val blockNumber = parseHex(log.optString("blockNumber", "0x0")).toLong()
                    val amount = parseHex(log.optString("data", "0x0"))
                    val from = topicToAddress(log.optJSONArray("topics")?.optString(1))
                    transfers["$txHash-in-$contract"] = TokenTransferActivity(
                        chainId = chain.chainId,
                        token = token,
                        txHash = txHash,
                        blockNumber = blockNumber,
                        timestamp = 0L,
                        from = from,
                        to = walletAddress,
                        amount = amount,
                        incoming = true,
                    )
                }
        }

        val blockTimestamps = transfers.values
            .map { it.blockNumber }
            .distinct()
            .associateWith { getBlockTimestamp(chain, it) }

        transfers.values
            .map { it.copy(timestamp = blockTimestamps[it.blockNumber] ?: System.currentTimeMillis()) }
            .sortedByDescending { it.timestamp }
            .take(limit)
    }

    private fun fetchTokenLogs(
        chain: WalletChain,
        tokenAddress: String,
        fromBlock: Long,
        toBlock: Long,
        topics: JSONArray,
    ): List<JSONObject> {
        val filter = JSONObject()
            .put("address", tokenAddress)
            .put("fromBlock", "0x${fromBlock.toString(16)}")
            .put("toBlock", "0x${toBlock.toString(16)}")
            .put("topics", topics)
        val resp = post(chain, buildRequest("eth_getLogs", JSONArray().put(filter)))
        val obj = JSONObject(resp)
        throwIfError(obj)
        val array = obj.optJSONArray("result") ?: return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                array.optJSONObject(index)?.let(::add)
            }
        }
    }

    private fun getBlockNumber(chain: WalletChain): Long {
        val resp = post(chain, buildRequest("eth_blockNumber", JSONArray()))
        return parseHexResult(resp).toLong()
    }

    private fun getBlockTimestamp(chain: WalletChain, blockNumber: Long): Long {
        val params = JSONArray().put("0x${blockNumber.toString(16)}").put(false)
        val resp = post(chain, buildRequest("eth_getBlockByNumber", params))
        val obj = JSONObject(resp)
        throwIfError(obj)
        val ts = obj.optJSONObject("result")?.optString("timestamp", "0x0").orEmpty()
        val seconds = parseHex(ts).toLong()
        return if (seconds > 0) seconds * 1000 else System.currentTimeMillis()
    }

    private fun buildRequest(method: String, params: JSONArray): String {
        return JSONObject()
            .put("jsonrpc", "2.0")
            .put("method", method)
            .put("params", params)
            .put("id", 1)
            .toString()
    }

    private fun parseHexResult(response: String, default: String = "0x0"): BigInteger {
        val obj = JSONObject(response)
        throwIfError(obj)
        val result = obj.optString("result", default)
        if (result == "0x" || result.isEmpty()) return BigInteger.ZERO
        return parseHex(result)
    }

    private fun parseHex(value: String): BigInteger {
        val normalized = value.removePrefix("0x").removePrefix("0X").ifBlank { "0" }
        return BigInteger(normalized, 16)
    }

    private fun topicToAddress(topic: String?): String {
        val value = topic.orEmpty().removePrefix("0x")
        if (value.length < 40) return ""
        return "0x" + value.takeLast(40)
    }

    private fun throwIfError(obj: JSONObject) {
        if (!obj.has("error")) return
        val error = obj.optJSONObject("error")
        throw RuntimeException(error?.optString("message", "RPC error") ?: "RPC error")
    }

    private fun post(chain: WalletChain, body: String): String {
        val request = Request.Builder()
            .url(chain.rpcUrl)
            .post(body.toRequestBody(JSON_MEDIA.toMediaType()))
            .build()
        val response = client.newCall(request).execute()
        if (!response.isSuccessful) throw RuntimeException("RPC failed: ${response.code}")
        return response.body?.string() ?: throw RuntimeException("Empty response")
    }
}

object ArbitrumRpc {
    suspend fun getBalance(address: String): BigInteger = EvmRpc.getBalance(WalletChains.ARBITRUM, address)
    suspend fun getTokenBalance(tokenAddress: String, walletAddress: String): BigInteger =
        EvmRpc.getTokenBalance(WalletChains.ARBITRUM, tokenAddress, walletAddress)

    suspend fun getNonce(address: String): BigInteger = EvmRpc.getNonce(WalletChains.ARBITRUM, address)
    suspend fun sendRawTransaction(rawTxHex: String): String = EvmRpc.sendRawTransaction(WalletChains.ARBITRUM, rawTxHex)
    suspend fun estimateGas(tx: Map<String, String>): BigInteger = EvmRpc.estimateGas(WalletChains.ARBITRUM, tx)
    suspend fun getGasPrice(): BigInteger = EvmRpc.getGasPrice(WalletChains.ARBITRUM)
    suspend fun getBlockGasParams(): Pair<BigInteger, BigInteger> = EvmRpc.getBlockGasParams(WalletChains.ARBITRUM)
}

private fun String.ensureHexPrefix(): String = if (startsWith("0x", ignoreCase = true)) this else "0x$this"
