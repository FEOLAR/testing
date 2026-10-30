package space.whitehole.tv

import android.content.Context
import org.json.JSONObject

/** Привязка телевизора к подписке: токен устройства, ссылка-подписка и последние данные /me. */
class Session(context: Context) {
    private val prefs = context.getSharedPreferences("tv_session", Context.MODE_PRIVATE)

    val token: String? get() = prefs.getString(KEY_TOKEN, null)
    val paired: Boolean get() = !token.isNullOrEmpty()

    var subUrl: String?
        get() = prefs.getString(KEY_SUB, null)
        set(v) {
            prefs.edit().putString(KEY_SUB, v).apply()
        }

    /** Какую ссылку мы уже отдали в Happ (чтобы не добавлять одну и ту же подписку каждый раз). */
    var pushedSubUrl: String?
        get() = prefs.getString(KEY_PUSHED, null)
        set(v) {
            prefs.edit().putString(KEY_PUSHED, v).apply()
        }

    val me: JSONObject?
        get() = try {
            prefs.getString(KEY_ME, null)?.let { JSONObject(it) }
        } catch (e: Exception) {
            null
        }

    val meAt: Long get() = prefs.getLong(KEY_ME_AT, 0L)

    fun saveMe(json: JSONObject) {
        val e = prefs.edit().putString(KEY_ME, json.toString()).putLong(KEY_ME_AT, System.currentTimeMillis())
        val sub = json.optString("sub_url", "")
        if (sub.isNotEmpty() && sub != "null") e.putString(KEY_SUB, sub)
        e.apply()
    }

    fun save(token: String, subUrl: String?) {
        prefs.edit().putString(KEY_TOKEN, token).putString(KEY_SUB, subUrl)
            .remove(KEY_ME).putLong(KEY_ME_AT, 0L).apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_TOKEN = "token"
        private const val KEY_SUB = "sub_url"
        private const val KEY_PUSHED = "pushed_sub_url"
        private const val KEY_ME = "me"
        private const val KEY_ME_AT = "me_at"
    }
}
