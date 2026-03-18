package io.arbitrum.wallet

import java.math.BigDecimal
import java.math.BigInteger
import java.math.RoundingMode
import java.nio.ByteBuffer
import java.security.SecureRandom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.msgpack.core.MessagePack
import org.web3j.crypto.Keys
import org.web3j.crypto.Sign
import org.web3j.crypto.StructuredDataEncoder
import org.web3j.utils.Numeric

data class HyperliquidAgentRecord(
    val accountAddress: String,
    val agentAddress: String,
    val privateKeyHex: String,
    val agentName: String,
    val approvedAt: Long,
    val validUntil: Long? = null,
)

data class HyperliquidMarketMeta(
    val name: String,
    val asset: Int,
    val szDecimals: Int,
    val maxLeverage: Int,
    val midPrice: String,
)

data class HyperliquidSnapshot(
    val status: String,
    val account: HyperliquidAccountUi?,
    val markets: List<HyperliquidMarketUi>,
    val marketMeta: Map<String, HyperliquidMarketMeta>,
    val openOrders: List<HyperliquidOpenOrderUi>,
    val fills: List<HyperliquidFillUi>,
    val storedAgentValidUntil: Long? = null,
)

data class HyperliquidApprovalRequest(
    val agent: HyperliquidAgentRecord,
    val nonce: Long,
    val typedDataJson: String,
    val action: LinkedHashMap<String, Any?>,
)

data class HyperliquidSignatureData(
    val r: String,
    val s: String,
    val v: Int,
)

object HyperliquidApi {
    private const val MAINNET_API_URL = "https://api.hyperliquid.xyz"
    private const val SIGNATURE_CHAIN_ID = 421614L
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient()

    suspend fun loadSnapshot(
        userAddress: String,
        storedAgent: HyperliquidAgentRecord?,
    ): HyperliquidSnapshot = withContext(Dispatchers.IO) {
        val metaAndCtxs = postInfo(JSONObject().put("type", "metaAndAssetCtxs")) as JSONArray
        val markets = mutableListOf<HyperliquidMarketUi>()
        val marketMeta = linkedMapOf<String, HyperliquidMarketMeta>()
        val universe = metaAndCtxs.getJSONObject(0).getJSONArray("universe")
        val assetCtxs = metaAndCtxs.getJSONArray(1)
        for (index in 0 until minOf(universe.length(), assetCtxs.length())) {
            val meta = universe.optJSONObject(index) ?: continue
            if (meta.optBoolean("isDelisted", false)) continue
            val name = meta.optString("name").trim()
            if (name.isBlank()) continue
            val ctx = assetCtxs.optJSONObject(index) ?: JSONObject()
            val midPrice = firstNonBlank(ctx.optString("midPx"), ctx.optString("markPx"), "0")
            val dayVolume = ctx.optString("dayNtlVlm").ifBlank { "0" }
            val funding = ctx.optString("funding").ifBlank { "0" }
            val openInterest = ctx.optString("openInterest").ifBlank { "0" }
            val market = HyperliquidMarketUi(
                name = name,
                midPrice = midPrice,
                dayVolume = trimDecimals(dayVolume),
                fundingRate = trimDecimals(funding),
                openInterest = trimDecimals(openInterest),
                szDecimals = meta.optInt("szDecimals", 0),
                maxLeverage = meta.optInt("maxLeverage", 1),
            )
            markets += market
            marketMeta[name.uppercase()] = HyperliquidMarketMeta(
                name = name,
                asset = index,
                szDecimals = market.szDecimals,
                maxLeverage = market.maxLeverage,
                midPrice = market.midPrice,
            )
        }

        val sortedMarkets = markets
            .sortedByDescending { decimalOrZero(it.dayVolume) }
            .take(12)

        val userState = runCatching {
            postInfo(
                JSONObject()
                    .put("type", "clearinghouseState")
                    .put("user", userAddress)
                    .put("dex", "")
            ) as JSONObject
        }.getOrNull()
        val account = userState?.let { state ->
            val marginSummary = state.optJSONObject("marginSummary") ?: JSONObject()
            HyperliquidAccountUi(
                accountValue = trimDecimals(marginSummary.optString("accountValue").ifBlank { "0" }),
                marginUsed = trimDecimals(marginSummary.optString("totalMarginUsed").ifBlank { "0" }),
                withdrawable = trimDecimals(state.optString("withdrawable").ifBlank { "0" }),
                notionalPosition = trimDecimals(marginSummary.optString("totalNtlPos").ifBlank { "0" }),
            )
        }

        val openOrders = runCatching {
            val array = postInfo(
                JSONObject()
                    .put("type", "frontendOpenOrders")
                    .put("user", userAddress)
                    .put("dex", "")
            ) as JSONArray
            buildList {
                for (index in 0 until minOf(array.length(), 8)) {
                    val item = array.optJSONObject(index) ?: continue
                    add(
                        HyperliquidOpenOrderUi(
                            oid = item.optLong("oid"),
                            coin = item.optString("coin"),
                            sideLabel = when (item.optString("side")) {
                                "A" -> "卖出"
                                else -> "买入"
                            },
                            limitPrice = item.optString("limitPx"),
                            size = item.optString("sz"),
                            timestamp = item.optLong("timestamp"),
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())

        val fills = runCatching {
            val array = postInfo(
                JSONObject()
                    .put("type", "userFills")
                    .put("user", userAddress)
            ) as JSONArray
            buildList {
                for (index in 0 until minOf(array.length(), 10)) {
                    val item = array.optJSONObject(index) ?: continue
                    add(
                        HyperliquidFillUi(
                            id = item.optString("hash").ifBlank { "fill-${item.optLong("time")}-${item.optLong("oid")}" },
                            coin = item.optString("coin"),
                            sideLabel = firstNonBlank(item.optString("dir"), item.optString("side"), "-"),
                            price = item.optString("px"),
                            size = item.optString("sz"),
                            pnl = item.optString("closedPnl").ifBlank { "0" },
                            timestamp = item.optLong("time"),
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())

        val storedAgentValidUntil = storedAgent?.let { agent ->
            runCatching {
                val array = postInfo(
                    JSONObject()
                        .put("type", "extraAgents")
                        .put("user", userAddress)
                ) as JSONArray
                var validUntil: Long? = null
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    if (item.optString("address").equals(agent.agentAddress, ignoreCase = true)) {
                        validUntil = item.optLong("validUntil").takeIf { it > 0 }
                        break
                    }
                }
                validUntil
            }.getOrNull()
        }

        val status = when {
            account == null -> "Hyperliquid 账户尚未激活或没有可读取的状态"
            storedAgent != null && storedAgentValidUntil != null -> "Hyperliquid 代理已授权"
            storedAgent != null -> "Hyperliquid 代理已保存，建议重新确认授权状态"
            else -> "先完成 Hyperliquid 代理授权，之后就能直接下单"
        }

        HyperliquidSnapshot(
            status = status,
            account = account,
            markets = sortedMarkets,
            marketMeta = marketMeta,
            openOrders = openOrders,
            fills = fills,
            storedAgentValidUntil = storedAgentValidUntil,
        )
    }

    fun buildApprovalRequest(userAddress: String): HyperliquidApprovalRequest {
        val normalizedUser = normalizeAddress(userAddress)
        val agentName = "satochip-${normalizedUser.takeLast(4).lowercase()}"
        val pair = Keys.createEcKeyPair(SecureRandom())
        val privateKeyHex = Numeric.toHexStringNoPrefixZeroPadded(pair.privateKey, 64)
        val agentAddress = "0x${Keys.getAddress(pair.publicKey)}"
        val nonce = System.currentTimeMillis()
        val agent = HyperliquidAgentRecord(
            accountAddress = normalizedUser,
            agentAddress = normalizeAddress(agentAddress),
            privateKeyHex = privateKeyHex,
            agentName = agentName,
            approvedAt = nonce,
        )
        val action = linkedMapOf<String, Any?>(
            "type" to "approveAgent",
            "agentAddress" to agent.agentAddress,
            "agentName" to agent.agentName,
            "nonce" to nonce,
        )
        return HyperliquidApprovalRequest(
            agent = agent,
            nonce = nonce,
            typedDataJson = buildApproveAgentTypedData(agent.agentAddress, agent.agentName, nonce),
            action = action,
        )
    }

    suspend fun approveAgent(
        request: HyperliquidApprovalRequest,
        signatureHex: String,
    ): JSONObject = withContext(Dispatchers.IO) {
        postExchange(request.action, request.nonce, parseSignature(signatureHex))
    }

    suspend fun placeOrder(
        agent: HyperliquidAgentRecord,
        market: HyperliquidMarketMeta,
        isBuy: Boolean,
        sizeText: String,
        orderMode: HyperliquidOrderMode,
        priceText: String?,
        reduceOnly: Boolean,
    ): JSONObject = withContext(Dispatchers.IO) {
        val size = validateSize(sizeText, market.szDecimals)
        val limitPx = when (orderMode) {
            HyperliquidOrderMode.MARKET -> aggressivePrice(market.midPrice, isBuy)
            HyperliquidOrderMode.LIMIT -> validatePrice(priceText ?: "")
        }
        val orderType = linkedMapOf<String, Any?>(
            "limit" to linkedMapOf<String, Any?>(
                "tif" to if (orderMode == HyperliquidOrderMode.MARKET) "Ioc" else "Gtc"
            )
        )
        val orderWire = linkedMapOf<String, Any?>(
            "a" to market.asset,
            "b" to isBuy,
            "p" to limitPx,
            "s" to size,
            "r" to reduceOnly,
            "t" to orderType,
        )
        val action = linkedMapOf<String, Any?>(
            "type" to "order",
            "orders" to listOf(orderWire),
            "grouping" to "na",
        )
        val nonce = System.currentTimeMillis()
        val signature = signL1Action(agent.privateKeyHex, action, nonce)
        postExchange(action, nonce, signature)
    }

    suspend fun cancelOrder(
        agent: HyperliquidAgentRecord,
        market: HyperliquidMarketMeta,
        oid: Long,
    ): JSONObject = withContext(Dispatchers.IO) {
        val action = linkedMapOf<String, Any?>(
            "type" to "cancel",
            "cancels" to listOf(
                linkedMapOf<String, Any?>(
                    "a" to market.asset,
                    "o" to oid,
                )
            ),
        )
        val nonce = System.currentTimeMillis()
        val signature = signL1Action(agent.privateKeyHex, action, nonce)
        postExchange(action, nonce, signature)
    }

    private fun buildApproveAgentTypedData(
        agentAddress: String,
        agentName: String,
        nonce: Long,
    ): String {
        return JSONObject().apply {
            put(
                "domain",
                JSONObject().apply {
                    put("name", "HyperliquidSignTransaction")
                    put("version", "1")
                    put("chainId", SIGNATURE_CHAIN_ID)
                    put("verifyingContract", ZERO_ADDRESS)
                }
            )
            put(
                "types",
                JSONObject().apply {
                    put(
                        "HyperliquidTransaction:ApproveAgent",
                        JSONArray().apply {
                            put(JSONObject().put("name", "hyperliquidChain").put("type", "string"))
                            put(JSONObject().put("name", "agentAddress").put("type", "address"))
                            put(JSONObject().put("name", "agentName").put("type", "string"))
                            put(JSONObject().put("name", "nonce").put("type", "uint64"))
                        }
                    )
                    put(
                        "EIP712Domain",
                        JSONArray().apply {
                            put(JSONObject().put("name", "name").put("type", "string"))
                            put(JSONObject().put("name", "version").put("type", "string"))
                            put(JSONObject().put("name", "chainId").put("type", "uint256"))
                            put(JSONObject().put("name", "verifyingContract").put("type", "address"))
                        }
                    )
                }
            )
            put("primaryType", "HyperliquidTransaction:ApproveAgent")
            put(
                "message",
                JSONObject().apply {
                    put("hyperliquidChain", "Mainnet")
                    put("agentAddress", agentAddress)
                    put("agentName", agentName)
                    put("nonce", nonce)
                }
            )
        }.toString()
    }

    private fun signL1Action(
        privateKeyHex: String,
        action: LinkedHashMap<String, Any?>,
        nonce: Long,
    ): HyperliquidSignatureData {
        val actionHash = actionHash(action, nonce)
        val typedData = JSONObject().apply {
            put(
                "domain",
                JSONObject().apply {
                    put("chainId", 1337)
                    put("name", "Exchange")
                    put("verifyingContract", ZERO_ADDRESS)
                    put("version", "1")
                }
            )
            put(
                "types",
                JSONObject().apply {
                    put(
                        "Agent",
                        JSONArray().apply {
                            put(JSONObject().put("name", "source").put("type", "string"))
                            put(JSONObject().put("name", "connectionId").put("type", "bytes32"))
                        }
                    )
                    put(
                        "EIP712Domain",
                        JSONArray().apply {
                            put(JSONObject().put("name", "name").put("type", "string"))
                            put(JSONObject().put("name", "version").put("type", "string"))
                            put(JSONObject().put("name", "chainId").put("type", "uint256"))
                            put(JSONObject().put("name", "verifyingContract").put("type", "address"))
                        }
                    )
                }
            )
            put("primaryType", "Agent")
            put(
                "message",
                JSONObject().apply {
                    put("source", "a")
                    put("connectionId", Numeric.toHexString(actionHash))
                }
            )
        }.toString()
        val digest = StructuredDataEncoder(typedData).hashStructuredData()
        val keyPair = org.web3j.crypto.ECKeyPair.create(BigInteger(privateKeyHex.removePrefix("0x"), 16))
        val signature = Sign.signMessage(digest, keyPair, false)
        return HyperliquidSignatureData(
            r = compactHex(signature.r),
            s = compactHex(signature.s),
            v = signature.v.first().toInt() and 0xFF,
        )
    }

    private fun actionHash(
        action: LinkedHashMap<String, Any?>,
        nonce: Long,
    ): ByteArray {
        val packer = MessagePack.newDefaultBufferPacker()
        packValue(packer, action)
        packer.writePayload(ByteBuffer.allocate(8).putLong(nonce).array())
        packer.packByte(0)
        packer.close()
        return org.web3j.crypto.Hash.sha3(packer.toByteArray())
    }

    private fun packValue(
        packer: org.msgpack.core.MessagePacker,
        value: Any?,
    ) {
        when (value) {
            null -> packer.packNil()
            is Boolean -> packer.packBoolean(value)
            is Byte -> packer.packByte(value)
            is Short -> packer.packShort(value)
            is Int -> packer.packInt(value)
            is Long -> packer.packLong(value)
            is Float -> packer.packDouble(value.toDouble())
            is Double -> packer.packDouble(value)
            is BigInteger -> {
                require(value.bitLength() <= 63) { "BigInteger 超出 long 编码范围: $value" }
                packer.packLong(value.toLong())
            }
            is String -> packer.packString(value)
            is ByteArray -> {
                packer.packBinaryHeader(value.size)
                packer.writePayload(value)
            }
            is List<*> -> {
                packer.packArrayHeader(value.size)
                value.forEach { entry -> packValue(packer, entry) }
            }
            is Map<*, *> -> {
                packer.packMapHeader(value.size)
                value.forEach { (key, entry) ->
                    packValue(packer, key.toString())
                    packValue(packer, entry)
                }
            }
            else -> error("Unsupported msgpack type: ${value::class.java.name}")
        }
    }

    private fun postExchange(
        action: LinkedHashMap<String, Any?>,
        nonce: Long,
        signature: HyperliquidSignatureData,
    ): JSONObject {
        val payload = JSONObject().apply {
            put("action", toJson(action))
            put("nonce", nonce)
            put(
                "signature",
                JSONObject().apply {
                    put("r", signature.r)
                    put("s", signature.s)
                    put("v", signature.v)
                }
            )
            put("vaultAddress", JSONObject.NULL)
            put("expiresAfter", JSONObject.NULL)
        }
        return postJson("/exchange", payload) as JSONObject
    }

    private fun postInfo(payload: JSONObject): Any = postJson("/info", payload)

    private fun postJson(path: String, payload: JSONObject): Any {
        val request = Request.Builder()
            .url(MAINNET_API_URL + path)
            .post(payload.toString().toRequestBody(jsonMediaType))
            .build()
        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                error("Hyperliquid 请求失败 (${response.code}): $body")
            }
            return JSONTokener(body).nextValue()
        }
    }

    private fun validateSize(sizeText: String, szDecimals: Int): String {
        val normalized = normalizeDecimalInput(sizeText, maxDecimals = szDecimals)
        require(decimalOrZero(normalized) > BigDecimal.ZERO) { "请输入有效数量" }
        return normalized
    }

    private fun validatePrice(priceText: String): String {
        val normalized = normalizeDecimalInput(priceText, maxDecimals = 8)
        require(decimalOrZero(normalized) > BigDecimal.ZERO) { "请输入有效价格" }
        return normalized
    }

    private fun aggressivePrice(midPrice: String, isBuy: Boolean): String {
        val mid = decimalOrZero(midPrice)
        require(mid > BigDecimal.ZERO) { "当前市场价格不可用" }
        val multiplier = if (isBuy) BigDecimal("1.05") else BigDecimal("0.95")
        return normalizeDecimalInput(
            mid.multiply(multiplier).setScale(6, RoundingMode.DOWN).toPlainString(),
            maxDecimals = 8,
        )
    }

    private fun parseSignature(signatureHex: String): HyperliquidSignatureData {
        val clean = Numeric.cleanHexPrefix(signatureHex)
        require(clean.length == 130) { "签名长度不正确" }
        val bytes = Numeric.hexStringToByteArray("0x$clean")
        val r = bytes.copyOfRange(0, 32)
        val s = bytes.copyOfRange(32, 64)
        var v = bytes[64].toInt() and 0xFF
        if (v < 27) v += 27
        return HyperliquidSignatureData(
            r = compactHex(r),
            s = compactHex(s),
            v = v,
        )
    }

    private fun toJson(value: Any?): Any {
        return when (value) {
            null -> JSONObject.NULL
            is Map<*, *> -> JSONObject().apply {
                value.forEach { (key, entry) -> put(key.toString(), toJson(entry)) }
            }
            is List<*> -> JSONArray().apply {
                value.forEach { put(toJson(it)) }
            }
            else -> value
        }
    }

    private fun compactHex(bytes: ByteArray): String {
        val value = BigInteger(1, bytes)
        return "0x${value.toString(16).ifBlank { "0" }}"
    }

    private fun normalizeDecimalInput(raw: String, maxDecimals: Int): String {
        val value = raw.trim()
        require(value.isNotBlank()) { "请输入数值" }
        val decimal = value.toBigDecimalOrNull() ?: error("数值格式错误")
        val stripped = decimal.stripTrailingZeros()
        val scale = stripped.scale().coerceAtLeast(0)
        require(scale <= maxDecimals) { "最多支持 $maxDecimals 位小数" }
        return stripped.toPlainString()
    }

    private fun normalizeAddress(raw: String): String {
        val value = raw.trim()
        val address = if (value.startsWith("0x", ignoreCase = true)) value else "0x$value"
        require(address.length == 42) { "地址格式错误" }
        return "0x${address.removePrefix("0x").removePrefix("0X").lowercase()}"
    }

    private fun decimalOrZero(raw: String): BigDecimal = raw.toBigDecimalOrNull() ?: BigDecimal.ZERO

    private fun trimDecimals(raw: String): String {
        return raw.toBigDecimalOrNull()?.setScale(6, RoundingMode.DOWN)?.stripTrailingZeros()?.toPlainString() ?: raw
    }

    private fun firstNonBlank(vararg values: String): String {
        return values.firstOrNull { it.isNotBlank() } ?: ""
    }

    private const val ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
}
