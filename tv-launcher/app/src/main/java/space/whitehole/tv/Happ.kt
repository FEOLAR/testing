package space.whitehole.tv

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Работа с Happ: добавить подписку и установить сам Happ.
 *
 * Подписка добавляется ссылкой happ://add/<ссылка-подписка> (ссылка как есть, без кодирования) —
 * так же, как это делают мини-апп бота и страница подписки Remnawave (app-config.json, urlScheme "happ://add/").
 */
object Happ {

    fun addSubscriptionUri(subUrl: String): Uri = Uri.parse("happ://add/$subUrl")

    /** Отдать подписку в Happ. true — Happ открылся. */
    fun pushSubscription(context: Context, subUrl: String, happPackage: String?): Boolean {
        val uri = addSubscriptionUri(subUrl)
        if (happPackage != null) {
            val intent = Intent(Intent.ACTION_VIEW, uri).setPackage(happPackage).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            try {
                context.startActivity(intent)
                return true
            } catch (e: Exception) {
                // этот пакет не принимает happ:// — попробуем без пакета
            }
        }
        return try {
            context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (e: Exception) {
            false
        }
    }

    // ---------- установка Happ без компьютера ----------

    private const val APK_NAME = "Happ.apk"

    /** Можно ли нам ставить приложения (Android 8+ спрашивает отдельно для каждого источника). */
    fun canInstall(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || context.packageManager.canRequestPackageInstalls()

    /** Открыть экран «Разрешить установку из этого источника» для WhiteHole. false — такого экрана нет. */
    fun openInstallPermission(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false
        return try {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + context.packageName))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            true
        } catch (e: Exception) {
            false
        }
    }

    /**
     * Скачать Happ.apk (через сервер WhiteHole, он перенаправит на GitHub). Блокирующий вызов, из фона.
     * progress(0..100). Возвращает файл или null.
     */
    fun download(context: Context, progress: (Int) -> Unit): File? {
        val dir = File(context.cacheDir, ApkProvider.DIR)
        dir.mkdirs()
        val tmp = File(dir, "$APK_NAME.part")
        val out = File(dir, APK_NAME)
        var conn: HttpURLConnection? = null
        try {
            var url = URL(Api.happApkUrl())
            // Редиректы переходим вручную: HttpURLConnection не ходит между разными хостами сам в некоторых версиях
            for (i in 0 until 6) {
                conn = url.openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 15_000
                conn.readTimeout = 30_000
                conn.setRequestProperty("User-Agent", "WhiteHoleTV/" + BuildConfig.VERSION_NAME)
                val code = conn.responseCode
                if (code in 300..399) {
                    val loc = conn.getHeaderField("Location") ?: return null
                    url = URL(url, loc)
                    conn.disconnect()
                    continue
                }
                if (code !in 200..299) return null
                val total: Long = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    conn.contentLengthLong
                } else {
                    conn.contentLength.toLong()
                }
                var done = 0L
                var last = -1
                conn.inputStream.use { input ->
                    FileOutputStream(tmp).use { fos ->
                        val buf = ByteArray(64 * 1024)
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            fos.write(buf, 0, n)
                            done += n
                            if (total > 0) {
                                val p = (done * 100 / total).toInt()
                                if (p != last) {
                                    last = p
                                    progress(p)
                                }
                            }
                        }
                    }
                }
                if (done < 100_000) return null
                out.delete()
                return if (tmp.renameTo(out)) out else null
            }
            return null
        } catch (e: Exception) {
            return null
        } finally {
            try {
                conn?.disconnect()
            } catch (e: Exception) {
                // ignore
            }
            tmp.delete()
        }
    }

    /** Запустить установщик Android для скачанного APK. */
    fun install(context: Context, file: File): Boolean {
        // Установщик Android 5–6 не умеет content://, только file:// — открываем файл на чтение всем
        val uri: Uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            ApkProvider.uriFor(file.name)
        } else {
            try {
                file.parentFile?.setExecutable(true, false)
                file.parentFile?.setReadable(true, false)
                file.setReadable(true, false)
            } catch (e: Exception) {
                // ignore
            }
            Uri.fromFile(file)
        }
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, ApkProvider.MIME)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            true
        } catch (e: Exception) {
            false
        }
    }

    /** Запасной путь: открыть ссылку на APK в браузере телевизора. */
    fun openInBrowser(context: Context, url: String): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (e: Exception) {
        false
    }
}
