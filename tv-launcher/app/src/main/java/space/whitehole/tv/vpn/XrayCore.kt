package space.whitehole.tv.vpn

import android.content.Context
import android.util.Log
import go.Seq
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray
import space.whitehole.tv.Api
import space.whitehole.tv.BuildConfig
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Обёртка над libv2ray.aar (AndroidLibXrayLite от 2dust — то же ядро, что в v2rayNG).
 * Xray сам читает tun-интерфейс: fd от VpnService передаётся в startLoop (вход "tun" в конфиге).
 * Используется только в процессе службы (:vpn) и только на Android 7+ (AAR собран под API 24).
 */
object XrayCore {
    private const val TAG = "WhVpnCore"
    const val TEST_URL = "https://www.gstatic.com/generate_204"

    private var controller: CoreController? = null
    private val testPool = Executors.newCachedThreadPool()

    @Synchronized
    fun init(ctx: Context) {
        if (controller != null) return
        val app = ctx.applicationContext
        Seq.setContext(app)
        // Xray читает geoip.dat из этой папки (GeoData.ensure кладёт его туда до init)
        Libv2ray.initCoreEnv(GeoData.dir(app).absolutePath, "")
        controller = Libv2ray.newCoreController(object : CoreCallbackHandler {
            override fun startup(): Long = 0
            override fun shutdown(): Long = 0
            override fun onEmitStatus(code: Long, msg: String?): Long {
                Log.i(TAG, "core: $msg")
                return 0
            }
        })
        Log.i(TAG, "core env ready: " + version())
    }

    fun version(): String = try {
        Libv2ray.checkVersionX()
    } catch (e: Throwable) {
        "?"
    }

    /**
     * Проверка сервера без tun: отдельный экземпляр ядра, запрос к generate_204 через прокси.
     * Задержка в мс или -1. Не ждём дольше [timeoutSec] (ядро само закроет зависший экземпляр).
     */
    /** Текст последней ошибки проверки (например, «failed to open geoip.dat»). */
    @Volatile var lastTestError: String = ""

    fun test(config: String, timeoutSec: Long = 10): Long {
        lastTestError = ""
        val f = testPool.submit(Callable {
            try {
                Libv2ray.measureOutboundDelay(config, TEST_URL)
            } catch (e: Throwable) {
                Log.w(TAG, "test failed: ${e.message}")
                lastTestError = e.message ?: ""
                -1L
            }
        })
        return try {
            f.get(timeoutSec, TimeUnit.SECONDS)
        } catch (e: Exception) {
            f.cancel(true)
            -1L
        }
    }

    @Synchronized
    fun start(config: String, tunFd: Int) {
        val c = controller ?: throw IllegalStateException("core not initialized")
        if (c.isRunning) c.stopLoop()
        c.startLoop(config, tunFd)
        if (!c.isRunning) throw IllegalStateException("core did not start")
    }

    @Synchronized
    fun stop() {
        try {
            val c = controller ?: return
            if (c.isRunning) c.stopLoop()
        } catch (e: Throwable) {
            Log.w(TAG, "stop: ${e.message}")
        }
    }

    val isRunning: Boolean
        get() = try {
            controller?.isRunning == true
        } catch (e: Throwable) {
            false
        }
}

/**
 * Компактная geoip.dat (только RU, ≈0,4 МБ). В APK лежит в assets (кладёт CI). Ядро Xray читает файл
 * только с диска (xray.location.asset = [dir]), поэтому перед проверками и запуском ядра файл синхронно
 * копируется из assets в filesDir/vpn/geo/geoip.dat (в процессе :vpn). Нет в APK — скачиваем с сервера.
 * geoip:ru используется ТОЛЬКО если этот файл реально есть на диске; иначе конфиг без geoip-правил.
 */
object GeoData {
    private const val TAG = "WhVpnGeo"
    private const val RETRY_MS = 60 * 60 * 1000L
    private const val MIN_SIZE = 10_000L
    private const val NAME = "geoip.dat"

    fun dir(ctx: Context): File = File(VpnFiles.dir(ctx), "geo").also { it.mkdirs() }

    fun file(ctx: Context): File = File(dir(ctx), NAME)

    /** Ровно тот файл, который откроет ядро. */
    fun available(ctx: Context): Boolean = file(ctx).let { it.isFile && it.length() > MIN_SIZE }

    /** true — geoip:ru можно использовать в правилах. Вызывать до XrayCore.init/test/start. */
    @Synchronized
    fun ensure(ctx: Context): Boolean {
        val f = file(ctx)
        val ver = BuildConfig.VERSION_CODE.toString()
        // копия из APK: при первом запуске и после обновления приложения (новая версия базы)
        if (!available(ctx) || VpnFiles.read(ctx, "geo_ver") != ver) {
            if (extractAsset(ctx, f)) VpnFiles.write(ctx, "geo_ver", ver)
        }
        if (!available(ctx)) {
            val last = VpnFiles.read(ctx, "geo_fail_at")?.trim()?.toLongOrNull() ?: 0L
            if (System.currentTimeMillis() - last !in 0..RETRY_MS) {
                val ok = download(ctx, Api.url("/miniapp/geoip.dat"), f)
                if (!ok) VpnFiles.write(ctx, "geo_fail_at", System.currentTimeMillis().toString())
            }
        }
        val ok = available(ctx)
        Log.i(TAG, "geoip: ${f.absolutePath} exists=${f.isFile} size=${f.length()} use=$ok")
        return ok
    }

    private fun extractAsset(ctx: Context, out: File): Boolean {
        val tmp = File(out.parentFile, "$NAME.part")
        return try {
            ctx.assets.open(NAME).use { input -> tmp.outputStream().use { input.copyTo(it) } }
            if (tmp.length() <= MIN_SIZE) {
                Log.w(TAG, "asset $NAME too small: ${tmp.length()}")
                false
            } else {
                out.delete()
                tmp.renameTo(out) && out.length() > MIN_SIZE
            }
        } catch (e: Exception) {
            Log.w(TAG, "no $NAME in APK assets: ${e.javaClass.simpleName}")
            false
        } finally {
            tmp.delete()
        }
    }

    private fun download(ctx: Context, url: String, out: File): Boolean {
        var conn: HttpURLConnection? = null
        val tmp = File(out.parentFile, out.name + ".part")
        return try {
            conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 20_000
            conn.setRequestProperty("Accept", "*/*")
            if (conn.responseCode !in 200..299) return false
            conn.inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
            if (tmp.length() <= MIN_SIZE) return false
            out.delete()
            tmp.renameTo(out)
        } catch (e: Exception) {
            Log.w(TAG, "geoip download failed: ${e.javaClass.simpleName}")
            false
        } finally {
            tmp.delete()
            try {
                conn?.disconnect()
            } catch (e: Exception) {
                // ignore
            }
        }
    }
}
