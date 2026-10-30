package space.whitehole.tv

import android.os.SystemClock
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL

/**
 * Честный пинг до сервера WhiteHole: время установки TCP-соединения с хостом из API_BASE
 * (DNS не считается). Лучший результат из трёх попыток. Никаких выдуманных скоростей.
 */
object Ping {
    /** Миллисекунды или -1, если сервер не ответил. Блокирующий вызов (фоновый поток). */
    fun measure(): Int {
        return try {
            val url = URL(BuildConfig.API_BASE)
            val host = url.host
            val port = if (url.port > 0) url.port else url.defaultPort
            val addr = InetAddress.getByName(host)
            var best = -1L
            for (i in 0 until 3) {
                val s = Socket()
                try {
                    val t0 = SystemClock.elapsedRealtimeNanos()
                    s.connect(InetSocketAddress(addr, port), 3000)
                    val ms = (SystemClock.elapsedRealtimeNanos() - t0) / 1_000_000L
                    if (best < 0 || ms < best) best = ms
                } catch (e: Exception) {
                    // попытка не удалась
                } finally {
                    try {
                        s.close()
                    } catch (e: Exception) {
                        // ignore
                    }
                }
            }
            if (best < 0) -1 else maxOf(1L, best).toInt()
        } catch (e: Exception) {
            -1
        }
    }
}
