package space.whitehole.tv.vpn

import android.app.ActivityManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.Process
import org.json.JSONObject
import java.util.concurrent.CopyOnWriteArrayList

enum class VpnStatus { DISCONNECTED, CONNECTING, CONNECTED, ERROR }

/**
 * Состояние встроенного VPN — простой наблюдаемый синглтон.
 *
 * Источник правды — служба в процессе :vpn: [publish] сохраняет состояние в файл и рассылает
 * broadcast внутри приложения. В процессе лаунчера тот же объект обновляется из broadcast'ов
 * ([bindUi]) и из файла при возврате на экран ([reload]). Слушатели вызываются в главном потоке.
 */
object VpnState {
    const val ACTION_STATE = "space.whitehole.tv.vpn.STATE"
    private const val FILE = "state.json"

    @Volatile var status: VpnStatus = VpnStatus.DISCONNECTED
        private set
    @Volatile var server: String = ""
        private set
    @Volatile var message: String = ""
        private set

    private val listeners = CopyOnWriteArrayList<(VpnStatus) -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private var uiReceiver: BroadcastReceiver? = null
    @Volatile private var localAt = 0L

    fun addListener(l: (VpnStatus) -> Unit) {
        listeners.addIfAbsent(l)
    }

    fun removeListener(l: (VpnStatus) -> Unit) {
        listeners.remove(l)
    }

    val isActive: Boolean get() = status == VpnStatus.CONNECTED || status == VpnStatus.CONNECTING

    private fun set(s: VpnStatus, srv: String, msg: String) {
        val changed = s != status || srv != server || msg != message
        status = s
        server = srv
        message = msg
        if (!changed) return
        val run = Runnable { listeners.forEach { it(s) } }
        if (Looper.myLooper() == Looper.getMainLooper()) run.run() else main.post(run)
    }

    /** Служба: новое состояние → файл + broadcast в лаунчер. */
    fun publish(ctx: Context, s: VpnStatus, srv: String = "", msg: String = "") {
        set(s, srv, msg)
        val j = JSONObject().put("status", s.name).put("server", srv).put("message", msg).put("pid", Process.myPid())
            .put("t", System.currentTimeMillis())
        VpnFiles.write(ctx, FILE, j.toString())
        try {
            ctx.sendBroadcast(
                Intent(ACTION_STATE).setPackage(ctx.packageName)
                    .putExtra("status", s.name).putExtra("server", srv).putExtra("message", msg)
            )
        } catch (e: Exception) {
            // ignore
        }
    }

    /** Лаунчер: локальное изменение до ответа службы (нажали «Подключить», отказ в разрешении). */
    fun setLocal(s: VpnStatus, srv: String = server, msg: String = "") {
        localAt = System.currentTimeMillis()
        set(s, srv, msg)
    }

    /** Лаунчер: подписаться на broadcast'ы службы (один раз на процесс). */
    @Synchronized
    fun bindUi(ctx: Context) {
        if (uiReceiver != null) return
        val app = ctx.applicationContext
        val r = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                val s = try {
                    VpnStatus.valueOf(i.getStringExtra("status") ?: return)
                } catch (e: Exception) {
                    return
                }
                set(s, i.getStringExtra("server") ?: "", i.getStringExtra("message") ?: "")
            }
        }
        val f = IntentFilter(ACTION_STATE)
        if (Build.VERSION.SDK_INT >= 33) {
            app.registerReceiver(r, f, Context.RECEIVER_NOT_EXPORTED)
        } else {
            app.registerReceiver(r, f)
        }
        uiReceiver = r
    }

    /** Лаунчер: перечитать файл состояния (служба могла умереть — тогда «отключено»). */
    fun reload(ctx: Context) {
        val j = try {
            VpnFiles.read(ctx, FILE)?.let { JSONObject(it) }
        } catch (e: Exception) {
            null
        }
        // файл старше локального нажатия — ждём свежий broadcast от службы
        if (j != null && j.optLong("t", 0L) < localAt && System.currentTimeMillis() - localAt < 60_000) return
        if (j == null) {
            if (System.currentTimeMillis() - localAt > 15_000) set(VpnStatus.DISCONNECTED, "", "")
            return
        }
        val s = try {
            VpnStatus.valueOf(j.optString("status"))
        } catch (e: Exception) {
            VpnStatus.DISCONNECTED
        }
        val alive = serviceProcessAlive(ctx, j.optInt("pid", -1))
        when {
            (s == VpnStatus.CONNECTED || s == VpnStatus.CONNECTING) && !alive -> set(VpnStatus.DISCONNECTED, "", "")
            else -> set(s, j.optString("server", ""), j.optString("message", ""))
        }
    }

    private fun serviceProcessAlive(ctx: Context, pid: Int): Boolean {
        if (pid <= 0) return false
        return try {
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            am.runningAppProcesses?.any { it.pid == pid && it.processName.endsWith(":vpn") } == true
        } catch (e: Exception) {
            true
        }
    }
}
