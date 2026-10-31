package space.whitehole.tv

import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/** Экран «Настройки» внутри лаунчера (плитка-шестерёнка). Строки пересобираются при каждом показе. */
class SettingsScreen(private val a: MainActivity, val page: View) {

    private val list: LinearLayout = page.findViewById(R.id.settings_list)
    private val handler = Handler(Looper.getMainLooper())
    private var unpairArmed = false
    private val disarm = Runnable {
        unpairArmed = false
        rebuild(null)
    }

    /** Пересобрать строки; focusKey — какую строку сфокусировать (или первую). */
    fun rebuild(focusKey: String?) {
        val prevFocus = focusKey ?: (list.findFocus()?.tag as? String)
        list.removeAllViews()
        val prefs = a.prefs

        add("anim", a.getString(R.string.set_animations), a.getString(if (prefs.animations) R.string.on else R.string.off)) {
            prefs.animations = !prefs.animations
            a.applyAnimationsSetting()
            rebuild("anim")
        }
        val idle = prefs.idleMinutes
        add("idle", a.getString(R.string.set_idle), idleText(idle)) {
            val choices = Prefs.IDLE_CHOICES
            val labels = choices.map { idleText(it) }
            a.choiceDialog.show(a.getString(R.string.choose_idle), labels, choices.indexOf(idle)) { i ->
                prefs.idleMinutes = choices[i]
                a.onIdleSettingChanged()
                rebuild("idle")
            }
        }
        add("city", a.getString(R.string.set_city), Weather.CITIES[prefs.cityIndex].name) {
            val labels = Weather.CITIES.map { it.name }
            a.choiceDialog.show(a.getString(R.string.choose_city), labels, prefs.cityIndex) { i ->
                prefs.cityIndex = i
                a.onCitySettingChanged()
                rebuild("city")
            }
        }
        a.addKidsSettingRow(this)
        space.whitehole.tv.vpn.VpnSettingsRows.add(this, a) // встроенный VPN
        if (!a.isDefaultHome()) {
            add("home", a.getString(R.string.set_make_home), "") { a.openHomeSettings() }
        }
        add("dream", a.getString(R.string.set_dream), a.getString(R.string.set_dream_value)) { a.openDreamSettings() }
        add("system", a.getString(R.string.set_system), "") { a.openSettings() }
        if (a.session.paired) {
            add("unpair", a.getString(R.string.set_unpair), if (unpairArmed) a.getString(R.string.set_unpair_confirm) else "") {
                if (!unpairArmed) {
                    unpairArmed = true
                    handler.removeCallbacks(disarm)
                    handler.postDelayed(disarm, 4000L)
                    rebuild("unpair")
                } else {
                    unpairArmed = false
                    handler.removeCallbacks(disarm)
                    a.unpairFromSettings()
                }
            }
        }
        val about = add("about", a.getString(R.string.set_about), a.getString(R.string.about_value, BuildConfig.VERSION_NAME), null)
        about.isFocusable = false

        var target: View? = null
        if (prevFocus != null) {
            for (i in 0 until list.childCount) {
                if (list.getChildAt(i).tag == prevFocus) target = list.getChildAt(i)
            }
        }
        if (target == null) target = list.getChildAt(0)
        target?.requestFocus()
    }

    fun add(key: String, title: String, value: String, onClick: (() -> Unit)?): View {
        val row = LayoutInflater.from(a).inflate(R.layout.item_setting, list, false)
        row.tag = key
        row.findViewById<TextView>(R.id.setting_title).text = title
        row.findViewById<TextView>(R.id.setting_value).text = value
        if (onClick != null) row.setOnClickListener { onClick() }
        a.setupFocusAnim(row, 1.02f)
        list.addView(row)
        return row
    }

    fun onHidden() {
        handler.removeCallbacks(disarm)
        unpairArmed = false
    }

    private fun idleText(min: Int): String =
        if (min <= 0) a.getString(R.string.off) else a.getString(R.string.idle_min, min)
}
