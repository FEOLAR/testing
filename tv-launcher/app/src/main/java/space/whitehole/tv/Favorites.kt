package space.whitehole.tv

import android.content.Context

/** Избранные приложения: порядок = порядок добавления. */
class Favorites(context: Context) {

    private val prefs = context.getSharedPreferences("whitehole", Context.MODE_PRIVATE)

    fun get(): MutableList<String> {
        val raw = prefs.getString(KEY, null) ?: return mutableListOf()
        return raw.split('\n').filter { it.isNotBlank() }.toMutableList()
    }

    fun contains(pkg: String): Boolean = get().contains(pkg)

    /** @return true если добавили, false если убрали */
    fun toggle(pkg: String): Boolean {
        val list = get()
        return if (list.remove(pkg)) {
            save(list)
            false
        } else {
            list.add(pkg)
            save(list)
            true
        }
    }

    /** При первом запуске: сначала известные видеосервисы, затем остальные — всего до 8. */
    fun ensureDefaults(apps: List<AppEntry>) {
        if (prefs.contains(KEY) || apps.isEmpty()) return
        val installed = HashSet<String>()
        for (a in apps) installed.add(a.packageName)
        val result = ArrayList<String>()
        for (p in KNOWN) {
            if (result.size >= DEFAULT_COUNT) break
            if (installed.contains(p) && !result.contains(p)) result.add(p)
        }
        for (a in apps) {
            if (result.size >= DEFAULT_COUNT) break
            if (!result.contains(a.packageName)) result.add(a.packageName)
        }
        save(result)
    }

    private fun save(list: List<String>) {
        prefs.edit().putString(KEY, list.joinToString("\n")).apply()
    }

    companion object {
        private const val KEY = "favorites"
        private const val DEFAULT_COUNT = 10
        private val KNOWN: List<String> = listOf(
            "com.yandex.tv.ytplayer",
            "com.google.android.youtube.tv",
            "ru.kinopoisk.yandex.tv",
            "ru.kinopoisk.tv",
            "su.happ.proxyutility",
            "com.happproxy",
            "com.happ.proxy",
            "su.happ.proxy",
            "ru.ivi.client",
            "ru.more.play",
            "ru.rt.video.app.tv",
            "com.vk.vkvideo.tv",
            "com.vk.tv",
            "ru.rutube.app",
            "ru.mts.mtstv",
            "com.yandex.tv.music",
            "com.yandex.browser.tv"
        )
    }
}
