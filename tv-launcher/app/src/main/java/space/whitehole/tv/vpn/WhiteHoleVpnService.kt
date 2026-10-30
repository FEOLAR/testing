package space.whitehole.tv.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import org.json.JSONObject
import space.whitehole.tv.MainActivity
import space.whitehole.tv.R
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * Встроенный VPN: VpnService + ядро Xray (tun читает само ядро).
 * Работает в отдельном процессе :vpn — падение Go-ядра не уронит домашний экран.
 *
 * Запуск: ACTION_START с EXTRA_SUB_URL и EXTRA_SERVER (ключ сервера, "" — Авто).
 * Порядок: подписка (кэш до 1 ч) → план попыток (TCP → XHTTP → резерв) → проверка каждой
 * попытки отдельным экземпляром ядра → tun + ядро с первой рабочей.
 */
class WhiteHoleVpnService : VpnService() {

    companion object {
        private const val TAG = "WhVpn"
        const val ACTION_START = "space.whitehole.tv.vpn.START"
        const val ACTION_STOP = "space.whitehole.tv.vpn.STOP"
        const val EXTRA_SUB_URL = "sub_url"
        const val EXTRA_SERVER = "server"
        private const val CHANNEL = "vpn"
        private const val NOTIF_ID = 7
        private const val LAST_START = "last_start.json"

        private const val TUN_ADDR = "10.10.14.1"
        private const val TUN_ADDR6 = "fd00:7768:6974::1"
        private const val TUN_DNS = "1.1.1.1"
        private const val MTU = 1500

        /** Маршруты в tun: весь IPv4, кроме локальных сетей (чтобы не ломать adb по Wi-Fi, Chromecast, DLNA). Список как в v2rayNG. */
        private val ROUTES = listOf(
            "0.0.0.0/5", "8.0.0.0/7", "11.0.0.0/8", "12.0.0.0/6", "16.0.0.0/4", "32.0.0.0/3", "64.0.0.0/2",
            "128.0.0.0/3", "160.0.0.0/5", "168.0.0.0/6", "172.0.0.0/12", "172.32.0.0/11", "172.64.0.0/10",
            "172.128.0.0/9", "173.0.0.0/8", "174.0.0.0/7", "176.0.0.0/4", "192.0.0.0/9", "192.128.0.0/11",
            "192.160.0.0/13", "192.169.0.0/16", "192.170.0.0/15", "192.172.0.0/14", "192.176.0.0/12",
            "192.192.0.0/10", "193.0.0.0/8", "194.0.0.0/7", "196.0.0.0/6", "200.0.0.0/5", "208.0.0.0/4",
        )
    }

    private class Request(val subUrl: String, val server: String) {
        fun toJson(): String = JSONObject().put("sub", subUrl).put("server", server).toString()

        companion object {
            fun from(i: Intent?): Request? {
                val sub = i?.getStringExtra(EXTRA_SUB_URL)?.takeIf { it.isNotEmpty() } ?: return null
                return Request(sub, i.getStringExtra(EXTRA_SERVER) ?: ServerCatalog.AUTO_KEY)
            }

            fun load(ctx: Context): Request? = try {
                val j = JSONObject(VpnFiles.read(ctx, LAST_START) ?: return null)
                j.optString("sub").takeIf { it.isNotEmpty() }?.let { Request(it, j.optString("server", "")) }
            } catch (e: Exception) {
                null
            }
        }
    }

    private val worker = Executors.newSingleThreadExecutor()
    private val gen = AtomicInteger()
    private val lock = Any()
    private var tun: ParcelFileDescriptor? = null
    @Volatile private var foreground = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            userStop()
            return START_NOT_STICKY
        }
        // START от лаунчера; null/SERVICE_INTERFACE — перезапуск системой (always-on, после убийства процесса)
        val req = Request.from(intent) ?: Request.load(this)
        if (req == null) {
            VpnState.publish(this, VpnStatus.DISCONNECTED)
            stopSelf()
            return START_NOT_STICKY
        }
        VpnFiles.write(this, LAST_START, req.toJson())
        goForeground(getString(R.string.vpn_notif_connecting))
        val g = gen.incrementAndGet()
        VpnState.publish(this, VpnStatus.CONNECTING, VpnState.server)
        worker.execute { connect(g, req) }
        return START_STICKY
    }

    private fun connect(g: Int, req: Request) {
        try {
            if (prepare(this) != null) {
                fail(g, getString(R.string.vpn_err_consent))
                return
            }
            var sub = SubscriptionStore.load(this, req.subUrl)
            if (sub.links.isEmpty()) {
                fail(g, subErrorText(sub.error))
                return
            }
            XrayCore.init(this)
            val geo = GeoData.ensure(this)
            Log.i(TAG, "connect: links=${sub.links.size} geoip=$geo server='${req.server}'")
            for (round in 0..1) {
                val entries = ServerCatalog.build(sub.links)
                val plan = ServerCatalog.attemptPlan(entries, req.server)
                if (plan.isEmpty()) {
                    fail(g, getString(R.string.vpn_err_no_servers))
                    return
                }
                for (a in plan) {
                    if (gen.get() != g) return
                    val cfg = XrayConfigBuilder.build(a.link, CoreOptions(geoipRu = geo, mtu = MTU))
                    val delay = XrayCore.test(cfg)
                    Log.i(TAG, "test ${a.link}: $delay ms")
                    if (delay < 0) continue
                    if (startCore(g, a, cfg)) return
                }
                // Все попытки не прошли на старом кэше — обновить подписку и попробовать ещё раз
                if (round == 0 && !sub.fetchedNow) {
                    val fresh = SubscriptionStore.load(this, req.subUrl, maxAgeMs = 0)
                    if (fresh.fetchedNow && fresh.links.isNotEmpty()) {
                        sub = fresh
                        continue
                    }
                }
                break
            }
            if (gen.get() == g) fail(g, getString(R.string.vpn_err_servers))
        } catch (e: Throwable) {
            Log.e(TAG, "connect failed", e)
            fail(g, getString(R.string.vpn_err_core))
        }
    }

    /** true — подключились (или попытка уже не актуальна). */
    private fun startCore(g: Int, a: Attempt, cfg: String): Boolean {
        synchronized(lock) {
            if (gen.get() != g) return true
            val fd = tun ?: establish()
            if (fd == null) {
                fail(g, getString(R.string.vpn_err_consent))
                return true
            }
            tun = fd
            return try {
                XrayCore.start(cfg, fd.fd)
                val name = a.entry.name
                VpnState.publish(this, VpnStatus.CONNECTED, name)
                goForeground(getString(R.string.vpn_notif_on, name))
                Log.i(TAG, "connected via ${a.link}")
                true
            } catch (e: Throwable) {
                Log.e(TAG, "core start failed", e)
                false
            }
        }
    }

    private fun establish(): ParcelFileDescriptor? {
        val b = Builder()
            .setSession(getString(R.string.app_name))
            .setMtu(MTU)
            .addAddress(TUN_ADDR, 30)
            .addDnsServer(TUN_DNS)
        for (r in ROUTES) {
            val p = r.split('/')
            b.addRoute(p[0], p[1].toInt())
        }
        // IPv6: забираем глобальные адреса в tun, чтобы трафик не шёл мимо VPN (DNS отдаёт только IPv4)
        try {
            b.addAddress(TUN_ADDR6, 126)
            b.addRoute("2000::", 3)
        } catch (e: Exception) {
            Log.w(TAG, "ipv6 not configured: ${e.message}")
        }
        try {
            // ядро Xray живёт в нашем приложении: его соединения с сервером идут мимо VPN
            b.addDisallowedApplication(packageName)
        } catch (e: Exception) {
            Log.w(TAG, "disallow self failed", e)
        }
        if (Build.VERSION.SDK_INT >= 29) b.setMetered(false)
        b.setConfigureIntent(openAppIntent())
        return try {
            b.establish()
        } catch (e: Exception) {
            Log.e(TAG, "establish failed", e)
            null
        }
    }

    private fun fail(g: Int, message: String) {
        synchronized(lock) {
            if (gen.get() != g) return
            gen.incrementAndGet()
            teardown()
            VpnState.publish(this, VpnStatus.ERROR, "", message)
        }
        leaveForeground()
        stopSelf()
    }

    private fun userStop() {
        synchronized(lock) {
            gen.incrementAndGet()
            teardown()
        }
        VpnState.publish(this, VpnStatus.DISCONNECTED)
        leaveForeground()
        stopSelf()
    }

    /** Под lock. */
    private fun teardown() {
        XrayCore.stop()
        try {
            tun?.close()
        } catch (e: Exception) {
            // ignore
        }
        tun = null
    }

    override fun onRevoke() {
        // Пользователь отключил VPN в настройках или включил другой VPN-сервис
        VpnFiles.setWanted(this, false)
        synchronized(lock) {
            gen.incrementAndGet()
            teardown()
        }
        VpnState.publish(this, VpnStatus.DISCONNECTED, "", getString(R.string.vpn_revoked))
        leaveForeground()
        stopSelf()
    }

    override fun onDestroy() {
        synchronized(lock) {
            gen.incrementAndGet()
            teardown()
        }
        if (VpnState.status != VpnStatus.ERROR) VpnState.publish(this, VpnStatus.DISCONNECTED)
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun subErrorText(e: SubError?): String = getString(
        when (e) {
            SubError.DEVICE_LIMIT -> R.string.vpn_err_devices
            SubError.HWID_REQUIRED -> R.string.vpn_err_devices
            SubError.NOT_FOUND -> R.string.vpn_err_sub_gone
            SubError.EMPTY -> R.string.vpn_err_no_servers
            else -> R.string.vpn_err_sub
        }
    )

    // ---------- уведомление (обязательно для VPN на Android 8+) ----------

    private fun openAppIntent(): PendingIntent {
        val i = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return PendingIntent.getActivity(this, 0, i, immutable())
    }

    private fun immutable(): Int =
        PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0)

    @Suppress("DEPRECATION")
    private fun buildNotification(text: String): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val b = if (Build.VERSION.SDK_INT >= 26) {
            if (nm.getNotificationChannel(CHANNEL) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, getString(R.string.vpn_notif_channel), NotificationManager.IMPORTANCE_LOW)
                )
            }
            Notification.Builder(this, CHANNEL)
        } else {
            Notification.Builder(this).setPriority(Notification.PRIORITY_LOW)
        }
        val stop = PendingIntent.getService(
            this, 1, Intent(this, WhiteHoleVpnService::class.java).setAction(ACTION_STOP), immutable()
        )
        return b.setSmallIcon(R.drawable.ic_stat_vpn)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setShowWhen(false)
            .setContentIntent(openAppIntent())
            .addAction(Notification.Action.Builder(R.drawable.ic_stat_vpn, getString(R.string.vpn_notif_stop), stop).build())
            .build()
    }

    private fun goForeground(text: String) {
        try {
            startForeground(NOTIF_ID, buildNotification(text))
            foreground = true
        } catch (e: Exception) {
            Log.e(TAG, "startForeground failed", e)
        }
    }

    @Suppress("DEPRECATION")
    private fun leaveForeground() {
        if (!foreground) return
        foreground = false
        try {
            stopForeground(true)
        } catch (e: Exception) {
            // ignore
        }
    }
}
