package io.arbitrum.wallet

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.math.BigInteger
import java.util.concurrent.TimeUnit

object ArbitrumRpc {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private const val JSON_MEDIA = "application/json"

    suspend fun getBalance(address: String): BigInteger = withContext(Dispatchers.IO) {
        val body = """{"jsonrpc":"2.0","method":"eth_getBalance","params":["$address","latest"],"id":1}"""
        val resp = post(body)
        val result = JSONObject(resp).optString("result", "0x0")
        BigInteger(result.removePrefix("0x"), 16)
    }

    suspend fun getTokenBalance(tokenAddress: String, walletAddress: String): BigInteger = withContext(Dispatchers.IO) {
        val data = "0x70a08231" + "0".repeat(24) + walletAddress.removePrefix("0x").lowercase()
        val body = """{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"$tokenAddress","data":"$data"},"latest"],"id":1}"""
        val resp = post(body)
        val result = JSONObject(resp).optString("result", "0x0")
        if (result == "0x" || result.isEmpty()) return@withContext BigInteger.ZERO
        BigInteger(result.removePrefix("0x"), 16)
    }

    suspend fun getNonce(address: String): BigInteger = withContext(Dispatchers.IO) {
        val body = """{"jsonrpc":"2.0","method":"eth_getTransactionCount","params":["$address","pending"],"id":1}"""
        val resp = post(body)
        val result = JSONObject(resp).optString("result", "0x0")
        BigInteger(result.removePrefix("0x"), 16)
    }

    suspend fun sendRawTransaction(rawTxHex: String): String = withContext(Dispatchers.IO) {
        val raw = if (rawTxHex.startsWith("0x")) rawTxHex else "0x$rawTxHex"
        val body = """{"jsonrpc":"2.0","method":"eth_sendRawTransaction","params":["$raw"],"id":1}"""
        val resp = post(body)
        val obj = JSONObject(resp)
        if (obj.has("error")) {
            val err = obj.optJSONObject("error")
            throw RuntimeException(err?.optString("message", "RPC error") ?: "RPC error")
        }
        obj.optString("result", "").removePrefix("0x")
    }

    suspend fun estimateGas(tx: Map<String, String>): BigInteger = withContext(Dispatchers.IO) {
        val params = JSONObject()
        tx["from"]?.let { params.put("from", it) }
        tx["to"]?.let { params.put("to", it) }
        tx["value"]?.let { params.put("value", it) }
        tx["data"]?.let { params.put("data", it) }
        val body = """{"jsonrpc":"2.0","method":"eth_estimateGas","params":[$params],"id":1}"""
        val resp = post(body)
        val result = JSONObject(resp).optString("result", "0x5208")
        BigInteger(result.removePrefix("0x"), 16)
    }

    suspend fun getGasPrice(): BigInteger = withContext(Dispatchers.IO) {
        val body = """{"jsonrpc":"2.0","method":"eth_gasPrice","params":[],"id":1}"""
        val resp = post(body)
        val result = JSONObject(resp).optString("result", "0x0")
        BigInteger(result.removePrefix("0x"), 16)
    }

    suspend fun getBlockGasParams(): Pair<BigInteger, BigInteger> = withContext(Dispatchers.IO) {
        val body = """{"jsonrpc":"2.0","method":"eth_getBlockByNumber","params":["latest",false],"id":1}"""
        val resp = post(body)
        val block = JSONObject(resp).optJSONObject("result")
        val baseFee = block?.optString("baseFeePerGas", "0x0")?.let { BigInteger(it.removePrefix("0x"), 16) }
            ?: BigInteger("1000000000")
        val maxPriority = baseFee.divide(BigInteger.TEN)
        val maxFee = baseFee.multiply(BigInteger.valueOf(2))
        maxPriority to maxFee
    }

    private fun post(body: String): String {
        val request = Request.Builder()
            .url(ArbitrumConfig.RPC_URL)
            .post(body.toRequestBody(JSON_MEDIA.toMediaType()))
            .build()
        val response = client.newCall(request).execute()
        if (!response.isSuccessful) throw RuntimeException("RPC failed: ${response.code}")
        return response.body?.string() ?: throw RuntimeException("Empty response")
    }
}
