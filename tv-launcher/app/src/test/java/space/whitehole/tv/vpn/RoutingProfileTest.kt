package space.whitehole.tv.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Профиль Happ из assets/routing (копия infra/happ-routing.json) → правила Xray. */
class RoutingProfileTest {

    private fun asset(name: String): String {
        // gradle запускает тесты из папки модуля (app/); локально можно задать WH_ASSETS
        val base = System.getenv("WH_ASSETS") ?: "src/main/assets"
        return File(base, "routing/$name").readText()
    }

    private val profile by lazy { RoutingProfile.parse(asset("happ-routing.json")) }
    private val uuid = "11111111-2222-3333-4444-555555555555"
    private val link = ShareLinkParser.parseVless(
        "vless://$uuid@203.0.113.10:443?security=reality&type=tcp&flow=xtls-rprx-vision&sni=s.example.org&fp=firefox&pbk=P&sid=1#x"
    )!!

    private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }
    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    private fun rules(opt: CoreOptions) =
        JSONObject(XrayConfigBuilder.build(link, opt)).getJSONObject("routing").getJSONArray("rules").objects()

    @Test
    fun parsesHappProfile() {
        val p = profile
        assertTrue(p.globalProxy)
        assertEquals("IPIfNonMatch", p.domainStrategy)
        assertEquals(listOf("block", "proxy", "direct"), p.routeOrder)
        assertTrue(p.directSites.size >= 150)
        assertTrue(p.directSites.containsAll(listOf("domain:ru", "domain:su", "domain:xn--p1ai", "domain:gosuslugi.ru", "domain:steampowered.com")))
        assertTrue(p.directIp.containsAll(listOf("geoip:ru", "77.88.8.8/32", "155.133.224.0/19", "162.254.192.0/21")))
        assertTrue(p.proxySites.containsAll(listOf("domain:youtube.com", "domain:googlevideo.com", "domain:telegram.org", "domain:t.me")))
        assertTrue(p.blockSites.isEmpty())
        assertEquals("https://1.1.1.1/dns-query", p.remoteDnsAddress())
        assertEquals("77.88.8.8", p.domesticDnsAddress())
    }

    @Test
    fun allProfileRulesReachConfigInOrder() {
        val r = rules(CoreOptions(geoipRu = true, profile = profile))
        val proxyIdx = r.indexOfFirst { it.optJSONArray("domain")?.strings()?.contains("domain:youtube.com") == true }
        val directIdx = r.indexOfFirst { it.optJSONArray("domain")?.strings()?.contains("domain:ru") == true }
        val directIpIdx = r.indexOfFirst { it.optJSONArray("ip")?.strings()?.contains("geoip:ru") == true }
        assertTrue(proxyIdx in 0 until directIdx)
        assertTrue(directIdx < directIpIdx)
        assertEquals("proxy", r[proxyIdx].getString("outboundTag"))
        assertEquals("direct", r[directIdx].getString("outboundTag"))
        assertEquals(profile.directSites.size, r[directIdx].getJSONArray("domain").length())
        assertTrue(r[directIpIdx].getJSONArray("ip").strings().contains("155.133.224.0/19"))
        assertEquals("proxy", r.last().getString("outboundTag"))
        assertTrue(r.none { it.optString("outboundTag") == "block" && it.has("domain") })
    }

    @Test
    fun dnsMatchesProfile() {
        val dns = JSONObject(XrayConfigBuilder.build(link, CoreOptions(true, profile = profile))).getJSONObject("dns")
        val servers = dns.getJSONArray("servers")
        val domestic = servers.getJSONObject(0)
        assertEquals("77.88.8.8", domestic.getString("address"))
        assertTrue(domestic.getJSONArray("domains").strings().contains("domain:gosuslugi.ru"))
        assertFalse(domestic.getJSONArray("domains").strings().contains("domain:youtube.com"))
        assertEquals("https://1.1.1.1/dns-query", servers.getString(1))
        val cfg = JSONObject(XrayConfigBuilder.build(link, CoreOptions(true, profile = profile)))
        assertEquals("IPIfNonMatch", cfg.getJSONObject("routing").getString("domainStrategy"))
    }

    @Test
    fun withoutGeoFileNoGeoipButRestStays() {
        val text = XrayConfigBuilder.build(link, CoreOptions(geoipRu = false, profile = profile))
        assertFalse(text.contains("geoip:"))
        assertFalse(text.contains("geosite:"))
        val r = rules(CoreOptions(geoipRu = false, profile = profile))
        assertTrue(r.any { it.optJSONArray("ip")?.strings()?.contains("155.133.224.0/19") == true })
    }

    @Test
    fun adblockAddsBlockRulesFirst() {
        val (sites, ips) = RoutingProfile.parseBlockLists(asset("happ-routing-adblock.json"))
        assertTrue(sites.contains("domain:doubleclick.net"))
        val p = profile.withBlock(sites, ips)
        val r = rules(CoreOptions(true, profile = p))
        val blockIdx = r.indexOfFirst { it.optString("outboundTag") == "block" && it.has("domain") }
        val proxyIdx = r.indexOfFirst { it.optJSONArray("domain")?.strings()?.contains("domain:youtube.com") == true }
        assertTrue(blockIdx in 0 until proxyIdx)
        assertTrue(r[blockIdx].getJSONArray("domain").strings().contains("full:an.yandex.ru"))
        // без тумблера блокировки нет
        assertTrue(rules(CoreOptions(true, profile = profile)).none { it.optString("outboundTag") == "block" && it.has("domain") })
    }

    @Test
    fun filtersUnsupportedGeoEntries() {
        assertEquals(listOf("domain:a.ru"), XrayConfigBuilder.sites(listOf("geosite:category-ru", "domain:a.ru", "ext:x.dat:y")))
        assertEquals(listOf("geoip:ru", "1.2.3.0/24"), XrayConfigBuilder.ips(listOf("geoip:ru", "geoip:private", "1.2.3.0/24"), true))
        assertEquals(listOf("1.2.3.0/24"), XrayConfigBuilder.ips(listOf("geoip:ru", "1.2.3.0/24"), false))
    }
}
