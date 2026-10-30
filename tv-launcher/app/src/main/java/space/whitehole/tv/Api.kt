package space.whitehole.tv

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Ответ сервера: код HTTP и JSON (или null, если сети нет / ответ не JSON). */
class ApiResult(val code: Int, val json: JSONObject?) {
    val ok: Boolean get() = code in 200..299 && json != null
}

/**
 * Вызовы бота WhiteHole (/miniapp/tv/...). Блокирующие — вызывать только из фонового потока.
 * Адрес сервера — BuildConfig.API_BASE (один на всё приложение).
 */
object Api {
    private const val TIMEOUT_MS = 12_000

    fun url(path: String): String = BuildConfig.API_BASE.trimEnd('/') + path

    private fun call(method: String, path: String, token: String? = null, body: JSONObject? = null): ApiResult {
        var conn: HttpURLConnection? = null
        return try {
            conn = URL(url(path)).openConnection() as HttpURLConnection
            conn.requestMethod = method
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = TIMEOUT_MS
            conn.useCaches = false
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("User-Agent", "WhiteHoleTV/" + BuildConfig.VERSION_NAME)
            if (token != null) conn.setRequestProperty("X-TV-Token", token)
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..399) conn.inputStream else conn.errorStream
            val text = stream?.use { s ->
                BufferedReader(InputStreamReader(s, Charsets.UTF_8)).readText()
            } ?: ""
            val json = try {
                JSONObject(text)
            } catch (e: Exception) {
                null
            }
            ApiResult(code, json)
        } catch (e: Exception) {
            ApiResult(0, null)
        } finally {
            try {
                conn?.disconnect()
            } catch (e: Exception) {
                // ignore
            }
        }
    }

    /** Новый код входа: {code, token, bot_link, expires_in}. */
    fun pairStart(deviceName: String): ApiResult =
        call("POST", "/miniapp/tv/pair/start", body = JSONObject().put("name", deviceName))

    /** {status: pending|confirmed|expired, sub_url?, device_name?}. */
    fun pairStatus(token: String): ApiResult =
        call("GET", "/miniapp/tv/pair/status?token=" + URLEncoder.encode(token, "UTF-8"))

    /** Подписка привязанного ТВ. 401 — телевизор отвязан. */
    fun me(token: String): ApiResult = call("GET", "/miniapp/tv/me", token = token)

    fun unpair(token: String): ApiResult = call("POST", "/miniapp/tv/unpair", token = token)

    /** Страница «Скачать WhiteHole для ТВ» (её адрес показываем QR-кодом и текстом). */
    fun pageUrl(): String = url("/miniapp/tv")

    fun happApkUrl(): String = url("/miniapp/tv/happ.apk")

    const val RENEW_LINK = "https://t.me/WhiteHoleVPNbot?start=src_tv_renew"
}
