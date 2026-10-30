package space.whitehole.tv

import android.content.Context
import android.content.Intent
import android.media.tv.TvContract
import android.media.tv.TvInputInfo
import android.media.tv.TvInputManager

/** Входы HDMI/AV телевизора (passthrough), если система их отдаёт. На приставках обычно пусто. */
object TvInputs {

    class Input(val id: String, val label: String, val type: Int)

    fun list(context: Context): List<Input> {
        return try {
            val tim = context.getSystemService(Context.TV_INPUT_SERVICE) as? TvInputManager ?: return emptyList()
            val out = ArrayList<Input>()
            for (info in tim.tvInputList) {
                if (!info.isPassthroughInput) continue
                if (info.isHidden(context)) continue
                val label = info.loadLabel(context)?.toString()?.trim().orEmpty()
                out.add(Input(info.id, label.ifEmpty { fallbackLabel(info.type) }, info.type))
            }
            out
        } catch (e: Throwable) {
            emptyList()
        }
    }

    fun intentFor(input: Input): Intent =
        Intent(Intent.ACTION_VIEW, TvContract.buildChannelUriForPassthroughInput(input.id))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    private fun fallbackLabel(type: Int): String = when (type) {
        TvInputInfo.TYPE_HDMI -> "HDMI"
        TvInputInfo.TYPE_COMPONENT -> "Component"
        TvInputInfo.TYPE_COMPOSITE -> "AV"
        TvInputInfo.TYPE_SCART -> "SCART"
        TvInputInfo.TYPE_VGA -> "VGA"
        TvInputInfo.TYPE_DVI -> "DVI"
        else -> "Вход"
    }
}
