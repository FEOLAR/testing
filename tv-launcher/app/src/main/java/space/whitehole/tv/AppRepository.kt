package space.whitehole.tv

import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.pm.ResolveInfo
import android.graphics.drawable.Drawable
import java.text.Collator
import java.util.Locale

class AppEntry(
    val packageName: String,
    val label: String,
    val activityInfo: ActivityInfo
)

object AppRepository {

    val HAPP_PACKAGES: List<String> = listOf("com.happproxy", "com.happ.proxy", "su.happ.proxy")

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
                if (pkg == own || result.containsKey(pkg)) continue
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

    fun loadBanner(pm: PackageManager, app: AppEntry): Drawable? {
        try {
            val d = app.activityInfo.loadBanner(pm)
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
        return try {
            app.activityInfo.loadIcon(pm)
        } catch (e: Exception) {
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
