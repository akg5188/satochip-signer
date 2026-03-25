package io.arbitrum.wallet

import java.math.BigInteger
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.json.JSONArray
import org.json.JSONObject

sealed interface WalletConnectPreparedRequest {
    data class ImmediateResult(
        val result: String?,
        val switchToChainId: Long? = null,
    ) : WalletConnectPreparedRequest

    data class RelayToPi(
        val title: String,
        val payload: String,
        val responseType: PendingResponseType,
        val chainId: Long,
    ) : WalletConnectPreparedRequest
}

object WalletConnectRequestCodec {
    private val typedJson = Json { ignoreUnknownKeys = true; isLenient = true }

    suspend fun prepare(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
        activeChainId: Long,
        derivationPath: String,
    ): WalletConnectPreparedRequest {
        val activeChain = WalletChains.require(activeChainId)
        return when (request.method.lowercase()) {
            "eth_accounts", "eth_requestaccounts" -> {
                WalletConnectPreparedRequest.ImmediateResult(JSONArray(listOf(selectedAddress)).toString())
            }

            "eth_chainid" -> {
                WalletConnectPreparedRequest.ImmediateResult(activeChain.chainIdHex)
            }

            "wallet_switchethereumchain", "wallet_addethereumchain" -> {
                val requestedChainId = parseRequestedChainId(request.params)
                    ?: throw IllegalArgumentException("未提供目标链 ID")
                val chain = WalletChains.byId(requestedChainId)
                    ?: throw IllegalArgumentException("当前不支持链 $requestedChainId")
                WalletConnectPreparedRequest.ImmediateResult(
                    result = null,
                    switchToChainId = chain.chainId,
                )
            }

            "eth_sendtransaction" -> prepareSendTransaction(
                request = request,
                selectedAddress = selectedAddress,
                activeChainId = activeChainId,
                derivationPath = derivationPath,
                title = "WalletConnect 交易签名",
                responseType = PendingResponseType.BROADCAST_TX,
            )
            "eth_signtransaction" -> prepareSendTransaction(
                request = request,
                selectedAddress = selectedAddress,
                activeChainId = activeChainId,
                derivationPath = derivationPath,
                title = "WalletConnect 交易签名",
                responseType = PendingResponseType.RETURN_RAW_TRANSACTION,
            )
            "personal_sign", "eth_sign" -> preparePersonalSign(request, selectedAddress, activeChainId, derivationPath)
            "eth_signtypeddata", "eth_signtypeddata_v3", "eth_signtypeddata_v4" ->
                prepareTypedDataSign(request, selectedAddress, activeChainId, derivationPath)
            else -> throw IllegalArgumentException("暂不支持的 WalletConnect 方法: ${request.method}")
        }
    }

    private suspend fun prepareSendTransaction(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
        activeChainId: Long,
        derivationPath: String,
        title: String,
        responseType: PendingResponseType,
    ): WalletConnectPreparedRequest.RelayToPi {
        val array = JSONArray(request.params)
        require(array.length() > 0) { "eth_sendTransaction 缺少参数" }
        val tx = array.optJSONObject(0) ?: throw IllegalArgumentException("eth_sendTransaction 参数格式错误")

        val from = normalizeAddress(tx.optString("from")).ifBlank { selectedAddress }
        require(from.equals(selectedAddress, ignoreCase = true)) { "请求地址与当前观察地址不一致" }

        val chain = resolveChain(
            parseChainIdValue(tx.opt("chainId")) ?: parseChainIdValue(request.chainId),
            activeChainId,
        )

        val to = tx.optString("to").takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("eth_sendTransaction 缺少 to 地址")
        val value = parseBigInt(tx.opt("value"))
        val data = tx.optString("data").ifBlank { tx.optString("input").ifBlank { "0x" } }
        val nonce = parseBigIntOrNull(tx.opt("nonce")) ?: EvmRpc.getNonce(chain, from)

        val estimateMap = linkedMapOf<String, String>()
        estimateMap["from"] = from
        estimateMap["to"] = to
        if (value > BigInteger.ZERO) estimateMap["value"] = "0x${value.toString(16)}"
        if (!isEmptyHex(data)) estimateMap["data"] = ensureHexPrefix(data)

        val gasLimit = parseBigIntOrNull(tx.opt("gas"))
            ?: parseBigIntOrNull(tx.opt("gasLimit"))
            ?: EvmRpc.estimateGas(chain, estimateMap)

        val explicitType = tx.opt("type")
        val has1559 = tx.has("maxFeePerGas") || tx.has("maxPriorityFeePerGas")
        val type = when {
            explicitType != null && explicitType != JSONObject.NULL -> parseBigInt(explicitType).toInt()
            has1559 -> 2
            else -> 0
        }

        val gasPrice = if (type == 0) {
            parseBigIntOrNull(tx.opt("gasPrice")) ?: EvmRpc.getGasPrice(chain)
        } else {
            null
        }

        val (fallbackPriority, fallbackMaxFee) = if (type == 2) {
            EvmRpc.getBlockGasParams(chain)
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
            chain = chain,
            requestId = request.requestId.toString(),
            derivationPath = derivationPath,
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = title,
            payload = payload,
            responseType = responseType,
            chainId = chain.chainId,
        )
    }

    private fun preparePersonalSign(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
        activeChainId: Long,
        derivationPath: String,
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
        val chain = resolveChain(parseChainIdValue(request.chainId), activeChainId)
        val payload = TpRequestBuilder.buildPersonalSignRequest(
            address = selectedAddress,
            message = message,
            chain = chain,
            requestId = request.requestId.toString(),
            derivationPath = derivationPath,
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = "WalletConnect 消息签名",
            payload = payload,
            responseType = PendingResponseType.SHOW_SIGNATURE,
            chainId = chain.chainId,
        )
    }

    private fun prepareTypedDataSign(
        request: WalletConnectPendingRequest,
        selectedAddress: String,
        activeChainId: Long,
        derivationPath: String,
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
        val parsed = typedJson.parseToJsonElement(typedData)
        val typedChainId = runCatching {
            parsed.jsonObject["domain"]?.jsonObject?.get("chainId")?.jsonPrimitive?.content
        }.getOrNull()
        val chain = resolveChain(
            parseChainIdValue(request.chainId) ?: parseChainIdValue(typedChainId),
            activeChainId,
        )

        val payload = TpRequestBuilder.buildSignTypedDataRequest(
            address = selectedAddress,
            typedDataJson = typedData,
            chain = chain,
            requestId = request.requestId.toString(),
            derivationPath = derivationPath,
        )
        return WalletConnectPreparedRequest.RelayToPi(
            title = "WalletConnect TypedData 签名",
            payload = payload,
            responseType = PendingResponseType.SHOW_SIGNATURE,
            chainId = chain.chainId,
        )
    }

    private fun resolveChain(explicitChainId: Long?, activeChainId: Long): WalletChain {
        val target = explicitChainId ?: activeChainId
        return WalletChains.byId(target) ?: throw IllegalArgumentException("当前不支持链 $target")
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
                    trimmed.startsWith("eip155:", ignoreCase = true) -> trimmed.substringAfterLast(':').toLongOrNull()
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
