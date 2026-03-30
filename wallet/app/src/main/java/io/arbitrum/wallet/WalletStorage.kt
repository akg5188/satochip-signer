package io.arbitrum.wallet

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

object WalletStorage {
    private const val LEGACY_PREFS_NAME = "satochip_multi_wallet"
    private const val SECURE_PREFS_NAME = "satochip_multi_wallet_secure"
    private const val KEY_MIGRATED_FROM_LEGACY = "_migrated_from_legacy"
    private const val KEY_ADDRESSES = "addresses"
    private const val KEY_SELECTED_ADDRESS = "selected_address"
    private const val KEY_SELECTED_CHAIN_ID = "selected_chain_id"
    private const val KEY_EVM_DERIVATION_PATH = "evm_derivation_path"
    private const val KEY_CONTACTS = "contacts"
    private const val KEY_ACTIVITY = "activity"
    private const val KEY_TRUSTED_DAPP_HOSTS = "trusted_dapp_hosts"
    private const val LEGACY_KEY_HYPERLIQUID_AGENTS = "hyperliquid_agents"
    private const val KEY_BITCOIN_WATCH_ACCOUNTS = "bitcoin_watch_accounts"

    fun openSecurePreferences(context: Context): SharedPreferences {
        val appContext = context.applicationContext
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        val securePrefs = EncryptedSharedPreferences.create(
            appContext,
            SECURE_PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
        migrateLegacyPrefs(appContext, securePrefs)
        securePrefs.edit().remove(LEGACY_KEY_HYPERLIQUID_AGENTS).apply()
        return securePrefs
    }

    private fun migrateLegacyPrefs(context: Context, securePrefs: SharedPreferences) {
        if (securePrefs.getBoolean(KEY_MIGRATED_FROM_LEGACY, false)) {
            return
        }
        val legacyPrefs = context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
        val editor = securePrefs.edit()
        if (legacyPrefs.contains(KEY_ADDRESSES)) {
            editor.putString(KEY_ADDRESSES, legacyPrefs.getString(KEY_ADDRESSES, null))
        }
        if (legacyPrefs.contains(KEY_SELECTED_ADDRESS)) {
            editor.putString(KEY_SELECTED_ADDRESS, legacyPrefs.getString(KEY_SELECTED_ADDRESS, null))
        }
        if (legacyPrefs.contains(KEY_SELECTED_CHAIN_ID)) {
            editor.putLong(KEY_SELECTED_CHAIN_ID, legacyPrefs.getLong(KEY_SELECTED_CHAIN_ID, WalletChains.DEFAULT.chainId))
        }
        if (legacyPrefs.contains(KEY_EVM_DERIVATION_PATH)) {
            editor.putString(KEY_EVM_DERIVATION_PATH, legacyPrefs.getString(KEY_EVM_DERIVATION_PATH, DEFAULT_EVM_DERIVATION_PATH))
        }
        if (legacyPrefs.contains(KEY_CONTACTS)) {
            editor.putString(KEY_CONTACTS, legacyPrefs.getString(KEY_CONTACTS, null))
        }
        if (legacyPrefs.contains(KEY_ACTIVITY)) {
            editor.putString(KEY_ACTIVITY, legacyPrefs.getString(KEY_ACTIVITY, null))
        }
        if (legacyPrefs.contains(KEY_TRUSTED_DAPP_HOSTS)) {
            editor.putString(KEY_TRUSTED_DAPP_HOSTS, legacyPrefs.getString(KEY_TRUSTED_DAPP_HOSTS, null))
        }
        if (legacyPrefs.contains(KEY_BITCOIN_WATCH_ACCOUNTS)) {
            editor.putString(KEY_BITCOIN_WATCH_ACCOUNTS, legacyPrefs.getString(KEY_BITCOIN_WATCH_ACCOUNTS, null))
        }
        editor.putBoolean(KEY_MIGRATED_FROM_LEGACY, true).apply()
        legacyPrefs.edit().clear().apply()
    }

    fun readAddresses(prefs: SharedPreferences, normalizer: (String?) -> String?): List<String> {
        val raw = prefs.getString(KEY_ADDRESSES, null)
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            buildList {
                val array = JSONArray(raw)
                for (index in 0 until array.length()) {
                    normalizer(array.optString(index))?.let(::add)
                }
            }
        }.getOrDefault(emptyList())
    }

    fun writeAddresses(prefs: SharedPreferences, addresses: List<String>, selectedAddress: String) {
        val array = JSONArray().apply {
            addresses.forEach(::put)
        }
        prefs.edit()
            .putString(KEY_ADDRESSES, array.toString())
            .putString(KEY_SELECTED_ADDRESS, selectedAddress)
            .apply()
    }

    fun readSelectedAddress(prefs: SharedPreferences, normalizer: (String?) -> String?): String {
        return normalizer(prefs.getString(KEY_SELECTED_ADDRESS, "")).orEmpty()
    }

    fun readSelectedChainId(prefs: SharedPreferences): Long {
        return prefs.getLong(KEY_SELECTED_CHAIN_ID, WalletChains.DEFAULT.chainId)
    }

    fun writeSelectedChainId(prefs: SharedPreferences, chainId: Long) {
        prefs.edit().putLong(KEY_SELECTED_CHAIN_ID, chainId).apply()
    }

    fun readEvmDerivationPath(prefs: SharedPreferences): String {
        return prefs.getString(KEY_EVM_DERIVATION_PATH, DEFAULT_EVM_DERIVATION_PATH)
            ?.trim()
            ?.takeIf { it.isNotBlank() }
            ?: DEFAULT_EVM_DERIVATION_PATH
    }

    fun writeEvmDerivationPath(prefs: SharedPreferences, path: String) {
        prefs.edit().putString(KEY_EVM_DERIVATION_PATH, path).apply()
    }

    fun readContacts(prefs: SharedPreferences, normalizer: (String?) -> String?): List<TransferContact> {
        val raw = prefs.getString(KEY_CONTACTS, null)
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            buildList {
                val array = JSONArray(raw)
                for (index in 0 until array.length()) {
                    val obj = array.optJSONObject(index) ?: continue
                    val address = normalizer(obj.optString("address")) ?: continue
                    add(
                        TransferContact(
                            id = obj.optString("id").ifBlank { "contact-$index" },
                            name = obj.optString("name").ifBlank { address.take(8) },
                            address = address,
                            note = obj.optString("note"),
                            chainId = obj.optLong("chainId").takeIf { obj.has("chainId") && it > 0 },
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    fun writeContacts(prefs: SharedPreferences, contacts: List<TransferContact>) {
        val array = JSONArray().apply {
            contacts.forEach { contact ->
                put(
                    JSONObject().apply {
                        put("id", contact.id)
                        put("name", contact.name)
                        put("address", contact.address)
                        put("note", contact.note)
                        contact.chainId?.let { put("chainId", it) }
                    }
                )
            }
        }
        prefs.edit().putString(KEY_CONTACTS, array.toString()).apply()
    }

    fun readActivity(prefs: SharedPreferences): List<WalletActivityItem> {
        val raw = prefs.getString(KEY_ACTIVITY, null)
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            buildList {
                val array = JSONArray(raw)
                for (index in 0 until array.length()) {
                    val obj = array.optJSONObject(index) ?: continue
                    add(
                        WalletActivityItem(
                            id = obj.optString("id").ifBlank { "activity-$index" },
                            chainId = obj.optLong("chainId", WalletChains.DEFAULT.chainId),
                            kind = WalletActivityKind.valueOf(
                                obj.optString("kind").ifBlank { WalletActivityKind.SYSTEM.name }
                            ),
                            title = obj.optString("title"),
                            subtitle = obj.optString("subtitle"),
                            detail = obj.optString("detail"),
                            amountLabel = obj.optString("amountLabel"),
                            statusLabel = obj.optString("statusLabel"),
                            timestamp = obj.optLong("timestamp"),
                            txHash = obj.optString("txHash"),
                            externalUrl = obj.optString("externalUrl"),
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    fun writeActivity(prefs: SharedPreferences, items: List<WalletActivityItem>) {
        val trimmed = items.sortedByDescending { it.timestamp }.take(100)
        val array = JSONArray().apply {
            trimmed.forEach { item ->
                put(
                    JSONObject().apply {
                        put("id", item.id)
                        put("chainId", item.chainId)
                        put("kind", item.kind.name)
                        put("title", item.title)
                        put("subtitle", item.subtitle)
                        put("detail", item.detail)
                        put("amountLabel", item.amountLabel)
                        put("statusLabel", item.statusLabel)
                        put("timestamp", item.timestamp)
                        put("txHash", item.txHash)
                        put("externalUrl", item.externalUrl)
                    }
                )
            }
        }
        prefs.edit().putString(KEY_ACTIVITY, array.toString()).apply()
    }

    fun readTrustedDappEntries(
        prefs: SharedPreferences,
        defaultChainId: Long,
        defaultAddress: String,
        normalizer: (String?) -> String?,
    ): List<TrustedDappEntry> {
        val raw = prefs.getString(KEY_TRUSTED_DAPP_HOSTS, null)
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            buildList {
                val array = JSONArray(raw)
                for (index in 0 until array.length()) {
                    when (val item = array.opt(index)) {
                        is String -> {
                            val host = item.trim().lowercase()
                            val address = normalizer(defaultAddress).orEmpty()
                            if (host.isNotBlank() && address.isNotBlank()) {
                                add(
                                    TrustedDappEntry(
                                        host = host,
                                        chainId = defaultChainId,
                                        address = address,
                                        trustedAt = 0L,
                                    )
                                )
                            }
                        }

                        is JSONObject -> {
                            val host = item.optString("host").trim().lowercase()
                            val chainId = item.optLong("chainId", defaultChainId)
                            val address = normalizer(item.optString("address")).orEmpty()
                            if (host.isNotBlank() && chainId > 0L && address.isNotBlank()) {
                                add(
                                    TrustedDappEntry(
                                        host = host,
                                        chainId = chainId,
                                        address = address,
                                        trustedAt = item.optLong("trustedAt", 0L),
                                    )
                                )
                            }
                        }
                    }
                }
            }.distinctBy { "${it.host}|${it.chainId}|${it.address.lowercase()}" }
        }.getOrDefault(emptyList())
    }

    fun writeTrustedDappEntries(prefs: SharedPreferences, entries: List<TrustedDappEntry>) {
        val array = JSONArray().apply {
            entries.mapNotNull { entry ->
                val host = entry.host.trim().lowercase()
                val address = entry.address.trim()
                if (host.isBlank() || address.isBlank() || entry.chainId <= 0L) {
                    null
                } else {
                    JSONObject().apply {
                        put("host", host)
                        put("chainId", entry.chainId)
                        put("address", address)
                        put("trustedAt", entry.trustedAt)
                    }
                }
            }.distinctBy { "${it.optString("host")}|${it.optLong("chainId")}|${it.optString("address").lowercase()}" }
                .forEach(::put)
        }
        prefs.edit().putString(KEY_TRUSTED_DAPP_HOSTS, array.toString()).apply()
    }

    fun readBitcoinWatchAccounts(prefs: SharedPreferences): List<BitcoinWatchAccount> {
        val raw = prefs.getString(KEY_BITCOIN_WATCH_ACCOUNTS, null)
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            buildList {
                val array = JSONArray(raw)
                for (index in 0 until array.length()) {
                    val obj = array.optJSONObject(index) ?: continue
                    val xpub = obj.optString("xpub").trim()
                    if (xpub.isBlank()) continue
                    add(
                        BitcoinWatchAccount(
                            id = obj.optString("id").ifBlank { "btc-account-$index" },
                            label = obj.optString("label").ifBlank { "BTC account ${index + 1}" },
                            xpub = xpub,
                            prefix = obj.optString("prefix").ifBlank { xpub.take(4).lowercase() },
                            networkLabel = obj.optString("networkLabel").ifBlank { "Bitcoin" },
                            scriptTypeLabel = obj.optString("scriptTypeLabel").ifBlank { "Unknown" },
                            accountPathHint = obj.optString("accountPathHint"),
                            sourceLabel = obj.optString("sourceLabel").ifBlank { "Imported from offline-signer get-xpub" },
                            importedAt = obj.optLong("importedAt"),
                            balanceSats = obj.optLong("balanceSats", 0L),
                            priceUsd = obj.optDouble("priceUsd").takeIf { !it.isNaN() && it > 0.0 },
                            utxoCount = obj.optInt("utxoCount", 0),
                            nextReceiveAddress = obj.optString("nextReceiveAddress"),
                            nextChangeAddress = obj.optString("nextChangeAddress"),
                            lastSyncStatus = obj.optString("lastSyncStatus"),
                            lastSyncAt = obj.optLong("lastSyncAt", 0L),
                            recentActivity = buildList {
                                val activityArray = obj.optJSONArray("recentActivity") ?: JSONArray()
                                for (activityIndex in 0 until activityArray.length()) {
                                    val item = activityArray.optJSONObject(activityIndex) ?: continue
                                    add(
                                        WalletActivityItem(
                                            id = item.optString("id").ifBlank { "btc-activity-$activityIndex" },
                                            chainId = item.optLong("chainId", WalletChains.DEFAULT.chainId),
                                            kind = WalletActivityKind.valueOf(
                                                item.optString("kind").ifBlank { WalletActivityKind.ONCHAIN.name }
                                            ),
                                            title = item.optString("title"),
                                            subtitle = item.optString("subtitle"),
                                            detail = item.optString("detail"),
                                            amountLabel = item.optString("amountLabel"),
                                            statusLabel = item.optString("statusLabel"),
                                            timestamp = item.optLong("timestamp", 0L),
                                            txHash = item.optString("txHash"),
                                            externalUrl = item.optString("externalUrl"),
                                        )
                                    )
                                }
                            },
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    fun writeBitcoinWatchAccounts(prefs: SharedPreferences, accounts: List<BitcoinWatchAccount>) {
        val array = JSONArray().apply {
            accounts.sortedByDescending { it.importedAt }.forEach { account ->
                put(
                    JSONObject().apply {
                        put("id", account.id)
                        put("label", account.label)
                        put("xpub", account.xpub)
                        put("prefix", account.prefix)
                        put("networkLabel", account.networkLabel)
                        put("scriptTypeLabel", account.scriptTypeLabel)
                        put("accountPathHint", account.accountPathHint)
                        put("sourceLabel", account.sourceLabel)
                        put("importedAt", account.importedAt)
                        put("balanceSats", account.balanceSats)
                        account.priceUsd?.let { put("priceUsd", it) }
                        put("utxoCount", account.utxoCount)
                        put("nextReceiveAddress", account.nextReceiveAddress)
                        put("nextChangeAddress", account.nextChangeAddress)
                        put("lastSyncStatus", account.lastSyncStatus)
                        put("lastSyncAt", account.lastSyncAt)
                        put(
                            "recentActivity",
                            JSONArray().apply {
                                account.recentActivity.forEach { item ->
                                    put(
                                        JSONObject().apply {
                                            put("id", item.id)
                                            put("chainId", item.chainId)
                                            put("kind", item.kind.name)
                                            put("title", item.title)
                                            put("subtitle", item.subtitle)
                                            put("detail", item.detail)
                                            put("amountLabel", item.amountLabel)
                                            put("statusLabel", item.statusLabel)
                                            put("timestamp", item.timestamp)
                                            put("txHash", item.txHash)
                                            put("externalUrl", item.externalUrl)
                                        }
                                    )
                                }
                            },
                        )
                    }
                )
            }
        }
        prefs.edit().putString(KEY_BITCOIN_WATCH_ACCOUNTS, array.toString()).apply()
    }

}
