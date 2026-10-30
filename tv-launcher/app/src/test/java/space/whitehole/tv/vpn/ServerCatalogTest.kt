package space.whitehole.tv.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerCatalogTest {

    private val uuid = "11111111-2222-3333-4444-555555555555"

    private fun link(remark: String, addr: String, port: Int, type: String, flow: String = "", sni: String = "sni.example.org") =
        VlessLink(
            uuid, addr, port, remark,
            linkedMapOf("type" to type, "security" to "reality", "pbk" to "PBK", "sid" to "ab", "sni" to sni, "fp" to "firefox", "flow" to flow),
        )

    private val sub = listOf(
        link("⚡ Авто — 💻 для ПК", "203.0.113.1", 8443, "xhttp"),
        link("⚡ Авто — 📱 для телефона", "203.0.113.1", 443, "tcp", "xtls-rprx-vision"),
        link("🌉 Резерв — 📱", "198.51.100.53", 443, "tcp", "xtls-rprx-vision"),
        link("🇫🇷 Франция — 📱 для телефона", "203.0.113.2", 443, "tcp", "xtls-rprx-vision"),
        link("🇫🇷 Франция — 💻 для ПК", "203.0.113.2", 8443, "xhttp"),
        link("🇩🇪 Германия — 📱 для телефона", "203.0.113.3", 443, "tcp", "xtls-rprx-vision"),
        link("📶 Мобильный интернет", "198.51.100.53", 443, "tcp", "xtls-rprx-vision", sni = "yastatic.net"),
        link("🌉 Резерв 2 — 💻 если не работает", "198.51.100.54", 8443, "xhttp"),
        VlessLink("00000000-0000-0000-0000-000000000000", "0.0.0.0", 1, "Подписка истекла", mapOf("type" to "tcp")),
    )

    @Test
    fun cleansNames() {
        assertEquals("Франция", ServerCatalog.cleanName("🇫🇷 Франция — 📱 для телефона"))
        assertEquals("Германия", ServerCatalog.cleanName("🇩🇪 Германия — 💻 для ПК ^~2~^"))
        assertEquals("Резерв 2", ServerCatalog.cleanName("🌉 Резерв 2 — 📱/💻"))
        assertEquals("Мост", ServerCatalog.cleanName("Мост 💻 если не работает"))
        assertEquals("Нидерланды", ServerCatalog.cleanName("🇳🇱 Нидерланды"))
    }

    @Test
    fun groupsAndOrders() {
        val e = ServerCatalog.build(sub)
        assertEquals(listOf("Авто", "Франция", "Германия", "Резерв", "Мобильный интернет", "Резерв 2"), e.map { it.name })
        assertTrue(e[0].isAuto)
        assertFalse(e[1].isReserve)
        assertTrue(e[3].isReserve && e[4].isReserve && e[5].isReserve)
        // внутри — сначала TCP+Vision, потом XHTTP
        assertEquals(listOf("tcp", "xhttp"), e[0].links.map { it.network })
        assertEquals(listOf("tcp", "xhttp"), e[1].links.map { it.network })
    }

    @Test
    fun dropsPlaceholderLinks() {
        assertTrue(ServerCatalog.build(sub).none { it.name.contains("истекла") })
    }

    @Test
    fun planForAuto() {
        val plan = ServerCatalog.attemptPlan(ServerCatalog.build(sub), ServerCatalog.AUTO_KEY)
        assertEquals(4, plan.size)
        assertEquals("Авто", plan[0].entry.name)
        assertEquals("tcp", plan[0].link.network)
        assertEquals("xhttp", plan[1].link.network)
        assertEquals("Франция", plan[2].entry.name)
        assertEquals("Резерв", plan[3].entry.name)
    }

    @Test
    fun planForCountryAndUnknownKey() {
        val entries = ServerCatalog.build(sub)
        val plan = ServerCatalog.attemptPlan(entries, "германия")
        assertEquals(listOf("Германия", "Резерв"), plan.map { it.entry.name })
        // сервер пропал из подписки — откатываемся на Авто
        assertEquals("Авто", ServerCatalog.attemptPlan(entries, "япония")[0].entry.name)
        // выбран резерв — только он
        assertEquals(listOf("Резерв 2"), ServerCatalog.attemptPlan(entries, "резерв 2").map { it.entry.name })
    }

    @Test
    fun noAutoFallsBackToFirstCountry() {
        val noAuto = sub.filter { !it.remark.contains("Авто") }
        val plan = ServerCatalog.attemptPlan(ServerCatalog.build(noAuto), "")
        assertEquals("Франция", plan[0].entry.name)
    }

    @Test
    fun emptySubscription() {
        assertTrue(ServerCatalog.attemptPlan(emptyList(), "").isEmpty())
    }
}
