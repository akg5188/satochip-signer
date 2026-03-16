package io.arbitrum.wallet

import java.math.BigInteger
import kotlinx.serialization.json.Json
import org.json.JSONArray
import org.json.JSONObject

sealed interface WalletConnectPreparedRequest {
    data class ImmediateResult(val result: String?) : WalletConnectPreparedRequest
    data class RelayToPi(
        val title: String,
        val payload: String,
        val responseType: PendingResponseType,
    ) : WalletConnectPreparedRequest
}

object WalletConnectRequestCodec {
    private val typedJson = Json { ignoreUnknownKeys = true; isLenient = true }

    suspend fun prepare(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
    ): WalletConnectPreparedRequest {
        return when (request.method.lowercase()) {
            "eth_accounts", "eth_requestaccounts" -> {
                WalletConnectPreparedRequest.ImmediateResult(JSONArray(listOf(selectedAddress)).toString())
            }

            "eth_chainid" -> {
                WalletConnectPreparedRequest.ImmediateResult(ArbitrumConfig.CHAIN_ID_HEX)
            }

            "wallet_switchethereumchain", "wallet_addethereumchain" -> {
                val requestedChainId = parseRequestedChainId(request.params)
                if (requestedChainId != null && requestedChainId != ArbitrumConfig.CHAIN_ID) {
                    throw IllegalArgumentException("当前仅支持 Arbitrum One")
                }
                WalletConnectPreparedRequest.ImmediateResult(null)
            }

            "eth_sendtransaction" -> prepareSendTransaction(request, selectedAddress)
            "personal_sign", "eth_sign" -> preparePersonalSign(request, selectedAddress)
            "eth_signtypeddata", "eth_signtypeddata_v4" -> prepareTypedDataSign(request, selectedAddress)
            else -> throw IllegalArgumentException("暂不支持的 WalletConnect 方法: ${request.method}")
        }
    }

    private suspend fun prepareSendTransaction(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
    ): WalletConnectPreparedRequest.RelayToPi {
        val array = JSONArray(request.params)
        require(array.length() > 0) { "eth_sendTransaction 缺少参数" }
        val tx = array.optJSONObject(0) ?: throw IllegalArgumentException("eth_sendTransaction 参数格式错误")

        val from = normalizeAddress(tx.optString("from")).ifBlank { selectedAddress }
        require(from.equals(selectedAddress, ignoreCase = true)) { "请求地址与当前观察地址不一致" }

        val requestedChainId = parseChainIdValue(tx.opt("chainId"))
        if (requestedChainId != null && requestedChainId != ArbitrumConfig.CHAIN_ID) {
            throw IllegalArgumentException("当前仅支持 Arbitrum One")
        }

        val to = tx.optString("to").takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("eth_sendTransaction 缺少 to 地址")
        val value = parseBigInt(tx.opt("value"))
        val data = tx.optString("data").ifBlank { tx.optString("input").ifBlank { "0x" } }
        val nonce = parseBigIntOrNull(tx.opt("nonce")) ?: ArbitrumRpc.getNonce(from)

        val estimateMap = linkedMapOf<String, String>()
        estimateMap["from"] = from
        estimateMap["to"] = to
        if (value > BigInteger.ZERO) estimateMap["value"] = "0x${value.toString(16)}"
        if (!isEmptyHex(data)) estimateMap["data"] = ensureHexPrefix(data)

        val gasLimit = parseBigIntOrNull(tx.opt("gas"))
            ?: parseBigIntOrNull(tx.opt("gasLimit"))
            ?: ArbitrumRpc.estimateGas(estimateMap)

        val explicitType = tx.opt("type")
        val has1559 = tx.has("maxFeePerGas") || tx.has("maxPriorityFeePerGas")
        val type = when {
            explicitType != null && explicitType != JSONObject.NULL -> parseBigInt(explicitType).toInt()
            has1559 -> 2
            else -> 0
        }

        val gasPrice = if (type == 0) {
            parseBigIntOrNull(tx.opt("gasPrice")) ?: ArbitrumRpc.getGasPrice()
        } else {
            null
        }

        val (fallbackPriority, fallbackMaxFee) = if (type == 2) {
            ArbitrumRpc.getBlockGasParams()
        } else {
            BigInteger.ZERO to BigInteger.ZERO
        }

        val maxPriority = if (type == 2) {
            parseBigIntOrNull(tx.opt("maxPriorityFeePerGas")) ?: fallbackPriority
        } else {
            null
        }
        val maxFee = if (type == 2) {
            parseBigIntOrNull(tx.opt("maxFeePerGas")) ?: fallbackMaxFee
        } else {
            null
        }

        val payload = TpRequestBuilder.buildSignTransactionRequest(
            fromAddress = from,
            txData = TxData(
                from = from,
                to = to,
                value = value,
                data = ensureHexPrefix(data),
                gasLimit = gasLimit,
                nonce = nonce,
                gasPrice = gasPrice,
                maxFeePerGas = maxFee,
                maxPriorityFeePerGas = maxPriority,
                type = type,
            ),
            requestId = request.requestId.toString(),
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = "WalletConnect 交易签名",
            payload = payload,
            responseType = PendingResponseType.BROADCAST_TX,
        )
    }

    private fun preparePersonalSign(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
    ): WalletConnectPreparedRequest.RelayToPi {
        val array = JSONArray(request.params)
        require(array.length() > 0) { "消息签名参数为空" }

        val first = array.optString(0)
        val second = array.optString(1)
        val address = when {
            isLikelyEvmAddress(first) -> normalizeAddress(first)
            isLikelyEvmAddress(second) -> normalizeAddress(second)
            else -> selectedAddress
        }
        require(address.equals(selectedAddress, ignoreCase = true)) { "请求地址与当前观察地址不一致" }

        val message = when {
            isLikelyEvmAddress(first) && second.isNotBlank() -> second
            isLikelyEvmAddress(second) -> first
            else -> first
        }
        val payload = TpRequestBuilder.buildPersonalSignRequest(
            address = selectedAddress,
            message = message,
            requestId = request.requestId.toString(),
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = "WalletConnect 消息签名",
            payload = payload,
            responseType = PendingResponseType.SHOW_SIGNATURE,
        )
    }

    private fun prepareTypedDataSign(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
    ): WalletConnectPreparedRequest.RelayToPi {
        val array = JSONArray(request.params)
        require(array.length() >= 2) { "TypedData 参数不足" }

        val first = array.opt(0)
        val second = array.opt(1)
        val firstText = jsonValueToString(first)
        val secondText = jsonValueToString(second)

        val address = when {
            isLikelyEvmAddress(firstText) -> normalizeAddress(firstText)
            isLikelyEvmAddress(secondText) -> normalizeAddress(secondText)
            else -> selectedAddress
        }
        require(address.equals(selectedAddress, ignoreCase = true)) { "请求地址与当前观察地址不一致" }

        val typedData = when {
            isLikelyEvmAddress(firstText) -> secondText
            isLikelyEvmAddress(secondText) -> firstText
            else -> firstText
        }
        typedJson.parseToJsonElement(typedData)

        val payload = TpRequestBuilder.buildSignTypedDataRequest(
            address = selectedAddress,
            typedDataJson = typedData,
            requestId = request.requestId.toString(),
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = "WalletConnect TypedData 签名",
            payload = payload,
            responseType = PendingResponseType.SHOW_SIGNATURE,
        )
    }

    private fun parseRequestedChainId(params: String): Long? {
        val array = JSONArray(params)
        if (array.length() == 0) return null
        val obj = array.optJSONObject(0) ?: return null
        return parseChainIdValue(obj.opt("chainId"))
    }

    private fun parseChainIdValue(value: Any?): Long? {
        if (value == null || value == JSONObject.NULL) return null
        return when (value) {
            is Number -> value.toLong()
            is String -> {
                val trimmed = value.trim()
                when {
                    trimmed.startsWith("0x", ignoreCase = true) -> trimmed.removePrefix("0x").removePrefix("0X").toLongOrNull(16)
                    else -> trimmed.toLongOrNull()
                }
            }
            else -> null
        }
    }

    private fun jsonValueToString(value: Any?): String {
        return when (value) {
            null, JSONObject.NULL -> ""
            is JSONObject -> value.toString()
            is JSONArray -> value.toString()
            else -> value.toString()
        }
    }

    private fun parseBigIntOrNull(value: Any?): BigInteger? {
        if (value == null || value == JSONObject.NULL) return null
        return runCatching { parseBigInt(value) }.getOrNull()
    }

    private fun parseBigInt(value: Any?): BigInteger {
        if (value == null || value == JSONObject.NULL) return BigInteger.ZERO
        return when (value) {
            is BigInteger -> value
            is Number -> value.toLong().toBigInteger()
            is String -> {
                val trimmed = value.trim()
                when {
                    trimmed.isBlank() -> BigInteger.ZERO
                    trimmed.startsWith("0x", ignoreCase = true) -> BigInteger(trimmed.removePrefix("0x").removePrefix("0X").ifBlank { "0" }, 16)
                    else -> trimmed.toBigInteger()
                }
            }
            else -> value.toString().toBigInteger()
        }
    }

    private fun normalizeAddress(raw: String?): String {
        val value = raw.orEmpty().trim().removePrefix("ethereum:")
        val address = if (value.startsWith("0x")) value else "0x$value"
        require(address.length == 42) { "地址格式错误" }
        require(address.removePrefix("0x").all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) { "地址格式错误" }
        return address
    }

    private fun isLikelyEvmAddress(value: String?): Boolean {
        val normalized = value.orEmpty().trim()
        return normalized.startsWith("0x") &&
            normalized.length == 42 &&
            normalized.removePrefix("0x").all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }
    }

    private fun ensureHexPrefix(value: String): String {
        val trimmed = value.trim()
        return if (trimmed.startsWith("0x", ignoreCase = true)) trimmed else "0x$trimmed"
    }

    private fun isEmptyHex(value: String): Boolean {
        val clean = value.removePrefix("0x").removePrefix("0X")
        return clean.isBlank()
    }
}
