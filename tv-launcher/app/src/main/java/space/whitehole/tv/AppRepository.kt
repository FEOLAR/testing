package space.whitehole.tv

import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.pm.ResolveInfo
import android.content.res.Resources
import android.graphics.drawable.Drawable
import android.util.DisplayMetrics
import java.text.Collator
import java.util.Locale

class AppEntry(
    val packageName: String,
    val label: String,
    val activityInfo: ActivityInfo
)

object AppRepository {

    val HAPP_PACKAGES: List<String> = listOf("su.happ.proxyutility", "com.happproxy", "com.happ.proxy", "su.happ.proxy")

    /** Системный и заводской мусор, который не показываем нигде. */
    private val EXCLUDED: Set<String> = setOf(
        "com.yandex.tv.home",
        "com.yandex.tv.setupwizard",
        "com.cvte.fac.menu",
        "com.changhong.factory.at",
        "com.dimowner.audiorecorder.debug"
    )
    private val EXCLUDED_PREFIXES: List<String> = listOf("com.cvte.factory")

    fun isExcluded(pkg: String): Boolean {
        if (EXCLUDED.contains(pkg)) return true
        for (p in EXCLUDED_PREFIXES) {
            if (pkg == p || pkg.startsWith("$p.")) return true
        }
        return false
    }

    /** Все запускаемые приложения (LEANBACK_LAUNCHER + LAUNCHER), без дублей и без нас самих. */
    @Suppress("DEPRECATION")
    fun loadApps(context: Context): List<AppEntry> {
        val pm = context.packageManager
        val own = context.packageName
        val result = LinkedHashMap<String, AppEntry>()
        val intents = listOf(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LEANBACK_LAUNCHER),
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        )
        for (intent in intents) {
            var list: List<ResolveInfo> = emptyList()
            try {
                list = pm.queryIntentActivities(intent, 0)
            } catch (e: Exception) {
                // ignore
            }
            for (ri in list) {
                val ai: ActivityInfo = ri.activityInfo ?: continue
                val pkg = ai.packageName
                if (pkg == own || isExcluded(pkg) || result.containsKey(pkg)) continue
                var label = pkg
                try {
                    label = ri.loadLabel(pm).toString()
                } catch (e: Exception) {
                    // ignore
                }
                if (label.isBlank()) label = pkg
                result[pkg] = AppEntry(pkg, label, ai)
            }
        }
        val collator = Collator.getInstance(Locale("ru"))
        return result.values.sortedWith(Comparator { a, b -> collator.compare(a.label, b.label) })
    }

    /**
     * Баннер в максимальном качестве: берём ресурс приложения сразу для плотности xxxhdpi
     * (на 4K-телевизоре иначе система может отдать картинку для меньшей плотности).
     */
    fun loadBanner(pm: PackageManager, app: AppEntry): Drawable? {
        val ai = app.activityInfo
        val appInfo: ApplicationInfo? = ai.applicationInfo
        val res = resourcesFor(pm, appInfo)
        if (res != null) {
            val ids = ArrayList<Int>()
            if (ai.banner != 0) ids.add(ai.banner)
            if (appInfo != null && appInfo.banner != 0) ids.add(appInfo.banner)
            for (id in ids) {
                val d = hiDensity(res, id)
                if (d != null) return d
            }
        }
        try {
            val d = ai.loadBanner(pm)
            if (d != null) return d
        } catch (e: Exception) {
            // ignore
        }
        try {
            val d = pm.getApplicationBanner(app.packageName)
            if (d != null) return d
        } catch (e: Exception) {
            // ignore
        }
        return null
    }

    fun loadIcon(pm: PackageManager, app: AppEntry): Drawable? {
        val ai = app.activityInfo
        val appInfo: ApplicationInfo? = ai.applicationInfo
        val res = resourcesFor(pm, appInfo)
        if (res != null) {
            val ids = ArrayList<Int>()
            if (ai.icon != 0) ids.add(ai.icon)
            if (appInfo != null && appInfo.icon != 0) ids.add(appInfo.icon)
            for (id in ids) {
                val d = hiDensity(res, id)
                if (d != null) return d
            }
        }
        return try {
            ai.loadIcon(pm)
        } catch (e: Exception) {
            null
        }
    }

    private fun resourcesFor(pm: PackageManager, appInfo: ApplicationInfo?): Resources? {
        if (appInfo == null) return null
        return try {
            pm.getResourcesForApplication(appInfo)
        } catch (e: Exception) {
            null
        }
    }

    private fun hiDensity(res: Resources, id: Int): Drawable? {
        return try {
            res.getDrawableForDensity(id, DisplayMetrics.DENSITY_XXXHIGH, null)
        } catch (e: Exception) {
            null
        } catch (e: OutOfMemoryError) {
            null
        }
    }

    fun launchIntent(pm: PackageManager, pkg: String): Intent? {
        var intent: Intent? = null
        try {
            intent = pm.getLeanbackLaunchIntentForPackage(pkg)
        } catch (e: Exception) {
            // ignore
        }
        if (intent == null) {
            try {
                intent = pm.getLaunchIntentForPackage(pkg)
            } catch (e: Exception) {
                // ignore
            }
        }
        return intent
    }

    /** Ищем Happ: сначала по известным пакетам, потом по названию. */
    fun findHapp(context: Context, apps: List<AppEntry>): String? {
        val pm = context.packageManager
        for (p in HAPP_PACKAGES) {
            if (launchIntent(pm, p) != null) return p
        }
        val byLabel = apps.firstOrNull { it.label.contains("happ", ignoreCase = true) }
        return byLabel?.packageName
    }
}
