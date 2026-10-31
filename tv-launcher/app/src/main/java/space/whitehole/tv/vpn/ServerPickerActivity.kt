package space.whitehole.tv.vpn

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import space.whitehole.tv.R
import space.whitehole.tv.Session
import space.whitehole.tv.UiScale
import java.util.concurrent.Executors

/** Экран «Сервер»: Авто, страны, внизу резервные. Выбор запоминается; при включённом VPN — переподключение. */
class ServerPickerActivity : Activity() {

    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var list: LinearLayout
    private lateinit var status: TextView
    private var destroyed = false

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        UiScale.overrideFor(newBase)?.let {
            try {
                applyOverrideConfiguration(it)
            } catch (e: Exception) {
                // ignore
            }
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#FF07090D"))
            setPadding(dp(64), dp(40), dp(64), dp(24))
            clipChildren = false
            clipToPadding = false
        }
        root.addView(TextView(this).apply {
            setText(R.string.vpn_servers_title)
            setTextColor(Color.WHITE)
            textSize = 34f
            typeface = Typeface.DEFAULT_BOLD
        })
        root.addView(TextView(this).apply {
            setText(R.string.vpn_servers_hint)
            setTextColor(getColor(R.color.text_secondary))
            textSize = 15f
            setPadding(0, dp(6), 0, dp(14))
        })
        status = TextView(this).apply {
            setTextColor(getColor(R.color.text_muted))
            textSize = 15f
            visibility = View.GONE
        }
        root.addView(status)
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            clipChildren = false
            clipToPadding = false
            setPadding(dp(8), dp(4), dp(8), dp(16))
        }
        val scroll = ScrollView(this).apply {
            isFillViewport = false
            clipChildren = false
            clipToPadding = false
            addView(list)
        }
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        load(false)
    }

    override fun onDestroy() {
        destroyed = true
        io.shutdownNow()
        super.onDestroy()
    }

    private fun load(force: Boolean) {
        val sub = Session(this).subUrl
        if (sub.isNullOrEmpty()) {
            showStatus(getString(R.string.vpn_err_no_sub_url))
            render(emptyList())
            return
        }
        // сразу показываем кэш, потом обновляем
        val cached = SubscriptionStore.cached(this, sub)?.let { ServerCatalog.build(ShareLinkParser.parseSubscription(it.first)) }
        if (!cached.isNullOrEmpty()) render(cached) else showStatus(getString(R.string.vpn_servers_loading))
        val ctx = applicationContext
        io.execute {
            val r = SubscriptionStore.load(ctx, sub, if (force || cached.isNullOrEmpty()) 0 else SubscriptionStore.MAX_AGE_MS)
            val entries = ServerCatalog.build(r.links)
            main.post {
                if (destroyed) return@post
                if (entries.isNotEmpty()) {
                    status.visibility = View.GONE
                    render(entries)
                } else if (cached.isNullOrEmpty()) {
                    showStatus(
                        getString(
                            if (r.error == SubError.DEVICE_LIMIT || r.error == SubError.HWID_REQUIRED) R.string.vpn_err_devices
                            else R.string.vpn_servers_failed
                        )
                    )
                    render(emptyList())
                }
            }
        }
    }

    private fun showStatus(text: String) {
        status.text = text
        status.visibility = View.VISIBLE
    }

    private fun render(entries: List<ServerEntry>) {
        val selected = VpnFiles.serverKey(this)
        list.removeAllViews()
        var focus: View? = null
        // «Авто» есть всегда (если в подписке нет такого хоста — подключимся к первому серверу)
        if (entries.none { it.isAuto }) {
            val v = addItem(ServerCatalog.AUTO_NAME, ServerCatalog.AUTO_KEY, selected.isEmpty())
            if (selected.isEmpty()) focus = v
        }
        var reserveHeader = false
        for (e in entries) {
            if (e.isReserve && !reserveHeader) {
                reserveHeader = true
                list.addView(TextView(this).apply {
                    setText(R.string.vpn_servers_reserve)
                    setTextColor(getColor(R.color.text_muted))
                    textSize = 13f
                    isAllCaps = true
                    setPadding(dp(4), dp(18), 0, dp(4))
                })
            }
            val key = if (e.isAuto) ServerCatalog.AUTO_KEY else e.key
            val isSel = if (e.isAuto) selected.isEmpty() else selected == e.key
            val v = addItem(e.name, key, isSel)
            if (isSel) focus = v
        }
        val retry = makeButton(getString(R.string.vpn_servers_retry), false)
        retry.setOnClickListener { load(true) }
        (retry.layoutParams as LinearLayout.LayoutParams).topMargin = dp(22)
        list.addView(retry)
        (focus ?: list.getChildAt(0))?.requestFocus()
    }

    private fun makeButton(text: String, selected: Boolean): TextView {
        val b = TextView(this, null, 0, R.style.WhButton)
        b.text = if (selected) "$text   ✓" else text
        b.gravity = Gravity.CENTER_VERTICAL or Gravity.START
        b.minWidth = dp(360)
        if (selected) b.setTypeface(b.typeface, Typeface.BOLD)
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.topMargin = dp(10)
        b.layoutParams = lp
        b.setOnFocusChangeListener { v, has ->
            val s = if (has) 1.04f else 1f
            v.animate().scaleX(s).scaleY(s).setDuration(120).start()
        }
        return b
    }

    private fun addItem(name: String, key: String, selected: Boolean): View {
        val b = makeButton(name, selected)
        b.setOnClickListener {
            val changed = key != VpnFiles.serverKey(this)
            VpnFiles.setServer(this, key, name)
            if (changed) VpnController.applyServerChange(this, Session(this))
            finish()
        }
        list.addView(b)
        return b
    }
}
