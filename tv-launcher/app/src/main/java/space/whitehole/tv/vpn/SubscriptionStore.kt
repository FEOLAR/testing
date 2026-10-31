package space.whitehole.tv.vpn

import android.content.Context
import android.os.Build
import android.util.Log
import space.whitehole.tv.BuildConfig
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

enum class SubError { NETWORK, DEVICE_LIMIT, HWID_REQUIRED, NOT_FOUND, EMPTY }

class SubResult(val links: List<VlessLink>, val fetchedNow: Boolean, val error: SubError?)

/**
 * Загрузка подписки Remnawave и кэш последней удачной копии (filesDir/vpn/sub.txt).
 *
 * Заголовки — как у клиентов с поддержкой HWID (docs.rw → HWID device limit):
 * x-hwid (обязателен при включённом лимите), x-device-os, x-ver-os, x-device-model, user-agent.
 * User-Agent свой («WhiteHoleTV/…»): он не попадает ни под одно правило ответа Remnawave, поэтому
 * панель отдаёт запасной формат XRAY_BASE64 — обычные vless:// ссылки. (UA v2rayNG/Happ при включённом
 * «serveJsonAtBaseSubscription» получил бы Xray-JSON — его мы тоже умеем разобрать, но base64 надёжнее.)
 * Accept задаём явно: стандартный Accept HttpURLConnection содержит text/html, и панель отдала бы HTML-страницу.
 */
object SubscriptionStore {
    private const val TAG = "WhVpnSub"
    const val MAX_AGE_MS = 60 * 60 * 1000L
    private const val TIMEOUT_MS = 15_000

    private fun urlKey(url: String): String = try {
        MessageDigest.getInstance("SHA-256").digest(url.toByteArray()).joinToString("") { "%02x".format(it) }.take(16)
    } catch (e: Exception) {
        url.hashCode().toString()
    }

    /** Кэш: текст подписки и время загрузки, если он от этой же ссылки. */
    fun cached(ctx: Context, subUrl: String): Pair<String, Long>? {
        val meta = VpnFiles.read(ctx, "sub.meta")?.lines() ?: return null
        if (meta.size < 2 || meta[1] != urlKey(subUrl)) return null
        val at = meta[0].toLongOrNull() ?: return null
        val body = VpnFiles.read(ctx, "sub.txt") ?: return null
        return body to at
    }

    private fun saveCache(ctx: Context, subUrl: String, text: String) {
        VpnFiles.write(ctx, "sub.txt", text)
        VpnFiles.write(ctx, "sub.meta", "${System.currentTimeMillis()}\n${urlKey(subUrl)}")
    }

    /**
     * Ссылки подписки: из кэша, если он моложе [maxAgeMs], иначе с сервера (при сбое сети — старый кэш).
     * Лимит устройств / удалённая подписка — ошибка без кэша, чтобы лимит в панели работал.
     */
    fun load(ctx: Context, subUrl: String, maxAgeMs: Long = MAX_AGE_MS): SubResult {
        val cache = cached(ctx, subUrl)
        val cachedLinks = cache?.let { ShareLinkParser.parseSubscription(it.first) } ?: emptyList()
        if (cache != null && cachedLinks.isNotEmpty() && System.currentTimeMillis() - cache.second in 0..maxAgeMs) {
            return SubResult(cachedLinks, false, null)
        }
        val f = fetch(ctx, subUrl)
        if (f.error == null) {
            val links = ShareLinkParser.parseSubscription(f.body)
            if (links.isNotEmpty()) {
                saveCache(ctx, subUrl, ShareLinkParser.decodeSubscriptionText(f.body))
                return SubResult(links, true, null)
            }
            return SubResult(cachedLinks.takeIf { cache != null } ?: emptyList(), false, if (cachedLinks.isEmpty()) SubError.EMPTY else null)
        }
        return when (f.error) {
            SubError.NETWORK -> SubResult(cachedLinks, false, if (cachedLinks.isEmpty()) SubError.NETWORK else null)
            else -> SubResult(emptyList(), false, f.error)
        }
    }

    private class Fetched(val body: String, val error: SubError?)

    private fun ascii(s: String): String = s.filter { it.code in 0x20..0x7e }.trim()

    private fun fetch(ctx: Context, subUrl: String): Fetched {
        var conn: HttpURLConnection? = null
        try {
            var url = URL(subUrl)
            for (hop in 0 until 4) {
                conn = url.openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = false
                conn.connectTimeout = TIMEOUT_MS
                conn.readTimeout = TIMEOUT_MS
                conn.useCaches = false
                conn.setRequestProperty("Accept", "*/*")
                conn.setRequestProperty("User-Agent", "WhiteHoleTV/" + BuildConfig.VERSION_NAME)
                conn.setRequestProperty("x-hwid", VpnFiles.hwid(ctx))
                conn.setRequestProperty("x-device-os", "Android")
                conn.setRequestProperty("x-ver-os", ascii(Build.VERSION.RELEASE ?: "").ifEmpty { "unknown" })
                conn.setRequestProperty("x-device-model", deviceModel())
                val code = conn.responseCode
                if (code in 300..399) {
                    val loc = conn.getHeaderField("Location") ?: return Fetched("", SubError.NETWORK)
                    url = URL(url, loc)
                    conn.disconnect()
                    continue
                }
                if (conn.getHeaderField("x-hwid-max-devices-reached") == "true") return Fetched("", SubError.DEVICE_LIMIT)
                if (conn.getHeaderField("x-hwid-not-supported") == "true") return Fetched("", SubError.HWID_REQUIRED)
                if (code == 404 || code == 403 || code == 410) return Fetched("", SubError.NOT_FOUND)
                if (code !in 200..299) return Fetched("", SubError.NETWORK)
                val bytes = conn.inputStream.use { input ->
                    val out = ByteArrayOutputStream()
                    val buf = ByteArray(16 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        if (out.size() > 4 * 1024 * 1024) break
                    }
                    out.toByteArray()
                }
                val body = String(bytes, Charsets.UTF_8)
                Log.i(TAG, "subscription: http $code, ${bytes.size} bytes")
                if (body.trimStart().startsWith("<")) return Fetched("", SubError.NETWORK) // HTML вместо подписки
                return Fetched(body, null)
            }
            return Fetched("", SubError.NETWORK)
        } catch (e: Exception) {
            Log.w(TAG, "subscription fetch failed: ${e.javaClass.simpleName}")
            return Fetched("", SubError.NETWORK)
        } finally {
            try {
                conn?.disconnect()
            } catch (e: Exception) {
                // ignore
            }
        }
    }

    /** «Tuvio XYZ (WhiteHole TV)» — так телевизор будет подписан в списке устройств бота. */
    fun deviceModel(): String {
        val man = ascii(Build.MANUFACTURER ?: "")
        val model = ascii(Build.MODEL ?: "")
        val name = if (model.startsWith(man, ignoreCase = true)) model else "$man $model"
        return (name.trim().ifEmpty { "Android TV" } + " (WhiteHole TV)").take(64)
    }
}
