package space.whitehole.tv

import android.app.ActivityManager
import android.content.Context

/** Настройки лаунчера (экран «Настройки» внутри WhiteHole). */
class Prefs(context: Context) {
    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences("whitehole_settings", Context.MODE_PRIVATE)

    /** Анимации: по умолчанию выключены на слабых устройствах. */
    var animations: Boolean
        get() = prefs.getBoolean(KEY_ANIM, !Perf.isLowEnd(app))
        set(v) {
            prefs.edit().putBoolean(KEY_ANIM, v).apply()
        }

    /** Заставка при простое на главной: 0 — выкл, иначе минуты. */
    var idleMinutes: Int
        get() = prefs.getInt(KEY_IDLE, 10)
        set(v) {
            prefs.edit().putInt(KEY_IDLE, v).apply()
        }

    /** Индекс города для погоды в [Weather.CITIES]. */
    var cityIndex: Int
        get() = prefs.getInt(KEY_CITY, 0).coerceIn(0, Weather.CITIES.size - 1)
        set(v) {
            prefs.edit().putInt(KEY_CITY, v).apply()
        }

    /** Последние открытые из лаунчера приложения (первое — самое свежее). */
    fun recents(): List<String> {
        val raw = prefs.getString(KEY_RECENTS, null) ?: return emptyList()
        return raw.split('\n').filter { it.isNotBlank() }
    }

    fun addRecent(pkg: String) {
        val list = recents().toMutableList()
        list.remove(pkg)
        list.add(0, pkg)
        while (list.size > MAX_RECENTS) list.removeAt(list.size - 1)
        prefs.edit().putString(KEY_RECENTS, list.joinToString("\n")).apply()
    }

    fun removeRecent(pkg: String) {
        val list = recents().toMutableList()
        if (list.remove(pkg)) prefs.edit().putString(KEY_RECENTS, list.joinToString("\n")).apply()
    }

    /** Когда скрыли напоминание о продлении (мс). */
    var renewDismissedAt: Long
        get() = prefs.getLong(KEY_RENEW, 0L)
        set(v) {
            prefs.edit().putLong(KEY_RENEW, v).apply()
        }

    // ---------- детский режим ----------

    var kidsEnabled: Boolean
        get() = prefs.getBoolean(KEY_KIDS, false)
        set(v) {
            prefs.edit().putBoolean(KEY_KIDS, v).apply()
        }

    /** PIN хранится как sha-256 (не в открытом виде). */
    val hasPin: Boolean get() = !prefs.getString(KEY_PIN, null).isNullOrEmpty()

    fun setPin(pin: String) {
        prefs.edit().putString(KEY_PIN, hash(pin)).apply()
    }

    fun checkPin(pin: String): Boolean = prefs.getString(KEY_PIN, null) == hash(pin)

    fun kidsApps(): List<String> {
        val raw = prefs.getString(KEY_KIDS_APPS, null) ?: return emptyList()
        return raw.split('\n').filter { it.isNotBlank() }
    }

    fun toggleKidsApp(pkg: String): Boolean {
        val list = kidsApps().toMutableList()
        val added = if (list.remove(pkg)) false else {
            list.add(pkg)
            true
        }
        prefs.edit().putString(KEY_KIDS_APPS, list.joinToString("\n")).apply()
        return added
    }

    private fun hash(pin: String): String {
        return try {
            val md = java.security.MessageDigest.getInstance("SHA-256")
            val bytes = md.digest(("whitehole-kids:" + pin).toByteArray(Charsets.UTF_8))
            val sb = StringBuilder()
            for (b in bytes) sb.append(String.format("%02x", b.toInt() and 0xff))
            sb.toString()
        } catch (e: Exception) {
            pin
        }
    }

    companion object {
        private const val KEY_ANIM = "animations"
        private const val KEY_IDLE = "idle_minutes"
        private const val KEY_CITY = "city_index"
        private const val KEY_RECENTS = "recents"
        private const val KEY_RENEW = "renew_dismissed_at"
        private const val KEY_KIDS = "kids_enabled"
        private const val KEY_PIN = "kids_pin"
        private const val KEY_KIDS_APPS = "kids_apps"
        const val MAX_RECENTS = 5
        val IDLE_CHOICES = intArrayOf(5, 10, 15, 0)
    }
}

/** Оценка «слабости» устройства: мало памяти или мало ядер — анимации по умолчанию выключены. */
object Perf {
    @Volatile
    private var cached: Boolean? = null

    fun isLowEnd(context: Context): Boolean {
        val c = cached
        if (c != null) return c
        val v = try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            val lowRam = am != null && (am.isLowRamDevice || am.memoryClass < 128)
            val mi = ActivityManager.MemoryInfo()
            am?.getMemoryInfo(mi)
            val smallTotal = mi.totalMem in 1L..(1_200L * 1024L * 1024L)
            val fewCores = Runtime.getRuntime().availableProcessors() <= 2
            lowRam || smallTotal || fewCores
        } catch (e: Exception) {
            false
        }
        cached = v
        return v
    }
}
