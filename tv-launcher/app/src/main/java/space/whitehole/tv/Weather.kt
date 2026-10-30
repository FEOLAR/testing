package space.whitehole.tv

import android.content.Context
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

/** Погода в верхней панели: Open-Meteo (без ключа), город выбирается в настройках, кэш 30 минут. */
object Weather {

    class City(val name: String, val lat: Double, val lon: Double)

    val CITIES: List<City> = listOf(
        City("Москва", 55.7558, 37.6173),
        City("Санкт-Петербург", 59.9386, 30.3141),
        City("Сергиев Посад", 56.3000, 38.1333),
        City("Новосибирск", 55.0302, 82.9204),
        City("Екатеринбург", 56.8380, 60.5973),
        City("Казань", 55.7963, 49.1088),
        City("Нижний Новгород", 56.3269, 44.0059),
        City("Челябинск", 55.1599, 61.4026),
        City("Самара", 53.1959, 50.1002),
        City("Уфа", 54.7388, 55.9721),
        City("Ростов-на-Дону", 47.2224, 39.7187),
        City("Краснодар", 45.0355, 38.9753),
        City("Сочи", 43.5855, 39.7231),
        City("Воронеж", 51.6608, 39.2003),
        City("Пермь", 58.0105, 56.2502),
        City("Красноярск", 56.0153, 92.8932),
        City("Владивосток", 43.1155, 131.8855),
        City("Калининград", 54.7104, 20.4522),
        City("Минск", 53.9045, 27.5615),
        City("Алматы", 43.2220, 76.8512)
    )

    class Now(val tempC: Int, val code: Int)

    private const val CACHE_MS = 30 * 60 * 1000L
    private const val PREFS = "weather_cache"

    /** Кэш, если он свежий и для того же города. */
    fun cached(context: Context, cityIndex: Int): Now? {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (p.getInt("city", -1) != cityIndex) return null
        if (System.currentTimeMillis() - p.getLong("at", 0L) > CACHE_MS) return null
        if (!p.contains("t")) return null
        return Now(p.getInt("t", 0), p.getInt("c", 0))
    }

    /** Блокирующий запрос (из фонового потока). null — ошибка (тогда погоду просто не показываем). */
    fun fetch(context: Context, cityIndex: Int): Now? {
        val city = CITIES[cityIndex.coerceIn(0, CITIES.size - 1)]
        var conn: HttpURLConnection? = null
        return try {
            val url = String.format(
                Locale.US,
                "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f&current=temperature_2m,weather_code&timezone=auto",
                city.lat, city.lon
            )
            conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = 8000
            conn.readTimeout = 8000
            conn.setRequestProperty("User-Agent", "WhiteHoleTV")
            if (conn.responseCode !in 200..299) return null
            val text = conn.inputStream.use { s -> BufferedReader(InputStreamReader(s, Charsets.UTF_8)).readText() }
            val json = JSONObject(text)
            val cur = json.optJSONObject("current") ?: return null
            if (!cur.has("temperature_2m")) return null
            val t = Math.round(cur.getDouble("temperature_2m")).toInt()
            val c = cur.optInt("weather_code", 0)
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putInt("city", cityIndex).putLong("at", System.currentTimeMillis())
                .putInt("t", t).putInt("c", c).apply()
            Now(t, c)
        } catch (e: Exception) {
            null
        } finally {
            try {
                conn?.disconnect()
            } catch (e: Exception) {
                // ignore
            }
        }
    }

    fun describe(code: Int): String = when (code) {
        0 -> "ясно"
        1 -> "малооблачно"
        2 -> "переменная облачность"
        3 -> "пасмурно"
        45, 48 -> "туман"
        51, 53, 55, 56, 57 -> "морось"
        61, 63, 65, 66, 67, 80, 81, 82 -> "дождь"
        71, 73, 75, 77, 85, 86 -> "снег"
        95, 96, 99 -> "гроза"
        else -> ""
    }

    fun format(now: Now): String {
        val t = if (now.tempC > 0) "+" + now.tempC else now.tempC.toString()
        val d = describe(now.code)
        return if (d.isEmpty()) "$t°" else "$t°, $d"
    }
}
