package space.whitehole.tv.vpn

import android.content.Context
import android.util.Log

/** Чтение профиля маршрутизации из assets/routing/ (копии infra/happ-routing*.json). */
object RoutingStore {
    private const val TAG = "WhVpnRouting"
    const val PROFILE = "routing/happ-routing.json"
    const val ADBLOCK = "routing/happ-routing-adblock.json"

    private fun asset(ctx: Context, name: String): String? = try {
        ctx.assets.open(name).use { String(it.readBytes(), Charsets.UTF_8) }
    } catch (e: Exception) {
        null
    }

    fun load(ctx: Context, adblock: Boolean): RoutingProfile {
        var p = try {
            asset(ctx, PROFILE)?.let { RoutingProfile.parse(it) }
        } catch (e: Exception) {
            Log.w(TAG, "bad $PROFILE: ${e.message}")
            null
        } ?: RuRouting.DEFAULT
        if (adblock) {
            try {
                asset(ctx, ADBLOCK)?.let { RoutingProfile.parseBlockLists(it) }?.let { (sites, ips) -> p = p.withBlock(sites, ips) }
            } catch (e: Exception) {
                Log.w(TAG, "bad $ADBLOCK: ${e.message}")
            }
        }
        Log.i(TAG, "profile '${p.name}': direct=${p.directSites.size}/${p.directIp.size} proxy=${p.proxySites.size} block=${p.blockSites.size} adblock=$adblock")
        return p
    }
}
