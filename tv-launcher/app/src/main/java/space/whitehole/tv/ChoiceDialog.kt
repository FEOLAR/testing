package space.whitehole.tv

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Простой выбор из списка поверх экрана (пульт: вверх/вниз, ОК — выбрать, «Назад» — закрыть).
 * Пока открыт, остальной экран не получает фокус (content блокируется снаружи через onShow/onHide).
 */
class ChoiceDialog(
    private val root: ViewGroup,
    private val onShow: () -> Unit,
    private val onHide: () -> Unit,
    private val focusAnim: (View) -> Unit
) {
    private var view: View? = null
    private var restoreFocus: View? = null

    val isShowing: Boolean get() = view != null

    fun show(title: String, options: List<String>, selected: Int, onPick: (Int) -> Unit) {
        dismiss()
        restoreFocus = root.findFocus()
        val v = LayoutInflater.from(root.context).inflate(R.layout.dialog_choice, root, false)
        v.findViewById<TextView>(R.id.choice_title).text = title
        val list = v.findViewById<LinearLayout>(R.id.choice_list)
        var toFocus: View? = null
        for ((i, text) in options.withIndex()) {
            val row = LayoutInflater.from(root.context).inflate(R.layout.item_setting, list, false)
            row.findViewById<TextView>(R.id.setting_title).text = text
            row.findViewById<TextView>(R.id.setting_value).text = if (i == selected) "•" else ""
            row.setOnClickListener {
                dismiss()
                onPick(i)
            }
            focusAnim(row)
            list.addView(row)
            if (i == selected) toFocus = row
        }
        if (toFocus == null) toFocus = list.getChildAt(0)
        v.setOnClickListener { dismiss() }
        root.addView(v)
        view = v
        onShow()
        toFocus?.requestFocus()
    }

    fun dismiss() {
        val v = view ?: return
        view = null
        root.removeView(v)
        onHide()
        val f = restoreFocus
        restoreFocus = null
        if (f != null && f.isShown) f.requestFocus()
    }
}
