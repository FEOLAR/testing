package space.whitehole.tv.vpn

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import space.whitehole.tv.R
import space.whitehole.tv.Session

/** Команды встроенному VPN из лаунчера (процесс UI). */
object VpnController {

    /** libv2ray.aar собран под Android 7+ (API 24); на 5–6 остаётся только Happ. */
    fun isSupported(): Boolean = Build.VERSION.SDK_INT >= 24

    fun toggle(activity: Activity, session: Session) {
        if (VpnState.isActive) disconnect(activity) else connect(activity, session)
    }

    fun connect(activity: Activity, session: Session) {
        val sub = session.subUrl
        if (sub.isNullOrEmpty()) {
            Toast.makeText(activity, R.string.vpn_err_no_sub_url, Toast.LENGTH_LONG).show()
            return
        }
        VpnFiles.setWanted(activity, true)
        VpnState.setLocal(VpnStatus.CONNECTING)
        activity.startActivity(
            Intent(activity, VpnConsentActivity::class.java)
                .putExtra(WhiteHoleVpnService.EXTRA_SUB_URL, sub)
                .putExtra(WhiteHoleVpnService.EXTRA_SERVER, VpnFiles.serverKey(activity))
        )
    }

    fun disconnect(ctx: Context) {
        VpnFiles.setWanted(ctx, false)
        VpnState.setLocal(VpnStatus.DISCONNECTED, "", "")
        try {
            ctx.startService(Intent(ctx, WhiteHoleVpnService::class.java).setAction(WhiteHoleVpnService.ACTION_STOP))
        } catch (e: Exception) {
            Log.w("WhVpn", "stop failed: ${e.message}")
        }
    }

    /** Сменили сервер — переподключиться, если VPN включён. */
    fun applyServerChange(ctx: Context, session: Session) {
        if (!VpnState.isActive) return
        val sub = session.subUrl ?: return
        VpnState.setLocal(VpnStatus.CONNECTING)
        startService(ctx, sub, VpnFiles.serverKey(ctx))
    }

    /** Запуск службы (разрешение VPN уже есть). */
    fun startService(ctx: Context, subUrl: String, serverKey: String): Boolean {
        val i = Intent(ctx, WhiteHoleVpnService::class.java)
            .setAction(WhiteHoleVpnService.ACTION_START)
            .putExtra(WhiteHoleVpnService.EXTRA_SUB_URL, subUrl)
            .putExtra(WhiteHoleVpnService.EXTRA_SERVER, serverKey)
        return try {
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
            true
        } catch (e: Exception) {
            Log.e("WhVpn", "start failed", e)
            false
        }
    }
}

/**
 * Невидимый экран: один раз спрашивает разрешение Android на VPN (VpnService.prepare) и запускает службу.
 * Отдельная activity, чтобы не трогать onActivityResult главного экрана.
 */
class VpnConsentActivity : Activity() {
    private var sub: String = ""
    private var server: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sub = intent.getStringExtra(WhiteHoleVpnService.EXTRA_SUB_URL) ?: ""
        server = intent.getStringExtra(WhiteHoleVpnService.EXTRA_SERVER) ?: ""
        if (savedInstanceState != null) return // ждём результат после пересоздания
        val consent = try {
            VpnService.prepare(this)
        } catch (e: Exception) {
            null
        }
        if (consent == null) {
            launch()
            return
        }
        try {
            startActivityForResult(consent, REQ)
        } catch (e: Exception) {
            // На некоторых ТВ-прошивках нет системного окна разрешения VPN
            fail(getString(R.string.vpn_err_no_dialog))
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ) return
        if (resultCode == RESULT_OK) launch() else fail(getString(R.string.vpn_err_consent))
    }

    private fun launch() {
        if (sub.isEmpty() || !VpnController.startService(this, sub, server)) fail(getString(R.string.vpn_err_core))
        finish()
    }

    private fun fail(msg: String) {
        VpnFiles.setWanted(this, false)
        VpnState.setLocal(VpnStatus.ERROR, "", msg)
        finish()
    }

    companion object {
        private const val REQ = 4201
    }
}

/** После перезагрузки: если VPN был включён и разрешение не отозвано — подключиться снова. */
class VpnBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val a = intent.action ?: return
        if (a != Intent.ACTION_BOOT_COMPLETED && a != "android.intent.action.QUICKBOOT_POWERON" &&
            a != Intent.ACTION_MY_PACKAGE_REPLACED
        ) return
        if (!VpnController.isSupported() || !VpnFiles.wanted(context)) return
        val session = Session(context)
        val sub = session.subUrl
        if (!session.paired || sub.isNullOrEmpty()) return
        val prepared = try {
            VpnService.prepare(context) == null
        } catch (e: Exception) {
            false
        }
        if (!prepared) return
        Log.i("WhVpn", "auto-connect after $a")
        VpnController.startService(context, sub, VpnFiles.serverKey(context))
    }
}
