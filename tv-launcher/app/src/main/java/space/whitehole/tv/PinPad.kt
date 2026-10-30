package space.whitehole.tv

import android.animation.ObjectAnimator
import android.view.Gravity
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.CycleInterpolator
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Ввод 4-значного PIN пультом: экранная клавиатура 3×4 (стрелки + ОК) или цифры на пульте.
 * onDone(pin) → true — закрыть, false — «неверно» (тряска, очистка).
 */
class PinPad(
    private val root: ViewGroup,
    private val onShow: () -> Unit,
    private val onHide: () -> Unit,
    private val focusAnim: (View) -> Unit
) {
    private var view: View? = null
    private var pin = StringBuilder()
    private var onDone: ((String) -> Boolean)? = null
    private var onCancel: (() -> Unit)? = null
    private var restoreFocus: View? = null

    val isShowing: Boolean get() = view != null

    fun show(title: String, done: (String) -> Boolean, cancel: () -> Unit) {
        dismiss(false)
        restoreFocus = root.findFocus()
        val ctx = root.context
        val v = LayoutInflater.from(ctx).inflate(R.layout.dialog_pin, root, false)
        v.findViewById<TextView>(R.id.pin_title).text = title
        v.findViewById<TextView>(R.id.pin_error).text = ""
        val grid = v.findViewById<GridLayout>(R.id.pin_grid)
        val keys = listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", ctx.getString(R.string.pin_erase), "0", ctx.getString(R.string.pin_cancel))
        val density = ctx.resources.displayMetrics.density
        var first: View? = null
        for (k in keys) {
            val b = TextView(ctx, null, 0, R.style.WhButton)
            b.text = k
            b.gravity = Gravity.CENTER
            if (k.length > 1) b.textSize = 13f
            val pad = (6 * density).toInt()
            b.setPadding(pad, 0, pad, 0)
            val lp = GridLayout.LayoutParams()
            lp.width = (88 * density).toInt()
            lp.height = (48 * density).toInt()
            val m = (5 * density).toInt()
            lp.setMargins(m, m, m, m)
            b.layoutParams = lp
            b.setOnClickListener { press(k) }
            b.setOnKeyListener { _, keyCode, event ->
                if (keyCode >= KeyEvent.KEYCODE_0 && keyCode <= KeyEvent.KEYCODE_9) {
                    if (event.action == KeyEvent.ACTION_UP) press((keyCode - KeyEvent.KEYCODE_0).toString())
                    true
                } else if (keyCode == KeyEvent.KEYCODE_DEL) {
                    if (event.action == KeyEvent.ACTION_UP) press(ctx.getString(R.string.pin_erase))
                    true
                } else {
                    false
                }
            }
            focusAnim(b)
            grid.addView(b)
            if (first == null) first = b
        }
        pin = StringBuilder()
        onDone = done
        onCancel = cancel
        root.addView(v)
        view = v
        updateDots()
        onShow()
        first?.requestFocus()
    }

    private fun press(k: String) {
        val v = view ?: return
        val ctx = v.context
        when {
            k == ctx.getString(R.string.pin_cancel) -> cancel()
            k == ctx.getString(R.string.pin_erase) -> {
                if (pin.isNotEmpty()) pin.setLength(pin.length - 1)
                updateDots()
            }
            k.length == 1 && pin.length < 4 -> {
                pin.append(k)
                updateDots()
                if (pin.length == 4) {
                    val entered = pin.toString()
                    val cb = onDone
                    val ok = cb?.invoke(entered) ?: true
                    if (ok) {
                        dismiss(true)
                    } else if (view === v) {
                        pin = StringBuilder()
                        updateDots()
                        v.findViewById<TextView>(R.id.pin_error).setText(R.string.pin_wrong)
                        val card = v.findViewById<View>(R.id.pin_card)
                        val shake = ObjectAnimator.ofFloat(card, View.TRANSLATION_X, 0f, 12f * ctx.resources.displayMetrics.density)
                        shake.interpolator = CycleInterpolator(3f)
                        shake.duration = 400
                        shake.start()
                    }
                }
            }
        }
    }

    /** Показать текст-подсказку под заголовком (например, «PIN-коды не совпали»). */
    fun setError(text: String) {
        view?.findViewById<TextView>(R.id.pin_error)?.text = text
    }

    private fun updateDots() {
        val v = view ?: return
        val dots = v.findViewById<LinearLayout>(R.id.pin_dots)
        for (i in 0 until dots.childCount) {
            dots.getChildAt(i).setBackgroundResource(if (i < pin.length) R.drawable.pin_dot_full else R.drawable.pin_dot_empty)
        }
    }

    fun cancel() {
        val c = onCancel
        dismiss(true)
        c?.invoke()
    }

    /** Закрыть; restore — вернуть фокус туда, где он был. */
    fun dismiss(restore: Boolean) {
        val v = view ?: return
        view = null
        onDone = null
        onCancel = null
        root.removeView(v)
        onHide()
        val f = restoreFocus
        restoreFocus = null
        if (restore && f != null && f.isShown) f.requestFocus()
    }
}
