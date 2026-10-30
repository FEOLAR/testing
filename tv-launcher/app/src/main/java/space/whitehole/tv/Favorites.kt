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

    /** Добавить в конец. @return false если уже было */
    fun add(pkg: String): Boolean {
        val list = get()
        if (list.contains(pkg)) return false
        list.add(pkg)
        save(list)
        return true
    }

    fun remove(pkg: String) {
        val list = get()
        if (list.remove(pkg)) save(list)
    }

    /** Сдвинуть на delta позиций (-1 влево, +1 вправо). */
    fun move(pkg: String, delta: Int) {
        val list = get()
        val from = list.indexOf(pkg)
        if (from < 0) return
        val to = (from + delta).coerceIn(0, list.size - 1)
        if (to == from) return
        list.removeAt(from)
        list.add(to, pkg)
        save(list)
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
        /** Порядок по умолчанию. Пакеты, которых нет на устройстве, просто пропускаются. */
        private val KNOWN: List<String> = listOf(
            // YouTube (Яндекс ТВ / Android TV / Google TV)
            "com.yandex.tv.ytplayer",
            "com.google.android.youtube.tv",
            // Кинопоиск
            "ru.kinopoisk.yandex.tv",
            "ru.kinopoisk.tv",
            // Happ
            "su.happ.proxyutility",
            "com.happproxy",
            "com.happ.proxy",
            "su.happ.proxy",
            // российские онлайн-кинотеатры и ТВ
            "ru.ivi.client",
            "ru.more.play",
            "ru.rt.video.app.tv",
            "com.vk.vkvideo.tv",
            "com.vk.tv",
            "ru.rutube.app",
            "ru.mts.mtstv",
            "ru.start.tv",
            "ru.start.androidmobile",
            "gpm.tnt_premier",
            // зарубежные сервисы
            "com.netflix.ninja",
            "com.amazon.amazonvideo.livingroom",
            "com.disney.disneyplus",
            "com.google.android.youtube.tvkids",
            "org.xbmc.kodi",
            // Яндекс: музыка и браузер — в конце
            "com.yandex.tv.music",
            "com.yandex.browser.tv"
        )
    }
}
