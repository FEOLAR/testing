package space.whitehole.tv.vpn

import android.app.Activity
import android.content.Intent
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import space.whitehole.tv.ConnectAnimator
import space.whitehole.tv.ConnectState
import space.whitehole.tv.R
import space.whitehole.tv.Session

/**
 * Всё, что встроенный VPN меняет на главном экране, — в одном месте (минимум правок в MainActivity):
 * большая кнопка «Подключить/Отключить», кнопка «Сервер: …» рядом с ней и строка статуса.
 */
class VpnHomeHook(
    private val activity: Activity,
    private val btnConnect: TextView,
    private val statusDot: View,
    private val statusText: TextView,
    /** Анимация подключения главного экрана (HomeConnectAnimator) — общий вход для Happ и встроенного VPN. */
    private val animator: ConnectAnimator?,
    private val onChanged: () -> Unit,
) {
    /** Встроенный VPN доступен (Android 7+). Иначе лаунчер работает по-старому, через Happ. */
    val enabled: Boolean = VpnController.isSupported()

    private var btnServer: TextView? = null
    private var lastStatus: VpnStatus? = null
    private var paired = false

    private val listener: (VpnStatus) -> Unit = { s -> onState(s) }

    init {
        if (enabled) {
            VpnState.bindUi(activity)
            VpnState.addListener(listener)
            btnServer = createServerButton()
        }
    }

    fun onResume() {
        if (!enabled) return
        VpnState.reload(activity)
        btnServer?.text = activity.getString(R.string.vpn_btn_server, VpnFiles.serverName(activity))
        onState(VpnState.status)
    }

    fun release() {
        VpnState.removeListener(listener)
    }

    /** Подпись большой кнопки, когда телевизор привязан (null — встроенного VPN нет). */
    fun connectLabel(): String? {
        if (!enabled) return null
        return activity.getString(if (VpnState.isActive) R.string.vpn_btn_disconnect else R.string.vpn_btn_connect)
    }

    fun setPaired(p: Boolean) {
        paired = p
        btnServer?.visibility = if (enabled && p) View.VISIBLE else View.GONE
    }

    /** Телевизор отвязан — выключить VPN (подписки больше нет). */
    fun onUnpaired() {
        if (enabled && VpnState.isActive) VpnController.disconnect(activity)
        else if (enabled) VpnFiles.setWanted(activity, false)
    }

    fun toggle(session: Session) = VpnController.toggle(activity, session)

    fun connect(session: Session) {
        if (!VpnState.isActive) VpnController.connect(activity, session)
    }

    /**
     * Статус «Защищено/Подключение…/Ошибка» нашего VPN. false — наш VPN выключен,
     * пусть MainActivity покажет общий статус (вдруг включён Happ или другой VPN).
     */
    fun applyStatus(): Boolean {
        if (!enabled) return false
        when (VpnState.status) {
            VpnStatus.CONNECTED -> {
                statusDot.setBackgroundResource(R.drawable.dot_green)
                val srv = VpnState.server
                statusText.text = if (srv.isNotEmpty()) activity.getString(R.string.vpn_status_on, srv)
                else activity.getString(R.string.status_on)
            }
            VpnStatus.CONNECTING -> {
                statusDot.setBackgroundResource(R.drawable.dot_yellow)
                statusText.setText(R.string.vpn_status_connecting)
            }
            VpnStatus.ERROR -> {
                statusDot.setBackgroundResource(R.drawable.dot_red)
                statusText.setText(R.string.vpn_status_error)
            }
            VpnStatus.DISCONNECTED -> return false
        }
        return true
    }

    private fun onState(s: VpnStatus) {
        if (s == lastStatus) {
            onChanged()
            return
        }
        val prev = lastStatus
        lastStatus = s
        if (s == VpnStatus.ERROR && prev != null && VpnState.message.isNotEmpty()) {
            Toast.makeText(activity, VpnState.message, Toast.LENGTH_LONG).show()
        }
        if (prev != null) animator?.play(toConnectState(s))
        onChanged()
    }

    private fun toConnectState(s: VpnStatus): ConnectState = when (s) {
        VpnStatus.DISCONNECTED -> ConnectState.IDLE
        VpnStatus.CONNECTING -> ConnectState.CONNECTING
        VpnStatus.CONNECTED -> ConnectState.CONNECTED
        VpnStatus.ERROR -> ConnectState.FAILED
    }

    private fun createServerButton(): TextView? {
        val parent = btnConnect.parent as? LinearLayout ?: return null
        val b = TextView(activity, null, 0, R.style.WhButton)
        b.id = View.generateViewId()
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        lp.leftMargin = (16 * activity.resources.displayMetrics.density + 0.5f).toInt()
        b.nextFocusUpId = btnConnect.nextFocusUpId
        b.text = activity.getString(R.string.vpn_btn_server, VpnFiles.serverName(activity))
        b.visibility = View.GONE
        b.setOnClickListener { activity.startActivity(Intent(activity, ServerPickerActivity::class.java)) }
        b.setOnFocusChangeListener { v, has ->
            val s = if (has) 1.06f else 1f
            v.animate().scaleX(s).scaleY(s).translationZ(if (has) 6 * activity.resources.displayMetrics.density else 0f)
                .setDuration(140).start()
        }
        parent.addView(b, parent.indexOfChild(btnConnect) + 1, lp)
        return b
    }
}
