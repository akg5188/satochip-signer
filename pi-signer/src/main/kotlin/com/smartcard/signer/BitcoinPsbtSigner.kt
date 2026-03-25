package com.smartcard.signer

import fr.acinq.bitcoin.ByteVector
import fr.acinq.bitcoin.DeterministicWallet
import fr.acinq.bitcoin.OP_PUSHDATA
import fr.acinq.bitcoin.PublicKey
import fr.acinq.bitcoin.Satoshi
import fr.acinq.bitcoin.Script
import fr.acinq.bitcoin.ScriptElt
import fr.acinq.bitcoin.ScriptWitness
import fr.acinq.bitcoin.SigHash
import fr.acinq.bitcoin.SigVersion
import fr.acinq.bitcoin.Transaction
import fr.acinq.bitcoin.psbt.Input
import fr.acinq.bitcoin.psbt.KeyPathWithMaster
import fr.acinq.bitcoin.psbt.ParseFailure
import fr.acinq.bitcoin.psbt.Psbt
import fr.acinq.bitcoin.utils.Either
import java.math.BigInteger
import java.util.Base64
import org.bouncycastle.asn1.ASN1EncodableVector
import org.bouncycastle.asn1.ASN1Integer
import org.bouncycastle.asn1.DERSequence
import org.bouncycastle.asn1.sec.SECNamedCurves
import org.satochip.client.SatochipCommandSet
import org.satochip.client.SatochipParser

data class PsbtSignedInputDetail(
    val inputIndex: Int,
    val derivationPath: String,
    val scriptType: String,
    val finalized: Boolean,
)

data class PsbtSigningOutcome(
    val signedPsbtBytes: ByteArray,
    val signedPsbtBase64: String,
    val extractedTxHex: String?,
    val signedInputs: List<PsbtSignedInputDetail>,
    val totalInputs: Int,
    val finalizedInputCount: Int,
    val skippedInputCount: Int,
)

internal class BitcoinPsbtSigner(
    private val commandSet: SatochipCommandSet,
) {
    private val parser = SatochipParser()
    private val cardPubKeyCache = linkedMapOf<String, PublicKey>()
    private var selectedPath: String? = null

    fun sign(psbtBytes: ByteArray): PsbtSigningOutcome {
        var psbt = parsePsbt(psbtBytes)
        val signedInputs = mutableListOf<PsbtSignedInputDetail>()
        var skippedInputs = 0

        psbt.inputs.forEachIndexed { index, input ->
            when (input) {
                is Input.FinalizedInputWithoutUtxo,
                is Input.WitnessInput.FinalizedWitnessInput,
                is Input.NonWitnessInput.FinalizedNonWitnessInput -> {
                    skippedInputs += 1
                }

                is Input.PartiallySignedInputWithoutUtxo -> {
                    skippedInputs += 1
                }

                is Input.WitnessInput.PartiallySignedWitnessInput -> {
                    if (input.taprootInternalKey != null || input.taprootDerivationPaths.isNotEmpty()) {
                        throw IllegalArgumentException("暂不支持 Taproot PSBT 输入，请先在 Electrum 中改用非 Taproot 账户")
                    }
                    val ownedKey = findOwnedKey(input.derivationPaths) ?: run {
                        skippedInputs += 1
                        return@forEachIndexed
                    }
                    if (input.partialSigs.containsKey(ownedKey.publicKey)) {
                        skippedInputs += 1
                        return@forEachIndexed
                    }

                    val plan = buildWitnessSigningPlan(input, ownedKey.publicKey)
                    val signature = signInputDigest(
                        tx = psbt.global.tx,
                        inputIndex = index,
                        signingScript = plan.signingScript,
                        sighashType = plan.sighashType,
                        amount = plan.amount,
                        signatureVersion = plan.signatureVersion,
                        derivationPath = ownedKey.derivationPath,
                    )

                    val updatedInput = input.copy(
                        partialSigs = input.partialSigs + (ownedKey.publicKey to signature)
                    )
                    val finalizedInput = finalizeWitnessInput(
                        updatedInput,
                        ownedKey.publicKey,
                        signature,
                        plan.finalization as WitnessFinalization,
                    )
                    psbt = psbt.copy(inputs = psbt.inputs.replaceAt(index, finalizedInput))
                    signedInputs += PsbtSignedInputDetail(
                        inputIndex = index,
                        derivationPath = ownedKey.derivationPath,
                        scriptType = plan.scriptType,
                        finalized = finalizedInput is Input.WitnessInput.FinalizedWitnessInput,
                    )
                }

                is Input.NonWitnessInput.PartiallySignedNonWitnessInput -> {
                    val ownedKey = findOwnedKey(input.derivationPaths) ?: run {
                        skippedInputs += 1
                        return@forEachIndexed
                    }
                    if (input.partialSigs.containsKey(ownedKey.publicKey)) {
                        skippedInputs += 1
                        return@forEachIndexed
                    }

                    val plan = buildNonWitnessSigningPlan(input, ownedKey.publicKey)
                    val signature = signInputDigest(
                        tx = psbt.global.tx,
                        inputIndex = index,
                        signingScript = plan.signingScript,
                        sighashType = plan.sighashType,
                        amount = plan.amount,
                        signatureVersion = plan.signatureVersion,
                        derivationPath = ownedKey.derivationPath,
                    )

                    val updatedInput = input.copy(
                        partialSigs = input.partialSigs + (ownedKey.publicKey to signature)
                    )
                    val finalizedInput = finalizeNonWitnessInput(
                        updatedInput,
                        ownedKey.publicKey,
                        signature,
                        plan.finalization as NonWitnessFinalization,
                    )
                    psbt = psbt.copy(inputs = psbt.inputs.replaceAt(index, finalizedInput))
                    signedInputs += PsbtSignedInputDetail(
                        inputIndex = index,
                        derivationPath = ownedKey.derivationPath,
                        scriptType = plan.scriptType,
                        finalized = finalizedInput is Input.NonWitnessInput.FinalizedNonWitnessInput,
                    )
                }
            }
        }

        require(signedInputs.isNotEmpty()) {
            "PSBT 中没有找到属于当前卡的可签输入，请确认 Electrum 导出的 PSBT 带有 BIP32 derivation 路径，并且卡内 seed 与该钱包一致"
        }

        val finalizedInputCount = psbt.inputs.count {
            it is Input.FinalizedInputWithoutUtxo ||
                it is Input.WitnessInput.FinalizedWitnessInput ||
                it is Input.NonWitnessInput.FinalizedNonWitnessInput
        }

        val extractedTxHex = if (finalizedInputCount == psbt.inputs.size) {
            when (val extracted = psbt.extract()) {
                is Either.Right -> bytesToHex(Transaction.write(extracted.value))
                is Either.Left -> null
            }
        } else {
            null
        }

        val signedPsbtBytes = Psbt.write(psbt).toByteArray()
        return PsbtSigningOutcome(
            signedPsbtBytes = signedPsbtBytes,
            signedPsbtBase64 = Base64.getEncoder().encodeToString(signedPsbtBytes),
            extractedTxHex = extractedTxHex,
            signedInputs = signedInputs,
            totalInputs = psbt.inputs.size,
            finalizedInputCount = finalizedInputCount,
            skippedInputCount = skippedInputs,
        )
    }

    private fun parsePsbt(psbtBytes: ByteArray): Psbt {
        return when (val parsed = Psbt.read(psbtBytes)) {
            is Either.Right -> parsed.value
            is Either.Left -> throw IllegalArgumentException("PSBT 解析失败: ${formatParseFailure(parsed.value)}")
        }
    }

    private fun findOwnedKey(derivationPaths: Map<PublicKey, KeyPathWithMaster>): OwnedCardKey? {
        for ((expectedPubKey, keyPath) in derivationPaths) {
            val derivationPath = keyPath.keyPath.asString('\'')
            val derivedPubKey = selectCardPublicKey(derivationPath)
            if (derivedPubKey == expectedPubKey) {
                return OwnedCardKey(
                    publicKey = expectedPubKey,
                    derivationPath = derivationPath,
                )
            }
        }
        return null
    }

    private fun selectCardPublicKey(derivationPath: String): PublicKey {
        val cached = cardPubKeyCache[derivationPath]
        if (cached != null && selectedPath == derivationPath) {
            return cached
        }

        val keyData = runCatching {
            commandSet.cardBip32GetExtendedKey(derivationPath, null, null)
        }.getOrElse { error ->
            throw IllegalStateException("BIP32 派生失败 [$derivationPath]: ${error.message}", error)
        }

        val publicKey = PublicKey.parse(keyData[0])
        cardPubKeyCache[derivationPath] = publicKey
        selectedPath = derivationPath
        return publicKey
    }

    private fun signInputDigest(
        tx: Transaction,
        inputIndex: Int,
        signingScript: List<ScriptElt>,
        sighashType: Int,
        amount: Satoshi,
        signatureVersion: Int,
        derivationPath: String,
    ): ByteVector {
        selectCardPublicKey(derivationPath)
        val digest = Transaction.hashForSigning(
            tx,
            inputIndex,
            signingScript,
            sighashType,
            amount,
            signatureVersion,
        )
        val response = runCatching {
            commandSet.cardSignTransactionHash(0xFF.toByte(), digest, null)
        }.getOrElse { error ->
            throw IllegalStateException("卡签名失败 [input=$inputIndex path=$derivationPath]: ${error.message}", error)
        }
        response.checkOK()

        val normalizedDer = normalizeLowS(response.getData())
        return ByteVector(normalizedDer + byteArrayOf((sighashType and 0xff).toByte()))
    }

    private fun buildWitnessSigningPlan(
        input: Input.WitnessInput.PartiallySignedWitnessInput,
        publicKey: PublicKey,
    ): SigningPlan {
        val sighashType = input.sighashType ?: SigHash.SIGHASH_ALL
        val scriptPubKey = runCatching {
            Script.parse(input.txOut.publicKeyScript)
        }.getOrElse { error ->
            throw IllegalArgumentException("无法解析 witness utxo scriptPubKey: ${error.message}", error)
        }

        return when {
            Script.isPay2tr(scriptPubKey) -> {
                throw IllegalArgumentException("暂不支持 Taproot PSBT 输入")
            }

            Script.isPay2wpkh(scriptPubKey) -> SigningPlan(
                signingScript = Script.pay2pkh(publicKey),
                amount = input.amount,
                signatureVersion = SigVersion.SIGVERSION_WITNESS_V0,
                sighashType = sighashType,
                scriptType = "p2wpkh",
                finalization = WitnessFinalization.P2WPKH,
            )

            Script.isPay2wsh(scriptPubKey) -> {
                val witnessScript = input.witnessScript
                    ?: throw IllegalArgumentException("P2WSH 输入缺少 witnessScript")
                SigningPlan(
                    signingScript = witnessScript,
                    amount = input.amount,
                    signatureVersion = SigVersion.SIGVERSION_WITNESS_V0,
                    sighashType = sighashType,
                    scriptType = "p2wsh",
                    finalization = WitnessFinalization.PartialOnly,
                )
            }

            Script.isPay2sh(scriptPubKey) -> {
                val redeemScript = input.redeemScript
                    ?: throw IllegalArgumentException("P2SH 输入缺少 redeemScript")
                val witnessScript = input.witnessScript
                when {
                    Script.isPay2wpkh(redeemScript) -> SigningPlan(
                        signingScript = Script.pay2pkh(publicKey),
                        amount = input.amount,
                        signatureVersion = SigVersion.SIGVERSION_WITNESS_V0,
                        sighashType = sighashType,
                        scriptType = "p2sh-p2wpkh",
                        finalization = WitnessFinalization.P2shP2wpkh(redeemScript),
                    )

                    witnessScript != null && redeemScript == Script.pay2wsh(witnessScript) -> SigningPlan(
                        signingScript = witnessScript,
                        amount = input.amount,
                        signatureVersion = SigVersion.SIGVERSION_WITNESS_V0,
                        sighashType = sighashType,
                        scriptType = "p2sh-p2wsh",
                        finalization = WitnessFinalization.PartialOnly,
                    )

                    else -> SigningPlan(
                        signingScript = redeemScript,
                        amount = input.amount,
                        signatureVersion = SigVersion.SIGVERSION_BASE,
                        sighashType = sighashType,
                        scriptType = "p2sh",
                        finalization = WitnessFinalization.PartialOnly,
                    )
                }
            }

            else -> throw IllegalArgumentException("暂不支持的 witness 输入类型")
        }
    }

    private fun buildNonWitnessSigningPlan(
        input: Input.NonWitnessInput.PartiallySignedNonWitnessInput,
        publicKey: PublicKey,
    ): SigningPlan {
        val sighashType = input.sighashType ?: SigHash.SIGHASH_ALL
        val prevOut = input.inputTx.txOut[input.outputIndex]
        val scriptPubKey = runCatching {
            Script.parse(prevOut.publicKeyScript)
        }.getOrElse { error ->
            throw IllegalArgumentException("无法解析 non-witness utxo scriptPubKey: ${error.message}", error)
        }

        return when {
            Script.isPay2pkh(scriptPubKey) -> SigningPlan(
                signingScript = scriptPubKey,
                amount = input.amount,
                signatureVersion = SigVersion.SIGVERSION_BASE,
                sighashType = sighashType,
                scriptType = "p2pkh",
                finalization = NonWitnessFinalization.P2PKH,
            )

            Script.isPay2sh(scriptPubKey) -> {
                val redeemScript = input.redeemScript
                    ?: throw IllegalArgumentException("P2SH 输入缺少 redeemScript")
                when {
                    Script.isPay2wpkh(redeemScript) -> SigningPlan(
                        signingScript = Script.pay2pkh(publicKey),
                        amount = input.amount,
                        signatureVersion = SigVersion.SIGVERSION_WITNESS_V0,
                        sighashType = sighashType,
                        scriptType = "p2sh-p2wpkh",
                        finalization = NonWitnessFinalization.P2shP2wpkh(redeemScript),
                    )

                    else -> SigningPlan(
                        signingScript = redeemScript,
                        amount = input.amount,
                        signatureVersion = SigVersion.SIGVERSION_BASE,
                        sighashType = sighashType,
                        scriptType = "p2sh",
                        finalization = NonWitnessFinalization.PartialOnly,
                    )
                }
            }

            else -> SigningPlan(
                signingScript = input.redeemScript ?: scriptPubKey,
                amount = input.amount,
                signatureVersion = SigVersion.SIGVERSION_BASE,
                sighashType = sighashType,
                scriptType = "legacy",
                finalization = NonWitnessFinalization.PartialOnly,
            )
        }
    }

    private fun finalizeWitnessInput(
        input: Input.WitnessInput.PartiallySignedWitnessInput,
        publicKey: PublicKey,
        signature: ByteVector,
        finalization: WitnessFinalization,
    ): Input {
        return when (finalization) {
            is WitnessFinalization.P2WPKH -> Input.WitnessInput.FinalizedWitnessInput(
                txOut = input.txOut,
                nonWitnessUtxo = input.nonWitnessUtxo,
                scriptWitness = ScriptWitness(
                    listOf(signature, publicKey.value)
                ),
                scriptSig = null,
                ripemd160 = input.ripemd160,
                sha256 = input.sha256,
                hash160 = input.hash160,
                hash256 = input.hash256,
                unknown = input.unknown,
            )

            is WitnessFinalization.P2shP2wpkh -> Input.WitnessInput.FinalizedWitnessInput(
                txOut = input.txOut,
                nonWitnessUtxo = input.nonWitnessUtxo,
                scriptWitness = ScriptWitness(
                    listOf(signature, publicKey.value)
                ),
                scriptSig = listOf(OP_PUSHDATA(Script.write(finalization.redeemScript))),
                ripemd160 = input.ripemd160,
                sha256 = input.sha256,
                hash160 = input.hash160,
                hash256 = input.hash256,
                unknown = input.unknown,
            )

            WitnessFinalization.PartialOnly -> input
        }
    }

    private fun finalizeNonWitnessInput(
        input: Input.NonWitnessInput.PartiallySignedNonWitnessInput,
        publicKey: PublicKey,
        signature: ByteVector,
        finalization: NonWitnessFinalization,
    ): Input {
        return when (finalization) {
            NonWitnessFinalization.P2PKH -> Input.NonWitnessInput.FinalizedNonWitnessInput(
                inputTx = input.inputTx,
                outputIndex = input.outputIndex,
                scriptSig = listOf(
                    OP_PUSHDATA(signature),
                    OP_PUSHDATA(publicKey.value),
                ),
                ripemd160 = input.ripemd160,
                sha256 = input.sha256,
                hash160 = input.hash160,
                hash256 = input.hash256,
                unknown = input.unknown,
            )

            is NonWitnessFinalization.P2shP2wpkh -> Input.WitnessInput.FinalizedWitnessInput(
                txOut = input.inputTx.txOut[input.outputIndex],
                nonWitnessUtxo = input.inputTx,
                scriptWitness = ScriptWitness(
                    listOf(signature, publicKey.value)
                ),
                scriptSig = listOf(OP_PUSHDATA(Script.write(finalization.redeemScript))),
                ripemd160 = input.ripemd160,
                sha256 = input.sha256,
                hash160 = input.hash160,
                hash256 = input.hash256,
                unknown = input.unknown,
            )

            NonWitnessFinalization.PartialOnly -> input
        }
    }

    private fun normalizeLowS(derSignature: ByteArray): ByteArray {
        val rs = parser.decodeFromDER(derSignature)
        val r = rs[0]
        val s = if (rs[1] > HALF_CURVE_ORDER) CURVE_ORDER.subtract(rs[1]) else rs[1]
        val vector = ASN1EncodableVector()
        vector.add(ASN1Integer(r))
        vector.add(ASN1Integer(s))
        return DERSequence(vector).encoded
    }

    private fun formatParseFailure(failure: ParseFailure): String {
        return when (failure) {
            ParseFailure.InvalidMagicBytes -> "缺少 PSBT 魔数"
            ParseFailure.InvalidSeparator -> "PSBT 头部分隔符错误"
            ParseFailure.DuplicateKeys -> "PSBT 中存在重复 key"
            ParseFailure.GlobalTxMissing -> "PSBT 缺少全局交易"
            ParseFailure.InvalidContent -> "PSBT 内容损坏"
            is ParseFailure.InvalidPsbtVersion -> failure.reason
            is ParseFailure.UnsupportedPsbtVersion -> "暂不支持的 PSBT 版本: ${failure.version}"
            is ParseFailure.InvalidGlobalTx -> failure.reason
            is ParseFailure.InvalidExtendedPublicKey -> failure.reason
            is ParseFailure.InvalidTxInput -> failure.reason
            is ParseFailure.InvalidTxOutput -> failure.reason
        }
    }

    private data class OwnedCardKey(
        val publicKey: PublicKey,
        val derivationPath: String,
    )

    private data class SigningPlan(
        val signingScript: List<ScriptElt>,
        val amount: Satoshi,
        val signatureVersion: Int,
        val sighashType: Int,
        val scriptType: String,
        val finalization: Finalization,
    )

    private sealed interface Finalization

    private sealed interface WitnessFinalization : Finalization {
        data object P2WPKH : WitnessFinalization
        data class P2shP2wpkh(val redeemScript: List<ScriptElt>) : WitnessFinalization
        data object PartialOnly : WitnessFinalization
    }

    private sealed interface NonWitnessFinalization : Finalization {
        data object P2PKH : NonWitnessFinalization
        data class P2shP2wpkh(val redeemScript: List<ScriptElt>) : NonWitnessFinalization
        data object PartialOnly : NonWitnessFinalization
    }

    private fun <T> List<T>.replaceAt(index: Int, value: T): List<T> {
        val mutable = toMutableList()
        mutable[index] = value
        return mutable.toList()
    }

    private companion object {
        private val CURVE_ORDER: BigInteger = SECNamedCurves.getByName("secp256k1").n
        private val HALF_CURVE_ORDER: BigInteger = CURVE_ORDER.shiftRight(1)
    }
}
