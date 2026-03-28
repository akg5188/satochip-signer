package io.arbitrum.wallet

import java.io.ByteArrayOutputStream
import java.math.BigDecimal
import java.math.RoundingMode
import java.net.URLEncoder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlin.math.ceil
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.bitcoinj.core.LegacyAddress
import org.bitcoinj.core.SegwitAddress
import org.bitcoinj.core.Utils
import org.bitcoinj.script.ScriptBuilder
import org.json.JSONArray
import org.json.JSONObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val BITCOIN_DEFAULT_GAP_LIMIT = 5
private const val BITCOIN_MAX_DISCOVERY_INDEX = 24
private const val BITCOIN_DUST_THRESHOLD_SATS = 546L

data class BitcoinAccountSnapshot(
    val balanceSats: Long,
    val priceUsd: Double?,
    val utxoCount: Int,
    val nextReceiveIndex: Int,
    val nextReceiveAddress: String,
    val nextChangeIndex: Int,
    val nextChangeAddress: String,
    val spendableUtxos: List<BitcoinSpendableUtxo>,
    val status: String,
    val recentActivity: List<WalletActivityItem>,
)

data class BitcoinPreparedTransfer(
    val requestPayload: String,
    val amountSats: Long,
    val feeSats: Long,
    val changeSats: Long,
    val destinationAddress: String,
    val changeAddress: String?,
    val inputCount: Int,
    val snapshot: BitcoinAccountSnapshot,
)

data class BitcoinTransactionDetail(
    val txid: String,
    val statusLabel: String,
    val fromSummary: String,
    val toSummary: String,
    val feeSats: Long,
    val blockHeight: Long?,
    val confirmations: Int?,
    val timestamp: Long,
    val inputCount: Int,
    val outputCount: Int,
    val size: Int,
    val weight: Int,
)

data class BitcoinSpendableUtxo(
    val txid: String,
    val vout: Int,
    val valueSats: Long,
    val keyMaterial: BitcoinDerivedKeyMaterial,
)

private data class BitcoinBranchDiscovery(
    val utxos: List<BitcoinSpendableUtxo>,
    val nextIndex: Int,
    val nextAddress: String,
    val usedAddresses: List<String>,
)

private data class BitcoinChainActivity(
    val txid: String,
    val timestamp: Long,
    val incoming: Boolean,
    val netSats: Long,
    val counterparty: String,
    val detail: String,
    val statusLabel: String,
    val externalUrl: String,
)

private data class BitcoinCoinSelection(
    val selected: List<BitcoinSpendableUtxo>,
    val feeSats: Long,
    val changeSats: Long,
    val changeAddress: String?,
)

object BitcoinTransferService {
    private val allowedHosts = setOf("blockstream.info")
    private val client = TrustedNetwork.newPinnedClient(
        OkHttpClient.Builder()
            .callTimeout(20, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
    ).build()

    suspend fun syncAccount(account: BitcoinWatchAccount): BitcoinAccountSnapshot = withContext(Dispatchers.IO) {
        val receive = discoverBranch(account, branch = 0)
        val change = discoverBranch(account, branch = 1)
        val utxos = receive.utxos + change.utxos
        val balanceSats = utxos.sumOf { it.valueSats }
        val priceUsd = EvmRpc.fetchCoingeckoPriceForSymbol("BTC")
        val recentActivity = fetchAccountActivity(
            prefix = account.prefix,
            ownedAddresses = (receive.usedAddresses + change.usedAddresses).toSet(),
        )
        BitcoinAccountSnapshot(
            balanceSats = balanceSats,
            priceUsd = priceUsd,
            utxoCount = utxos.size,
            nextReceiveIndex = receive.nextIndex,
            nextReceiveAddress = receive.nextAddress,
            nextChangeIndex = change.nextIndex,
            nextChangeAddress = change.nextAddress,
            spendableUtxos = utxos.sortedByDescending { it.valueSats },
            status = if (utxos.isEmpty()) {
                "已同步链上状态，当前没有可用 UTXO。"
            } else {
                "已发现 ${utxos.size} 个 UTXO，可用余额 ${formatBitcoinSats(balanceSats)}"
            },
            recentActivity = recentActivity,
        )
    }

    suspend fun prepareTransfer(
        account: BitcoinWatchAccount,
        destinationAddress: String,
        amountText: String,
        feeRateText: String?,
    ): BitcoinPreparedTransfer = withContext(Dispatchers.IO) {
        val amountSats = parseBitcoinAmountToSats(amountText)
        require(amountSats > 0L) { "请输入大于 0 的 BTC 数量" }

        val snapshot = syncAccount(account)
        require(snapshot.spendableUtxos.isNotEmpty()) { "当前 BTC 账户没有可用 UTXO" }

        val destinationScript = outputScriptForAddress(account.prefix, destinationAddress)
        val changeKey = deriveBitcoinKeyMaterial(account, branch = 1, index = snapshot.nextChangeIndex)
        val feeRate = parseFeeRateOrDefault(account.prefix, feeRateText)
        val selection = selectCoins(
            utxos = snapshot.spendableUtxos,
            amountSats = amountSats,
            feeRate = feeRate,
            destinationScriptSize = destinationScript.size,
            changeScriptSize = changeKey.scriptPubKey.size,
            prefix = account.prefix,
            changeAddress = changeKey.address,
        )

        val outputs = buildList {
            add(BitcoinTxOutput(destinationAddress, amountSats, destinationScript))
            if (selection.changeSats > 0 && selection.changeAddress != null) {
                add(BitcoinTxOutput(selection.changeAddress, selection.changeSats, changeKey.scriptPubKey))
            }
        }
        val unsignedTx = serializeUnsignedTransaction(selection.selected, outputs)
        val psbtBytes = buildPsbt(
            prefix = account.prefix,
            accountFingerprintHex = account.accountFingerprintHex,
            selectedUtxos = selection.selected,
            outputs = outputs,
            unsignedTx = unsignedTx,
        )
        val psbtBase64 = android.util.Base64.encodeToString(
            psbtBytes,
            android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
        )
        val requestPayload = buildSignPsbtRequest(
            prefix = account.prefix,
            requestId = "btc-psbt-${UUID.randomUUID()}",
            psbtBase64 = psbtBase64,
            destinationAddress = destinationAddress,
            amountSats = amountSats,
            feeSats = selection.feeSats,
            accountLabel = account.label,
        )

        BitcoinPreparedTransfer(
            requestPayload = requestPayload,
            amountSats = amountSats,
            feeSats = selection.feeSats,
            changeSats = selection.changeSats,
            destinationAddress = destinationAddress,
            changeAddress = selection.changeAddress,
            inputCount = selection.selected.size,
            snapshot = snapshot,
        )
    }

    suspend fun broadcastTransaction(prefix: String, txHex: String): String = withContext(Dispatchers.IO) {
        val request = TrustedNetwork.requestBuilder("${bitcoinEsploraBaseUrl(prefix)}/tx", allowedHosts)
            .post(txHex.trim().toRequestBody("text/plain; charset=utf-8".toMediaType()))
            .build()
        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty().trim()
            require(response.isSuccessful) { body.ifBlank { "BTC 广播失败 (${response.code})" } }
            require(body.isNotBlank()) { "BTC 广播成功但未返回 txid" }
            body
        }
    }

    suspend fun fetchTransactionDetail(
        externalUrl: String,
        txid: String,
    ): BitcoinTransactionDetail? = withContext(Dispatchers.IO) {
        if (txid.isBlank()) return@withContext null
        val cleanTxid = txid.removePrefix("0x")
        val baseUrl = externalUrl.substringBefore("/tx/").trim().ifBlank { return@withContext null }
        val tx = fetchJsonObject("$baseUrl/tx/$cleanTxid")
        val status = tx.optJSONObject("status")
        val confirmed = status?.optBoolean("confirmed") == true
        val blockHeight = status?.optLong("block_height")?.takeIf { it > 0L }
        val blockTime = status?.optLong("block_time")?.takeIf { it > 0L }?.times(1000)
            ?: System.currentTimeMillis()
        val confirmations = if (confirmed && blockHeight != null) {
            val tipHeight = fetchText("$baseUrl/blocks/tip/height").trim().toLongOrNull()
            tipHeight?.let { (it - blockHeight + 1L).coerceAtLeast(1L).toInt() }
        } else {
            0
        }
        val vin = tx.optJSONArray("vin") ?: JSONArray()
        val vout = tx.optJSONArray("vout") ?: JSONArray()
        val fromAddresses = linkedSetOf<String>()
        val toAddresses = linkedSetOf<String>()
        for (index in 0 until vin.length()) {
            val address = vin.optJSONObject(index)
                ?.optJSONObject("prevout")
                ?.optString("scriptpubkey_address")
                .orEmpty()
                .trim()
            if (address.isNotBlank()) fromAddresses += address
        }
        for (index in 0 until vout.length()) {
            val address = vout.optJSONObject(index)
                ?.optString("scriptpubkey_address")
                .orEmpty()
                .trim()
            if (address.isNotBlank()) toAddresses += address
        }
        BitcoinTransactionDetail(
            txid = cleanTxid,
            statusLabel = if (confirmed) "链上确认" else "待确认",
            fromSummary = summarizeAddresses(fromAddresses.toList()),
            toSummary = summarizeAddresses(toAddresses.toList()),
            feeSats = tx.optLong("fee", 0L),
            blockHeight = blockHeight,
            confirmations = confirmations,
            timestamp = blockTime,
            inputCount = vin.length(),
            outputCount = vout.length(),
            size = tx.optInt("size", 0),
            weight = tx.optInt("weight", 0),
        )
    }

    private suspend fun discoverBranch(
        account: BitcoinWatchAccount,
        branch: Int,
    ): BitcoinBranchDiscovery {
        val utxos = mutableListOf<BitcoinSpendableUtxo>()
        val usedAddresses = mutableListOf<String>()
        var index = 0
        var consecutiveUnused = 0
        var lastUsedIndex = -1

        while (index < BITCOIN_MAX_DISCOVERY_INDEX && consecutiveUnused < BITCOIN_DEFAULT_GAP_LIMIT) {
            val material = deriveBitcoinKeyMaterial(account, branch = branch, index = index)
            val addressInfo = fetchAddressInfo(account.prefix, material.address)
            if (addressInfo.isUsed) {
                lastUsedIndex = index
                consecutiveUnused = 0
                usedAddresses += material.address
                val utxoArray = fetchAddressUtxos(account.prefix, material.address)
                for (position in 0 until utxoArray.length()) {
                    val utxo = utxoArray.optJSONObject(position) ?: continue
                    utxos += BitcoinSpendableUtxo(
                        txid = utxo.getString("txid"),
                        vout = utxo.getInt("vout"),
                        valueSats = utxo.getLong("value"),
                        keyMaterial = material,
                    )
                }
            } else {
                consecutiveUnused += 1
            }
            index += 1
        }

        val nextIndex = (lastUsedIndex + 1).coerceAtLeast(0)
        val nextAddress = deriveBitcoinKeyMaterial(account, branch = branch, index = nextIndex).address
        return BitcoinBranchDiscovery(
            utxos = utxos,
            nextIndex = nextIndex,
            nextAddress = nextAddress,
            usedAddresses = usedAddresses.distinct(),
        )
    }

    private suspend fun fetchAddressInfo(prefix: String, address: String): BitcoinAddressInfo {
        val json = fetchJsonObject("${bitcoinEsploraBaseUrl(prefix)}/address/$address")
        val chainStats = json.optJSONObject("chain_stats") ?: JSONObject()
        val mempoolStats = json.optJSONObject("mempool_stats") ?: JSONObject()
        val used = (
            chainStats.optLong("funded_txo_count", 0) > 0 ||
                chainStats.optLong("spent_txo_count", 0) > 0 ||
                mempoolStats.optLong("funded_txo_count", 0) > 0 ||
                mempoolStats.optLong("spent_txo_count", 0) > 0
            )
        return BitcoinAddressInfo(isUsed = used)
    }

    private suspend fun fetchAddressUtxos(prefix: String, address: String): JSONArray {
        return fetchJsonArray("${bitcoinEsploraBaseUrl(prefix)}/address/$address/utxo")
    }

    private suspend fun fetchAddressTransactions(prefix: String, address: String): List<JSONObject> {
        val baseUrl = "${bitcoinEsploraBaseUrl(prefix)}/address/$address/txs"
        val all = mutableListOf<JSONObject>()
        var page = fetchJsonArray(baseUrl)
        while (page.length() > 0 && all.size < 120) {
            for (index in 0 until page.length()) {
                val tx = page.optJSONObject(index) ?: continue
                all += tx
            }
            if (page.length() < 25) break
            val lastTxid = page.optJSONObject(page.length() - 1)?.optString("txid").orEmpty()
            if (lastTxid.isBlank()) break
            page = fetchJsonArray("$baseUrl/chain/$lastTxid")
        }
        return all
    }

    private suspend fun fetchAccountActivity(
        prefix: String,
        ownedAddresses: Set<String>,
    ): List<WalletActivityItem> {
        if (ownedAddresses.isEmpty()) return emptyList()
        val txMap = linkedMapOf<String, JSONObject>()
        ownedAddresses.forEach { address ->
            fetchAddressTransactions(prefix, address).forEach { tx ->
                val txid = tx.optString("txid").trim()
                if (txid.isNotBlank()) {
                    txMap.putIfAbsent(txid, tx)
                }
            }
        }
        return txMap.values.mapNotNull { tx ->
            val parsed = parseAccountTransaction(prefix, tx, ownedAddresses) ?: return@mapNotNull null
            WalletActivityItem(
                id = "btc-chain-${parsed.txid}",
                chainId = WalletChains.DEFAULT.chainId,
                kind = WalletActivityKind.ONCHAIN,
                title = if (parsed.incoming) "收到 BTC" else "转出 BTC",
                subtitle = parsed.counterparty,
                detail = parsed.detail,
                amountLabel = "${if (parsed.netSats >= 0) "+" else "-"}${formatBitcoinSats(kotlin.math.abs(parsed.netSats))}",
                statusLabel = parsed.statusLabel,
                timestamp = parsed.timestamp,
                txHash = parsed.txid,
                externalUrl = parsed.externalUrl,
            )
        }.sortedByDescending { it.timestamp }
    }

    private fun parseAccountTransaction(
        prefix: String,
        tx: JSONObject,
        ownedAddresses: Set<String>,
    ): BitcoinChainActivity? {
        val txid = tx.optString("txid").trim()
        if (txid.isBlank()) return null
        val vinArray = tx.optJSONArray("vin") ?: JSONArray()
        val voutArray = tx.optJSONArray("vout") ?: JSONArray()

        var receivedSats = 0L
        var spentSats = 0L
        var externalInput = ""
        var externalOutput = ""

        for (index in 0 until vinArray.length()) {
            val vin = vinArray.optJSONObject(index) ?: continue
            val prevout = vin.optJSONObject("prevout") ?: continue
            val address = prevout.optString("scriptpubkey_address").trim()
            val value = prevout.optLong("value", 0L)
            if (ownedAddresses.contains(address)) {
                spentSats += value
            } else if (externalInput.isBlank() && address.isNotBlank()) {
                externalInput = address
            }
        }

        for (index in 0 until voutArray.length()) {
            val vout = voutArray.optJSONObject(index) ?: continue
            val address = vout.optString("scriptpubkey_address").trim()
            val value = vout.optLong("value", 0L)
            if (ownedAddresses.contains(address)) {
                receivedSats += value
            } else if (externalOutput.isBlank() && address.isNotBlank()) {
                externalOutput = address
            }
        }

        val netSats = receivedSats - spentSats
        if (netSats == 0L && receivedSats == 0L && spentSats == 0L) return null

        val status = tx.optJSONObject("status")
        val timestamp = status?.optLong("block_time", 0L)?.takeIf { it > 0L }?.times(1000)
            ?: System.currentTimeMillis()
        val incoming = netSats >= 0L
        val detail = "${shortBitcoinCounterparty(externalInput)} -> ${shortBitcoinCounterparty(externalOutput)}"
        return BitcoinChainActivity(
            txid = txid,
            timestamp = timestamp,
            incoming = incoming,
            netSats = if (netSats == 0L && receivedSats > 0L) receivedSats else netSats,
            counterparty = if (incoming) {
                shortBitcoinCounterparty(externalInput.ifBlank { "链上账户" })
            } else {
                shortBitcoinCounterparty(externalOutput.ifBlank { "链上账户" })
            },
            detail = detail,
            statusLabel = if (status?.optBoolean("confirmed") == true) "链上确认" else "待确认",
            externalUrl = "${bitcoinEsploraBaseUrl(prefix)}/tx/$txid",
        )
    }

    private fun shortBitcoinCounterparty(address: String): String {
        val trimmed = address.trim()
        if (trimmed.isBlank()) return "链上账户"
        if (trimmed.length <= 18) return trimmed
        return "${trimmed.take(8)}...${trimmed.takeLast(6)}"
    }

    private fun summarizeAddresses(addresses: List<String>): String {
        if (addresses.isEmpty()) return "链上账户"
        if (addresses.size == 1) return addresses.first()
        val preview = addresses.take(2).joinToString("\n")
        return "$preview\n等 ${addresses.size} 个地址"
    }

    private suspend fun fetchTransactionHex(prefix: String, txid: String): ByteArray {
        return hexToBytes(fetchText("${bitcoinEsploraBaseUrl(prefix)}/tx/$txid/hex"))
    }

    private suspend fun fetchRecommendedFeeRate(prefix: String): Double {
        val json = fetchJsonObject("${bitcoinEsploraBaseUrl(prefix)}/fee-estimates")
        val fast = json.optDouble("2", Double.NaN)
        val fallback = json.optDouble("6", Double.NaN)
        val value = when {
            !fast.isNaN() && fast > 0.0 -> fast
            !fallback.isNaN() && fallback > 0.0 -> fallback
            else -> 3.0
        }
        return value.coerceAtLeast(1.0)
    }

    private suspend fun fetchJsonObject(url: String): JSONObject {
        val text = fetchText(url)
        return JSONObject(text)
    }

    private suspend fun fetchJsonArray(url: String): JSONArray {
        val text = fetchText(url)
        return JSONArray(text)
    }

    private suspend fun fetchText(url: String): String {
        val request = TrustedNetwork.requestBuilder(url, allowedHosts).build()
        return client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            require(response.isSuccessful) { body.ifBlank { "请求失败 (${response.code})" } }
            body
        }
    }

    private suspend fun buildPsbt(
        prefix: String,
        accountFingerprintHex: String,
        selectedUtxos: List<BitcoinSpendableUtxo>,
        outputs: List<BitcoinTxOutput>,
        unsignedTx: ByteArray,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(byteArrayOf(0x70, 0x73, 0x62, 0x74, 0xff.toByte()))
        writeKeyValue(out, byteArrayOf(0x00), unsignedTx)
        writeVarInt(out, 0)

        for (utxo in selectedUtxos) {
            val inputMap = ByteArrayOutputStream()
            when (prefix.lowercase(Locale.US)) {
                "xpub", "tpub" -> {
                    writeKeyValue(inputMap, byteArrayOf(0x00), fetchTransactionHex(prefix, utxo.txid))
                }
                "ypub", "upub", "zpub", "vpub" -> {
                    writeKeyValue(inputMap, byteArrayOf(0x01), serializeWitnessUtxo(utxo))
                    if (prefix.equals("ypub", ignoreCase = true) || prefix.equals("upub", ignoreCase = true)) {
                        writeKeyValue(inputMap, byteArrayOf(0x04), buildNestedSegwitRedeemScript(utxo.keyMaterial.publicKey))
                    }
                }
                else -> error("不支持的 BTC 扩展公钥前缀: $prefix")
            }
            writeKeyValue(
                inputMap,
                byteArrayOf(0x06) + utxo.keyMaterial.publicKey,
                buildDerivationValue(accountFingerprintHex, utxo.keyMaterial.path),
            )
            writeVarInt(inputMap, 0)
            out.write(inputMap.toByteArray())
        }

        repeat(outputs.size) {
            writeVarInt(out, 0)
        }
        return out.toByteArray()
    }

    private fun serializeUnsignedTransaction(
        utxos: List<BitcoinSpendableUtxo>,
        outputs: List<BitcoinTxOutput>,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(intToLittleEndian(2))
        writeVarInt(out, utxos.size.toLong())
        utxos.forEach { utxo ->
            out.write(hexToBytes(utxo.txid).reversedArray())
            out.write(intToLittleEndian(utxo.vout))
            writeVarInt(out, 0)
            out.write(intToLittleEndian(0xFFFFFFFD.toInt()))
        }
        writeVarInt(out, outputs.size.toLong())
        outputs.forEach { output ->
            out.write(longToLittleEndian(output.valueSats))
            writeVarBytes(out, output.scriptPubKey)
        }
        out.write(intToLittleEndian(0))
        return out.toByteArray()
    }

    private fun selectCoins(
        utxos: List<BitcoinSpendableUtxo>,
        amountSats: Long,
        feeRate: Double,
        destinationScriptSize: Int,
        changeScriptSize: Int,
        prefix: String,
        changeAddress: String,
    ): BitcoinCoinSelection {
        require(utxos.isNotEmpty()) { "没有可用 UTXO" }
        var total = 0L
        val selected = mutableListOf<BitcoinSpendableUtxo>()
        val outputSizeNoChange = serializedOutputSize(destinationScriptSize)
        val outputSizeWithChange = outputSizeNoChange + serializedOutputSize(changeScriptSize)

        utxos.forEach { utxo ->
            selected += utxo
            total += utxo.valueSats

            val feeWithChange = estimateFee(selected.size, prefix, feeRate, outputSizeWithChange)
            val changeSats = total - amountSats - feeWithChange
            if (changeSats >= BITCOIN_DUST_THRESHOLD_SATS) {
                return BitcoinCoinSelection(
                    selected = selected.toList(),
                    feeSats = feeWithChange,
                    changeSats = changeSats,
                    changeAddress = changeAddress,
                )
            }

            val feeNoChange = estimateFee(selected.size, prefix, feeRate, outputSizeNoChange)
            val remaining = total - amountSats - feeNoChange
            if (remaining >= 0) {
                return BitcoinCoinSelection(
                    selected = selected.toList(),
                    feeSats = feeNoChange + remaining,
                    changeSats = 0L,
                    changeAddress = null,
                )
            }
        }

        error("余额不足，请减少发送数量或等待更多 BTC 到账")
    }

    private fun estimateFee(
        inputCount: Int,
        prefix: String,
        feeRate: Double,
        outputsSerializedSize: Int,
    ): Long {
        val inputVbytes = when (prefix.lowercase(Locale.US)) {
            "xpub", "tpub" -> 148
            "ypub", "upub" -> 91
            "zpub", "vpub" -> 68
            else -> error("不支持的 BTC 扩展公钥前缀: $prefix")
        }
        val vbytes = 10 + (inputCount * inputVbytes) + outputsSerializedSize
        return ceil(vbytes * feeRate).toLong().coerceAtLeast(150L)
    }

    private fun parseBitcoinAmountToSats(raw: String): Long {
        val value = raw.trim()
        require(value.isNotBlank()) { "请输入 BTC 数量" }
        val decimal = value.toBigDecimal()
        require(decimal > BigDecimal.ZERO) { "BTC 数量必须大于 0" }
        return decimal.multiply(BigDecimal(100_000_000L))
            .setScale(0, RoundingMode.DOWN)
            .longValueExact()
    }

    private suspend fun parseFeeRateOrDefault(prefix: String, raw: String?): Double {
        val candidate = raw.orEmpty().trim()
        if (candidate.isBlank()) return fetchRecommendedFeeRate(prefix)
        val parsed = candidate.toDoubleOrNull()
        require(parsed != null && parsed > 0.0) { "手续费率请输入正数 sat/vB" }
        return parsed
    }

    private fun outputScriptForAddress(prefix: String, address: String): ByteArray {
        val params = bitcoinNetworkParamsForPrefix(prefix)
        return if (address.lowercase(Locale.US).startsWith("bc1") || address.lowercase(Locale.US).startsWith("tb1")) {
            ScriptBuilder.createOutputScript(SegwitAddress.fromBech32(params, address)).program
        } else {
            ScriptBuilder.createOutputScript(LegacyAddress.fromBase58(params, address)).program
        }
    }

    private fun serializeWitnessUtxo(utxo: BitcoinSpendableUtxo): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(longToLittleEndian(utxo.valueSats))
        writeVarBytes(out, utxo.keyMaterial.scriptPubKey)
        return out.toByteArray()
    }

    private fun buildNestedSegwitRedeemScript(publicKey: ByteArray): ByteArray {
        val pubKeyHash = Utils.sha256hash160(publicKey)
        return byteArrayOf(0x00, 0x14) + pubKeyHash
    }

    private fun buildDerivationValue(accountFingerprintHex: String, path: String): ByteArray {
        val fingerprint = accountFingerprintHex.takeIf { it.length == 8 }?.let(::hexToBytes) ?: byteArrayOf(0, 0, 0, 0)
        val out = ByteArrayOutputStream()
        out.write(fingerprint)
        parseDerivationPath(path).forEach { index ->
            out.write(intToLittleEndian(index))
        }
        return out.toByteArray()
    }

    private fun parseDerivationPath(path: String): List<Int> {
        val normalized = path.trim()
        if (normalized == "m") return emptyList()
        require(normalized.startsWith("m/")) { "无效的 BIP32 路径: $path" }
        return normalized.split("/").drop(1).map { part ->
            val hardened = part.endsWith("'")
            val value = part.removeSuffix("'").toInt()
            if (hardened) value or 0x80000000.toInt() else value
        }
    }

    private fun buildSignPsbtRequest(
        prefix: String,
        requestId: String,
        psbtBase64: String,
        destinationAddress: String,
        amountSats: Long,
        feeSats: Long,
        accountLabel: String,
    ): String {
        val dataJson = JSONObject().apply {
            put("psbt", psbtBase64)
            put("to", destinationAddress)
            put("amountSats", amountSats)
            put("feeSats", feeSats)
            put("accountLabel", accountLabel)
        }
        val network = when (prefix.lowercase(Locale.US)) {
            "xpub", "ypub", "zpub" -> "bitcoin-mainnet"
            "tpub", "upub", "vpub" -> "bitcoin-testnet"
            else -> error("不支持的 BTC 扩展公钥前缀: $prefix")
        }
        val query = listOf(
            "version" to "1.0",
            "protocol" to "BitcoinWallet",
            "network" to network,
            "requestId" to requestId,
            "data" to dataJson.toString(),
        ).joinToString("&") { (key, value) ->
            "$key=${URLEncoder.encode(value, StandardCharsets.UTF_8.name())}"
        }
        return "tp:signPsbt-$query"
    }

    private fun writeKeyValue(out: ByteArrayOutputStream, key: ByteArray, value: ByteArray) {
        writeVarBytes(out, key)
        writeVarBytes(out, value)
    }

    private fun writeVarBytes(out: ByteArrayOutputStream, value: ByteArray) {
        writeVarInt(out, value.size.toLong())
        out.write(value)
    }

    private fun writeVarInt(out: ByteArrayOutputStream, value: Long) {
        when {
            value < 0xfd -> out.write(value.toInt())
            value <= 0xffff -> {
                out.write(0xfd)
                out.write(shortToLittleEndian(value.toInt()))
            }
            value <= 0xffffffffL -> {
                out.write(0xfe)
                out.write(intToLittleEndian(value.toInt()))
            }
            else -> {
                out.write(0xff)
                out.write(longToLittleEndian(value))
            }
        }
    }

    private fun serializedOutputSize(scriptSize: Int): Int {
        return 8 + varIntSize(scriptSize.toLong()) + scriptSize
    }

    private fun varIntSize(value: Long): Int {
        return when {
            value < 0xfd -> 1
            value <= 0xffff -> 3
            value <= 0xffffffffL -> 5
            else -> 9
        }
    }

    private fun shortToLittleEndian(value: Int): ByteArray {
        return ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(value.toShort()).array()
    }

    private fun intToLittleEndian(value: Int): ByteArray {
        return ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value).array()
    }

    private fun longToLittleEndian(value: Long): ByteArray {
        return ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value).array()
    }

    private fun hexToBytes(raw: String): ByteArray {
        val clean = raw.trim().removePrefix("0x")
        require(clean.length % 2 == 0) { "十六进制长度无效" }
        return ByteArray(clean.length / 2) { index ->
            clean.substring(index * 2, index * 2 + 2).toInt(16).toByte()
        }
    }
}

private data class BitcoinAddressInfo(
    val isUsed: Boolean,
)

private data class BitcoinTxOutput(
    val address: String,
    val valueSats: Long,
    val scriptPubKey: ByteArray,
)
