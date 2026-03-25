package io.arbitrum.wallet

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Message
import android.text.format.DateUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import java.math.BigDecimal
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private interface InjectedBrowserHost {
    fun createInjectedWalletBridge(): InjectedWalletBridge
    fun injectWalletProviderInto(webView: WebView)
    fun reportBrowserRuntimeIssue(message: String)
}

abstract class InjectedWalletBridge {
    @JavascriptInterface
    abstract fun request(requestId: String, method: String, paramsJson: String?, origin: String?)

    @JavascriptInterface
    abstract fun reportIssue(level: String?, message: String?, source: String?, line: Int)
}

class MainActivity : BiometricGateActivity(), InjectedBrowserHost {
    private enum class GalleryImportTarget {
        REQUEST,
        RESPONSE,
    }

    private val viewModel: MainViewModel by viewModels()
    private var galleryImportTarget = GalleryImportTarget.REQUEST
    private var hyperliquidWebView: WebView? = null

    private val requestQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(ContinuousQrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.onRequestScanResult(text)
    }

    private val bitcoinImportQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(QrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.setBitcoinImportInput(text)
    }

    private val responseQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(QrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.onResponseScanResult(text)
    }

    private val galleryQrLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val payload = QrImageDecoder.decodeFromUri(this@MainActivity, uri)
            if (payload.isNullOrBlank()) {
                Toast.makeText(this@MainActivity, "相册图片未识别到二维码", Toast.LENGTH_SHORT).show()
                return@launch
            }
            when (galleryImportTarget) {
                GalleryImportTarget.REQUEST -> viewModel.onRequestScanResult(payload)
                GalleryImportTarget.RESPONSE -> viewModel.onResponseScanResult(payload)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        lifecycleScope.launch {
            viewModel.browserCommands.collect { command ->
                dispatchInjectedBrowserCommand(command)
            }
        }
        setContent {
            val state by viewModel.uiState.collectAsStateWithLifecycle()
            MaterialTheme {
                WalletScreen(
                    state = state,
                    onSelectTab = viewModel::setActiveTab,
                    onOpenHyperliquid = ::openHyperliquid,
                    onSelectChain = viewModel::selectChain,
                    onNewAddressChange = viewModel::setNewAddressInput,
                    onEvmDerivationPathChange = viewModel::setEvmDerivationPath,
                    onAddAddress = viewModel::addAddressFromInput,
                    onPrepareDerivedAddressImport = viewModel::prepareDerivedAddressImport,
                    onSelectAddress = viewModel::selectAddress,
                    onRemoveAddress = viewModel::removeAddress,
                    onRefreshBalances = viewModel::refreshSelectedActivity,
                    onBitcoinImportInputChange = viewModel::setBitcoinImportInput,
                    onScanBitcoinWatchAccount = ::startBitcoinImportScan,
                    onImportBitcoinWatchAccount = viewModel::importBitcoinWatchAccount,
                    onRemoveBitcoinWatchAccount = viewModel::removeBitcoinWatchAccount,
                    onSyncBitcoinWatchAccount = viewModel::syncBitcoinWatchAccount,
                    onPrepareBitcoinTransfer = viewModel::prepareBitcoinTransfer,
                    onTransferToChange = viewModel::setTransferTo,
                    onTransferAmountChange = viewModel::setTransferAmount,
                    onTransferTokenChange = viewModel::setTransferToken,
                    onTransferAmountAll = viewModel::transferAllTokens,
                    onPrepareTransfer = viewModel::prepareTransfer,
                    onRequestInputChange = viewModel::setRequestInput,
                    onImportRawRequest = viewModel::importRawRequest,
                    onImportRequestFromClipboard = ::importRequestFromClipboard,
                    onApproveWalletConnectProposal = viewModel::approveWalletConnectProposal,
                    onRejectWalletConnectProposal = viewModel::rejectWalletConnectProposal,
                    onPrevRelayPage = viewModel::prevSignQrPage,
                    onNextRelayPage = viewModel::nextSignQrPage,
                    onAutoAdvanceRelayPage = viewModel::nextSignQrPage,
                    onScanRequest = ::startRequestScan,
                    onPickRequestFromGallery = ::startRequestGalleryImport,
                    onScanResponse = ::startResponseScan,
                    onPickResponseFromGallery = ::startResponseGalleryImport,
                    onOpenUrl = ::openExternalUrl,
                    onClearPreparedRequest = viewModel::clearPreparedRequest,
                    onClearError = viewModel::clearError,
                    onClearInfo = viewModel::clearInfo,
                    onClearTxHash = viewModel::clearTxHash,
                    onClearSignature = viewModel::clearSignature,
                )
            }
        }
    }

    private fun attachHyperliquidWebView(webView: WebView?) {
        hyperliquidWebView = webView
    }

    private fun dispatchInjectedBrowserCommand(command: InjectedBrowserCommand) {
        val webView = hyperliquidWebView ?: return
        val script = when (command) {
            is InjectedBrowserCommand.Resolve ->
                """
                    (function() {
                      if (typeof window.__satochipWalletResolve === 'function') {
                        window.__satochipWalletResolve(${jsString(command.requestId)}, ${command.resultJsonLiteral});
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.Reject ->
                """
                    (function() {
                      if (typeof window.__satochipWalletReject === 'function') {
                        window.__satochipWalletReject(${jsString(command.requestId)}, ${command.code}, ${jsString(command.message)});
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.AccountsChanged ->
                """
                    (function() {
                      var accounts = ${org.json.JSONArray(command.accounts).toString()};
                      window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                      window.__SATOCHIP_BOOTSTRAP__.accounts = accounts;
                      if (typeof window.__satochipWalletSetAccounts === 'function') {
                        window.__satochipWalletSetAccounts(accounts);
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.ChainChanged ->
                """
                    (function() {
                      var chainId = ${jsString(command.chainIdHex)};
                      window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                      window.__SATOCHIP_BOOTSTRAP__.chainId = chainId;
                      if (typeof window.__satochipWalletSetChain === 'function') {
                        window.__satochipWalletSetChain(chainId);
                      }
                    })();
                """.trimIndent()
        }
        webView.post {
            webView.evaluateJavascript(script, null)
        }
    }

    private fun injectWalletProvider(webView: WebView) {
        webView.post {
            webView.evaluateJavascript(buildInjectedEthereumProviderScript(), null)
        }
    }

    private inner class InjectedWalletJavascriptBridge : InjectedWalletBridge() {
        @JavascriptInterface
        override fun request(requestId: String, method: String, paramsJson: String?, origin: String?) {
            viewModel.handleInjectedBrowserRequest(
                requestId = requestId,
                method = method,
                paramsJson = paramsJson.orEmpty().ifBlank { "[]" },
                origin = origin.orEmpty(),
            )
        }

        @JavascriptInterface
        override fun reportIssue(level: String?, message: String?, source: String?, line: Int) {
            val parts = buildList {
                add(level.orEmpty().ifBlank { "js" })
                source?.takeIf { it.isNotBlank() }?.let { add(it) }
                if (line > 0) add("line $line")
                message?.takeIf { it.isNotBlank() }?.let { add(it) }
            }
            viewModel.reportBrowserRuntimeIssue(parts.joinToString(" · "))
        }
    }

    override fun createInjectedWalletBridge(): InjectedWalletBridge = InjectedWalletJavascriptBridge()
    override fun injectWalletProviderInto(webView: WebView) = injectWalletProvider(webView)
    override fun reportBrowserRuntimeIssue(message: String) = viewModel.reportBrowserRuntimeIssue(message)

    private fun startRequestScan() {
        val intent = Intent(this, ContinuousQrScanActivity::class.java)
            .putExtra(ContinuousQrScanActivity.EXTRA_SCAN_MODE, ContinuousQrScanActivity.MODE_REQUEST)
        requestQrLauncher.launch(intent)
    }

    private fun startBitcoinImportScan() {
        val intent = Intent(this, QrScanActivity::class.java)
            .putExtra(QrScanActivity.EXTRA_STATUS_TEXT, "请扫描树莓派导出的 xpub / zpub 二维码")
        bitcoinImportQrLauncher.launch(intent)
    }

    private fun startResponseScan() {
        val intent = Intent(this, QrScanActivity::class.java)
            .putExtra(QrScanActivity.EXTRA_STATUS_TEXT, "请扫描树莓派签名结果二维码")
        responseQrLauncher.launch(intent)
    }

    private fun startRequestGalleryImport() {
        galleryImportTarget = GalleryImportTarget.REQUEST
        galleryQrLauncher.launch("image/*")
    }

    private fun startResponseGalleryImport() {
        galleryImportTarget = GalleryImportTarget.RESPONSE
        galleryQrLauncher.launch("image/*")
    }

    private fun importRequestFromClipboard() {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val text = clipboard.primaryClip?.getItemAt(0)?.coerceToText(this)?.toString()?.trim().orEmpty()
        if (text.isBlank()) {
            Toast.makeText(this, "剪贴板没有可用链接", Toast.LENGTH_SHORT).show()
            return
        }
        viewModel.onRequestScanResult(text)
    }

    private fun openExternalUrl(url: String) {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }

    private fun openHyperliquid() {
        startActivity(Intent(this, HyperliquidActivity::class.java))
    }
}

class HyperliquidActivity : BiometricGateActivity(), InjectedBrowserHost {
    private val viewModel: MainViewModel by viewModels()
    private var hyperliquidWebView: WebView? = null
    private var currentState = WalletUiState()
    private var qrAutoAdvanceJob: Job? = null
    private lateinit var rootLayout: FrameLayout
    private lateinit var contentLayout: LinearLayout
    private lateinit var toolbarLayout: LinearLayout
    private lateinit var bannerContainer: LinearLayout
    private lateinit var bottomBannerContainer: LinearLayout
    private lateinit var qrOverlay: FrameLayout
    private lateinit var qrCard: LinearLayout
    private lateinit var qrTitleView: TextView
    private lateinit var qrSummaryView: TextView
    private lateinit var qrHintView: TextView
    private lateinit var qrPageView: TextView
    private lateinit var qrImageView: ImageView
    private lateinit var qrPrevButton: TextView
    private lateinit var qrNextButton: TextView
    private lateinit var qrScanButton: TextView
    private lateinit var qrGalleryButton: TextView
    private lateinit var qrCloseButton: TextView

    private val responseQrLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val text = result.data?.getStringExtra(QrScanActivity.EXTRA_QR_RESULT) ?: return@registerForActivityResult
        viewModel.onResponseScanResult(text)
    }

    private val galleryQrLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val payload = QrImageDecoder.decodeFromUri(this@HyperliquidActivity, uri)
            if (payload.isNullOrBlank()) {
                Toast.makeText(this@HyperliquidActivity, "相册图片未识别到二维码", Toast.LENGTH_SHORT).show()
                return@launch
            }
            viewModel.onResponseScanResult(payload)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        configureWindowChrome()
        buildNativeLayout()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (currentState.signQrBitmap != null) {
                    viewModel.clearPreparedRequest()
                } else {
                    finish()
                }
            }
        })
        lifecycleScope.launch {
            viewModel.browserCommands.collect { command ->
                dispatchInjectedBrowserCommand(command)
            }
        }
        lifecycleScope.launch {
            viewModel.uiState.collect { state ->
                currentState = state
                renderState(state)
            }
        }
    }

    private fun attachHyperliquidWebView(webView: WebView?) {
        hyperliquidWebView = webView
    }

    private fun dispatchInjectedBrowserCommand(command: InjectedBrowserCommand) {
        val webView = hyperliquidWebView ?: return
        val script = when (command) {
            is InjectedBrowserCommand.Resolve ->
                """
                    (function() {
                      if (typeof window.__satochipWalletResolve === 'function') {
                        window.__satochipWalletResolve(${jsString(command.requestId)}, ${command.resultJsonLiteral});
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.Reject ->
                """
                    (function() {
                      if (typeof window.__satochipWalletReject === 'function') {
                        window.__satochipWalletReject(${jsString(command.requestId)}, ${command.code}, ${jsString(command.message)});
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.AccountsChanged ->
                """
                    (function() {
                      var accounts = ${org.json.JSONArray(command.accounts).toString()};
                      window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                      window.__SATOCHIP_BOOTSTRAP__.accounts = accounts;
                      if (typeof window.__satochipWalletSetAccounts === 'function') {
                        window.__satochipWalletSetAccounts(accounts);
                      }
                    })();
                """.trimIndent()
            is InjectedBrowserCommand.ChainChanged ->
                """
                    (function() {
                      var chainId = ${jsString(command.chainIdHex)};
                      window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                      window.__SATOCHIP_BOOTSTRAP__.chainId = chainId;
                      if (typeof window.__satochipWalletSetChain === 'function') {
                        window.__satochipWalletSetChain(chainId);
                      }
                    })();
                """.trimIndent()
        }
        webView.post {
            webView.evaluateJavascript(script, null)
        }
    }

    private inner class InjectedWalletJavascriptBridge : InjectedWalletBridge() {
        @JavascriptInterface
        override fun request(requestId: String, method: String, paramsJson: String?, origin: String?) {
            viewModel.handleInjectedBrowserRequest(
                requestId = requestId,
                method = method,
                paramsJson = paramsJson.orEmpty().ifBlank { "[]" },
                origin = origin.orEmpty(),
            )
        }

        @JavascriptInterface
        override fun reportIssue(level: String?, message: String?, source: String?, line: Int) {
            val parts = buildList {
                add(level.orEmpty().ifBlank { "js" })
                source?.takeIf { it.isNotBlank() }?.let { add(it) }
                if (line > 0) add("line $line")
                message?.takeIf { it.isNotBlank() }?.let { add(it) }
            }
            viewModel.reportBrowserRuntimeIssue(parts.joinToString(" · "))
        }
    }

    override fun createInjectedWalletBridge(): InjectedWalletBridge = InjectedWalletJavascriptBridge()

    override fun injectWalletProviderInto(webView: WebView) {
        webView.post {
            webView.evaluateJavascript(buildInjectedEthereumProviderScript(), null)
        }
    }

    override fun reportBrowserRuntimeIssue(message: String) {
        viewModel.reportBrowserRuntimeIssue(message)
    }

    private fun configureWindowChrome() {
        val dark = 0xFF07111C.toInt()
        window.statusBarColor = dark
        window.navigationBarColor = dark
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
        }
        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.isAppearanceLightStatusBars = false
        controller.isAppearanceLightNavigationBars = false
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun buildNativeLayout() {
        rootLayout = FrameLayout(this).apply {
            setBackgroundColor(0xFF07111C.toInt())
        }
        contentLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFF07111C.toInt())
        }
        rootLayout.addView(
            contentLayout,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )

        toolbarLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(0xFF07111C.toInt())
        }
        val closeView = toolbarActionText("关闭", Gravity.START) { finish() }.apply {
            setTextColor(0xFFE2E8F0.toInt())
        }
        val titleView = TextView(this).apply {
            text = getString(R.string.hyperliquid_name)
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 19f
            gravity = Gravity.CENTER
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val externalView = toolbarActionText("外部打开", Gravity.END) {
            openExternalUrl("https://app.hyperliquid.xyz/trade")
        }.apply {
            setTextColor(0xFF67E8F9.toInt())
        }
        toolbarLayout.addView(closeView)
        toolbarLayout.addView(titleView)
        toolbarLayout.addView(externalView)
        contentLayout.addView(
            toolbarLayout,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT),
        )

        val webView = WebView(this).apply {
            setBackgroundColor(0xFF07111C.toInt())
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            settings.useWideViewPort = false
            settings.loadWithOverviewMode = false
            settings.setSupportZoom(false)
            settings.setSupportMultipleWindows(true)
            settings.builtInZoomControls = false
            settings.displayZoomControls = false
            settings.javaScriptCanOpenWindowsAutomatically = true
            settings.textZoom = 100
            settings.userAgentString = buildBrowserLikeUserAgent(settings.userAgentString)
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            overScrollMode = WebView.OVER_SCROLL_NEVER
            clearCache(true)
            webChromeClient = HyperliquidWebChromeClient(
                onOpenExternal = ::openExternalUrl,
                onBrowserIssue = { message -> reportBrowserRuntimeIssue(message) },
            )
            addJavascriptInterface(createInjectedWalletBridge(), "SatochipAndroid")
            val supportsDocumentStart = registerDocumentStartScriptIfAvailable(
                this,
                buildInjectedEthereumProviderScript(),
            )
            webViewClient = HyperliquidInjectedWebViewClient(
                injectOnPageFinished = !supportsDocumentStart,
                onInjectProvider = ::injectWalletProviderInto,
                onOpenExternal = ::openExternalUrl,
                onBrowserIssue = { message -> reportBrowserRuntimeIssue(message) },
                onPageReady = { view ->
                    view?.let(::refreshInjectedBrowserViewport)
                    viewModel.syncInjectedBrowserContext()
                },
            )
            loadUrl("https://app.hyperliquid.xyz/trade")
        }
        attachHyperliquidWebView(webView)
        contentLayout.addView(
            webView,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )

        bannerContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
        }
        rootLayout.addView(
            bannerContainer,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP),
        )

        bottomBannerContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
        }
        rootLayout.addView(
            bottomBannerContainer,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM),
        )

        qrOverlay = FrameLayout(this).apply {
            setBackgroundColor(0xB3000000.toInt())
            visibility = View.GONE
            isClickable = true
            isFocusable = true
        }
        val qrScroll = ScrollView(this).apply {
            isFillViewport = true
        }
        val qrScrollContent = FrameLayout(this)
        qrScroll.addView(
            qrScrollContent,
            ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )
        qrCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBackground(0xFFFFFFFF.toInt(), 24)
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }
        qrScrollContent.addView(
            qrCard,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER).apply {
                marginStart = dp(12)
                marginEnd = dp(12)
            },
        )
        qrTitleView = cardTitleView()
        qrSummaryView = bodyTextView(0xFF344054.toInt(), 12f)
        qrHintView = bodyTextView(0xFF667085.toInt(), 12f)
        qrPageView = bodyTextView(0xFF667085.toInt(), 12f).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        }
        qrImageView = ImageView(this).apply {
            adjustViewBounds = true
            scaleType = ImageView.ScaleType.FIT_CENTER
            background = roundedBackground(0xFFF8FAFC.toInt(), 20)
            setPadding(dp(12), dp(12), dp(12), dp(12))
        }
        qrPrevButton = primaryActionButton("上一张") { viewModel.prevSignQrPage() }
        qrNextButton = primaryActionButton("下一张") { viewModel.nextSignQrPage() }
        qrScanButton = primaryActionButton("扫码结果") { startResponseScan() }
        qrGalleryButton = primaryActionButton("相册二维码") { startResponseGalleryImport() }
        qrCloseButton = secondaryActionButton("关闭") { viewModel.clearPreparedRequest() }

        val pagerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(qrPrevButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(qrPageView, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(qrNextButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(qrScanButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(qrGalleryButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginStart = dp(10)
            })
        }
        qrCard.addView(qrTitleView)
        qrCard.addView(spacer(8))
        qrCard.addView(qrSummaryView)
        qrCard.addView(spacer(8))
        qrCard.addView(qrHintView)
        qrCard.addView(spacer(12))
        qrCard.addView(
            qrImageView,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT),
        )
        qrCard.addView(spacer(12))
        qrCard.addView(pagerRow)
        qrCard.addView(spacer(10))
        qrCard.addView(actionRow)
        qrCard.addView(spacer(10))
        qrCard.addView(qrCloseButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        qrOverlay.addView(
            qrScroll,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )
        rootLayout.addView(
            qrOverlay,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )

        ViewCompat.setOnApplyWindowInsetsListener(rootLayout) { _, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            toolbarLayout.setPadding(dp(12), systemBars.top + dp(10), dp(12), dp(10))
            contentLayout.setPadding(0, 0, 0, systemBars.bottom)
            (bannerContainer.layoutParams as? FrameLayout.LayoutParams)?.let { params ->
                params.topMargin = systemBars.top + dp(84)
                params.marginStart = dp(12)
                params.marginEnd = dp(12)
                bannerContainer.layoutParams = params
            }
            (bottomBannerContainer.layoutParams as? FrameLayout.LayoutParams)?.let { params ->
                params.bottomMargin = systemBars.bottom + dp(12)
                params.marginStart = dp(12)
                params.marginEnd = dp(12)
                bottomBannerContainer.layoutParams = params
            }
            qrOverlay.setPadding(dp(12), systemBars.top + dp(24), dp(12), systemBars.bottom + dp(12))
            insets
        }

        setContentView(rootLayout)
    }

    private fun startResponseScan() {
        val intent = Intent(this, QrScanActivity::class.java)
            .putExtra(QrScanActivity.EXTRA_STATUS_TEXT, "请扫描树莓派签名结果二维码")
        responseQrLauncher.launch(intent)
    }

    private fun startResponseGalleryImport() {
        galleryQrLauncher.launch("image/*")
    }

    private fun openExternalUrl(url: String) {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }

    private fun renderState(state: WalletUiState) {
        hyperliquidWebView?.let { syncInjectedProviderState(it, state) }
        renderTopBanners(state)
        renderQrOverlay(state)
        renderBottomBanners(state)
    }

    private fun renderTopBanners(state: WalletUiState) {
        val discoverError = state.error.takeUnless { it.startsWith("加载 ", ignoreCase = true) }
        bannerContainer.removeAllViews()
        if (!discoverError.isNullOrBlank()) {
            bannerContainer.addView(
                floatingBanner("错误", discoverError, 0xCC7F1D1D.toInt(), "关闭") { viewModel.clearError() },
            )
        }
        if (state.info.isNotBlank()) {
            if (bannerContainer.childCount > 0) {
                bannerContainer.addView(spacer(8))
            }
            bannerContainer.addView(
                floatingBanner("提示", state.info, 0xCC0C4A6E.toInt(), "关闭") { viewModel.clearInfo() },
            )
        }
        bannerContainer.visibility = if (bannerContainer.childCount > 0) View.VISIBLE else View.GONE
    }

    private fun renderQrOverlay(state: WalletUiState) {
        val bitmap = state.signQrBitmap
        syncQrAutoAdvance(state)
        if (bitmap == null) {
            qrOverlay.visibility = View.GONE
            return
        }
        qrOverlay.visibility = View.VISIBLE
        qrTitleView.text = state.requestTitle.ifBlank { "树莓派签名请求" }
        qrSummaryView.text = state.requestSummary.ifBlank { "请让树莓派扫描下方二维码。" }
        qrSummaryView.visibility = if (state.requestSummary.isBlank()) View.GONE else View.VISIBLE
        qrHintView.text = state.relayHint
        qrHintView.visibility = if (state.relayHint.isBlank()) View.GONE else View.VISIBLE
        qrImageView.setImageBitmap(bitmap)
        val multiplePages = state.signQrPages.size > 1
        qrPrevButton.visibility = if (multiplePages) View.VISIBLE else View.INVISIBLE
        qrNextButton.visibility = if (multiplePages) View.VISIBLE else View.INVISIBLE
        qrPageView.text = if (multiplePages) {
            "第 ${state.signQrPageIndex + 1} / ${state.signQrPages.size} 张"
        } else {
            "静态二维码"
        }
    }

    private fun syncQrAutoAdvance(state: WalletUiState) {
        val shouldAutoAdvance = state.signQrBitmap != null && state.signQrPages.size > 1
        if (!shouldAutoAdvance) {
            qrAutoAdvanceJob?.cancel()
            qrAutoAdvanceJob = null
            return
        }
        if (qrAutoAdvanceJob?.isActive == true) return
        qrAutoAdvanceJob = lifecycleScope.launch {
            while (isActive) {
                delay(1000)
                if (currentState.signQrBitmap == null || currentState.signQrPages.size <= 1) {
                    break
                }
                viewModel.nextSignQrPage()
            }
        }
    }

    private fun renderBottomBanners(state: WalletUiState) {
        bottomBannerContainer.removeAllViews()
        if (state.signQrBitmap != null) {
            bottomBannerContainer.visibility = View.GONE
            return
        }
        if (state.txHash.isNotBlank()) {
            val txChain = WalletChains.require(state.txHashChainId ?: state.selectedChainId)
            bottomBannerContainer.addView(
                actionBanner(
                    title = "交易已广播",
                    message = txChain.txUrl("0x${state.txHash}"),
                    backgroundColor = 0xCC111827.toInt(),
                    actionLabel = "查看详情",
                    onAction = { openExternalUrl(txChain.txUrl("0x${state.txHash}")) },
                    onDismiss = { viewModel.clearTxHash() },
                ),
            )
        }
        if (state.lastSignature.isNotBlank()) {
            if (bottomBannerContainer.childCount > 0) {
                bottomBannerContainer.addView(spacer(8))
            }
            bottomBannerContainer.addView(
                actionBanner(
                    title = "签名结果",
                    message = "签名已经生成，可以关闭这条提示继续操作。",
                    backgroundColor = 0xCC111827.toInt(),
                    actionLabel = null,
                    onAction = null,
                    onDismiss = { viewModel.clearSignature() },
                ),
            )
        }
        bottomBannerContainer.visibility = if (bottomBannerContainer.childCount > 0) View.VISIBLE else View.GONE
    }

    private fun toolbarActionText(label: String, gravity: Int, onClick: () -> Unit): TextView {
        return TextView(this).apply {
            text = label
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 14f
            this.gravity = gravity or Gravity.CENTER_VERTICAL
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
    }

    private fun cardTitleView(): TextView {
        return TextView(this).apply {
            setTextColor(0xFF101828.toInt())
            textSize = 18f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }
    }

    private fun bodyTextView(color: Int, sizeSp: Float): TextView {
        return TextView(this).apply {
            setTextColor(color)
            textSize = sizeSp
            setLineSpacing(0f, 1f)
        }
    }

    private fun primaryActionButton(label: String, onClick: () -> Unit): TextView {
        return TextView(this).apply {
            text = label
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 14f
            gravity = Gravity.CENTER
            background = roundedBackground(0xFF5B3FD1.toInt(), 16)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            setOnClickListener { onClick() }
        }
    }

    private fun secondaryActionButton(label: String, onClick: () -> Unit): TextView {
        return TextView(this).apply {
            text = label
            setTextColor(0xFF101828.toInt())
            textSize = 14f
            gravity = Gravity.CENTER
            background = strokeBackground(0xFFFFFFFF.toInt(), 0xFFD0D5DD.toInt(), 16)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            setOnClickListener { onClick() }
        }
    }

    private fun floatingBanner(
        title: String,
        message: String,
        backgroundColor: Int,
        dismissLabel: String,
        onDismiss: () -> Unit,
    ): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBackground(backgroundColor, 20)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            addView(TextView(context).apply {
                text = title
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 18f
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            })
            addView(spacer(8))
            addView(TextView(context).apply {
                text = message
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 15f
                setLineSpacing(0f, 1f)
            })
            addView(spacer(12))
            addView(TextView(context).apply {
                text = dismissLabel
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 16f
                gravity = Gravity.END
                setOnClickListener { onDismiss() }
            })
        }
    }

    private fun actionBanner(
        title: String,
        message: String,
        backgroundColor: Int,
        actionLabel: String?,
        onAction: (() -> Unit)?,
        onDismiss: () -> Unit,
    ): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBackground(backgroundColor, 18)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            addView(TextView(context).apply {
                text = title
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 16f
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            })
            addView(spacer(6))
            addView(TextView(context).apply {
                text = message
                setTextColor(0xFFE5E7EB.toInt())
                textSize = 13f
            })
            addView(spacer(10))
            val actions = LinearLayout(context).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            if (actionLabel != null && onAction != null) {
                actions.addView(TextView(context).apply {
                    text = actionLabel
                    setTextColor(0xFF67E8F9.toInt())
                    textSize = 14f
                    setOnClickListener { onAction() }
                })
            }
            actions.addView(View(context), LinearLayout.LayoutParams(0, 0, 1f))
            actions.addView(TextView(context).apply {
                text = "关闭"
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 14f
                setOnClickListener { onDismiss() }
            })
            addView(actions)
        }
    }

    private fun roundedBackground(color: Int, radiusDp: Int): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(radiusDp).toFloat()
            setColor(color)
        }
    }

    private fun strokeBackground(fillColor: Int, strokeColor: Int, radiusDp: Int): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(radiusDp).toFloat()
            setColor(fillColor)
            setStroke(dp(1), strokeColor)
        }
    }

    private fun spacer(heightDp: Int): View {
        return View(this).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(heightDp))
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density + 0.5f).toInt()

    override fun onDestroy() {
        qrAutoAdvanceJob?.cancel()
        qrAutoAdvanceJob = null
        hyperliquidWebView?.let { webView ->
            webView.stopLoading()
            webView.webChromeClient = WebChromeClient()
            webView.webViewClient = WebViewClient()
            webView.removeJavascriptInterface("SatochipAndroid")
            webView.destroy()
        }
        hyperliquidWebView = null
        super.onDestroy()
    }
}

@Composable
private fun WalletScreen(
    state: WalletUiState,
    onSelectTab: (WalletTab) -> Unit,
    onOpenHyperliquid: () -> Unit,
    onSelectChain: (Long) -> Unit,
    onNewAddressChange: (String) -> Unit,
    onEvmDerivationPathChange: (String) -> Unit,
    onAddAddress: () -> Unit,
    onPrepareDerivedAddressImport: () -> Unit,
    onSelectAddress: (String) -> Unit,
    onRemoveAddress: (String) -> Unit,
    onRefreshBalances: () -> Unit,
    onBitcoinImportInputChange: (String) -> Unit,
    onScanBitcoinWatchAccount: () -> Unit,
    onImportBitcoinWatchAccount: () -> Unit,
    onRemoveBitcoinWatchAccount: (String) -> Unit,
    onSyncBitcoinWatchAccount: (String) -> Unit,
    onPrepareBitcoinTransfer: (String, String, String, String?) -> Unit,
    onTransferToChange: (String) -> Unit,
    onTransferAmountChange: (String) -> Unit,
    onTransferTokenChange: (String) -> Unit,
    onTransferAmountAll: () -> Unit,
    onPrepareTransfer: () -> Unit,
    onRequestInputChange: (String) -> Unit,
    onImportRawRequest: () -> Unit,
    onImportRequestFromClipboard: () -> Unit,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
    onPrevRelayPage: () -> Unit,
    onNextRelayPage: () -> Unit,
    onAutoAdvanceRelayPage: () -> Unit,
    onScanRequest: () -> Unit,
    onPickRequestFromGallery: () -> Unit,
    onScanResponse: () -> Unit,
    onPickResponseFromGallery: () -> Unit,
    onOpenUrl: (String) -> Unit,
    onClearPreparedRequest: () -> Unit,
    onClearError: () -> Unit,
    onClearInfo: () -> Unit,
    onClearTxHash: () -> Unit,
    onClearSignature: () -> Unit,
) {
    if (state.signQrPages.size > 1 && state.signQrBitmap != null) {
        LaunchedEffect(state.signQrPages) {
            while (true) {
                delay(1000)
                onAutoAdvanceRelayPage()
            }
        }
    }

    val chain = WalletChains.require(state.selectedChainId)
    val portfolio = state.chainPortfolios[state.selectedChainId]
    val context = LocalContext.current

    if (state.activeTab == WalletTab.DISCOVER) {
        LaunchedEffect(Unit) {
            onSelectTab(WalletTab.HOME)
            onOpenHyperliquid()
        }
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFFF6F7FB)),
        )
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF6F7FB))
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        WalletTabs(state.activeTab, onSelectTab)

        if (state.error.isNotBlank()) {
            MessageCard(
                title = "错误",
                message = state.error,
                background = Color(0xFFFFE4E6),
                onDismiss = onClearError,
            )
        }
        if (state.info.isNotBlank()) {
            MessageCard(
                title = "提示",
                message = state.info,
                background = Color(0xFFE0F2FE),
                onDismiss = onClearInfo,
            )
        }

        if (state.signQrBitmap != null) {
            PreparedRequestSection(
                state = state,
                onPrevRelayPage = onPrevRelayPage,
                onNextRelayPage = onNextRelayPage,
                onScanResponse = onScanResponse,
                onPickResponseFromGallery = onPickResponseFromGallery,
                onClearPreparedRequest = onClearPreparedRequest,
            )
        }

        if (state.txHash.isNotBlank()) {
            val txChain = WalletChains.require(state.txHashChainId ?: state.selectedChainId)
            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("交易已广播", fontWeight = FontWeight.Bold, color = Color(0xFF166534))
                    Text("${txChain.shortName} 浏览器", fontSize = 12.sp, color = Color(0xFF475467))
                    SelectionContainer {
                        Text(txChain.txUrl("0x${state.txHash}"), fontSize = 12.sp)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { onOpenUrl(txChain.txUrl("0x${state.txHash}")) }) { Text("查看详情") }
                        TextButton(onClick = onClearTxHash) { Text("关闭") }
                    }
                }
            }
        }

        if (state.lastSignature.isNotBlank()) {
            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("签名结果", fontWeight = FontWeight.Bold)
                    if (state.lastSignatureAddress.isNotBlank()) {
                        Text("地址: ${state.lastSignatureAddress}", fontSize = 12.sp, color = Color(0xFF667085))
                    }
                    SelectionContainer {
                        Text(state.lastSignature, fontSize = 12.sp)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("signature", state.lastSignature))
                        }) {
                            Text("复制签名")
                        }
                        TextButton(onClick = onClearSignature) { Text("关闭") }
                    }
                }
            }
        }

        when (state.activeTab) {
            WalletTab.HOME -> {
                WalletOverviewSection(
                    state = state,
                    chain = chain,
                    onRefreshBalances = onRefreshBalances,
                    onNewAddressChange = onNewAddressChange,
                    onEvmDerivationPathChange = onEvmDerivationPathChange,
                    onAddAddress = onAddAddress,
                    onPrepareDerivedAddressImport = onPrepareDerivedAddressImport,
                    onSelectAddress = onSelectAddress,
                    onRemoveAddress = onRemoveAddress,
                )
                TransferSection(
                    state = state,
                    chain = chain,
                    onTransferToChange = onTransferToChange,
                    onTransferAmountChange = onTransferAmountChange,
                    onTransferTokenChange = onTransferTokenChange,
                    onTransferAmountAll = onTransferAmountAll,
                    onPrepareTransfer = onPrepareTransfer,
                )
                BitcoinPrototypeSection(
                    state = state,
                    onImportInputChange = onBitcoinImportInputChange,
                    onScanImport = onScanBitcoinWatchAccount,
                    onImportAccount = onImportBitcoinWatchAccount,
                    onRemoveAccount = onRemoveBitcoinWatchAccount,
                    onSyncAccount = onSyncBitcoinWatchAccount,
                    onPrepareTransfer = onPrepareBitcoinTransfer,
                )
                if (WalletChains.ALL.size > 1) {
                    ChainSelectorSection(
                        selectedChainId = state.selectedChainId,
                        onSelectChain = onSelectChain,
                    )
                }
                PortfolioSection(
                    chain = chain,
                    portfolio = portfolio,
                    isLoading = state.loadingBalances,
                )
                DappToolsSection(
                    state = state,
                    onRequestInputChange = onRequestInputChange,
                    onImportRawRequest = onImportRawRequest,
                    onImportRequestFromClipboard = onImportRequestFromClipboard,
                    onApproveWalletConnectProposal = onApproveWalletConnectProposal,
                    onRejectWalletConnectProposal = onRejectWalletConnectProposal,
                    onScanRequest = onScanRequest,
                    onPickRequestFromGallery = onPickRequestFromGallery,
                )
            }

            WalletTab.ACTIVITY -> {
                ActivitySection(
                    state = state,
                    chain = chain,
                    onRefresh = onRefreshBalances,
                    onOpenUrl = onOpenUrl,
                )
            }

            WalletTab.DISCOVER -> Unit
        }
    }
}

@Composable
private fun HyperliquidBrowserScreen(
    state: WalletUiState,
    onBackToWallet: () -> Unit,
    onPrevRelayPage: () -> Unit,
    onNextRelayPage: () -> Unit,
    onScanResponse: () -> Unit,
    onPickResponseFromGallery: () -> Unit,
    onOpenUrl: (String) -> Unit,
    onClearPreparedRequest: () -> Unit,
    onClearError: () -> Unit,
    onClearInfo: () -> Unit,
    onClearTxHash: () -> Unit,
    onClearSignature: () -> Unit,
    onAttachWebView: (WebView?) -> Unit,
    onInjectedBrowserReady: () -> Unit,
) {
    val activity = LocalContext.current as? ComponentActivity
    val latestBackToWallet = rememberUpdatedState(onBackToWallet)
    DisposableEffect(activity) {
        val window = activity?.window
        val previousStatusColor = window?.statusBarColor
        val previousNavColor = window?.navigationBarColor
        val controller = window?.let { WindowInsetsControllerCompat(it, it.decorView) }
        val previousLightStatus = controller?.isAppearanceLightStatusBars
        val previousLightNav = controller?.isAppearanceLightNavigationBars
        if (window != null) {
            window.statusBarColor = Color(0xFF07111C).toArgb()
            window.navigationBarColor = Color(0xFF07111C).toArgb()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.isNavigationBarContrastEnforced = false
            }
            controller?.isAppearanceLightStatusBars = false
            controller?.isAppearanceLightNavigationBars = false
        }
        onDispose {
            if (window != null) {
                previousStatusColor?.let { window.statusBarColor = it }
                previousNavColor?.let { window.navigationBarColor = it }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    window.isNavigationBarContrastEnforced = true
                }
                if (previousLightStatus != null) controller.isAppearanceLightStatusBars = previousLightStatus
                if (previousLightNav != null) controller.isAppearanceLightNavigationBars = previousLightNav
            }
        }
    }

    BackHandler {
        if (state.signQrBitmap != null) {
            onClearPreparedRequest()
        } else {
            latestBackToWallet.value()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF07111C)),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFF07111C)),
        ) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Color(0xFF07111C),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        TextButton(onClick = onBackToWallet) {
                            Text("关闭", color = Color.White)
                        }
                        Text(
                            "Hyperliquid",
                            modifier = Modifier.weight(1f),
                            color = Color.White,
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                            textAlign = TextAlign.Center,
                        )
                        TextButton(onClick = { onOpenUrl("https://app.hyperliquid.xyz/trade") }) {
                            Text("外部打开", color = Color(0xFF67E8F9), fontSize = 12.sp)
                        }
                    }
                }
            }

            HyperliquidBrowserSection(
                state = state,
                onAttachWebView = onAttachWebView,
                onInjectedBrowserReady = onInjectedBrowserReady,
                modifier = Modifier.weight(1f),
            )
        }

        val discoverError = state.error.takeUnless { it.startsWith("加载 ", ignoreCase = true) }
        if (!discoverError.isNullOrBlank() || state.info.isNotBlank()) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = 12.dp, vertical = 84.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (!discoverError.isNullOrBlank()) {
                    BrowserFloatingBanner(
                        title = "错误",
                        message = discoverError,
                        background = Color(0xCC7F1D1D),
                        onDismiss = onClearError,
                    )
                }
                if (state.info.isNotBlank()) {
                    BrowserFloatingBanner(
                        title = "提示",
                        message = state.info,
                        background = Color(0xCC0C4A6E),
                        onDismiss = onClearInfo,
                    )
                }
            }
        }

        if (state.signQrBitmap != null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color(0xB3000000))
                    .navigationBarsPadding()
                    .padding(12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState()),
                ) {
                    PreparedRequestSection(
                        state = state,
                        onPrevRelayPage = onPrevRelayPage,
                        onNextRelayPage = onNextRelayPage,
                        onScanResponse = onScanResponse,
                        onPickResponseFromGallery = onPickResponseFromGallery,
                        onClearPreparedRequest = onClearPreparedRequest,
                    )
                }
            }
        } else if (state.txHash.isNotBlank() || state.lastSignature.isNotBlank()) {
            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (state.txHash.isNotBlank()) {
                    val txChain = WalletChains.require(state.txHashChainId ?: state.selectedChainId)
                    BrowserActionBanner(
                        title = "交易已广播",
                        message = txChain.txUrl("0x${state.txHash}"),
                        actionLabel = "查看详情",
                        onAction = { onOpenUrl(txChain.txUrl("0x${state.txHash}")) },
                        onDismiss = onClearTxHash,
                    )
                }
                if (state.lastSignature.isNotBlank()) {
                    BrowserActionBanner(
                        title = "签名已返回网页",
                        message = "Hyperliquid 页面已经收到签名结果。",
                        actionLabel = null,
                        onAction = null,
                        onDismiss = onClearSignature,
                    )
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun HyperliquidBrowserSection(
    state: WalletUiState,
    onAttachWebView: (WebView?) -> Unit,
    onInjectedBrowserReady: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val browserHost = LocalContext.current as? InjectedBrowserHost
    val injectedBridge: InjectedWalletBridge? = remember(browserHost) { browserHost?.createInjectedWalletBridge() }
    val providerScript = remember { buildInjectedEthereumProviderScript() }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .background(Color(0xFF07111C)),
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                WebView(context).apply {
                    setBackgroundColor(0xFF07111C.toInt())
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.databaseEnabled = true
                    settings.cacheMode = WebSettings.LOAD_NO_CACHE
                    settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                    settings.useWideViewPort = false
                    settings.loadWithOverviewMode = false
                    settings.setSupportZoom(false)
                    settings.setSupportMultipleWindows(true)
                    settings.builtInZoomControls = false
                    settings.displayZoomControls = false
                    settings.javaScriptCanOpenWindowsAutomatically = true
                    settings.textZoom = 100
                    settings.userAgentString = buildBrowserLikeUserAgent(settings.userAgentString)
                    isVerticalScrollBarEnabled = false
                    isHorizontalScrollBarEnabled = false
                    overScrollMode = WebView.OVER_SCROLL_NEVER
                    clearCache(true)
                    webChromeClient = HyperliquidWebChromeClient(
                        onOpenExternal = { url ->
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        },
                        onBrowserIssue = browserHost?.let { { message -> it.reportBrowserRuntimeIssue(message) } },
                    )
                    injectedBridge?.let { addWalletJavascriptInterface(this, it) }
                    val supportsDocumentStart = registerDocumentStartScriptIfAvailable(this, providerScript)
                    webViewClient = HyperliquidInjectedWebViewClient(
                        injectOnPageFinished = !supportsDocumentStart,
                        onInjectProvider = { view -> browserHost?.injectWalletProviderInto(view) },
                        onOpenExternal = { url ->
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        },
                        onBrowserIssue = browserHost?.let { { message -> it.reportBrowserRuntimeIssue(message) } },
                        onPageReady = { view ->
                            view?.let(::refreshInjectedBrowserViewport)
                            onInjectedBrowserReady()
                        },
                    )
                    loadUrl("https://app.hyperliquid.xyz/trade")
                    onAttachWebView(this)
                }
            },
            update = { view ->
                syncInjectedProviderState(view, state)
            },
        )

    }

    DisposableEffect(Unit) {
        onDispose { onAttachWebView(null) }
    }
}

private class HyperliquidWebChromeClient(
    private val onOpenExternal: (String) -> Unit,
    private val onBrowserIssue: ((String) -> Unit)?,
) : WebChromeClient() {
    override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
        val message = consoleMessage ?: return super.onConsoleMessage(null)
        val rawMessage = message.message().orEmpty()
        if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR && shouldReportHyperliquidConsoleError(rawMessage)) {
            onBrowserIssue?.invoke(
                buildString {
                    append("console error")
                    message.sourceId()?.takeIf { it.isNotBlank() }?.let { append(" · ").append(it) }
                    if (message.lineNumber() > 0) append(" · line ").append(message.lineNumber())
                    rawMessage.takeIf { it.isNotBlank() }?.let { append(" · ").append(it) }
                },
            )
        }
        return super.onConsoleMessage(message)
    }

    override fun onCreateWindow(
        view: WebView?,
        isDialog: Boolean,
        isUserGesture: Boolean,
        resultMsg: Message?,
    ): Boolean {
        val parent = view ?: return false
        val transport = resultMsg?.obj as? WebView.WebViewTransport ?: return false
        val passthroughWebView = WebView(parent.context).apply {
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val url = request?.url?.toString() ?: return false
                    return when (request.url.scheme?.lowercase()) {
                        "http", "https", "about", "javascript", "data", "blob" -> {
                            parent.post { parent.loadUrl(url) }
                            true
                        }
                        else -> {
                            onOpenExternal(url)
                            true
                        }
                    }
                }
            }
        }
        transport.webView = passthroughWebView
        resultMsg.sendToTarget()
        return true
    }
}

private fun shouldReportHyperliquidConsoleError(message: String): Boolean {
    val normalized = message.trim()
    if (normalized.isBlank()) return false
    if (normalized.contains("Uncaught (in promise) #<Object>", ignoreCase = true)) return false
    if (normalized.contains("ResizeObserver loop completed with undelivered notifications", ignoreCase = true)) return false
    return true
}

private class HyperliquidInjectedWebViewClient(
    private val injectOnPageFinished: Boolean,
    private val onInjectProvider: (WebView) -> Unit,
    private val onOpenExternal: (String) -> Unit,
    private val onBrowserIssue: ((String) -> Unit)?,
    private val onPageReady: (WebView?) -> Unit,
) : WebViewClient() {
    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
        super.onPageStarted(view, url, favicon)
        view?.let { ensureProviderStubs(it) }
    }

    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
        val url = request?.url ?: return false
        if (!request.isForMainFrame) return false

        return when (url.scheme?.lowercase()) {
            "http", "https", "about", "javascript", "data", "blob" -> false
            else -> {
                onOpenExternal(url.toString())
                true
            }
        }
    }

    override fun onReceivedError(
        view: WebView?,
        request: WebResourceRequest?,
        error: WebResourceError?,
    ) {
        super.onReceivedError(view, request, error)
        if (request?.isForMainFrame == true) {
            onBrowserIssue?.invoke(
                "load error · ${request.url} · ${error?.description ?: "unknown"}"
            )
        }
    }

    override fun onReceivedHttpError(
        view: WebView?,
        request: WebResourceRequest?,
        errorResponse: WebResourceResponse?,
    ) {
        super.onReceivedHttpError(view, request, errorResponse)
        if (request?.isForMainFrame == true) {
            onBrowserIssue?.invoke(
                "http error · ${request.url} · status ${errorResponse?.statusCode ?: -1}"
            )
        }
    }

    override fun onPageFinished(view: WebView?, url: String?) {
        super.onPageFinished(view, url)
        if (injectOnPageFinished) {
            view?.let { onInjectProvider(it) }
        }
        onPageReady(view)
    }
}

@SuppressLint("RequiresFeature")
private fun registerDocumentStartScriptIfAvailable(webView: WebView, script: String): Boolean {
    if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) return false
    WebViewCompat.addDocumentStartJavaScript(webView, script, setOf("https://app.hyperliquid.xyz"))
    return true
}

private fun addWalletJavascriptInterface(webView: WebView, bridge: InjectedWalletBridge) {
    webView.addJavascriptInterface(bridge, "SatochipAndroid")
}

private fun ensureProviderStubs(webView: WebView) {
    val stubScript = """
        (function() {
          if (!window.__SATOCHIP_PROVIDER_STUB__) {
            window.__SATOCHIP_PROVIDER_STUB__ = true;
            window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
            if (typeof window.__satochipWalletSetAccounts !== 'function') {
              window.__satochipWalletSetAccounts = function(accounts) {
                window.__SATOCHIP_BOOTSTRAP__.accounts = accounts;
              };
            }
            if (typeof window.__satochipWalletSetChain !== 'function') {
              window.__satochipWalletSetChain = function(chainId) {
                if (!chainId) return;
                window.__SATOCHIP_BOOTSTRAP__.chainId = chainId;
              };
            }
          }
        })();
    """.trimIndent()
    webView.post { webView.evaluateJavascript(stubScript, null) }
}

private fun refreshInjectedBrowserViewport(webView: WebView) {
    val refreshScript = """
        (function() {
          if (typeof window.__satochipRefreshViewport === 'function') {
            window.__satochipRefreshViewport();
          } else {
            window.dispatchEvent(new Event('resize'));
          }
        })();
    """.trimIndent()
    webView.post {
        webView.evaluateJavascript(refreshScript, null)
        webView.postDelayed({ webView.evaluateJavascript(refreshScript, null) }, 60)
        webView.postDelayed({ webView.evaluateJavascript(refreshScript, null) }, 240)
        webView.postDelayed({ webView.evaluateJavascript(refreshScript, null) }, 900)
    }
}

private fun syncInjectedProviderState(
    webView: WebView,
    state: WalletUiState,
) {
    val accounts = if (!state.browserAuthorized || state.selectedAddress.isBlank()) {
        "[]"
    } else {
        org.json.JSONArray(listOf(state.selectedAddress)).toString()
    }
    val chainIdHex = WalletChains.require(state.selectedChainId).chainIdHex
    webView.post {
        webView.evaluateJavascript(
            """
                (function() {
                  window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                  window.__SATOCHIP_BOOTSTRAP__.accounts = $accounts;
                  if (typeof window.__satochipWalletSetAccounts === 'function') {
                    window.__satochipWalletSetAccounts($accounts);
                  }
                })();
            """.trimIndent(),
            null,
        )
        webView.evaluateJavascript(
            """
                (function() {
                  var chainId = ${jsString(chainIdHex)};
                  window.__SATOCHIP_BOOTSTRAP__ = window.__SATOCHIP_BOOTSTRAP__ || {};
                  window.__SATOCHIP_BOOTSTRAP__.chainId = chainId;
                  if (typeof window.__satochipWalletSetChain === 'function') {
                    window.__satochipWalletSetChain(chainId);
                  }
                })();
            """.trimIndent(),
            null,
        )
    }
}

private fun buildInjectedEthereumProviderScript(): String {
    val icon = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='18' fill='%23111827'/%3E%3Cpath d='M18 46h28V18H18z' fill='%235B3FD1'/%3E%3Cpath d='M24 24h16v16H24z' fill='%23fff' fill-opacity='.16'/%3E%3C/svg%3E"
    return """
        (function() {
          if (window.__SATOCHIP_PROVIDER__) return;
          const listeners = {};
          const pending = {};
          const provider = {
            isSatochipWallet: true,
            isMetaMask: false,
            providers: null,
            selectedAddress: null,
            chainId: "0xa4b1",
            networkVersion: "42161",
            request: function(args) {
              const payload = args || {};
              const method = String(payload.method || "");
              const params = payload.params == null ? [] : payload.params;
              if (method === "eth_accounts") {
                return Promise.resolve(provider.selectedAddress ? [provider.selectedAddress] : []);
              }
              if (method === "eth_coinbase") {
                return Promise.resolve(provider.selectedAddress || null);
              }
              if (method === "eth_chainId") {
                return Promise.resolve(provider.chainId);
              }
              if (method === "net_version") {
                return Promise.resolve(String(parseInt(provider.chainId, 16)));
              }
              return new Promise(function(resolve, reject) {
                const id = "satochip_" + Date.now() + "_" + Math.random().toString(16).slice(2);
                pending[id] = { resolve: resolve, reject: reject, method: method };
                if (!window.SatochipAndroid || !window.SatochipAndroid.request) {
                  delete pending[id];
                  reject({ code: 4900, message: "Wallet bridge unavailable" });
                  return;
                }
                window.SatochipAndroid.request(id, method, JSON.stringify(params), window.location.origin || window.location.href || "");
              });
            },
            on: function(event, listener) {
              listeners[event] = listeners[event] || [];
              listeners[event].push(listener);
              return provider;
            },
            removeListener: function(event, listener) {
              const items = listeners[event] || [];
              listeners[event] = items.filter(function(item) { return item !== listener; });
              return provider;
            },
            removeAllListeners: function(event) {
              if (event) delete listeners[event];
              return provider;
            },
            emit: function(event, payload) {
              (listeners[event] || []).slice().forEach(function(listener) {
                try { listener(payload); } catch (error) {}
              });
              return true;
            },
            enable: function() {
              return provider.request({ method: "eth_requestAccounts" });
            },
            isConnected: function() {
              return !!provider.selectedAddress;
            }
          };
          provider.providers = [provider];

          function announceProvider() {
            window.dispatchEvent(new CustomEvent("eip6963:announceProvider", {
              detail: {
                info: {
                  uuid: "${UUID.randomUUID()}",
                  name: "Satochip Wallet",
                  icon: "${icon}",
                  rdns: "io.arbitrum.wallet"
                },
                provider: provider
              }
            }));
          }

          function reportIssue(level, message, source, line) {
            try {
              if (window.SatochipAndroid && window.SatochipAndroid.reportIssue) {
                window.SatochipAndroid.reportIssue(
                  String(level || "js"),
                  String(message || ""),
                  source ? String(source) : "",
                  Number(line || 0)
                );
              }
            } catch (error) {}
          }

          function applyViewportFix() {
            try {
              var viewport = window.visualViewport || null;
              var width = Math.round((viewport && viewport.width) || window.innerWidth || document.documentElement.clientWidth || 0);
              var height = Math.round((viewport && viewport.height) || window.innerHeight || document.documentElement.clientHeight || 0);
              if (!height) return;
              var style = document.getElementById("__satochipViewportStyle");
              if (!style) {
                style = document.createElement("style");
                style.id = "__satochipViewportStyle";
                (document.head || document.documentElement).appendChild(style);
              }
              style.textContent =
                "html,body{width:100% !important;height:" + height + "px !important;min-height:" + height + "px !important;overflow-x:hidden !important;}" +
                "body>#root,#root,[data-reactroot]{width:100% !important;height:" + height + "px !important;min-height:" + height + "px !important;overflow:visible !important;}" +
                "#root>div:first-child{min-height:" + height + "px !important;}";
              document.documentElement.style.setProperty("--satochip-vw", width + "px");
              document.documentElement.style.setProperty("--satochip-vh", height + "px");
              document.documentElement.style.height = height + "px";
              document.documentElement.style.minHeight = height + "px";
              document.documentElement.style.overflowX = "hidden";
              document.documentElement.style.removeProperty("overflowY");
              if (document.body) {
                document.body.style.height = height + "px";
                document.body.style.minHeight = height + "px";
                document.body.style.overflowX = "hidden";
                document.body.style.removeProperty("overflowY");
              }
              var root = document.getElementById("root") || document.querySelector("[data-reactroot]");
              if (root) {
                root.style.height = height + "px";
                root.style.minHeight = height + "px";
                root.style.overflow = "visible";
              }
            } catch (error) {}
          }

          function scheduleViewportFix() {
            applyViewportFix();
            requestAnimationFrame(function() {
              applyViewportFix();
              setTimeout(applyViewportFix, 80);
              setTimeout(applyViewportFix, 320);
            });
          }

          window.__satochipRefreshViewport = function() {
            scheduleViewportFix();
            try {
              window.dispatchEvent(new Event("resize"));
            } catch (error) {}
          };

          if (!window.__SATOCHIP_VIEWPORT_FIX__) {
            window.__SATOCHIP_VIEWPORT_FIX__ = true;
            var observer = null;
            var pendingViewportFix = null;
            function requestViewportFix() {
              if (pendingViewportFix != null) {
                cancelAnimationFrame(pendingViewportFix);
              }
              pendingViewportFix = requestAnimationFrame(function() {
                pendingViewportFix = null;
                scheduleViewportFix();
              });
            }
            if (document.readyState === "loading") {
              document.addEventListener("DOMContentLoaded", scheduleViewportFix, { once: true });
            } else {
              scheduleViewportFix();
            }
            window.addEventListener("load", scheduleViewportFix);
            window.addEventListener("resize", applyViewportFix);
            window.addEventListener("orientationchange", scheduleViewportFix);
            document.addEventListener("click", requestViewportFix, true);
            document.addEventListener("transitionend", requestViewportFix, true);
            document.addEventListener("animationend", requestViewportFix, true);
            if (window.visualViewport) {
              window.visualViewport.addEventListener("resize", applyViewportFix);
              window.visualViewport.addEventListener("scroll", applyViewportFix);
            }
            var rootNode = document.getElementById("root") || document.body;
            if (rootNode && typeof MutationObserver !== "undefined") {
              observer = new MutationObserver(function() {
                requestViewportFix();
              });
              observer.observe(rootNode, { childList: true, subtree: true, attributes: true });
            }
          }

          window.__satochipWalletResolve = function(id, result) {
            const entry = pending[id];
            if (!entry) return;
            delete pending[id];
            try {
              if (entry.method === "eth_requestAccounts" && Array.isArray(result)) {
                window.__satochipWalletSetAccounts(result);
              }
              if (
                (entry.method === "wallet_requestPermissions" || entry.method === "wallet_grantPermissions") &&
                Array.isArray(result)
              ) {
                var permission = result[0] || null;
                var caveats = permission && Array.isArray(permission.caveats) ? permission.caveats : [];
                var accountCaveat = caveats.find(function(item) {
                  return item && item.type === "restrictReturnedAccounts" && Array.isArray(item.value);
                });
                if (accountCaveat && Array.isArray(accountCaveat.value)) {
                  window.__satochipWalletSetAccounts(accountCaveat.value);
                }
              }
            } catch (error) {}
            entry.resolve(result);
          };

          window.__satochipWalletReject = function(id, code, message) {
            const entry = pending[id];
            if (!entry) return;
            delete pending[id];
            entry.reject({ code: code, message: message });
          };

          window.__satochipWalletSetAccounts = function(accounts) {
            const normalized = Array.isArray(accounts) ? accounts : [];
            const previous = provider.selectedAddress;
            provider.selectedAddress = normalized[0] || null;
            if (provider.selectedAddress !== previous) {
              provider.emit("accountsChanged", normalized);
              if (provider.selectedAddress) {
                provider.emit("connect", { chainId: provider.chainId });
              }
            }
          };

          window.__satochipWalletSetChain = function(chainId) {
            if (!chainId) return;
            if (provider.chainId !== chainId) {
              provider.chainId = chainId;
              provider.networkVersion = String(parseInt(chainId, 16));
              provider.emit("chainChanged", chainId);
            }
          };

          var bootstrap = window.__SATOCHIP_BOOTSTRAP__ || {};
          if (Object.prototype.hasOwnProperty.call(bootstrap, "accounts")) {
            window.__satochipWalletSetAccounts(bootstrap.accounts);
          }
          if (bootstrap.chainId) {
            window.__satochipWalletSetChain(bootstrap.chainId);
          }

          if (!window.__SATOCHIP_ERROR_HOOK__) {
            window.__SATOCHIP_ERROR_HOOK__ = true;
            window.addEventListener("error", function(event) {
              reportIssue("window.error", event && event.message, event && event.filename, event && event.lineno);
            });
            window.addEventListener("unhandledrejection", function(event) {
              const reason = event && event.reason;
              const text = reason && reason.message ? reason.message : String(reason);
              reportIssue("unhandledrejection", text, "", 0);
            });
            const originalConsoleError = console.error;
            console.error = function() {
              try {
                const text = Array.prototype.slice.call(arguments).map(function(item) {
                  if (item && item.stack) return String(item.stack);
                  if (typeof item === "object") return JSON.stringify(item);
                  return String(item);
                }).join(" ");
                reportIssue("console.error", text, "", 0);
              } catch (error) {}
              return originalConsoleError.apply(console, arguments);
            };
          }

          window.__SATOCHIP_PROVIDER__ = provider;
          Object.defineProperty(window, "ethereum", {
            configurable: true,
            enumerable: true,
            get: function() { return provider; }
          });
          window.addEventListener("eip6963:requestProvider", announceProvider);
          announceProvider();
          window.dispatchEvent(new Event("ethereum#initialized"));
        })();
    """.trimIndent()
}

private fun jsString(value: String): String = org.json.JSONObject.quote(value)

private fun buildBrowserLikeUserAgent(defaultUserAgent: String): String {
    val withoutWv = defaultUserAgent
        .replace("; wv", "")
        .replace(" wv)", ")")
        .replace(" Version/4.0", "")

    return if (Regex(" Chrome/\\d").containsMatchIn(withoutWv)) {
        withoutWv
    } else {
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36"
    }
}

@Composable
private fun BrowserFloatingBanner(
    title: String,
    message: String,
    background: Color,
    onDismiss: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = background,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(title, color = Color.White, fontWeight = FontWeight.Bold)
            Text(message, color = Color.White, fontSize = 12.sp)
            TextButton(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) {
                Text("关闭", color = Color.White)
            }
        }
    }
}

@Composable
private fun BrowserActionBanner(
    title: String,
    message: String,
    actionLabel: String?,
    onAction: (() -> Unit)?,
    onDismiss: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xE6111827),
        shape = RoundedCornerShape(22.dp),
        border = BorderStroke(1.dp, Color(0xFF1F2937)),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(title, color = Color.White, fontWeight = FontWeight.Bold)
            Text(message, color = Color(0xFFE2E8F0), fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (actionLabel != null && onAction != null) {
                    Button(onClick = onAction) { Text(actionLabel) }
                }
                TextButton(onClick = onDismiss) { Text("关闭") }
            }
        }
    }
}

@Composable
private fun WalletTabs(activeTab: WalletTab, onSelectTab: (WalletTab) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.White, RoundedCornerShape(18.dp))
            .border(1.dp, Color(0xFFE5E7EB), RoundedCornerShape(18.dp))
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        WalletTabItem("首页", activeTab == WalletTab.HOME, Modifier.weight(1f)) { onSelectTab(WalletTab.HOME) }
        WalletTabItem("活动", activeTab == WalletTab.ACTIVITY, Modifier.weight(1f)) { onSelectTab(WalletTab.ACTIVITY) }
        WalletTabItem("Hyperliquid", activeTab == WalletTab.DISCOVER, Modifier.weight(1f)) { onSelectTab(WalletTab.DISCOVER) }
    }
}

@Composable
private fun WalletTabItem(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val background = if (selected) Color(0xFF0F172A) else Color.Transparent
    val contentColor = if (selected) Color.White else Color(0xFF475467)
    Box(
        modifier = modifier,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(background, RoundedCornerShape(14.dp))
                .clickable(onClick = onClick)
                .padding(vertical = 11.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                label,
                color = contentColor,
                textAlign = TextAlign.Center,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun WalletSectionCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(22.dp),
        border = BorderStroke(1.dp, Color(0xFFE5E7EB)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            content = content,
        )
    }
}

@Composable
private fun SectionHeader(
    title: String,
    subtitle: String,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(title, fontWeight = FontWeight.Bold, color = Color(0xFF101828))
            Text(subtitle, fontSize = 12.sp, color = Color(0xFF667085))
        }
        if (trailing != null) {
            Box(contentAlignment = Alignment.CenterEnd) { trailing() }
        }
    }
}

@Composable
private fun StatusChip(
    label: String,
    background: Color = Color(0xFFF8FAFC),
    contentColor: Color = Color(0xFF344054),
) {
    Surface(
        color = background,
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
    ) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            fontSize = 11.sp,
            color = contentColor,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun WalletOverviewSection(
    state: WalletUiState,
    chain: WalletChain,
    onRefreshBalances: () -> Unit,
    onNewAddressChange: (String) -> Unit,
    onEvmDerivationPathChange: (String) -> Unit,
    onAddAddress: () -> Unit,
    onPrepareDerivedAddressImport: () -> Unit,
    onSelectAddress: (String) -> Unit,
    onRemoveAddress: (String) -> Unit,
) {
    var showManualImport by rememberSaveable { mutableStateOf(false) }
    var showAddressManager by rememberSaveable { mutableStateOf(false) }

    WalletSectionCard {
        SectionHeader(
            title = chain.displayName,
            subtitle = if (state.addresses.isEmpty()) "先从树莓派导入观察地址，再查看资产与签名" else "已接入 ${state.addresses.size} 个观察地址",
            trailing = {
                TextButton(onClick = onRefreshBalances) {
                    Text(if (state.loadingBalances) "同步中" else "刷新", fontSize = 12.sp)
                }
            },
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            StatusChip(if (state.selectedAddress.isBlank()) "未选地址" else "当前地址已选")
            StatusChip("${state.addresses.size} 个地址")
            StatusChip(chain.shortName)
            StatusChip("路径已固定")
        }

        Surface(
            color = Color(0xFFF8FAFC),
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
        ) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text("当前派生路径", fontSize = 12.sp, color = Color(0xFF667085))
                OutlinedTextField(
                    value = state.evmDerivationPath,
                    onValueChange = onEvmDerivationPathChange,
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    placeholder = { Text(DEFAULT_EVM_DERIVATION_PATH, fontSize = 12.sp) },
                )
                Text(
                    if (state.selectedAddress.isBlank()) {
                        "当前还没有 EVM 观察地址，建议直接用树莓派按这个路径导入。"
                    } else {
                        "当前地址: ${shortAddressLabel(state.selectedAddress, head = 10, tail = 8)}"
                    },
                    fontSize = 12.sp,
                    color = Color(0xFF475467),
                )
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = onPrepareDerivedAddressImport,
                modifier = Modifier.weight(1f),
            ) {
                Text("从树莓派导入", fontSize = 12.sp)
            }
            OutlinedButton(
                onClick = { showAddressManager = !showAddressManager },
                modifier = Modifier.weight(1f),
            ) {
                Text(if (showAddressManager) "收起地址" else "管理地址", fontSize = 12.sp)
            }
        }

        TextButton(onClick = { showManualImport = !showManualImport }) {
            Text(if (showManualImport) "收起手动添加" else "手动添加地址", fontSize = 12.sp)
        }

        if (showManualImport) {
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = state.newAddressInput,
                    onValueChange = onNewAddressChange,
                    placeholder = { Text("添加地址 (0x...)", fontSize = 12.sp) },
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 56.dp),
                    singleLine = true,
                )
                Button(onClick = onAddAddress, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("添加", fontSize = 12.sp)
                }
            }
        }

        if (showAddressManager && state.addresses.isNotEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                state.addresses.forEach { address ->
                    AddressListItem(
                        address = address,
                        isSelected = address.equals(state.selectedAddress, ignoreCase = true),
                        onSelect = { onSelectAddress(address) },
                        onRemove = { onRemoveAddress(address) },
                    )
                }
            }
        } else if (state.addresses.isEmpty()) {
            Surface(
                color = Color(0xFFF8FAFC),
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
            ) {
                Text(
                    "推荐流程：设置派生路径 -> 点“从树莓派导入” -> 树莓派扫码 -> 手机扫回结果。导入后资产、转账和 WalletConnect 都会围着这个地址展开。",
                    modifier = Modifier.padding(12.dp),
                    fontSize = 12.sp,
                    color = Color(0xFF667085),
                )
            }
        }
    }
}

@Composable
private fun BitcoinPrototypeSection(
    state: WalletUiState,
    onImportInputChange: (String) -> Unit,
    onScanImport: () -> Unit,
    onImportAccount: () -> Unit,
    onRemoveAccount: (String) -> Unit,
    onSyncAccount: (String) -> Unit,
    onPrepareTransfer: (String, String, String, String?) -> Unit,
) {
    var showImportPanel by rememberSaveable { mutableStateOf(state.bitcoinWatchAccounts.isEmpty()) }
    var showAccounts by rememberSaveable { mutableStateOf(false) }
    var expandedAccountId by rememberSaveable { mutableStateOf<String?>(null) }

    WalletSectionCard {
        SectionHeader(
            title = "Bitcoin 观察账户",
            subtitle = "首页只保留账户摘要，地址预览放到二级展开",
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            StatusChip("${state.bitcoinWatchAccounts.size} 个账户")
            StatusChip("只读")
            StatusChip("树莓派导入")
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = { showImportPanel = !showImportPanel },
                modifier = Modifier.weight(1f),
            ) {
                Text(if (showImportPanel) "收起导入" else "导入账户", fontSize = 12.sp)
            }
            OutlinedButton(
                onClick = { showAccounts = !showAccounts },
                modifier = Modifier.weight(1f),
            ) {
                Text(if (showAccounts) "收起账户" else "查看账户", fontSize = 12.sp)
            }
        }

        Surface(
            color = Color(0xFFF8FAFC),
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
        ) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    state.bitcoinPrototypeStatus,
                    fontSize = 12.sp,
                    color = Color(0xFF475467),
                )
                Text(
                    "树莓派导出：pi-signer get-xpub --pin <PIN> --xtype zpub",
                    fontSize = 11.sp,
                    color = Color(0xFF667085),
                )
            }
        }

        if (showImportPanel || state.bitcoinWatchAccounts.isEmpty()) {
            OutlinedTextField(
                value = state.bitcoinImportInput,
                onValueChange = onImportInputChange,
                placeholder = {
                    Text("粘贴 zpub / xpub，或直接扫码导入", fontSize = 12.sp)
                },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
                maxLines = 4,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(onClick = onScanImport, modifier = Modifier.weight(1f)) { Text("扫码导入", fontSize = 12.sp) }
                Button(onClick = onImportAccount, modifier = Modifier.weight(1f)) { Text("导入 BTC 账户", fontSize = 12.sp) }
            }
        }

        if (state.bitcoinWatchAccounts.isEmpty()) {
            Surface(
                color = Color(0xFFFEF3F2),
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, Color(0xFFFECACA)),
            ) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text("还没有 BTC 观察账户", fontWeight = FontWeight.Medium, color = Color(0xFF101828))
                    Text(
                        "先从树莓派导出 zpub，再扫码或粘贴进来。当前这版已经能做地址派生预览。",
                        fontSize = 12.sp,
                        color = Color(0xFF667085),
                    )
                }
            }
        } else if (showAccounts) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                state.bitcoinWatchAccounts.forEach { account ->
                    BitcoinWatchAccountCard(
                        account = account,
                        expanded = expandedAccountId == account.id,
                        onToggleExpanded = {
                            expandedAccountId = if (expandedAccountId == account.id) null else account.id
                        },
                        onRemoveAccount = onRemoveAccount,
                        onSyncAccount = onSyncAccount,
                        onPrepareTransfer = onPrepareTransfer,
                    )
                }
            }
        } else {
            Surface(
                color = Color(0xFFF8FAFC),
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
            ) {
                Text(
                    "账户和地址预览已隐藏到二级列表，点“查看账户”再展开具体地址。",
                    modifier = Modifier.padding(12.dp),
                    fontSize = 12.sp,
                    color = Color(0xFF667085),
                )
            }
        }
    }
}

@Composable
private fun BitcoinWatchAccountCard(
    account: BitcoinWatchAccount,
    expanded: Boolean,
    onToggleExpanded: () -> Unit,
    onRemoveAccount: (String) -> Unit,
    onSyncAccount: (String) -> Unit,
    onPrepareTransfer: (String, String, String, String?) -> Unit,
) {
    val context = LocalContext.current
    var showTransferComposer by rememberSaveable(account.id) { mutableStateOf(false) }
    var transferTo by rememberSaveable(account.id) { mutableStateOf("") }
    var transferAmount by rememberSaveable(account.id) { mutableStateOf("") }
    var feeRate by rememberSaveable(account.id) { mutableStateOf("") }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(account.label, fontWeight = FontWeight.SemiBold, color = Color(0xFF101828))
                    Text("${account.networkLabel} · ${account.scriptTypeLabel}", fontSize = 11.sp, color = Color(0xFF667085))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    StatusChip(label = account.prefix.uppercase())
                    StatusChip(label = "只读")
                    TextButton(onClick = onToggleExpanded) {
                        Text(if (expanded) "收起" else "查看", fontSize = 11.sp)
                    }
                }
            }

            Text(account.accountPathHint, fontSize = 12.sp, color = Color(0xFF344054))
            if (account.accountFingerprintHex.isNotBlank()) {
                Text("账户指纹: ${account.accountFingerprintHex}", fontSize = 11.sp, color = Color(0xFF667085))
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = { onSyncAccount(account.id) },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (account.syncing) "同步中..." else "同步余额", fontSize = 12.sp)
                }
                Button(
                    onClick = { showTransferComposer = !showTransferComposer },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (showTransferComposer) "收起转账" else "发送 BTC", fontSize = 12.sp)
                }
            }

            Surface(
                color = Color.White,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
            ) {
                Column(
                    modifier = Modifier.padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        if (account.balanceSats > 0) "可用余额: ${formatBitcoinSats(account.balanceSats)}" else "可用余额: 未同步",
                        fontSize = 12.sp,
                        color = Color(0xFF101828),
                    )
                    Text(
                        if (account.lastSyncStatus.isNotBlank()) account.lastSyncStatus else "点“同步余额”后会拉取链上 UTXO 和下一收款地址。",
                        fontSize = 11.sp,
                        color = Color(0xFF667085),
                    )
                    if (account.nextReceiveAddress.isNotBlank()) {
                        Text(
                            "下一收款地址: ${shortAddressLabel(account.nextReceiveAddress, head = 12, tail = 8)}",
                            fontSize = 11.sp,
                            color = Color(0xFF344054),
                        )
                    }
                }
            }

            if (showTransferComposer) {
                OutlinedTextField(
                    value = transferTo,
                    onValueChange = { transferTo = it },
                    placeholder = { Text("收款 BTC 地址", fontSize = 12.sp) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedTextField(
                        value = transferAmount,
                        onValueChange = { transferAmount = it },
                        placeholder = { Text("数量 (BTC)", fontSize = 12.sp) },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                    )
                    OutlinedTextField(
                        value = feeRate,
                        onValueChange = { feeRate = it },
                        placeholder = { Text("手续费 sat/vB", fontSize = 12.sp) },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                    )
                }
                Text(
                    "手续费留空就用当前链上推荐值。准备后会生成树莓派扫描用的 BTC PSBT 二维码。",
                    fontSize = 11.sp,
                    color = Color(0xFF667085),
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = { showTransferComposer = false },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("取消", fontSize = 12.sp)
                    }
                    Button(
                        onClick = {
                            onPrepareTransfer(account.id, transferTo, transferAmount, feeRate.takeIf { it.isNotBlank() })
                        },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("准备签名", fontSize = 12.sp)
                    }
                }
            }

            if (expanded) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        shortAddressLabel(account.xpub, head = 18, tail = 14),
                        modifier = Modifier.weight(1f),
                        fontSize = 11.sp,
                        lineHeight = 15.sp,
                        color = Color(0xFF0F172A),
                    )
                    TextButton(
                        onClick = {
                            copyPlainText(
                                context = context,
                                label = "btc-xpub",
                                value = account.xpub,
                                successMessage = "扩展公钥已复制",
                            )
                        }
                    ) {
                        Text("复制 xpub", fontSize = 11.sp)
                    }
                }
                if (account.derivationError.isNotBlank()) {
                    Text(account.derivationError, fontSize = 11.sp, color = Color(0xFFB42318))
                } else {
                    BitcoinAddressPreviewGroup(
                        title = "收款地址预览",
                        addresses = account.receivePreview,
                    )
                    BitcoinAddressPreviewGroup(
                        title = "找零地址预览",
                        addresses = account.changePreview,
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = { onRemoveAccount(account.id) }) {
                    Text("删除", fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun BitcoinAddressPreviewGroup(
    title: String,
    addresses: List<BitcoinDerivedAddressPreview>,
) {
    if (addresses.isEmpty()) return
    val context = LocalContext.current

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            title,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            color = Color(0xFF101828),
        )
        addresses.forEach { preview ->
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Color.White,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
            ) {
                Column(
                    modifier = Modifier.padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "${preview.branchLabel} #${preview.index}",
                            fontSize = 11.sp,
                            color = Color(0xFF475467),
                        )
                        TextButton(
                            onClick = {
                                copyPlainText(
                                    context = context,
                                    label = "btc-address",
                                    value = preview.address,
                                    successMessage = "BTC 地址已复制",
                                )
                            }
                        ) {
                            Text("复制", fontSize = 11.sp)
                        }
                    }
                    SelectionContainer {
                        Text(
                            preview.address,
                            fontSize = 12.sp,
                            color = Color(0xFF0F172A),
                        )
                    }
                    Text(
                        preview.path,
                        fontSize = 10.sp,
                        color = Color(0xFF667085),
                    )
                }
            }
        }
    }
}

private fun shortAddressLabel(address: String, head: Int = 8, tail: Int = 6): String {
    if (address.length <= head + tail + 3) return address
    return "${address.take(head)}...${address.takeLast(tail)}"
}

private fun copyPlainText(
    context: Context,
    label: String,
    value: String,
    successMessage: String,
) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText(label, value))
    Toast.makeText(context, successMessage, Toast.LENGTH_SHORT).show()
}

private val usdFormatter: NumberFormat = NumberFormat.getCurrencyInstance(Locale.US).apply {
    maximumFractionDigits = 2
}

private fun formatUsdAmount(value: Double?): String? = value?.let { usdFormatter.format(it) }

private fun calculateUsdPreview(amount: String, priceUsd: Double?): String? {
    val decimal = amount.toBigDecimalOrNull() ?: return null
    return priceUsd?.let { decimal.multiply(BigDecimal.valueOf(it)).toDouble() }
        ?.let { usdFormatter.format(it) }
}

private fun findTokenPrice(state: WalletUiState, chain: WalletChain, symbol: String): Double? {
    val assets = state.chainPortfolios[chain.chainId]?.assets ?: return null
    return assets.firstOrNull { it.symbol.equals(symbol, ignoreCase = true) }?.priceUsd
}

private fun formatPriceTime(timestamp: Long): String {
    return SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(timestamp))
}

@Composable
private fun ChainSelectorSection(
    selectedChainId: Long,
    onSelectChain: (Long) -> Unit,
) {
    val selectedChain = WalletChains.require(selectedChainId)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(22.dp),
        border = BorderStroke(1.dp, Color(0xFFE5E7EB)),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text("网络", fontWeight = FontWeight.Bold)
                    Text("切换后同步该链资产和活动", fontSize = 12.sp, color = Color(0xFF667085))
                }
                Surface(
                    color = Color(0xFFF8FAFC),
                    shape = RoundedCornerShape(999.dp),
                    border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                ) {
                    Text(
                        selectedChain.shortName,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                        fontSize = 12.sp,
                        color = Color(0xFF344054),
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                WalletChains.ALL.forEach { chain ->
                    val selected = chain.chainId == selectedChainId
                    Box(
                        modifier = Modifier
                            .background(
                                color = if (selected) Color(chain.accentColor) else Color(0xFFF8FAFC),
                                shape = RoundedCornerShape(18.dp),
                            )
                            .border(
                                width = 1.dp,
                                color = if (selected) Color.Transparent else Color(0xFFE2E8F0),
                                shape = RoundedCornerShape(18.dp),
                            )
                            .clickable { onSelectChain(chain.chainId) },
                    ) {
                        Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                            Text(
                                chain.shortName,
                                color = if (selected) Color.White else Color(0xFF111827),
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                chain.nativeSymbol,
                                color = if (selected) Color(0xFFE2E8F0) else Color(0xFF64748B),
                                fontSize = 11.sp,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AddressListItem(
    address: String,
    isSelected: Boolean,
    onSelect: () -> Unit,
    onRemove: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFFF8FAFC), RoundedCornerShape(10.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.CenterStart,
        ) {
            SelectionContainer {
                Text(
                    text = address,
                    fontSize = 11.sp,
                    lineHeight = 15.sp,
                    color = Color(0xFF0F172A),
                    softWrap = true,
                    overflow = TextOverflow.Visible,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (isSelected) {
                Text(
                    "当前",
                    fontSize = 11.sp,
                    color = Color(0xFF475467),
                    modifier = Modifier.padding(end = 4.dp),
                )
            }
            TextButton(
                onClick = onSelect,
                enabled = !isSelected,
            ) {
                Text("切换", fontSize = 12.sp)
            }
            TextButton(onClick = onRemove) {
                Text("删除", fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun PortfolioSection(
    chain: WalletChain,
    portfolio: ChainPortfolioUi?,
    isLoading: Boolean,
) {
    WalletSectionCard {
    val priceLabel = portfolio?.lastUpdatedAt?.let { "价格 ${formatPriceTime(it)}" }
    SectionHeader(
        title = "资产",
        subtitle = chain.displayName,
        trailing = priceLabel?.let {
            {
                Text(it, fontSize = 11.sp, color = Color(0xFF667085))
            }
        },
    )
            if (isLoading && portfolio == null) {
                Text("正在同步余额...", color = Color(0xFF64748B))
            } else if (portfolio == null) {
                Text("添加观察地址后，这里会展示当前链资产。", color = Color(0xFF64748B))
            } else {
                portfolio.assets
                    .sortedBy { assetAmountLooksZero(it.amount) }
                    .forEach { asset ->
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            color = if (asset.isNative) Color(0xFFF8FAFC) else Color.White,
                            shape = RoundedCornerShape(16.dp),
                            border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                        ) {
                        val usdLabel = formatUsdAmount(asset.usdAmount)
                        val unitPriceLabel = asset.priceUsd?.let { formatUsdAmount(it) }
                        val usdCaption = when {
                            usdLabel != null -> "≈ $usdLabel"
                            unitPriceLabel != null -> "≈ $unitPriceLabel / ${asset.symbol}"
                            else -> "≈ --"
                        }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 14.dp, vertical = 12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                                        Text(asset.symbol, fontWeight = FontWeight.SemiBold, color = Color(0xFF101828))
                                        if (asset.isNative) {
                                            StatusChip(
                                                label = "主币",
                                                background = Color(0xFFEFF8FF),
                                                contentColor = Color(0xFF175CD3),
                                            )
                                        }
                                    }
                                    Text(asset.name, fontSize = 11.sp, color = Color(0xFF667085))
                                }
                                Column(
                                    horizontalAlignment = Alignment.End,
                                    verticalArrangement = Arrangement.spacedBy(2.dp),
                                ) {
                                    Text(
                                        asset.amount,
                                        fontWeight = FontWeight.Medium,
                                        color = if (assetAmountLooksZero(asset.amount)) Color(0xFF98A2B3) else Color(0xFF101828),
                                    )
                                    Text(
                                        usdCaption,
                                        fontSize = 11.sp,
                                        color = Color(0xFF475467),
                                    )
                                }
                            }
                        }
                    }
            }
        }
    }

    @Composable
    private fun TransferSection(
        state: WalletUiState,
        chain: WalletChain,
        onTransferToChange: (String) -> Unit,
        onTransferAmountChange: (String) -> Unit,
        onTransferTokenChange: (String) -> Unit,
        onTransferAmountAll: () -> Unit,
        onPrepareTransfer: () -> Unit,
    ) {
        WalletSectionCard {
            SectionHeader(
                title = "转账",
                subtitle = "生成树莓派签名二维码",
            )
            OutlinedTextField(
                value = state.transferTo,
                onValueChange = onTransferToChange,
                label = { Text("接收地址") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = state.transferAmount,
                    onValueChange = onTransferAmountChange,
                    label = { Text("数量") },
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
                TextButton(onClick = onTransferAmountAll) { Text("全部", fontSize = 12.sp) }
            }
            val transferUsdLabel = calculateUsdPreview(
                state.transferAmount,
                findTokenPrice(state, chain, state.transferToken),
            )
            if (transferUsdLabel != null) {
                Text(
                    "≈ $transferUsdLabel",
                    fontSize = 12.sp,
                    color = Color(0xFF475467),
                    modifier = Modifier.padding(top = 4.dp, bottom = 4.dp),
                )
            }
            Text("代币", fontSize = 12.sp, color = Color(0xFF667085))
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                chain.tokens.forEach { token ->
                    val selected = token.symbol.equals(state.transferToken, ignoreCase = true)
                    Box(
                        modifier = Modifier
                            .background(
                                color = if (selected) Color(chain.accentColor) else Color(0xFFF8FAFC),
                                shape = RoundedCornerShape(999.dp),
                            )
                            .border(
                                width = 1.dp,
                                color = if (selected) Color.Transparent else Color(0xFFE2E8F0),
                                shape = RoundedCornerShape(999.dp),
                            )
                            .clickable { onTransferTokenChange(token.symbol) },
                    ) {
                        Text(
                            token.symbol,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                            color = if (selected) Color.White else Color(0xFF0F172A),
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium,
                        )
                    }
                }
            }
            Button(onClick = onPrepareTransfer, modifier = Modifier.fillMaxWidth()) {
                Text("生成转账请求")
            }
        }
}

@Composable
private fun DappToolsSection(
    state: WalletUiState,
    onRequestInputChange: (String) -> Unit,
    onImportRawRequest: () -> Unit,
    onImportRequestFromClipboard: () -> Unit,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
    onScanRequest: () -> Unit,
    onPickRequestFromGallery: () -> Unit,
) {
    var showManualTools by rememberSaveable { mutableStateOf(false) }

    WalletSectionCard {
        SectionHeader(
            title = "DApp 签名工具",
            subtitle = "扫码 WalletConnect 链接后，会优先按当前观察地址自动连接",
        )
        Surface(
            color = Color(0xFFF8FAFC),
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
        ) {
            Text(
                "推荐直接扫 DApp 给出的二维码；如果已经选好观察地址，收到提案后会自动批准 WalletConnect 会话。",
                modifier = Modifier.padding(12.dp),
                fontSize = 12.sp,
                color = Color(0xFF475467),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = onScanRequest, modifier = Modifier.weight(1f)) { Text("扫码连接", fontSize = 12.sp) }
            OutlinedButton(onClick = onImportRequestFromClipboard, modifier = Modifier.weight(1f)) { Text("粘贴连接", fontSize = 12.sp) }
        }
        TextButton(onClick = { showManualTools = !showManualTools }) {
            Text(if (showManualTools) "收起高级导入" else "高级导入", fontSize = 12.sp)
        }
        if (showManualTools) {
            OutlinedTextField(
                value = state.requestInput,
                onValueChange = onRequestInputChange,
                label = { Text("WalletConnect 连接 / DApp 原始请求") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onPickRequestFromGallery, modifier = Modifier.weight(1f)) { Text("相册二维码", fontSize = 12.sp) }
                OutlinedButton(onClick = onImportRawRequest, modifier = Modifier.weight(1f)) { Text("解析文本", fontSize = 12.sp) }
            }
        }
            if (state.walletConnectStatus.isNotBlank()) {
                Text(
                    state.walletConnectStatus,
                    fontSize = 12.sp,
                    color = Color(0xFF475467),
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            state.walletConnectProposal?.let { proposal ->
                Text(
                    "待连接: ${proposal.peerName.ifBlank { proposal.peerUrl.ifBlank { "-" } }}",
                    fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Button(onClick = onApproveWalletConnectProposal) { Text("批准", fontSize = 12.sp) }
                    TextButton(onClick = onRejectWalletConnectProposal) { Text("拒绝", fontSize = 12.sp) }
                }
            }
            state.walletConnectPendingRequest?.let { request ->
                Text(
                    "当前请求: ${request.peerName.ifBlank { request.peerUrl.ifBlank { "-" } }} · ${request.method}",
                    fontSize = 12.sp,
                    color = Color(0xFF475467),
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
    }

@Composable
private fun ActivitySection(
    state: WalletUiState,
    chain: WalletChain,
    onRefresh: () -> Unit,
    onOpenUrl: (String) -> Unit,
) {
    val filteredItems = state.activityItems.filter {
        it.chainId == chain.chainId || it.kind == WalletActivityKind.DAPP || it.kind == WalletActivityKind.SYSTEM
    }
    WalletSectionCard {
        SectionHeader(
            title = "活动",
            subtitle = if (state.syncingActivity) "正在同步最近代币活动..." else "本地操作记录和最近链上代币转账",
            trailing = { TextButton(onClick = onRefresh) { Text("刷新") } },
        )
            if (filteredItems.isEmpty()) {
                Text("还没有活动记录。完成转账、签名或连接 DApp 后会显示在这里。", color = Color(0xFF64748B))
            } else {
                filteredItems.forEach { item ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = Color(0xFFF8FAFC),
                        shape = RoundedCornerShape(18.dp),
                        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                    ) {
                        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(item.title, fontWeight = FontWeight.SemiBold)
                                    Text(item.subtitle, fontSize = 12.sp, color = Color(0xFF64748B))
                                }
                                if (item.amountLabel.isNotBlank()) {
                                    Text(item.amountLabel, fontWeight = FontWeight.Medium)
                                }
                            }
                            if (item.detail.isNotBlank()) {
                                Text(item.detail, fontSize = 12.sp, color = Color(0xFF475467))
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    "${WalletChains.require(item.chainId).shortName} · ${DateUtils.getRelativeTimeSpanString(item.timestamp)}",
                                    fontSize = 11.sp,
                                    color = Color(0xFF64748B),
                                )
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    if (item.statusLabel.isNotBlank()) {
                                        Text(item.statusLabel, fontSize = 11.sp, color = Color(0xFF0F766E))
                                    }
                                    if (item.externalUrl.isNotBlank()) {
                                        TextButton(onClick = { onOpenUrl(item.externalUrl) }) { Text("查看") }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

@Composable
private fun DiscoverSection(
    state: WalletUiState,
    chain: WalletChain,
    onRefreshHyperliquid: () -> Unit,
    onBeginHyperliquidApproval: () -> Unit,
    onHyperliquidMarketInputChange: (String) -> Unit,
    onSelectHyperliquidMarket: (String) -> Unit,
    onSetHyperliquidOrderMode: (HyperliquidOrderMode) -> Unit,
    onSetHyperliquidOrderSide: (Boolean) -> Unit,
    onHyperliquidOrderSizeChange: (String) -> Unit,
    onHyperliquidOrderPriceChange: (String) -> Unit,
    onToggleHyperliquidReduceOnly: () -> Unit,
    onPlaceHyperliquidOrder: () -> Unit,
    onCancelHyperliquidOrder: (String, Long) -> Unit,
    onRequestInputChange: (String) -> Unit,
    onImportRawRequest: () -> Unit,
    onImportRequestFromClipboard: () -> Unit,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
    onScanRequest: () -> Unit,
    onPickRequestFromGallery: () -> Unit,
    onOpenUrl: (String) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Hyperliquid", fontWeight = FontWeight.Bold)
            Text(
                "内置 DApp 已收敛为 Hyperliquid。主钱包通过树莓派离线签名批准 agent，之后订单和撤单会在 app 内直接完成。",
                fontSize = 12.sp,
                color = Color(0xFF667085),
            )
            Text(
                state.hyperliquidStatus.ifBlank { "先完成 Hyperliquid 授权" },
                fontSize = 12.sp,
                color = Color(0xFF475467),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onRefreshHyperliquid, modifier = Modifier.weight(1f), enabled = !state.hyperliquidLoading) {
                    Text(if (state.hyperliquidLoading) "同步中" else "刷新面板")
                }
                Button(onClick = onBeginHyperliquidApproval, modifier = Modifier.weight(1f), enabled = !state.hyperliquidLoading) {
                    Text(if (state.hyperliquidAgent == null) "启用交易" else "重建代理")
                }
            }
            state.hyperliquidAgent?.let { agent ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = Color(0xFFF8FAFC),
                    shape = RoundedCornerShape(18.dp),
                    border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                ) {
                    Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("当前 Agent", fontWeight = FontWeight.SemiBold)
                        Text(agent.agentName, fontSize = 12.sp, color = Color(0xFF475467))
                        Text(agent.agentAddress, fontSize = 12.sp, color = Color(0xFF475467))
                        agent.validUntil?.takeIf { it > 0 }?.let {
                            Text(
                                "有效期: ${DateUtils.getRelativeTimeSpanString(it, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS)}",
                                fontSize = 12.sp,
                                color = Color(0xFF475467),
                            )
                        }
                    }
                }
            }
            state.hyperliquidAccount?.let { account ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    HyperliquidMetricCard("权益", account.accountValue, Modifier.weight(1f))
                    HyperliquidMetricCard("占用保证金", account.marginUsed, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    HyperliquidMetricCard("可提现", account.withdrawable, Modifier.weight(1f))
                    HyperliquidMetricCard("总仓位", account.notionalPosition, Modifier.weight(1f))
                }
            }
            if (state.hyperliquidMarkets.isNotEmpty()) {
                Text("热门市场", fontWeight = FontWeight.SemiBold)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    state.hyperliquidMarkets.forEach { market ->
                        OutlinedButton(onClick = { onSelectHyperliquidMarket(market.name) }) {
                            Text(
                                "${market.name} ${market.midPrice}",
                                color = if (market.name.equals(state.hyperliquidSelectedMarket, ignoreCase = true)) {
                                    Color(0xFF5B3FD1)
                                } else {
                                    Color(0xFF344054)
                                },
                            )
                        }
                    }
                }
            }
            OutlinedTextField(
                value = state.hyperliquidSelectedMarket,
                onValueChange = onHyperliquidMarketInputChange,
                label = { Text("交易对 / Coin") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    onClick = { onSetHyperliquidOrderMode(HyperliquidOrderMode.MARKET) },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (state.hyperliquidOrderMode == HyperliquidOrderMode.MARKET) "市价中" else "市价单")
                }
                OutlinedButton(
                    onClick = { onSetHyperliquidOrderMode(HyperliquidOrderMode.LIMIT) },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (state.hyperliquidOrderMode == HyperliquidOrderMode.LIMIT) "限价中" else "限价单")
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    onClick = { onSetHyperliquidOrderSide(true) },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (state.hyperliquidOrderSideBuy) "买入中" else "买入")
                }
                OutlinedButton(
                    onClick = { onSetHyperliquidOrderSide(false) },
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (!state.hyperliquidOrderSideBuy) "卖出中" else "卖出")
                }
            }
            OutlinedTextField(
                value = state.hyperliquidOrderSizeInput,
                onValueChange = onHyperliquidOrderSizeChange,
                label = { Text("数量") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            if (state.hyperliquidOrderMode == HyperliquidOrderMode.LIMIT) {
                OutlinedTextField(
                    value = state.hyperliquidOrderPriceInput,
                    onValueChange = onHyperliquidOrderPriceChange,
                    label = { Text("限价") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            } else {
                Text("市价单会按当前中价附近生成 IoC 订单。", fontSize = 12.sp, color = Color(0xFF667085))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onToggleHyperliquidReduceOnly, modifier = Modifier.weight(1f)) {
                    Text(if (state.hyperliquidReduceOnly) "只减仓: 开" else "只减仓: 关")
                }
                Button(
                    onClick = onPlaceHyperliquidOrder,
                    modifier = Modifier.weight(1f),
                    enabled = !state.hyperliquidLoading && state.hyperliquidAgent != null,
                ) {
                    Text("提交订单")
                }
            }
            TextButton(onClick = { onOpenUrl("https://app.hyperliquid.xyz") }) { Text("打开官方站点") }
        }
    }

    if (state.hyperliquidOpenOrders.isNotEmpty()) {
        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("当前挂单", fontWeight = FontWeight.Bold)
                state.hyperliquidOpenOrders.forEach { order ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = Color(0xFFF8FAFC),
                        shape = RoundedCornerShape(16.dp),
                        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                    ) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("${order.coin} ${order.sideLabel}", fontWeight = FontWeight.SemiBold)
                            Text("价格 ${order.limitPrice} / 数量 ${order.size}", fontSize = 12.sp, color = Color(0xFF475467))
                            Text(
                                DateUtils.getRelativeTimeSpanString(order.timestamp, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString(),
                                fontSize = 12.sp,
                                color = Color(0xFF667085),
                            )
                            TextButton(onClick = { onCancelHyperliquidOrder(order.coin, order.oid) }) { Text("撤单") }
                        }
                    }
                }
            }
        }
    }

    if (state.hyperliquidFills.isNotEmpty()) {
        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("最近成交", fontWeight = FontWeight.Bold)
                state.hyperliquidFills.forEach { fill ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = Color(0xFFF8FAFC),
                        shape = RoundedCornerShape(16.dp),
                        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                    ) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("${fill.coin} ${fill.sideLabel}", fontWeight = FontWeight.SemiBold)
                            Text("价格 ${fill.price} / 数量 ${fill.size}", fontSize = 12.sp, color = Color(0xFF475467))
                            Text("已实现 PnL ${fill.pnl}", fontSize = 12.sp, color = Color(0xFF475467))
                            Text(
                                DateUtils.getRelativeTimeSpanString(fill.timestamp, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString(),
                                fontSize = 12.sp,
                                color = Color(0xFF667085),
                            )
                        }
                    }
                }
            }
        }
    }

    WalletConnectSection(
        state = state,
        onApproveWalletConnectProposal = onApproveWalletConnectProposal,
        onRejectWalletConnectProposal = onRejectWalletConnectProposal,
    )

    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("${chain.shortName} 高级工具", fontWeight = FontWeight.Bold)
            Text("保留 WalletConnect / 原始请求导入能力，方便处理 Hyperliquid 之外的离线签名场景。", fontSize = 12.sp, color = Color(0xFF667085))
            OutlinedTextField(
                value = state.requestInput,
                onValueChange = onRequestInputChange,
                label = { Text("粘贴 WalletConnect / DApp 原始请求") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 4,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onImportRawRequest, modifier = Modifier.weight(1f)) { Text("解析请求") }
                Button(onClick = onScanRequest, modifier = Modifier.weight(1f)) { Text("扫码二维码") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onPickRequestFromGallery, modifier = Modifier.weight(1f)) { Text("相册导入") }
                Button(onClick = onImportRequestFromClipboard, modifier = Modifier.weight(1f)) { Text("剪贴板导入") }
            }
        }
    }
}

@Composable
private fun HyperliquidMetricCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, fontSize = 12.sp, color = Color(0xFF667085))
            Text(value.ifBlank { "-" }, fontWeight = FontWeight.SemiBold, color = Color(0xFF111827))
        }
    }
}

@Composable
private fun WalletConnectSection(
    state: WalletUiState,
    onApproveWalletConnectProposal: () -> Unit,
    onRejectWalletConnectProposal: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("WalletConnect", fontWeight = FontWeight.Bold)
            Text(
                state.walletConnectStatus.ifBlank { "尚未建立 WalletConnect 会话" },
                fontSize = 12.sp,
                color = Color(0xFF475467),
            )
            state.walletConnectProposal?.let { proposal ->
                SectionLabel("待批准会话")
                Text("DApp: ${proposal.peerName.ifBlank { "-" }}", fontSize = 12.sp)
                if (proposal.peerUrl.isNotBlank()) {
                    Text("URL: ${proposal.peerUrl}", fontSize = 12.sp)
                }
                if (proposal.requiredChains.isNotEmpty()) {
                    Text("链: ${proposal.requiredChains.joinToString()}", fontSize = 12.sp)
                }
                if (proposal.requiredMethods.isNotEmpty()) {
                    Text("方法: ${proposal.requiredMethods.joinToString()}", fontSize = 12.sp)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onApproveWalletConnectProposal) { Text("批准连接") }
                    TextButton(onClick = onRejectWalletConnectProposal) { Text("拒绝") }
                }
            }
            state.walletConnectPendingRequest?.let { request ->
                SectionLabel("当前请求")
                Text("DApp: ${request.peerName.ifBlank { "-" }}", fontSize = 12.sp)
                Text("方法: ${request.method}", fontSize = 12.sp)
                request.chainId?.takeIf { it.isNotBlank() }?.let {
                    Text("链: $it", fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun PreparedRequestSection(
    state: WalletUiState,
    onPrevRelayPage: () -> Unit,
    onNextRelayPage: () -> Unit,
    onScanResponse: () -> Unit,
    onPickResponseFromGallery: () -> Unit,
    onClearPreparedRequest: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(state.requestTitle.ifBlank { "树莓派签名请求" }, fontWeight = FontWeight.Bold)
            if (state.requestSummary.isNotBlank()) {
                SelectionContainer {
                    Text(state.requestSummary, modifier = Modifier.fillMaxWidth(), fontSize = 12.sp)
                }
            }
            if (state.transferInfo.isNotBlank()) {
                SectionLabel("转账信息")
                SelectionContainer {
                    Text(state.transferInfo, modifier = Modifier.fillMaxWidth(), fontSize = 11.sp, color = Color(0xFF475467))
                }
            }
            if (state.dappInfo.isNotBlank()) {
                SectionLabel("DApp 信息")
                SelectionContainer {
                    Text(state.dappInfo, modifier = Modifier.fillMaxWidth(), fontSize = 11.sp, color = Color(0xFF475467))
                }
            }
            if (state.relayHint.isNotBlank()) {
                Text(state.relayHint, fontSize = 11.sp, color = Color(0xFF667085))
            }
            if (state.signQrPages.size > 1) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = onPrevRelayPage) { Text("上一张") }
                    Text("${state.signQrPageIndex + 1}/${state.signQrPages.size}")
                    TextButton(onClick = onNextRelayPage) { Text("下一张") }
                }
            }
            RelayQrFrame(
                bitmap = state.signQrBitmap!!,
                pageIndex = state.signQrPageIndex,
                pageCount = state.signQrPages.size,
                qrSize = if (state.signQrPages.size > 1) 312.dp else 320.dp,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onScanResponse, modifier = Modifier.weight(1f)) { Text("扫码结果", fontSize = 12.sp) }
                OutlinedButton(onClick = onPickResponseFromGallery, modifier = Modifier.weight(1f)) { Text("相册导入", fontSize = 12.sp) }
            }
            TextButton(onClick = onClearPreparedRequest) { Text("取消") }
        }
    }
}

@Composable
private fun MessageCard(title: String, message: String, background: Color, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = background),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, background.copy(alpha = 0.55f)),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, fontWeight = FontWeight.Bold, color = Color(0xFF101828))
                TextButton(onClick = onDismiss) { Text("关闭") }
            }
            Text(message, fontSize = 12.sp, color = Color(0xFF344054))
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text, modifier = Modifier.fillMaxWidth(), fontWeight = FontWeight.Medium)
}

private fun assetAmountLooksZero(value: String): Boolean {
    val normalized = value.trim().lowercase()
    if (normalized.isBlank()) return true
    if (normalized == "0") return true
    return normalized.toDoubleOrNull()?.let { kotlin.math.abs(it) < 0.0000000001 } ?: false
}

@Composable
private fun RelayQrFrame(bitmap: Bitmap, pageIndex: Int, pageCount: Int, qrSize: Dp) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF0F172A)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (pageCount > 1) {
                Surface(
                    color = Color(0xFF1D4ED8),
                    shape = RectangleShape,
                ) {
                    Text(
                        text = "动态中转 ${pageIndex + 1}/$pageCount · 1 秒轮播",
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        color = Color.White,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            Box(
                modifier = Modifier
                    .background(Color.White)
                    .border(2.dp, Color(0xFFE5E7EB))
                    .padding(12.dp),
            ) {
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "relay qr",
                    modifier = Modifier.size(qrSize),
                )
            }
        }
    }
}
