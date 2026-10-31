package space.whitehole.tv.vpn

import org.json.JSONArray
import org.json.JSONObject

/**
 * Профиль маршрутизации в формате Happ (infra/happ-routing.json — тот же, что отдаёт панель в заголовке
 * `routing`). В APK лежит копией в assets/routing/; чтобы поменять правила, достаточно заменить файл.
 */
class RoutingProfile(
    val name: String,
    val globalProxy: Boolean,
    val remoteDnsType: String,
    val remoteDnsDomain: String,
    val remoteDnsIp: String,
    val domesticDnsType: String,
    val domesticDnsDomain: String,
    val domesticDnsIp: String,
    val dnsHosts: Map<String, String>,
    val directSites: List<String>,
    val directIp: List<String>,
    val proxySites: List<String>,
    val proxyIp: List<String>,
    val blockSites: List<String>,
    val blockIp: List<String>,
    val domainStrategy: String,
    val routeOrder: List<String>,
) {
    /**
     * Адрес удалённого DNS для Xray. DoH — по IP (https://1.1.1.1/dns-query), чтобы не нужен был
     * отдельный DNS для имени самого DoH-сервера; запросы идут через VPN (1.1.1.1 — не RU).
     */
    fun remoteDnsAddress(): String = when (remoteDnsType.lowercase()) {
        "doh" -> {
            val path = remoteDnsDomain.substringAfter("://", "").substringAfter('/', "dns-query")
            if (remoteDnsIp.isNotEmpty()) "https://$remoteDnsIp/$path" else remoteDnsDomain
        }
        else -> remoteDnsIp.ifEmpty { "1.1.1.1" }
    }

    /** Российский DNS (DoU = обычный UDP) — напрямую. */
    fun domesticDnsAddress(): String = when (domesticDnsType.lowercase()) {
        "doh" -> domesticDnsDomain.ifEmpty { domesticDnsIp }
        else -> domesticDnsIp.ifEmpty { "77.88.8.8" }
    }

    /** Копия с другими BlockSites/BlockIp (тестовый блок рекламы). */
    fun withBlock(sites: List<String>, ips: List<String>): RoutingProfile = RoutingProfile(
        name, globalProxy, remoteDnsType, remoteDnsDomain, remoteDnsIp, domesticDnsType, domesticDnsDomain,
        domesticDnsIp, dnsHosts, directSites, directIp, proxySites, proxyIp,
        (blockSites + sites).distinct(), (blockIp + ips).distinct(), domainStrategy, routeOrder,
    )

    companion object {
        fun parse(text: String): RoutingProfile {
            val j = JSONObject(text)
            fun list(key: String): List<String> {
                val a: JSONArray = j.optJSONArray(key) ?: return emptyList()
                return (0 until a.length()).map { a.optString(it, "").trim() }.filter { it.isNotEmpty() }
            }
            val hosts = LinkedHashMap<String, String>()
            j.optJSONObject("DnsHosts")?.let { h -> h.keys().forEach { k -> hosts[k] = h.optString(k) } }
            val order = j.optString("RouteOrder", "block-proxy-direct").lowercase().split('-')
                .map { it.trim() }.filter { it in setOf("block", "proxy", "direct") }.distinct()
            return RoutingProfile(
                name = j.optString("Name", ""),
                globalProxy = j.optString("GlobalProxy", "true").lowercase() != "false",
                remoteDnsType = j.optString("RemoteDNSType", "DoH"),
                remoteDnsDomain = j.optString("RemoteDNSDomain", "https://cloudflare-dns.com/dns-query"),
                remoteDnsIp = j.optString("RemoteDNSIP", "1.1.1.1"),
                domesticDnsType = j.optString("DomesticDNSType", "DoU"),
                domesticDnsDomain = j.optString("DomesticDNSDomain", ""),
                domesticDnsIp = j.optString("DomesticDNSIP", "77.88.8.8"),
                dnsHosts = hosts,
                directSites = list("DirectSites"),
                directIp = list("DirectIp"),
                proxySites = list("ProxySites"),
                proxyIp = list("ProxyIp"),
                blockSites = list("BlockSites"),
                blockIp = list("BlockIp"),
                domainStrategy = j.optString("DomainStrategy", "IPIfNonMatch").ifEmpty { "IPIfNonMatch" },
                routeOrder = (order + listOf("block", "proxy", "direct")).distinct(),
            )
        }

        /** Только BlockSites/BlockIp из профиля-с-блокировкой (infra/happ-routing-adblock.json). */
        fun parseBlockLists(text: String): Pair<List<String>, List<String>> {
            val p = parse(text)
            return p.blockSites to p.blockIp
        }
    }
}
