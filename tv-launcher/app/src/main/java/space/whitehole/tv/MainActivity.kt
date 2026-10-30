package space.whitehole.tv

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Shader
import android.graphics.drawable.Drawable
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.GridLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : Activity() {

    private enum class Page { HOME, APPS, HELP }

    private class Visual(val drawable: Drawable?, val banner: Boolean)

    private val mainHandler = Handler(Looper.getMainLooper())
    private val io: ExecutorService = Executors.newFixedThreadPool(2)
    private val visualCache = HashMap<String, Visual>()

    private lateinit var favorites: Favorites
    private var apps: List<AppEntry> = emptyList()
    private var happPackage: String? = null
    private var page = Page.HOME
    private var loadGeneration = 0
    private var lastFavSig = ""
    private var lastAppsSig = ""
    private var destroyed = false

    private lateinit var dim: View
    private lateinit var tabHome: TextView
    private lateinit var tabApps: TextView
    private lateinit var clock: TextView
    private lateinit var pageHome: View
    private lateinit var pageApps: View
    private lateinit var pageHelp: View
    private lateinit var statusDot: View
    private lateinit var statusText: TextView
    private lateinit var heroTitle: TextView
    private lateinit var btnConnect: TextView
    private lateinit var btnHow: TextView
    private lateinit var favScroll: HorizontalScrollView
    private lateinit var favRow: LinearLayout
    private lateinit var appsScroll: ScrollView
    private lateinit var appsGrid: GridLayout
    private lateinit var appsEmpty: TextView
    private lateinit var qrImage: ImageView
    private lateinit var btnOpenHapp: TextView
    private lateinit var btnHelpBack: TextView

    private var connectivity: ConnectivityManager? = null
    private var vpnCallbackRegistered = false
    private var receiverRegistered = false

    private var clockFormat = SimpleDateFormat("HH:mm", Locale.getDefault())

    private val clockTick = object : Runnable {
        override fun run() {
            clock.text = clockFormat.format(Date())
            val now = System.currentTimeMillis()
            mainHandler.postDelayed(this, 60_000L - (now % 60_000L) + 50L)
        }
    }

    private val vpnCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            mainHandler.post { updateVpnStatus() }
        }

        override fun onLost(network: Network) {
            mainHandler.post { updateVpnStatus() }
        }

        override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) {
            mainHandler.post { updateVpnStatus() }
        }
    }

    private val packageReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            visualCache.clear()
            lastFavSig = ""
            lastAppsSig = ""
            reloadApps()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        favorites = Favorites(this)

        dim = findViewById(R.id.dim)
        tabHome = findViewById(R.id.tab_home)
        tabApps = findViewById(R.id.tab_apps)
        clock = findViewById(R.id.clock)
        pageHome = findViewById(R.id.page_home)
        pageApps = findViewById(R.id.page_apps)
        pageHelp = findViewById(R.id.page_help)
        statusDot = findViewById(R.id.status_dot)
        statusText = findViewById(R.id.status_text)
        heroTitle = findViewById(R.id.hero_title)
        btnConnect = findViewById(R.id.btn_connect)
        btnHow = findViewById(R.id.btn_how)
        favScroll = findViewById(R.id.fav_scroll)
        favRow = findViewById(R.id.fav_row)
        appsScroll = findViewById(R.id.apps_scroll)
        appsGrid = findViewById(R.id.apps_grid)
        appsEmpty = findViewById(R.id.apps_empty)
        qrImage = findViewById(R.id.qr_image)
        btnOpenHapp = findViewById(R.id.btn_open_happ)
        btnHelpBack = findViewById(R.id.btn_help_back)

        // Градиент на заголовке: белый → #AAB3C5
        val titleWidth = heroTitle.paint.measureText(heroTitle.text.toString())
        heroTitle.paint.shader = LinearGradient(
            0f, 0f, titleWidth, 0f,
            Color.WHITE, Color.parseColor("#AAB3C5"), Shader.TileMode.CLAMP
        )

        tabHome.setOnClickListener { showPage(Page.HOME, true) }
        tabApps.setOnClickListener { showPage(Page.APPS, true) }
        btnConnect.setOnClickListener { onConnectClicked() }
        btnHow.setOnClickListener { showPage(Page.HELP, true) }
        btnHelpBack.setOnClickListener { showPage(Page.HOME, true) }
        btnOpenHapp.setOnClickListener {
            val p = happPackage
            if (p != null) launchApp(p)
        }

        for (v in listOf<View>(tabHome, tabApps, btnConnect, btnHow, btnOpenHapp, btnHelpBack)) {
            setupFocusAnim(v, 1.06f)
        }

        val qr = makeQr(BOT_LINK, dp(232))
        if (qr != null) qrImage.setImageBitmap(qr)

        connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        registerVpnCallback()
        registerPackageReceiver()

        showPage(Page.HOME, false)
        btnConnect.requestFocus()
        reloadApps()
    }

    override fun onResume() {
        super.onResume()
        clockFormat = SimpleDateFormat("HH:mm", Locale.getDefault())
        mainHandler.removeCallbacks(clockTick)
        clockTick.run()
        updateVpnStatus()
        reloadApps()
    }

    override fun onPause() {
        super.onPause()
        mainHandler.removeCallbacks(clockTick)
    }

    override fun onDestroy() {
        destroyed = true
        mainHandler.removeCallbacksAndMessages(null)
        if (vpnCallbackRegistered) {
            try {
                connectivity?.unregisterNetworkCallback(vpnCallback)
            } catch (e: Exception) {
                // ignore
            }
            vpnCallbackRegistered = false
        }
        if (receiverRegistered) {
            try {
                unregisterReceiver(packageReceiver)
            } catch (e: Exception) {
                // ignore
            }
            receiverRegistered = false
        }
        io.shutdownNow()
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Нажали «Домой», когда мы уже открыты — возвращаемся на главную
        showPage(Page.HOME, true)
        favScroll.scrollTo(0, 0)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // На главном экране «Назад» ничего не делает (мы — домашний экран)
        if (page != Page.HOME) {
            showPage(Page.HOME, true)
        }
    }

    // ---------- Страницы ----------

    private fun showPage(p: Page, moveFocus: Boolean) {
        page = p
        pageHome.visibility = if (p == Page.HOME) View.VISIBLE else View.GONE
        pageApps.visibility = if (p == Page.APPS) View.VISIBLE else View.GONE
        pageHelp.visibility = if (p == Page.HELP) View.VISIBLE else View.GONE
        tabHome.isSelected = p == Page.HOME
        tabApps.isSelected = p == Page.APPS
        dim.animate().alpha(if (p == Page.HOME) 0f else 0.82f).setDuration(200).start()

        if (p == Page.HELP) {
            if (happPackage == null) happPackage = AppRepository.findHapp(this, apps)
            btnOpenHapp.visibility = if (happPackage != null) View.VISIBLE else View.GONE
        }

        if (!moveFocus) return
        when (p) {
            Page.HOME -> btnConnect.requestFocus()
            Page.APPS -> {
                appsScroll.scrollTo(0, 0)
                val first = appsGrid.getChildAt(0)
                if (first != null) first.requestFocus() else tabApps.requestFocus()
            }
            Page.HELP -> {
                if (btnOpenHapp.visibility == View.VISIBLE) btnOpenHapp.requestFocus() else btnHelpBack.requestFocus()
            }
        }
    }

    private fun onConnectClicked() {
        val p = happPackage ?: AppRepository.findHapp(this, apps)
        if (p != null) {
            happPackage = p
            launchApp(p)
        } else {
            showPage(Page.HELP, true)
        }
    }

    // ---------- Приложения ----------

    private fun reloadApps() {
        val gen = ++loadGeneration
        val ctx = applicationContext
        try {
            io.execute {
                val list = AppRepository.loadApps(ctx)
                val happ = AppRepository.findHapp(ctx, list)
                mainHandler.post {
                    if (gen == loadGeneration && !destroyed) onAppsLoaded(list, happ)
                }
            }
        } catch (e: Exception) {
            // executor уже остановлен
        }
    }

    private fun onAppsLoaded(list: List<AppEntry>, happ: String?) {
        apps = list
        happPackage = happ
        favorites.ensureDefaults(list)

        val appsSig = list.joinToString("|") { it.packageName + ":" + it.label }
        if (appsSig != lastAppsSig) {
            lastAppsSig = appsSig
            buildAppsGrid()
        }
        val favSig = favorites.get().joinToString("|") + "#" + appsSig
        if (favSig != lastFavSig) {
            lastFavSig = favSig
            buildFavRow()
        }
        if (page == Page.HELP) {
            btnOpenHapp.visibility = if (happPackage != null) View.VISIBLE else View.GONE
        }
    }

    private fun buildFavRow() {
        val focused = favRow.focusedChild
        val focusedIndex = if (focused != null) favRow.indexOfChild(focused) else -1
        favRow.removeAllViews()

        val byPkg = HashMap<String, AppEntry>()
        for (a in apps) byPkg[a.packageName] = a
        for (pkg in favorites.get()) {
            val app = byPkg[pkg] ?: continue
            val tile = inflateTile(favRow)
            bindAppTile(tile, app)
            favRow.addView(tile)
        }
        favRow.addView(makeActionTile(favRow, R.drawable.ic_settings, getString(R.string.tile_settings)) {
            openSettings()
        })
        favRow.addView(makeActionTile(favRow, R.drawable.ic_apps, getString(R.string.tile_all_apps)) {
            showPage(Page.APPS, true)
        })

        if (focusedIndex >= 0 && page == Page.HOME) {
            val idx = minOf(focusedIndex, favRow.childCount - 1)
            favRow.getChildAt(idx)?.requestFocus()
        }
    }

    private fun buildAppsGrid() {
        val focusedTag = appsGrid.focusedChild?.tag as? String
        appsGrid.removeAllViews()
        for (app in apps) {
            val tile = inflateTile(appsGrid)
            bindAppTile(tile, app)
            appsGrid.addView(tile)
        }
        appsEmpty.visibility = if (apps.isEmpty()) View.VISIBLE else View.GONE

        if (page == Page.APPS && focusedTag != null) {
            for (i in 0 until appsGrid.childCount) {
                val c = appsGrid.getChildAt(i)
                if (c.tag == focusedTag) {
                    c.requestFocus()
                    return
                }
            }
            appsGrid.getChildAt(0)?.requestFocus()
        }
    }

    private fun inflateTile(parent: ViewGroup): View {
        val tile = layoutInflater.inflate(R.layout.item_tile, parent, false)
        val lp = tile.layoutParams as ViewGroup.MarginLayoutParams
        lp.width = dp(156)
        lp.height = dp(88)
        lp.setMargins(dp(6), dp(6), dp(6), dp(6))
        tile.layoutParams = lp
        tile.clipToOutline = true
        return tile
    }

    private fun bindAppTile(tile: View, app: AppEntry) {
        val label = tile.findViewById<TextView>(R.id.tile_label)
        label.text = app.label
        tile.contentDescription = app.label
        tile.tag = app.packageName

        val cached = visualCache[app.packageName]
        if (cached != null) {
            applyVisual(tile, cached)
        } else {
            tile.findViewById<View>(R.id.tile_banner).visibility = View.GONE
            tile.findViewById<View>(R.id.tile_icon_box).visibility = View.VISIBLE
            tile.findViewById<ImageView>(R.id.tile_icon).setImageDrawable(null)
            val pm = packageManager
            try {
                io.execute {
                    val banner = AppRepository.loadBanner(pm, app)
                    val vis = if (banner != null) Visual(banner, true) else Visual(AppRepository.loadIcon(pm, app), false)
                    mainHandler.post {
                        if (!destroyed) {
                            visualCache[app.packageName] = vis
                            if (tile.tag == app.packageName) applyVisual(tile, vis)
                        }
                    }
                }
            } catch (e: Exception) {
                // executor уже остановлен
            }
        }

        tile.setOnClickListener { launchApp(app.packageName) }
        tile.setOnLongClickListener {
            toggleFavorite(app)
            true
        }
        tile.setOnKeyListener { _, keyCode, event ->
            if (keyCode == KeyEvent.KEYCODE_MENU) {
                if (event.action == KeyEvent.ACTION_UP) toggleFavorite(app)
                true
            } else {
                false
            }
        }
        setupFocusAnim(tile, 1.06f)
    }

    private fun applyVisual(tile: View, vis: Visual) {
        val bannerView = tile.findViewById<ImageView>(R.id.tile_banner)
        val iconBox = tile.findViewById<View>(R.id.tile_icon_box)
        val iconView = tile.findViewById<ImageView>(R.id.tile_icon)
        val src = vis.drawable
        val d: Drawable? = if (src != null) (src.constantState?.newDrawable() ?: src) else null
        if (vis.banner && d != null) {
            bannerView.setImageDrawable(d)
            bannerView.visibility = View.VISIBLE
            iconBox.visibility = View.GONE
        } else {
            bannerView.visibility = View.GONE
            iconBox.visibility = View.VISIBLE
            if (d != null) {
                iconView.setImageDrawable(d)
            } else {
                iconView.setImageResource(android.R.drawable.sym_def_app_icon)
            }
        }
    }

    private fun makeActionTile(parent: ViewGroup, iconRes: Int, text: String, action: () -> Unit): View {
        val tile = inflateTile(parent)
        tile.findViewById<View>(R.id.tile_banner).visibility = View.GONE
        tile.findViewById<View>(R.id.tile_icon_box).visibility = View.VISIBLE
        tile.findViewById<ImageView>(R.id.tile_icon).setImageResource(iconRes)
        tile.findViewById<TextView>(R.id.tile_label).text = text
        tile.contentDescription = text
        tile.setOnClickListener { action() }
        setupFocusAnim(tile, 1.06f)
        return tile
    }

    private fun toggleFavorite(app: AppEntry) {
        val added = favorites.toggle(app.packageName)
        val msg = if (added) getString(R.string.fav_added, app.label) else getString(R.string.fav_removed, app.label)
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        lastFavSig = favorites.get().joinToString("|") + "#" + lastAppsSig
        buildFavRow()
    }

    private fun launchApp(pkg: String) {
        val intent = AppRepository.launchIntent(packageManager, pkg)
        if (intent == null) {
            Toast.makeText(this, R.string.launch_failed, Toast.LENGTH_SHORT).show()
            return
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(this, R.string.launch_failed, Toast.LENGTH_SHORT).show()
        }
    }

    private fun openSettings() {
        try {
            startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Exception) {
            Toast.makeText(this, R.string.launch_failed, Toast.LENGTH_SHORT).show()
        }
    }

    // ---------- VPN-статус ----------

    private fun registerVpnCallback() {
        val cm = connectivity ?: return
        try {
            val request = NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_VPN)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
            cm.registerNetworkCallback(request, vpnCallback)
            vpnCallbackRegistered = true
        } catch (e: Exception) {
            vpnCallbackRegistered = false
        }
    }

    @Suppress("DEPRECATION")
    private fun isVpnActive(): Boolean {
        val cm = connectivity ?: return false
        return try {
            cm.allNetworks.any { n ->
                cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
            }
        } catch (e: Exception) {
            false
        }
    }

    private fun updateVpnStatus() {
        if (destroyed) return
        if (isVpnActive()) {
            statusDot.setBackgroundResource(R.drawable.dot_green)
            statusText.setText(R.string.status_on)
        } else {
            statusDot.setBackgroundResource(R.drawable.dot_grey)
            statusText.setText(R.string.status_off)
        }
    }

    // ---------- Прочее ----------

    private fun registerPackageReceiver() {
        val filter = IntentFilter()
        filter.addAction(Intent.ACTION_PACKAGE_ADDED)
        filter.addAction(Intent.ACTION_PACKAGE_REMOVED)
        filter.addAction(Intent.ACTION_PACKAGE_CHANGED)
        filter.addAction(Intent.ACTION_PACKAGE_REPLACED)
        filter.addDataScheme("package")
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(packageReceiver, filter, Context.RECEIVER_EXPORTED)
            } else {
                registerReceiver(packageReceiver, filter)
            }
            receiverRegistered = true
        } catch (e: Exception) {
            receiverRegistered = false
        }
    }

    private fun setupFocusAnim(v: View, scale: Float) {
        v.setOnFocusChangeListener { view, hasFocus ->
            val s = if (hasFocus) scale else 1f
            view.animate()
                .scaleX(s)
                .scaleY(s)
                .translationZ(if (hasFocus) dp(6).toFloat() else 0f)
                .setDuration(140)
                .start()
        }
    }

    private fun makeQr(text: String, size: Int): Bitmap? {
        return try {
            val hints = HashMap<EncodeHintType, Any>()
            hints[EncodeHintType.MARGIN] = 1
            hints[EncodeHintType.ERROR_CORRECTION] = ErrorCorrectionLevel.M
            hints[EncodeHintType.CHARACTER_SET] = "UTF-8"
            val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, hints)
            val w = matrix.width
            val h = matrix.height
            val pixels = IntArray(w * h)
            for (y in 0 until h) {
                val offset = y * w
                for (x in 0 until w) {
                    pixels[offset + x] = if (matrix.get(x, y)) Color.BLACK else Color.WHITE
                }
            }
            Bitmap.createBitmap(pixels, w, h, Bitmap.Config.ARGB_8888)
        } catch (e: Exception) {
            null
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    companion object {
        private const val BOT_LINK = "https://t.me/WhiteHoleVPNbot?start=src_tv"
    }
}
