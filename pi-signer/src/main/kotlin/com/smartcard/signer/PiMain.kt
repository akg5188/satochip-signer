package com.smartcard.signer

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.client.j2se.MatrixToImageWriter
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.util.Base64

private const val DEFAULT_PATH = "m/44'/60'/0'/0/0"
private const val DEFAULT_BTC_XTYPE = "zpub"
private const val DEFAULT_TIMEOUT_SEC = 25

private data class BitcoinXpubType(
    val label: String,
    val xtype: Long,
    val defaultPath: String,
    val networkLabel: String,
    val scriptTypeLabel: String,
)

fun main(args: Array<String>) {
    if (args.isEmpty() || args[0] in setOf("-h", "--help")) {
        printUsage()
        return
    }

    val command = args[0].lowercase()
    val options = parseOptions(args.drop(1))

    when (command) {
        "unlock" -> runUnlock(options)
        "sign" -> runSign(options)
        "get-xpub" -> runGetXpub(options)
        "sign-psbt" -> runSignPsbt(options)
        else -> throw IllegalArgumentException("未知命令: $command")
    }
}

private fun runUnlock(options: CliOptions) {
    val pin = options.required("pin")
    val path = options.value("path", DEFAULT_PATH)
    val reader = options.valueOrNull("reader")
    val timeout = options.intValue("timeout-sec", DEFAULT_TIMEOUT_SEC)

    val connected = PcscConnector.connect(reader, timeout)
    try {
        println("已连接读卡器: ${connected.readerName}")
        println("卡 ATR: ${connected.atrHex}")

        val signer = SatochipSigner()
        val unlocked = signer.unlockCard(
            channel = connected.channel,
            derivationPath = path,
            pin = pin
        )
        println("解锁成功")
        println("地址: ${unlocked.address.lowercase()}")
    } finally {
        connected.channel.disconnect(false)
    }
}

private fun runSign(options: CliOptions) {
    val pin = options.required("pin")
    val path = options.value("path", DEFAULT_PATH)
    val reader = options.valueOrNull("reader")
    val timeout = options.intValue("timeout-sec", DEFAULT_TIMEOUT_SEC)
    val payloadInput = loadPayloadInput(options)
    val payload = normalizePayload(payloadInput)

    val request = TpQrCodec.parseSignRequest(payload)

    val connected = PcscConnector.connect(reader, timeout)
    try {
        println("已连接读卡器: ${connected.readerName}")
        println("卡 ATR: ${connected.atrHex}")

        val signer = SatochipSigner()
        val outcome = signer.signWithCard(
            channel = connected.channel,
            request = request,
            derivationPath = path,
            pin = pin
        )

        val responsePath = options.pathValue("out", Paths.get("response.txt"))
        writeTextFile(responsePath, outcome.responsePayload + "\n")

        val qrPath = options.pathValue("qr", Paths.get("response.png"))
        writeQrPng(outcome.responsePayload, qrPath)

        println("签名成功")
        println("签名地址: ${outcome.signerAddress.lowercase()}")
        println("${outcome.digestLabel}: ${outcome.digestHex}")
        println("${outcome.resultLabel}: ${outcome.resultHex}")
        println("回传字符串已写入: ${responsePath.toAbsolutePath()}")
        println("回传二维码已写入: ${qrPath.toAbsolutePath()}")
        println("\n----- TP Response Begin -----")
        println(outcome.responsePayload)
        println("----- TP Response End -----")
    } finally {
        connected.channel.disconnect(false)
    }
}

private fun runGetXpub(options: CliOptions) {
    val pin = options.required("pin")
    val reader = options.valueOrNull("reader")
    val timeout = options.intValue("timeout-sec", DEFAULT_TIMEOUT_SEC)
    val xtype = parseBitcoinXpubType(options.value("xtype", DEFAULT_BTC_XTYPE))
    val path = options.value("path", xtype.defaultPath)

    val connected = PcscConnector.connect(reader, timeout)
    try {
        println("已连接读卡器: ${connected.readerName}")
        println("卡 ATR: ${connected.atrHex}")

        val signer = SatochipSigner()
        val outcome = signer.exportBip32Xpub(
            channel = connected.channel,
            derivationPath = path,
            pin = pin,
            xtype = xtype.xtype,
        )

        println("导出成功")
        println("network: ${xtype.networkLabel}")
        println("script: ${xtype.scriptTypeLabel}")
        println("path: ${outcome.derivationPath}")
        println("${xtype.label}: ${outcome.xpub}")
    } finally {
        connected.channel.disconnect(false)
    }
}

private fun runSignPsbt(options: CliOptions) {
    val pin = options.required("pin")
    val reader = options.valueOrNull("reader")
    val timeout = options.intValue("timeout-sec", DEFAULT_TIMEOUT_SEC)
    val psbtBytes = loadPsbtInput(options)

    val connected = PcscConnector.connect(reader, timeout)
    try {
        println("已连接读卡器: ${connected.readerName}")
        println("卡 ATR: ${connected.atrHex}")

        val signer = SatochipSigner()
        val outcome = signer.signPsbtWithCard(
            channel = connected.channel,
            psbtBytes = psbtBytes,
            pin = pin,
        )

        val rawPsbtPath = options.pathValue("out-psbt", Paths.get("signed.psbt"))
        writeBinaryFile(rawPsbtPath, outcome.signedPsbtBytes)

        val psbtBase64Path = options.pathValue("out-psbt-base64", Paths.get("signed.psbt.txt"))
        writeTextFile(psbtBase64Path, outcome.signedPsbtBase64 + "\n")

        val txPath = options.pathValue("out-tx", Paths.get("signed.tx.hex"))
        outcome.extractedTxHex?.let { writeTextFile(txPath, it + "\n") }

        println("PSBT 签名成功")
        println("共签名输入: ${outcome.signedInputs.size}")
        println("已完成输入: ${outcome.finalizedInputCount}/${outcome.totalInputs}")
        println("已跳过输入: ${outcome.skippedInputCount}")
        outcome.signedInputs.forEach { detail ->
            println(
                "  - input ${detail.inputIndex}: ${detail.scriptType} path=${detail.derivationPath} " +
                    "finalized=${if (detail.finalized) "yes" else "no"}"
            )
        }
        println("原始 PSBT 已写入: ${rawPsbtPath.toAbsolutePath()}")
        println("Base64 PSBT 已写入: ${psbtBase64Path.toAbsolutePath()}")
        if (outcome.extractedTxHex != null) {
            println("最终交易 Hex 已写入: ${txPath.toAbsolutePath()}")
        } else {
            println("这份 PSBT 目前只生成了已签名 PSBT，尚未抽取最终交易。")
        }
        println("\n----- Signed PSBT Base64 Begin -----")
        println(outcome.signedPsbtBase64)
        println("----- Signed PSBT Base64 End -----")
        outcome.extractedTxHex?.let {
            println("\n----- Final Tx Hex Begin -----")
            println(it)
            println("----- Final Tx Hex End -----")
        }
    } finally {
        connected.channel.disconnect(false)
    }
}

private fun loadPayloadInput(options: CliOptions): String {
    val payload = options.valueOrNull("payload")
    if (!payload.isNullOrBlank()) {
        return payload.trim()
    }

    val payloadFile = options.valueOrNull("payload-file")
    if (!payloadFile.isNullOrBlank()) {
        val path = Paths.get(payloadFile)
        require(Files.isRegularFile(path)) { "payload-file 不存在: $payloadFile" }
        return Files.readString(path, StandardCharsets.UTF_8)
    }

    val stdinText = generateSequence { readLine() }
        .joinToString("\n")
        .trim()
    require(stdinText.isNotBlank()) {
        "请提供 --payload 或 --payload-file，或者从 stdin 输入 TP 请求字符串"
    }
    return stdinText
}

private fun loadPsbtInput(options: CliOptions): ByteArray {
    val psbt = options.valueOrNull("psbt")
    if (!psbt.isNullOrBlank()) {
        return decodePsbtInput(psbt.trim().toByteArray(StandardCharsets.UTF_8))
    }

    val psbtFile = options.valueOrNull("psbt-file")
    if (!psbtFile.isNullOrBlank()) {
        val path = Paths.get(psbtFile)
        require(Files.isRegularFile(path)) { "psbt-file 不存在: $psbtFile" }
        return decodePsbtInput(Files.readAllBytes(path))
    }

    val stdinBytes = System.`in`.readAllBytes()
    require(stdinBytes.isNotEmpty()) {
        "请提供 --psbt 或 --psbt-file，或者从 stdin 输入 PSBT"
    }
    return decodePsbtInput(stdinBytes)
}

private fun decodePsbtInput(raw: ByteArray): ByteArray {
    if (raw.size >= 5 &&
        raw[0] == 0x70.toByte() &&
        raw[1] == 0x73.toByte() &&
        raw[2] == 0x62.toByte() &&
        raw[3] == 0x74.toByte() &&
        raw[4] == 0xff.toByte()
    ) {
        return raw
    }

    val text = raw.toString(StandardCharsets.UTF_8)
        .lineSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .joinToString("")
    require(text.isNotBlank()) { "PSBT 输入为空" }

    val decoded = runCatching {
        Base64.getDecoder().decode(text)
    }.getOrElse { error ->
        throw IllegalArgumentException("PSBT 输入既不是原始二进制，也不是合法 Base64: ${error.message}", error)
    }

    require(
        decoded.size >= 5 &&
            decoded[0] == 0x70.toByte() &&
            decoded[1] == 0x73.toByte() &&
            decoded[2] == 0x62.toByte() &&
            decoded[3] == 0x74.toByte() &&
            decoded[4] == 0xff.toByte()
    ) {
        "Base64 解码后不是合法 PSBT 魔数"
    }
    return decoded
}

private fun normalizePayload(input: String): String {
    val lines = input.lineSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toList()
    require(lines.isNotEmpty()) { "TP 请求内容为空" }

    if (lines.size == 1 && !lines[0].startsWith("tp:multiFragment-", ignoreCase = true)) {
        return lines[0]
    }

    if (!lines.all { it.startsWith("tp:multiFragment-", ignoreCase = true) }) {
        return lines.joinToString(separator = "")
    }

    val assembler = MultiFragmentAssembler()
    for (line in lines) {
        val parsed = TpQrCodec.parseInput(line)
        val fragment = (parsed as? ParseResult.Fragment)?.fragment
            ?: throw IllegalArgumentException("分片输入中包含非 multiFragment 字符串")

        when (val result = assembler.accept(fragment)) {
            is AssemblyResult.Progress -> Unit
            is AssemblyResult.Complete -> return result.payload
            is AssemblyResult.Error -> throw IllegalArgumentException(result.reason)
        }
    }

    throw IllegalArgumentException("分片未收齐，请补齐所有 tp:multiFragment 二维码内容")
}

private fun writeTextFile(path: Path, content: String) {
    val parent = path.toAbsolutePath().parent
    if (parent != null) {
        Files.createDirectories(parent)
    }
    Files.write(path, content.toByteArray(StandardCharsets.UTF_8))
}

private fun writeBinaryFile(path: Path, content: ByteArray) {
    val parent = path.toAbsolutePath().parent
    if (parent != null) {
        Files.createDirectories(parent)
    }
    Files.write(path, content)
}

private fun writeQrPng(content: String, path: Path, size: Int = 600) {
    val parent = path.toAbsolutePath().parent
    if (parent != null) {
        Files.createDirectories(parent)
    }

    val hints = mapOf(
        EncodeHintType.CHARACTER_SET to "UTF-8",
        EncodeHintType.MARGIN to 1,
        EncodeHintType.ERROR_CORRECTION to "M"
    )

    val matrix = QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints)
    MatrixToImageWriter.writeToPath(matrix, "PNG", path)
}

private data class CliOptions(
    val values: Map<String, String>,
    val flags: Set<String>
) {
    fun required(name: String): String {
        return valueOrNull(name)
            ?.takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("缺少参数 --$name")
    }

    fun value(name: String, defaultValue: String): String {
        return valueOrNull(name)?.takeIf { it.isNotBlank() } ?: defaultValue
    }

    fun valueOrNull(name: String): String? {
        return values[name]
    }

    fun intValue(name: String, defaultValue: Int): Int {
        return valueOrNull(name)?.toIntOrNull() ?: defaultValue
    }

    fun pathValue(name: String, defaultValue: Path): Path {
        val raw = valueOrNull(name) ?: return defaultValue
        return Paths.get(raw)
    }

    @Suppress("unused")
    fun hasFlag(name: String): Boolean {
        return flags.contains(name)
    }
}

private fun parseOptions(tokens: List<String>): CliOptions {
    val values = linkedMapOf<String, String>()
    val flags = linkedSetOf<String>()

    var i = 0
    while (i < tokens.size) {
        val token = tokens[i]
        require(token.startsWith("--")) { "参数格式错误: $token" }

        val keyValue = token.removePrefix("--")
        if (keyValue.contains("=")) {
            val idx = keyValue.indexOf('=')
            val key = keyValue.substring(0, idx)
            val value = keyValue.substring(idx + 1)
            values[key] = value
            i += 1
            continue
        }

        val key = keyValue
        val next = tokens.getOrNull(i + 1)
        if (next != null && !next.startsWith("--")) {
            values[key] = next
            i += 2
        } else {
            flags += key
            i += 1
        }
    }

    return CliOptions(values = values, flags = flags)
}

private fun parseBitcoinXpubType(raw: String): BitcoinXpubType {
    return when (raw.trim().lowercase()) {
        "xpub" -> BitcoinXpubType(
            label = "xpub",
            xtype = 0x0488B21EL,
            defaultPath = "m/44'/0'/0'",
            networkLabel = "Bitcoin Mainnet",
            scriptTypeLabel = "Legacy / BIP44",
        )
        "ypub" -> BitcoinXpubType(
            label = "ypub",
            xtype = 0x049D7CB2L,
            defaultPath = "m/49'/0'/0'",
            networkLabel = "Bitcoin Mainnet",
            scriptTypeLabel = "Nested SegWit / BIP49",
        )
        "zpub" -> BitcoinXpubType(
            label = "zpub",
            xtype = 0x04B24746L,
            defaultPath = "m/84'/0'/0'",
            networkLabel = "Bitcoin Mainnet",
            scriptTypeLabel = "Native SegWit / BIP84",
        )
        "tpub" -> BitcoinXpubType(
            label = "tpub",
            xtype = 0x043587CFL,
            defaultPath = "m/44'/1'/0'",
            networkLabel = "Bitcoin Testnet",
            scriptTypeLabel = "Legacy / BIP44",
        )
        "upub" -> BitcoinXpubType(
            label = "upub",
            xtype = 0x044A5262L,
            defaultPath = "m/49'/1'/0'",
            networkLabel = "Bitcoin Testnet",
            scriptTypeLabel = "Nested SegWit / BIP49",
        )
        "vpub" -> BitcoinXpubType(
            label = "vpub",
            xtype = 0x045F1CF6L,
            defaultPath = "m/84'/1'/0'",
            networkLabel = "Bitcoin Testnet",
            scriptTypeLabel = "Native SegWit / BIP84",
        )
        else -> throw IllegalArgumentException("不支持的 xtype: $raw，可选 xpub/ypub/zpub/tpub/upub/vpub")
    }
}

private fun printUsage() {
    println(
        """
        TP Satochip Pi Signer

        用法:
          pi-signer unlock --pin <PIN> [--path <BIP32>] [--reader <关键字>] [--timeout-sec <秒>]
          pi-signer sign --pin <PIN> [--path <BIP32>] (--payload <TP字符串> | --payload-file <文件>)
                         [--reader <关键字>] [--timeout-sec <秒>] [--out response.txt] [--qr response.png]
          pi-signer get-xpub --pin <PIN> [--xtype zpub] [--path <BIP32账户路径>]
                             [--reader <关键字>] [--timeout-sec <秒>]

        例子:
          pi-signer unlock --pin 123456
          pi-signer sign --pin 123456 --payload-file request.txt --out response.txt --qr response.png
          pi-signer get-xpub --pin 123456 --xtype zpub
          pi-signer sign-psbt --pin 123456 --psbt-file unsigned.psbt --out-psbt signed.psbt
        """.trimIndent()
    )
}
