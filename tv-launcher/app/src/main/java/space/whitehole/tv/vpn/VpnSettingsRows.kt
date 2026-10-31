package space.whitehole.tv.vpn

import space.whitehole.tv.MainActivity
import space.whitehole.tv.R
import space.whitehole.tv.SettingsScreen

/** Строки встроенного VPN на экране «Настройки». */
object VpnSettingsRows {
    fun add(screen: SettingsScreen, a: MainActivity) {
        if (!VpnController.isSupported()) return
        val on = VpnFiles.adblock(a)
        screen.add("vpn_adblock", a.getString(R.string.vpn_set_adblock), a.getString(if (on) R.string.on else R.string.off)) {
            VpnFiles.setAdblock(a, !on)
            // правила меняются только при запуске ядра — переподключаемся, если VPN включён
            VpnController.applyServerChange(a, a.session)
            screen.rebuild("vpn_adblock")
        }
    }
}
