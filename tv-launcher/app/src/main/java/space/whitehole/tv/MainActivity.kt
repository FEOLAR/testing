package space.whitehole.tv

import android.app.Activity
import android.animation.ArgbEvaluator
import android.animation.ValueAnimator
import android.app.ActivityManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Shader
import android.graphics.drawable.BitmapDrawable
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
import android.util.DisplayMetrics
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.animation.DecelerateInterpolator
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
import android.widget.ProgressBar
import org.json.JSONObject
import java.util.Calendar
import java.util.TimeZone

class MainActivity : Activity() {

    private enum class Page { HOME, APPS, HELP, PAIR, SUB, SETTINGS }

    internal lateinit var session: Session
    internal lateinit var prefs: Prefs
    internal lateinit var choiceDialog: ChoiceDialog
    private lateinit var settings: SettingsScreen
    private lateinit var blackHole: BlackHoleView
    private lateinit var bgTint: View
    private lateinit var connectAnim: HomeConnectAnimator

    /** Анимация кнопки «Подключиться» — её вызывает и путь через Happ, и встроенный VPN. */
    internal val connectAnimator: ConnectAnimator get() = connectAnim
    private var lastVpnActive: Boolean? = null
    private val tintCache = HashMap<String, Int>()
    private var tintTarget = 0
    private var tintCurrent = 0
    private var tintAnimator: ValueAnimator? = null

    // заставка при простое
    private var lastInputAt = System.currentTimeMillis()
    private var idleView: View? = null
    private var idleController: ScreensaverController? = null
    private var swallowKeyUp = -1

    // недавние, погода, входы
    private lateinit var homeScroll: ScrollView
    private lateinit var homeHero: View
    private lateinit var topBar: View
    private lateinit var topWeather: TextView
    private lateinit var topDate: TextView
    private lateinit var btnContinue: TextView
    private lateinit var recentsLabel: View
    private lateinit var recentsScroll: View
    private lateinit var recentsRow: LinearLayout
    private lateinit var inputsLabel: View
    private lateinit var inputsScroll: View
    private lateinit var inputsRow: LinearLayout
    private var lastRecentsSig = "?"
    private var lastInputsSig = "?"
    private var weatherLoading = false
    private var dateFormat = SimpleDateFormat("EE, d MMM", Locale("ru"))
    private val idleCheck = object : Runnable {
        override fun run() {
            checkIdle()
            mainHandler.postDelayed(this, 20_000L)
        }
    }
    private lateinit var mainContent: View
    private lateinit var btnSub: TextView
    private lateinit var subLine: TextView
    private lateinit var helpStatus: TextView
    private lateinit var btnInstallHapp: TextView
    private lateinit var pagePair: View
    private lateinit var pairTitle: TextView
    private lateinit var pairSubtitle: TextView
    private lateinit var pairForm: View
    private lateinit var pairQr: ImageView
    private lateinit var pairCodeView: TextView
    private lateinit var pairDot: View
    private lateinit var pairStatus: TextView
    private lateinit var btnPairMain: TextView
    private lateinit var btnPairBack: TextView
    private lateinit var pageSub: View
    private lateinit var subPlan: TextView
    private lateinit var subDays: TextView
    private lateinit var subDaysLabel: TextView
    private lateinit var subUntil: TextView
    private lateinit var subDevices: TextView
    private lateinit var subProgress: ProgressBar
    private lateinit var subDeviceName: TextView
    private lateinit var subQr: ImageView
    private lateinit var btnSubBack: TextView
    private lateinit var btnSubRefresh: TextView
    private lateinit var btnSubUnpair: TextView

    // вход по коду
    private var pairGen = 0
    private var pairToken: String? = null
    private var pairDone = false
    private var resumed = false
    private var unpairArmed = false
    private var downloading = false
    private var meLoading = false

    private class Visual(val drawable: Drawable?, val banner: Boolean)

    private val mainHandler = Handler(Looper.getMainLooper())
    private val focusInterpolator = DecelerateInterpolator(1.6f)
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
    private var qrBuiltSize = 0
    private var pickMode = false
    private var menuPkg: String? = null
    private var longPressFired = false
    private var confirmDownView: View? = null
    private lateinit var notHomeChip: TextView
    private lateinit var makeHomeNote: TextView
    private lateinit var btnMakeHome: TextView

    private lateinit var heroBg: ImageView
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
    private lateinit var content: ViewGroup
    private lateinit var appsHint: TextView
    private lateinit var tileMenu: View
    private lateinit var menuTitle: TextView
    private lateinit var menuLeft: TextView
    private lateinit var menuRight: TextView
    private lateinit var menuRemove: TextView
    private lateinit var menuCancel: TextView

    private var connectivity: ConnectivityManager? = null
    private var vpnCallbackRegistered = false
    private var receiverRegistered = false

    private var clockFormat = SimpleDateFormat("HH:mm", Locale.getDefault())

    private val clockTick = object : Runnable {
        override fun run() {
            clock.text = clockFormat.format(Date())
            if (::topDate.isInitialized) topDate.text = dateFormat.format(Date())
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

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        // Один и тот же вид (960×540 dp) на 720p/1080p/4K и на нестандартных плотностях
        val o = UiScale.overrideFor(newBase)
        if (o != null) {
            try {
                applyOverrideConfiguration(o)
            } catch (e: Exception) {
                // уже поздно переопределять — работаем с системной плотностью
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        favorites = Favorites(this)
        prefs = Prefs(this)

        heroBg = findViewById(R.id.hero_bg)
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
        content = findViewById(R.id.content)
        appsHint = findViewById(R.id.apps_hint)
        tileMenu = findViewById(R.id.tile_menu)
        menuTitle = findViewById(R.id.menu_title)
        menuLeft = findViewById(R.id.menu_left)
        menuRight = findViewById(R.id.menu_right)
        menuRemove = findViewById(R.id.menu_remove)
        menuCancel = findViewById(R.id.menu_cancel)
        menuLeft.setOnClickListener { onMenuAction(MENU_LEFT) }
        menuRight.setOnClickListener { onMenuAction(MENU_RIGHT) }
        menuRemove.setOnClickListener { onMenuAction(MENU_REMOVE) }
        menuCancel.setOnClickListener { onMenuAction(MENU_CANCEL) }
        tileMenu.setOnClickListener { hideTileMenu(true) }
        notHomeChip = findViewById(R.id.not_home_chip)
        makeHomeNote = findViewById(R.id.make_home_note)
        btnMakeHome = findViewById(R.id.btn_make_home)
        notHomeChip.setOnClickListener { openHomeSettings() }
        btnMakeHome.setOnClickListener { openHomeSettings() }
        setupFocusAnim(notHomeChip, 1.06f)
        setupFocusAnim(btnMakeHome, 1.06f)
        session = Session(this)
        blackHole = findViewById(R.id.black_hole)
        homeScroll = findViewById(R.id.page_home)
        homeHero = findViewById(R.id.home_hero)
        topBar = findViewById(R.id.top_bar)
        topWeather = findViewById(R.id.top_weather)
        topDate = findViewById(R.id.top_date)
        btnContinue = findViewById(R.id.btn_continue)
        recentsLabel = findViewById(R.id.recents_label)
        recentsScroll = findViewById(R.id.recents_scroll)
        recentsRow = findViewById(R.id.recents_row)
        inputsLabel = findViewById(R.id.inputs_label)
        inputsScroll = findViewById(R.id.inputs_scroll)
        inputsRow = findViewById(R.id.inputs_row)
        btnContinue.setOnClickListener {
            val last = prefs.recents().firstOrNull { p -> apps.any { it.packageName == p } }
            if (last != null) launchApp(last)
        }
        setupFocusAnim(btnContinue, 1.06f)
        bgTint = findViewById(R.id.bg_tint)
        val pages = findViewById<ViewGroup>(R.id.pages)
        val settingsView = layoutInflater.inflate(R.layout.page_settings, pages, false)
        pages.addView(settingsView)
        settings = SettingsScreen(this, settingsView)
        val rootView = findViewById<ViewGroup>(R.id.root)
        choiceDialog = ChoiceDialog(
            rootView,
            { content.descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS },
            { content.descendantFocusability = ViewGroup.FOCUS_AFTER_DESCENDANTS },
            { v -> setupFocusAnim(v, 1.02f) }
        )
        connectAnim = HomeConnectAnimator(blackHole, findViewById(R.id.status_chip), btnConnect) { prefs.animations }
        rootView.viewTreeObserver.addOnGlobalFocusChangeListener { _, newFocus -> onFocusMoved(newFocus) }
        mainContent = findViewById(R.id.content)
        btnSub = findViewById(R.id.btn_sub)
        subLine = findViewById(R.id.sub_line)
        helpStatus = findViewById(R.id.help_status)
        btnInstallHapp = findViewById(R.id.btn_install_happ)
        pagePair = findViewById(R.id.page_pair)
        pairTitle = findViewById(R.id.pair_title)
        pairSubtitle = findViewById(R.id.pair_subtitle)
        pairForm = findViewById(R.id.pair_form)
        pairQr = findViewById(R.id.pair_qr)
        pairCodeView = findViewById(R.id.pair_code)
        pairDot = findViewById(R.id.pair_dot)
        pairStatus = findViewById(R.id.pair_status)
        btnPairMain = findViewById(R.id.btn_pair_main)
        btnPairBack = findViewById(R.id.btn_pair_back)
        pageSub = findViewById(R.id.page_sub)
        subPlan = findViewById(R.id.sub_plan)
        subDays = findViewById(R.id.sub_days)
        subDaysLabel = findViewById(R.id.sub_days_label)
        subUntil = findViewById(R.id.sub_until)
        subDevices = findViewById(R.id.sub_devices)
        subProgress = findViewById(R.id.sub_progress)
        subDeviceName = findViewById(R.id.sub_device_name)
        subQr = findViewById(R.id.sub_qr)
        btnSubBack = findViewById(R.id.btn_sub_back)
        btnSubRefresh = findViewById(R.id.btn_sub_refresh)
        btnSubUnpair = findViewById(R.id.btn_sub_unpair)
        findViewById<View>(R.id.sub_card).clipToOutline = true

        // Градиент на заголовках: белый → #AAB3C5
        for (t in listOf(heroTitle, findViewById<TextView>(R.id.pair_brand), findViewById<TextView>(R.id.sub_brand))) {
            applyTitleGradient(t)
        }

        btnSub.setOnClickListener { showPage(Page.SUB, true) }
        btnInstallHapp.setOnClickListener { installHapp() }
        btnPairBack.setOnClickListener { showPage(Page.HOME, true) }
        btnPairMain.setOnClickListener { onPairMainClicked() }
        btnSubBack.setOnClickListener { showPage(Page.HOME, true) }
        btnSubRefresh.setOnClickListener { refreshMe(true) }
        btnSubUnpair.setOnClickListener { onUnpairClicked() }
        for (v in listOf<View>(btnSub, btnInstallHapp, btnPairMain, btnPairBack, btnSubBack, btnSubRefresh, btnSubUnpair)) {
            setupFocusAnim(v, 1.06f)
        }
        setQr(subQr, Api.RENEW_LINK, dp(130))
        updateHomeUi()

        tabHome.setOnClickListener { showPage(Page.HOME, true) }
        tabApps.setOnClickListener {
            pickMode = false
            showPage(Page.APPS, true)
        }
        btnConnect.setOnClickListener { onConnectClicked() }
        btnHow.setOnClickListener { showPage(Page.HELP, true) }
        btnHelpBack.setOnClickListener { showPage(Page.HOME, true) }
        btnOpenHapp.setOnClickListener {
            val p = happPackage
            if (p != null) launchApp(p)
        }

        for (v in listOf<View>(tabHome, tabApps, btnConnect, btnHow, btnOpenHapp, btnHelpBack, menuLeft, menuRight, menuRemove, menuCancel)) {
            setupFocusAnim(v, 1.06f)
        }

        // QR строим под точный размер в пикселях, когда известен размер view
        qrImage.addOnLayoutChangeListener { v, left, top, right, bottom, _, _, _, _ ->
            val size = minOf(right - left, bottom - top)
            if (size > 0 && size != qrBuiltSize) {
                qrBuiltSize = size
                renderQr(v as ImageView, size)
            }
        }

        val realMetrics = logDisplayMetrics()
        loadHeroBackground(realMetrics.widthPixels, realMetrics.heightPixels)

        connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        registerVpnCallback()
        registerPackageReceiver()

        showPage(Page.HOME, false)
        btnConnect.requestFocus()
        applyAnimationsSetting()
        reloadApps()
    }

    override fun onResume() {
        super.onResume()
        clockFormat = SimpleDateFormat("HH:mm", Locale.getDefault())
        dateFormat = SimpleDateFormat("EE, d MMM", Locale("ru"))
        refreshWeather(false)
        refreshInputs()
        mainHandler.removeCallbacks(clockTick)
        clockTick.run()
        updateVpnStatus()
        reloadApps()
        resumed = true
        lastInputAt = System.currentTimeMillis()
        mainHandler.removeCallbacks(idleCheck)
        mainHandler.postDelayed(idleCheck, 20_000L)
        updateVpnStatus()
        updateBlackHoleRunning()
        updateDefaultHomeUi()
        updateHomeUi()
        refreshMe(false)
        if (page == Page.PAIR && !pairDone) {
            if (pairToken != null) schedulePoll(pairGen, 500L) else startPairing()
        }
    }

    override fun onPause() {
        super.onPause()
        resumed = false
        mainHandler.removeCallbacks(idleCheck)
        hideIdle()
        updateBlackHoleRunning()
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
        hideTileMenu(false)
        pickMode = false
        showPage(Page.HOME, true)
        favScroll.scrollTo(0, 0)
        homeScroll.scrollTo(0, 0)
    }

    // Геймпад: B = «Назад» (на случай, если система не переводит B в BACK сама)
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BUTTON_B) return true
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BUTTON_B) {
            onBackPressed()
            return true
        }
        return super.onKeyUp(keyCode, event)
    }

    // ---------- Главный экран системы ----------

    /** Мы ли сейчас домашний экран по умолчанию. */
    internal fun isDefaultHome(): Boolean {
        return try {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            val ri = packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
            ri?.activityInfo?.packageName == packageName
        } catch (e: Exception) {
            true
        }
    }

    private fun updateDefaultHomeUi() {
        val isHome = isDefaultHome()
        notHomeChip.visibility = if (isHome) View.GONE else View.VISIBLE
        makeHomeNote.visibility = if (isHome) View.GONE else View.VISIBLE
        btnMakeHome.visibility = if (isHome) View.GONE else View.VISIBLE
    }

    /** Настройки «Главный экран», если есть; иначе общие настройки. */
    internal fun openHomeSettings() {
        val home = Intent(Settings.ACTION_HOME_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            if (home.resolveActivity(packageManager) != null) {
                startActivity(home)
                return
            }
        } catch (e: Exception) {
            // нет такого экрана
        }
        openSettings()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // На главном экране «Назад» ничего не делает (мы — домашний экран)
        if (choiceDialog.isShowing) {
            choiceDialog.dismiss()
            return
        }
        if (tileMenu.visibility == View.VISIBLE) {
            hideTileMenu(true)
            return
        }
        if (page != Page.HOME) {
            val wasPick = pickMode
            pickMode = false
            showPage(Page.HOME, !wasPick)
            if (wasPick) focusAddTile()
        }
    }

    // ---------- Страницы ----------

    private fun showPage(p: Page, moveFocus: Boolean) {
        val prev = page
        page = p
        if (p != Page.APPS) pickMode = false
        if (prev == Page.PAIR && p != Page.PAIR) stopPairing()
        if (p != Page.SUB) disarmUnpair()
        val full = p == Page.PAIR || p == Page.SUB
        mainContent.visibility = if (full) View.GONE else View.VISIBLE
        pagePair.visibility = if (p == Page.PAIR) View.VISIBLE else View.GONE
        pageSub.visibility = if (p == Page.SUB) View.VISIBLE else View.GONE
        pageHome.visibility = if (p == Page.HOME) View.VISIBLE else View.GONE
        pageApps.visibility = if (p == Page.APPS) View.VISIBLE else View.GONE
        pageHelp.visibility = if (p == Page.HELP) View.VISIBLE else View.GONE
        settings.page.visibility = if (p == Page.SETTINGS) View.VISIBLE else View.GONE
        if (prev == Page.SETTINGS && p != Page.SETTINGS) settings.onHidden()
        if (p != Page.HOME) tintTo(0)
        updateBlackHoleRunning()
        if (prev != p) animatePageIn(pageViewFor(p))
        tabHome.isSelected = p == Page.HOME
        tabApps.isSelected = p == Page.APPS
        appsHint.setText(if (pickMode) R.string.pick_hint else R.string.apps_hint)
        appsHint.setTextColor(if (pickMode) Color.WHITE else Color.parseColor("#8A8F99"))
        dim.animate().alpha(if (p == Page.HOME) 0f else 0.82f).setDuration(200).start()

        if (p == Page.HELP) {
            updateHelpButtons()
            updateDefaultHomeUi()
        }
        if (p == Page.HOME) updateHomeUi()
        if (p == Page.SUB) {
            bindSub()
            refreshMe(false)
        }
        if (p == Page.APPS) refreshBadges()

        if (!moveFocus) return
        when (p) {
            Page.HOME -> btnConnect.requestFocus()
            Page.APPS -> {
                appsScroll.scrollTo(0, 0)
                val first = appsGrid.getChildAt(0)
                if (first != null) first.requestFocus() else tabApps.requestFocus()
            }
            Page.HELP -> {
                when {
                    btnInstallHapp.visibility == View.VISIBLE -> btnInstallHapp.requestFocus()
                    btnOpenHapp.visibility == View.VISIBLE -> btnOpenHapp.requestFocus()
                    else -> btnHelpBack.requestFocus()
                }
            }
            Page.PAIR -> btnPairMain.requestFocus()
            Page.SUB -> btnSubBack.requestFocus()
            Page.SETTINGS -> settings.rebuild(null)
        }
    }

    private fun openPicker() {
        pickMode = true
        showPage(Page.APPS, true)
    }

    private fun focusAddTile() {
        for (i in 0 until favRow.childCount) {
            val c = favRow.getChildAt(i)
            if (c.tag == TAG_ADD) {
                c.requestFocus()
                return
            }
        }
    }

    private fun onConnectClicked() {
        if (!session.paired) {
            openPair()
            return
        }
        connectHapp()
    }

    /** Подключиться: отдать подписку в Happ (если ещё не отдавали эту ссылку), иначе просто открыть Happ. */
    private fun connectHapp() {
        val p = happPackage ?: AppRepository.findHapp(this, apps)
        if (p == null) {
            connectAnim.play(ConnectState.FAILED)
            Toast.makeText(this, R.string.happ_missing, Toast.LENGTH_LONG).show()
            mainHandler.postDelayed({ if (!destroyed && page == Page.HOME) showPage(Page.HELP, true) }, 450L)
            return
        }
        happPackage = p
        if (!isVpnActive()) connectAnim.play(ConnectState.CONNECTING)
        val sub = session.subUrl
        if (!sub.isNullOrEmpty() && sub != session.pushedSubUrl) {
            if (Happ.pushSubscription(this, sub, p)) {
                session.pushedSubUrl = sub
                Toast.makeText(this, R.string.sub_pushed, Toast.LENGTH_LONG).show()
                return
            }
        }
        launchApp(p)
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
            if (tileMenu.visibility != View.VISIBLE) buildFavRow(null)
        }
        if (page == Page.HELP) {
            btnOpenHapp.visibility = if (happPackage != null) View.VISIBLE else View.GONE
        }
        refreshBadges()
        if (page == Page.HELP) updateHelpButtons()
        if (page == Page.PAIR && pairDone) showPairDone()
        buildRecentsRow()
    }

    /** Перестроить ряд на главной. focusPkg — какую плитку сфокусировать после. */
    private fun buildFavRow(focusPkg: String?) {
        val focused = favRow.focusedChild
        val focusedIndex = if (focused != null) favRow.indexOfChild(focused) else -1
        favRow.removeAllViews()

        val byPkg = HashMap<String, AppEntry>()
        for (a in apps) byPkg[a.packageName] = a
        for (pkg in favorites.get()) {
            val app = byPkg[pkg] ?: continue
            val tile = inflateTile(favRow)
            bindAppTile(tile, app, true)
            favRow.addView(tile)
        }
        val addTile = makeActionTile(favRow, R.drawable.ic_add, getString(R.string.tile_add)) { openPicker() }
        addTile.tag = TAG_ADD
        favRow.addView(addTile)
        favRow.addView(makeActionTile(favRow, R.drawable.ic_apps, getString(R.string.tile_all_apps)) {
            pickMode = false
            showPage(Page.APPS, true)
        })
        favRow.addView(makeActionTile(favRow, R.drawable.ic_settings, getString(R.string.tile_settings)) {
            showPage(Page.SETTINGS, true)
        })
        lastFavSig = favorites.get().joinToString("|") + "#" + lastAppsSig

        if (page != Page.HOME) return
        if (focusPkg != null) {
            for (i in 0 until favRow.childCount) {
                val c = favRow.getChildAt(i)
                if (c.tag == focusPkg) {
                    c.requestFocus()
                    return
                }
            }
        }
        if (focusedIndex >= 0) {
            val idx = minOf(focusedIndex, favRow.childCount - 1)
            favRow.getChildAt(idx)?.requestFocus()
        }
    }

    private fun buildAppsGrid() {
        val focusedTag = appsGrid.focusedChild?.tag as? String
        appsGrid.removeAllViews()
        for (app in apps) {
            val tile = inflateTile(appsGrid)
            bindAppTile(tile, app, false)
            appsGrid.addView(tile)
        }
        appsEmpty.visibility = if (apps.isEmpty()) View.VISIBLE else View.GONE
        refreshBadges()

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

    /** Галочка на плитках в сетке у приложений, которые уже на главном. */
    private fun refreshBadges() {
        val favs = HashSet(favorites.get())
        for (i in 0 until appsGrid.childCount) {
            val c = appsGrid.getChildAt(i)
            val pkg = c.tag as? String ?: continue
            val badge = c.findViewById<View>(R.id.tile_badge) ?: continue
            badge.visibility = if (favs.contains(pkg)) View.VISIBLE else View.GONE
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

    private fun bindAppTile(tile: View, app: AppEntry, inHomeRow: Boolean) {
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

        tile.setOnClickListener {
            if (!inHomeRow && pickMode) {
                pickApp(app)
            } else {
                launchApp(app.packageName)
            }
        }
        tile.setOnLongClickListener {
            onTileLongPress(app, inHomeRow)
            true
        }
        tile.setOnKeyListener { v, keyCode, event ->
            handleTileKey(v, keyCode, event) { onTileLongPress(app, inHomeRow) }
        }
        setupFocusAnim(tile, 1.08f)
    }

    /**
     * Кнопки пульта/геймпада на плитке приложения.
     * ОК (DPAD_CENTER / ENTER / NUMPAD_ENTER / геймпад A): короткое — открыть, удержание ≥0,5 с — меню.
     * Удержание ловим и по автоповтору, и по длительности при отпускании (у пультов без автоповтора).
     * «Меню» — то же, что удержание.
     */
    private fun handleTileKey(v: View, keyCode: Int, event: KeyEvent, onLong: () -> Unit): Boolean {
        if (keyCode == KeyEvent.KEYCODE_MENU) {
            if (event.action == KeyEvent.ACTION_UP) onLong()
            return true
        }
        val confirm = keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER ||
            keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER || keyCode == KeyEvent.KEYCODE_BUTTON_A
        if (!confirm) return false
        when (event.action) {
            KeyEvent.ACTION_DOWN -> {
                if (event.repeatCount == 0) {
                    longPressFired = false
                    confirmDownView = v
                } else if (!longPressFired && confirmDownView === v &&
                    event.eventTime - event.downTime >= LONG_PRESS_MS
                ) {
                    longPressFired = true
                    onLong()
                }
                return true
            }
            KeyEvent.ACTION_UP -> {
                val wasDown = confirmDownView === v
                confirmDownView = null
                if (!wasDown || event.isCanceled) return true
                if (longPressFired) {
                    longPressFired = false
                    return true
                }
                if (event.eventTime - event.downTime >= LONG_PRESS_MS) {
                    onLong()
                } else {
                    v.performClick()
                }
                return true
            }
            else -> {
                // другие действия не обрабатываем
            }
        }
        return false
    }

    private fun onTileLongPress(app: AppEntry, inHomeRow: Boolean) {
        if (inHomeRow) {
            showTileMenu(app)
        } else {
            toggleFavorite(app)
        }
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
        setupFocusAnim(tile, 1.08f)
        return tile
    }

    /** Режим «выбор»: ОК добавляет приложение на главный и возвращает туда. */
    private fun pickApp(app: AppEntry) {
        val added = favorites.add(app.packageName)
        val msg = if (added) getString(R.string.fav_added, app.label) else getString(R.string.fav_already, app.label)
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        pickMode = false
        showPage(Page.HOME, false)
        buildFavRow(app.packageName)
        refreshBadges()
    }

    private fun toggleFavorite(app: AppEntry) {
        val added = favorites.toggle(app.packageName)
        val msg = if (added) getString(R.string.fav_added, app.label) else getString(R.string.fav_removed, app.label)
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        buildFavRow(null)
        refreshBadges()
    }

    // ---------- Меню плитки на главном ----------

    private fun showTileMenu(app: AppEntry) {
        menuPkg = app.packageName
        menuTitle.text = app.label
        val list = favorites.get()
        val idx = list.indexOf(app.packageName)
        menuLeft.visibility = if (idx > 0) View.VISIBLE else View.GONE
        menuRight.visibility = if (idx >= 0 && idx < list.size - 1) View.VISIBLE else View.GONE
        tileMenu.visibility = View.VISIBLE
        var first: View = menuRemove
        if (menuRight.visibility == View.VISIBLE) first = menuRight
        if (menuLeft.visibility == View.VISIBLE) first = menuLeft
        first.requestFocus()
        // Пока меню открыто, фокус не уходит на экран под ним
        content.descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
    }

    private fun hideTileMenu(restoreFocus: Boolean) {
        if (tileMenu.visibility != View.VISIBLE) return
        tileMenu.visibility = View.GONE
        content.descendantFocusability = ViewGroup.FOCUS_AFTER_DESCENDANTS
        val pkg = menuPkg
        menuPkg = null
        if (restoreFocus && pkg != null) {
            for (i in 0 until favRow.childCount) {
                val c = favRow.getChildAt(i)
                if (c.tag == pkg) {
                    c.requestFocus()
                    return
                }
            }
        }
    }

    private fun onMenuAction(action: Int) {
        val pkg = menuPkg ?: return
        when (action) {
            MENU_LEFT, MENU_RIGHT -> {
                favorites.move(pkg, if (action == MENU_LEFT) -1 else 1)
                hideTileMenu(false)
                buildFavRow(pkg)
            }
            MENU_REMOVE -> {
                var index = -1
                for (i in 0 until favRow.childCount) {
                    if (favRow.getChildAt(i).tag == pkg) index = i
                }
                favorites.remove(pkg)
                hideTileMenu(false)
                buildFavRow(null)
                refreshBadges()
                val target = favRow.getChildAt(maxOf(0, minOf(index, favRow.childCount - 1)))
                target?.requestFocus()
            }
            else -> hideTileMenu(true)
        }
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
            if (pkg != packageName) prefs.addRecent(pkg)
        } catch (e: Exception) {
            Toast.makeText(this, R.string.launch_failed, Toast.LENGTH_SHORT).show()
        }
    }

    // ---------- Недавние, погода, входы ----------

    /** Ряд «Недавние» (до 5 последних открытых из лаунчера) и кнопка «Продолжить». */
    private fun buildRecentsRow() {
        val byPkg = HashMap<String, AppEntry>()
        for (a in apps) byPkg[a.packageName] = a
        val list = prefs.recents().mapNotNull { byPkg[it] }
        val kids = isKidsMode()
        val sig = list.joinToString("|") { it.packageName } + "#" + kids
        val first = list.firstOrNull()
        if (first != null && !kids) {
            btnContinue.text = getString(R.string.btn_continue, first.label)
            btnContinue.visibility = View.VISIBLE
        } else {
            btnContinue.visibility = View.GONE
        }
        if (sig == lastRecentsSig) return
        lastRecentsSig = sig
        val focusedTag = recentsRow.focusedChild?.tag as? String
        recentsRow.removeAllViews()
        val show = list.isNotEmpty() && !kids
        recentsLabel.visibility = if (show) View.VISIBLE else View.GONE
        recentsScroll.visibility = if (show) View.VISIBLE else View.GONE
        if (!show) return
        for (app in list) {
            val tile = inflateTile(recentsRow)
            bindAppTile(tile, app, false)
            // в «Недавних» удержание убирает из списка
            tile.setOnLongClickListener {
                removeRecent(app)
                true
            }
            tile.setOnKeyListener { v, keyCode, event ->
                handleTileKey(v, keyCode, event) { removeRecent(app) }
            }
            recentsRow.addView(tile)
        }
        recentsScroll.scrollTo(0, 0)
        if (focusedTag != null && page == Page.HOME) {
            for (i in 0 until recentsRow.childCount) {
                if (recentsRow.getChildAt(i).tag == focusedTag) recentsRow.getChildAt(i).requestFocus()
            }
        }
    }

    private fun removeRecent(app: AppEntry) {
        val idx = recentsRow.indexOfChild(recentsRow.focusedChild)
        prefs.removeRecent(app.packageName)
        Toast.makeText(this, getString(R.string.recent_removed, app.label), Toast.LENGTH_SHORT).show()
        buildRecentsRow()
        if (recentsRow.childCount > 0) {
            recentsRow.getChildAt(maxOf(0, minOf(idx, recentsRow.childCount - 1))).requestFocus()
        } else {
            favRow.getChildAt(0)?.requestFocus()
        }
    }

    /** Погода в верхней панели: кэш 30 минут, при ошибке просто скрыта. */
    private fun refreshWeather(force: Boolean) {
        val city = prefs.cityIndex
        val cached = if (force) null else Weather.cached(this, city)
        if (cached != null) {
            showWeather(city, cached)
            return
        }
        if (weatherLoading) return
        weatherLoading = true
        val ctx = applicationContext
        try {
            io.execute {
                val now = Weather.fetch(ctx, city)
                mainHandler.post {
                    weatherLoading = false
                    if (destroyed) return@post
                    if (now != null) {
                        showWeather(city, now)
                    } else if (Weather.cached(ctx, prefs.cityIndex) == null) {
                        topWeather.visibility = View.GONE
                    }
                }
            }
        } catch (e: Exception) {
            weatherLoading = false
        }
    }

    private fun showWeather(city: Int, now: Weather.Now) {
        if (city != prefs.cityIndex) return
        topWeather.text = Weather.CITIES[city].name + "  " + Weather.format(now)
        topWeather.visibility = View.VISIBLE
    }

    /** Ряд «Входы»: HDMI и другие входы телевизора, если система их отдаёт. */
    private fun refreshInputs() {
        val ctx = applicationContext
        try {
            io.execute {
                val list = TvInputs.list(ctx)
                val usable = list.isNotEmpty() && TvInputs.intentFor(list[0]).resolveActivity(ctx.packageManager) != null
                mainHandler.post { if (!destroyed) buildInputsRow(if (usable) list else emptyList()) }
            }
        } catch (e: Exception) {
            // ignore
        }
    }

    private fun buildInputsRow(list: List<TvInputs.Input>) {
        val kids = isKidsMode()
        val sig = list.joinToString("|") { it.id + ":" + it.label } + "#" + kids
        if (sig == lastInputsSig) return
        lastInputsSig = sig
        inputsRow.removeAllViews()
        val show = list.isNotEmpty() && !kids
        inputsLabel.visibility = if (show) View.VISIBLE else View.GONE
        inputsScroll.visibility = if (show) View.VISIBLE else View.GONE
        if (!show) return
        for (input in list) {
            val tile = makeActionTile(inputsRow, R.drawable.ic_input, input.label) {
                try {
                    startActivity(TvInputs.intentFor(input))
                } catch (e: Exception) {
                    Toast.makeText(this, R.string.input_failed, Toast.LENGTH_LONG).show()
                }
            }
            tile.tag = "action:input:" + input.id
            inputsRow.addView(tile)
        }
    }

    /** Детский режим (подключается отдельно). */
    private fun isKidsMode(): Boolean = false

    internal fun openSettings() {
        try {
            startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Exception) {
            Toast.makeText(this, R.string.launch_failed, Toast.LENGTH_SHORT).show()
        }
    }

    // ---------- VPN-статус ----------

    private fun registerVpnCallback() {
        val cm = connectivity ?: return
        // removeCapability(NOT_VPN) есть только с Android 6; на 5.x статус обновляется в onResume
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
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
        val active = isVpnActive()
        if (active) {
            statusDot.setBackgroundResource(R.drawable.dot_green)
            statusText.setText(R.string.status_on)
        } else {
            statusDot.setBackgroundResource(R.drawable.dot_grey)
            statusText.setText(R.string.status_off)
        }
        val prev = lastVpnActive
        lastVpnActive = active
        if (active && (prev == false || connectAnim.state == ConnectState.CONNECTING)) {
            connectAnim.play(ConnectState.CONNECTED)
        } else if (!active && connectAnim.state == ConnectState.CONNECTING && resumed) {
            connectAnim.play(ConnectState.IDLE)
        } else if (!active && connectAnim.state == ConnectState.CONNECTED) {
            connectAnim.play(ConnectState.IDLE)
        }
    }

    // ---------- Главная: вход / подписка ----------

    private fun updateHomeUi() {
        if (session.paired) {
            btnConnect.setText(R.string.btn_connect)
            btnSub.visibility = View.VISIBLE
            val me = session.me
            val line = if (me != null) subLineText(me) else null
            subLine.text = line ?: ""
            subLine.visibility = if (line != null) View.VISIBLE else View.GONE
        } else {
            btnConnect.setText(R.string.btn_login)
            btnSub.visibility = View.GONE
            subLine.visibility = View.GONE
        }
    }

    private fun subLineText(me: JSONObject): String? {
        val status = me.optString("status", "")
        val days = me.optInt("days_left", 0)
        val date = formatDate(me.optString("expire_at", ""))
        return when {
            status == "ACTIVE" && date != null -> getString(R.string.sub_line, date, days)
            status.isNotEmpty() && status != "ACTIVE" -> getString(R.string.sub_line_expired)
            else -> null
        }
    }

    /** Обновить данные подписки с сервера (не чаще раза в 5 минут, если не force). Ошибки — молча. */
    private fun refreshMe(force: Boolean) {
        val token = session.token ?: return
        if (meLoading) return
        if (!force && System.currentTimeMillis() - session.meAt < ME_INTERVAL_MS) return
        meLoading = true
        try {
            io.execute {
                val r = Api.me(token)
                mainHandler.post {
                    meLoading = false
                    if (destroyed || session.token != token) return@post
                    when {
                        r.code == 401 -> {
                            session.clear()
                            Toast.makeText(this, R.string.unpaired, Toast.LENGTH_LONG).show()
                            if (page == Page.SUB) showPage(Page.HOME, true) else updateHomeUi()
                        }
                        r.ok -> {
                            session.saveMe(r.json!!)
                            updateHomeUi()
                            if (page == Page.SUB) bindSub()
                        }
                        force -> Toast.makeText(this, R.string.me_failed, Toast.LENGTH_SHORT).show()
                    }
                }
            }
        } catch (e: Exception) {
            meLoading = false
        }
    }

    // ---------- Экран «Подписка» ----------

    private fun bindSub() {
        val me = session.me
        if (me == null) {
            subPlan.setText(R.string.plan_regular)
            subDays.setText(R.string.dash)
            subDaysLabel.setText(R.string.days_left_many)
            subUntil.setText(R.string.me_loading)
            subDevices.text = ""
            subProgress.progress = 0
            subDeviceName.text = ""
            return
        }
        val status = me.optString("status", "")
        val days = me.optInt("days_left", 0)
        subPlan.setText(
            when {
                status == "NONE" -> R.string.plan_none
                me.optBoolean("family", false) -> R.string.plan_family
                else -> R.string.plan_regular
            }
        )
        subDays.text = days.toString()
        subDaysLabel.setText(
            when {
                days % 100 in 11..14 -> R.string.days_left_many
                days % 10 == 1 -> R.string.days_left_one
                days % 10 in 2..4 -> R.string.days_left_few
                else -> R.string.days_left_many
            }
        )
        val date = formatDate(me.optString("expire_at", ""))
        subUntil.text = if (status == "ACTIVE" && date != null) getString(R.string.sub_until, date)
        else getString(R.string.sub_expired)
        val used = me.optInt("devices_used", 0)
        val limit = me.optInt("device_limit", 0)
        subDevices.text = if (limit > 0) getString(R.string.devices_of, used, limit) else ""
        subProgress.progress = if (limit > 0) minOf(100, used * 100 / limit) else 0
        val name = me.optString("device_name", "")
        subDeviceName.text = if (name.isNotEmpty() && name != "null") getString(R.string.this_device, name) else ""
    }

    private fun onUnpairClicked() {
        if (!unpairArmed) {
            unpairArmed = true
            btnSubUnpair.setText(R.string.unpair_confirm)
            mainHandler.postDelayed({ disarmUnpair() }, 4000L)
            return
        }
        disarmUnpair()
        val token = session.token
        session.clear()
        if (token != null) {
            try {
                io.execute { Api.unpair(token) }
            } catch (e: Exception) {
                // ignore
            }
        }
        Toast.makeText(this, R.string.unpaired, Toast.LENGTH_LONG).show()
        showPage(Page.HOME, true)
    }

    private fun disarmUnpair() {
        if (!unpairArmed) return
        unpairArmed = false
        btnSubUnpair.setText(R.string.btn_unpair)
    }

    // ---------- Вход через Telegram ----------

    private fun openPair() {
        pairDone = false
        pairToken = null
        showPairForm()
        showPage(Page.PAIR, true)
        startPairing()
    }

    private fun showPairForm() {
        pairTitle.setText(R.string.pair_title)
        pairSubtitle.setText(R.string.pair_subtitle)
        pairForm.visibility = View.VISIBLE
        btnPairMain.setText(R.string.btn_new_code)
        pairCodeView.setText(R.string.pair_code_placeholder)
        pairQr.setImageDrawable(null)
        setPairStatus(R.string.pair_loading, R.drawable.dot_yellow)
    }

    private fun setPairStatus(text: Int, dot: Int) {
        pairStatus.setText(text)
        pairDot.setBackgroundResource(dot)
    }

    private fun stopPairing() {
        pairGen++
        pairToken = null
    }

    private fun startPairing() {
        val gen = ++pairGen
        pairToken = null
        setPairStatus(R.string.pair_loading, R.drawable.dot_yellow)
        val name = deviceName()
        try {
            io.execute {
                val r = Api.pairStart(name)
                mainHandler.post {
                    if (destroyed || gen != pairGen || page != Page.PAIR) return@post
                    val j = r.json
                    if (r.ok && j != null && j.optString("token").isNotEmpty()) {
                        pairToken = j.optString("token")
                        val code = j.optString("code")
                        pairCodeView.text = if (code.length == 6) code.substring(0, 3) + " " + code.substring(3) else code
                        setQr(pairQr, j.optString("bot_link"), dp(148))
                        setPairStatus(R.string.pair_wait, R.drawable.dot_yellow)
                        schedulePoll(gen, POLL_MS)
                    } else if (r.code == 429) {
                        setPairStatus(R.string.pair_too_many, R.drawable.dot_red)
                        mainHandler.postDelayed({ if (gen == pairGen && page == Page.PAIR && resumed) startPairing() }, 60_000L)
                    } else {
                        setPairStatus(R.string.pair_no_net, R.drawable.dot_red)
                        mainHandler.postDelayed({ if (gen == pairGen && page == Page.PAIR && resumed) startPairing() }, 5_000L)
                    }
                }
            }
        } catch (e: Exception) {
            // executor остановлен
        }
    }

    private fun schedulePoll(gen: Int, delay: Long) {
        mainHandler.postDelayed({ pollPairing(gen) }, delay)
    }

    private fun pollPairing(gen: Int) {
        val token = pairToken ?: return
        if (destroyed || gen != pairGen || page != Page.PAIR || pairDone) return
        if (!resumed) return  // вернёмся — onResume продолжит опрос
        try {
            io.execute {
                val r = Api.pairStatus(token)
                mainHandler.post {
                    if (destroyed || gen != pairGen || page != Page.PAIR || pairDone) return@post
                    val j = r.json
                    val status = if (r.ok && j != null) j.optString("status") else ""
                    when (status) {
                        "confirmed" -> onPaired(token, j!!.optString("sub_url", ""))
                        "expired" -> startPairing()
                        "pending" -> {
                            setPairStatus(R.string.pair_wait, R.drawable.dot_yellow)
                            schedulePoll(gen, POLL_MS)
                        }
                        else -> {
                            setPairStatus(R.string.pair_no_net, R.drawable.dot_red)
                            schedulePoll(gen, POLL_MS)
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // executor остановлен
        }
    }

    private fun onPaired(token: String, subUrl: String) {
        pairDone = true
        pairGen++
        pairToken = null
        val sub = if (subUrl.isEmpty() || subUrl == "null") null else subUrl
        session.save(token, sub)
        showPairDone()
        btnPairMain.requestFocus()
        refreshMe(true)
        // Даём увидеть «Телевизор подключён», потом отдаём подписку в Happ
        val happ = happPackage ?: AppRepository.findHapp(this, apps)
        if (happ != null && sub != null) {
            happPackage = happ
            mainHandler.postDelayed({
                if (!destroyed && session.subUrl == sub && session.pushedSubUrl != sub && page == Page.PAIR) {
                    if (Happ.pushSubscription(this, sub, happ)) session.pushedSubUrl = sub
                }
            }, 1500L)
        }
    }

    private fun showPairDone() {
        val happ = happPackage ?: AppRepository.findHapp(this, apps)
        pairTitle.setText(R.string.pair_done_title)
        pairSubtitle.text = if (happ != null) getString(R.string.pair_done_subtitle, getString(R.string.app_name))
        else getString(R.string.pair_done_no_happ)
        pairForm.visibility = View.GONE
        btnPairMain.setText(if (happ != null) R.string.btn_connect else R.string.btn_install_happ)
    }

    private fun onPairMainClicked() {
        if (!pairDone) {
            startPairing()
            return
        }
        val happ = happPackage ?: AppRepository.findHapp(this, apps)
        if (happ != null) {
            connectHapp()
        } else {
            showPage(Page.HELP, true)
            installHapp()
        }
    }

    private fun deviceName(): String {
        val manufacturer = (Build.MANUFACTURER ?: "").trim()
        val model = (Build.MODEL ?: "").trim()
        val name = if (model.startsWith(manufacturer, ignoreCase = true)) model else "$manufacturer $model"
        return name.trim().replaceFirstChar { it.uppercase() }.take(48).ifEmpty { "Android TV" }
    }

    // ---------- Установка Happ ----------

    private fun updateHelpButtons() {
        if (happPackage == null) happPackage = AppRepository.findHapp(this, apps)
        val has = happPackage != null
        btnOpenHapp.visibility = if (has) View.VISIBLE else View.GONE
        btnInstallHapp.visibility = if (has) View.GONE else View.VISIBLE
        if (has && !downloading) helpStatus.visibility = View.GONE
    }

    private fun setHelpStatus(text: String) {
        helpStatus.text = text
        helpStatus.visibility = View.VISIBLE
    }

    private fun installHapp() {
        if (downloading) return
        if (!Happ.canInstall(this)) {
            if (Happ.openInstallPermission(this)) {
                setHelpStatus(getString(R.string.happ_allow_install))
                Toast.makeText(this, R.string.happ_allow_install, Toast.LENGTH_LONG).show()
                return
            }
        }
        downloading = true
        setHelpStatus(getString(R.string.happ_download_start))
        val ctx = applicationContext
        try {
            io.execute {
                val file = Happ.download(ctx) { p ->
                    mainHandler.post { if (!destroyed) setHelpStatus(getString(R.string.happ_downloading, p)) }
                }
                mainHandler.post {
                    downloading = false
                    if (destroyed) return@post
                    if (file == null) {
                        setHelpStatus(getString(R.string.happ_download_failed))
                        Happ.openInBrowser(this, Api.happApkUrl())
                    } else if (Happ.install(this, file)) {
                        setHelpStatus(getString(R.string.happ_installing))
                    } else {
                        setHelpStatus(getString(R.string.happ_download_failed))
                    }
                }
            }
        } catch (e: Exception) {
            downloading = false
        }
    }

    private fun formatDate(iso: String): String? {
        if (iso.length < 19 || iso == "null") return null
        return try {
            val f = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
            f.timeZone = TimeZone.getTimeZone("UTC")
            val d = f.parse(iso.substring(0, 19)) ?: return null
            val c = Calendar.getInstance()
            c.time = d
            c.get(Calendar.DAY_OF_MONTH).toString() + " " + MONTHS[c.get(Calendar.MONTH)]
        } catch (e: Exception) {
            null
        }
    }

    private fun applyTitleGradient(t: TextView) {
        val w = t.paint.measureText(t.text.toString())
        t.paint.shader = LinearGradient(0f, 0f, w, 0f, Color.WHITE, Color.parseColor("#AAB3C5"), Shader.TileMode.CLAMP)
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

    internal fun setupFocusAnim(v: View, scale: Float) {
        v.setOnFocusChangeListener { view, hasFocus ->
            val sc = if (hasFocus) scale else 1f
            val z = if (hasFocus) dp(8).toFloat() else 0f
            if (prefs.animations) {
                view.animate()
                    .scaleX(sc)
                    .scaleY(sc)
                    .translationZ(z)
                    .setInterpolator(focusInterpolator)
                    .setDuration(180)
                    .start()
            } else {
                view.animate().cancel()
                view.scaleX = sc
                view.scaleY = sc
                view.translationZ = z
            }
        }
    }

    // ---------- Анимации, фон, настройки ----------

    /** Применить настройку «Анимации» (и автоматическое выключение на слабых ТВ). */
    internal fun applyAnimationsSetting() {
        blackHole.setAnimationsEnabled(prefs.animations)
        if (!prefs.animations) {
            connectAnim.play(ConnectState.IDLE)
            tintAnimator?.cancel()
        }
        updateBlackHoleRunning()
    }

    private fun updateBlackHoleRunning() {
        blackHole.setRunning(resumed && page == Page.HOME && !destroyed && idleView == null)
    }

    private fun pageViewFor(p: Page): View = when (p) {
        Page.HOME -> pageHome
        Page.APPS -> pageApps
        Page.HELP -> pageHelp
        Page.PAIR -> pagePair
        Page.SUB -> pageSub
        Page.SETTINGS -> settings.page
    }

    /** Смена экрана: мягкое появление со сдвигом снизу, 200 мс. */
    private fun animatePageIn(v: View) {
        if (!prefs.animations) {
            v.alpha = 1f
            v.translationY = 0f
            return
        }
        v.alpha = 0f
        v.translationY = dp(14).toFloat()
        v.animate().alpha(1f).translationY(0f).setDuration(200).setInterpolator(focusInterpolator).start()
    }

    /** Фокус на плитке приложения на главной → фон плавно окрашивается в её цвет. */
    private fun onFocusMoved(v: View?) {
        if (destroyed || page != Page.HOME || v == null) return
        if (isInside(v, homeHero) || isInside(v, topBar)) homeScroll.smoothScrollTo(0, 0)
        val pkg = v.tag as? String
        if (pkg == null || pkg.startsWith("action:")) {
            tintTo(0)
            return
        }
        val cached = tintCache[pkg]
        if (cached != null) {
            tintTo(cached)
            return
        }
        val d = visualCache[pkg]?.drawable
        if (d == null) {
            tintTo(0)
            return
        }
        val dom = ColorUtil.dominant(d)
        val color = if (dom != null) Color.argb(0x55, Color.red(dom), Color.green(dom), Color.blue(dom)) else 0
        tintCache[pkg] = color
        tintTo(color)
    }

    private fun isInside(v: View, parent: View): Boolean {
        var cur: View? = v
        while (cur != null) {
            if (cur === parent) return true
            cur = cur.parent as? View
        }
        return false
    }

    private fun tintTo(color: Int) {
        if (color == tintTarget) return
        tintTarget = color
        tintAnimator?.cancel()
        if (!prefs.animations) {
            tintCurrent = color
            bgTint.setBackgroundColor(color)
            return
        }
        val va = ValueAnimator.ofObject(ArgbEvaluator(), tintCurrent, color)
        va.duration = 700
        va.addUpdateListener { anim ->
            tintCurrent = anim.animatedValue as Int
            bgTint.setBackgroundColor(tintCurrent)
        }
        va.start()
        tintAnimator = va
    }

    internal fun onIdleSettingChanged() {
        lastInputAt = System.currentTimeMillis()
    }

    // ---------- Заставка при простое ----------

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        lastInputAt = System.currentTimeMillis()
        if (idleView != null) {
            // любая кнопка только убирает заставку
            if (event.action == KeyEvent.ACTION_DOWN) {
                swallowKeyUp = event.keyCode
                hideIdle()
            }
            return true
        }
        if (swallowKeyUp != -1 && event.keyCode == swallowKeyUp) {
            // повторы и отпускание кнопки, которой разбудили, тоже съедаем
            if (event.action == KeyEvent.ACTION_UP) swallowKeyUp = -1
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    /** Экран выбора системной заставки (если есть на устройстве). */
    internal fun openDreamSettings() {
        val i = Intent(Settings.ACTION_DREAM_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            if (i.resolveActivity(packageManager) != null) {
                startActivity(i)
                return
            }
        } catch (e: Exception) {
            // нет такого экрана
        }
        openSettings()
    }

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        lastInputAt = System.currentTimeMillis()
        if (idleView != null) {
            if (ev.actionMasked == MotionEvent.ACTION_DOWN) hideIdle()
            return true
        }
        return super.dispatchTouchEvent(ev)
    }

    override fun dispatchGenericMotionEvent(ev: MotionEvent): Boolean {
        lastInputAt = System.currentTimeMillis()
        if (idleView != null) {
            hideIdle()
            return true
        }
        return super.dispatchGenericMotionEvent(ev)
    }

    private fun checkIdle() {
        val min = prefs.idleMinutes
        if (min <= 0 || !resumed || idleView != null) return
        if (page != Page.HOME || tileMenu.visibility == View.VISIBLE || choiceDialog.isShowing) return
        if (System.currentTimeMillis() - lastInputAt >= min * 60_000L) showIdle()
    }

    private fun showIdle() {
        if (idleView != null) return
        val root = findViewById<ViewGroup>(R.id.root)
        val v = layoutInflater.inflate(R.layout.screensaver, root, false)
        v.alpha = 0f
        root.addView(v)
        idleView = v
        val c = ScreensaverController(v, prefs.animations)
        idleController = c
        c.start()
        v.animate().alpha(1f).setDuration(if (prefs.animations) 800L else 0L).start()
        v.requestFocus()
        updateBlackHoleRunning()
    }

    private fun hideIdle() {
        val v = idleView ?: return
        idleView = null
        idleController?.stop()
        idleController = null
        (v.parent as? ViewGroup)?.removeView(v)
        lastInputAt = System.currentTimeMillis()
        updateBlackHoleRunning()
        if (page == Page.HOME && !btnConnect.hasFocus() && currentFocus == null) btnConnect.requestFocus()
    }

    internal fun onCitySettingChanged() {
        topWeather.visibility = View.GONE
        refreshWeather(true)
    }

    internal fun addKidsSettingRow(screen: SettingsScreen) {
        // детский режим — подключается отдельно
    }

    /** «Отвязать телевизор» из настроек (то же, что на экране «Подписка»). */
    internal fun unpairFromSettings() {
        val token = session.token
        session.clear()
        if (token != null) {
            try {
                io.execute { Api.unpair(token) }
            } catch (e: Exception) {
                // ignore
            }
        }
        Toast.makeText(this, R.string.unpaired, Toast.LENGTH_LONG).show()
        updateHomeUi()
        showPage(Page.HOME, true)
    }

    /**
     * QR: 1 модуль = целое число пикселей, без сглаживания — чётко на любом экране.
     */
    /** QR произвольного текста (вход, продление): целый масштаб модулей, без размытия. */
    private fun setQr(view: ImageView, text: String, sizePx: Int) {
        try {
            val hints = HashMap<EncodeHintType, Any>()
            hints[EncodeHintType.MARGIN] = 1
            hints[EncodeHintType.ERROR_CORRECTION] = ErrorCorrectionLevel.M
            hints[EncodeHintType.CHARACTER_SET] = "UTF-8"
            val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0, hints)
            val modules = matrix.width
            val scale = maxOf(1, sizePx / modules)
            val side = modules * scale
            val pixels = IntArray(side * side)
            for (y in 0 until side) {
                val my = y / scale
                val row = y * side
                for (x in 0 until side) {
                    pixels[row + x] = if (matrix.get(x / scale, my)) Color.BLACK else Color.WHITE
                }
            }
            val drawable = BitmapDrawable(resources, Bitmap.createBitmap(pixels, side, side, Bitmap.Config.ARGB_8888))
            drawable.setFilterBitmap(false)
            drawable.setAntiAlias(false)
            view.setImageDrawable(drawable)
        } catch (e: Exception) {
            view.setImageDrawable(null)
        }
    }

    private fun renderQr(view: ImageView, sizePx: Int) {
        try {
            val hints = HashMap<EncodeHintType, Any>()
            hints[EncodeHintType.MARGIN] = 1
            hints[EncodeHintType.ERROR_CORRECTION] = ErrorCorrectionLevel.M
            hints[EncodeHintType.CHARACTER_SET] = "UTF-8"
            // размер 0 → матрица «1 пиксель на модуль»
            val matrix = QRCodeWriter().encode(BOT_LINK, BarcodeFormat.QR_CODE, 0, 0, hints)
            val modules = matrix.width
            val scale = maxOf(1, sizePx / modules)
            val side = modules * scale
            val pixels = IntArray(side * side)
            for (my in 0 until modules) {
                for (mx in 0 until modules) {
                    val color = if (matrix.get(mx, my)) Color.BLACK else Color.WHITE
                    val baseY = my * scale
                    val baseX = mx * scale
                    for (dy in 0 until scale) {
                        val row = (baseY + dy) * side + baseX
                        for (dx in 0 until scale) {
                            pixels[row + dx] = color
                        }
                    }
                }
            }
            val bmp = Bitmap.createBitmap(pixels, side, side, Bitmap.Config.ARGB_8888)
            val drawable = BitmapDrawable(resources, bmp)
            drawable.setFilterBitmap(false)
            drawable.setAntiAlias(false)
            view.setImageDrawable(drawable)
        } catch (e: Exception) {
            Log.w(TAG, "QR failed", e)
        }
    }

    @Suppress("DEPRECATION")
    private fun logDisplayMetrics(): DisplayMetrics {
        val real = DisplayMetrics()
        try {
            windowManager.defaultDisplay.getRealMetrics(real)
        } catch (e: Exception) {
            real.setTo(resources.displayMetrics)
        }
        val dm = resources.displayMetrics
        var mode = "?"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val m = windowManager.defaultDisplay.mode
                mode = "${m.physicalWidth}x${m.physicalHeight}@${m.refreshRate}"
            } catch (e: Exception) {
                // ignore
            }
        }
        Log.i(
            TAG,
            "display real=${real.widthPixels}x${real.heightPixels} densityDpi=${real.densityDpi} " +
                "density=${dm.density} logical=${(dm.widthPixels / dm.density).toInt()}x${(dm.heightPixels / dm.density).toInt()}dp " +
                "scaledDensity=${dm.scaledDensity} mode=$mode"
        )
        return real
    }

    /**
     * Фон 3840×2160 без масштабирования ресурсов (inScaled=false). Если экран меньше
     * хотя бы в 2 раза — уменьшаем через inSampleSize; увеличивать никогда не увеличиваем.
     */
    private fun loadHeroBackground(screenW: Int, screenH: Int) {
        val res = resources
        var sw = if (screenW > 0) screenW else 1920
        var sh = if (screenH > 0) screenH else 1080
        // Слабые приставки: фон не больше 1280×720
        val lowRam = isLowMemoryDevice()
        if (lowRam) {
            sw = minOf(sw, 1280)
            sh = minOf(sh, 720)
        }
        try {
            io.execute {
                var bmp: Bitmap? = null
                try {
                    val bounds = BitmapFactory.Options()
                    bounds.inJustDecodeBounds = true
                    bounds.inScaled = false
                    BitmapFactory.decodeResource(res, R.drawable.hero_bg, bounds)
                    var sample = 1
                    while (bounds.outWidth / (sample * 2) >= sw && bounds.outHeight / (sample * 2) >= sh) {
                        sample *= 2
                    }
                    val opts = BitmapFactory.Options()
                    opts.inScaled = false
                    opts.inPreferredConfig = Bitmap.Config.ARGB_8888
                    opts.inSampleSize = sample
                    bmp = BitmapFactory.decodeResource(res, R.drawable.hero_bg, opts)
                    val decoded = bmp
                    if (lowRam && decoded != null && decoded.width > sw * 5 / 4) {
                        val th = decoded.height * sw / decoded.width
                        val scaled = Bitmap.createScaledBitmap(decoded, sw, th, true)
                        if (scaled != decoded) decoded.recycle()
                        bmp = scaled
                    }
                    Log.i(TAG, "lowRam=$lowRam hero ${bounds.outWidth}x${bounds.outHeight} sample=$sample -> ${bmp?.width}x${bmp?.height}")
                } catch (e: OutOfMemoryError) {
                    Log.w(TAG, "hero OOM, fallback to sample=2")
                    try {
                        val opts = BitmapFactory.Options()
                        opts.inScaled = false
                        opts.inSampleSize = 2
                        bmp = BitmapFactory.decodeResource(res, R.drawable.hero_bg, opts)
                    } catch (e2: Throwable) {
                        bmp = null
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "hero decode failed", e)
                }
                val result = bmp
                if (result != null) {
                    mainHandler.post {
                        if (!destroyed) {
                            val d = BitmapDrawable(res, result)
                            d.setFilterBitmap(true)
                            heroBg.setImageDrawable(d)
                            // тот же битмап — фон экранов «Вход через Telegram» и «Подписка» (без второй копии в памяти)
                            for (id in intArrayOf(R.id.pair_hero, R.id.sub_hero)) {
                                val extra = BitmapDrawable(res, result)
                                extra.setFilterBitmap(true)
                                findViewById<ImageView>(id).setImageDrawable(extra)
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // executor уже остановлен
        }
    }

    private fun isLowMemoryDevice(): Boolean {
        return try {
            val am = getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return false
            am.isLowRamDevice || am.memoryClass < 128
        } catch (e: Exception) {
            false
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    companion object {
        private const val TAG = "WhiteHole"
        private const val TAG_ADD = "action:add"
        private const val LONG_PRESS_MS = 500L
        private const val MENU_LEFT = 1
        private const val MENU_RIGHT = 2
        private const val MENU_REMOVE = 3
        private const val MENU_CANCEL = 4
        private const val BOT_LINK = "https://t.me/WhiteHoleVPNbot?start=src_tv"
        private const val POLL_MS = 3_000L
        private const val ME_INTERVAL_MS = 5 * 60_000L
        private val MONTHS = arrayOf(
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        )
    }
}
