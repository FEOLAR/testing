package space.whitehole.tv

import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.view.View
import android.view.animation.CycleInterpolator

/** Состояния кнопки «Подключиться» — общий вход для Happ и для встроенного VPN. */
enum class ConnectState { IDLE, CONNECTING, CONNECTED, FAILED }

/** Анимация подключения. Оба пути подключения вызывают только play(state). */
interface ConnectAnimator {
    fun play(state: ConnectState)
}

/**
 * Главная: кольцо сжимается в чёрную дыру → при успехе зелёная вспышка и мягкая пульсация «Защищено»,
 * при ошибке — короткая тряска кнопки и красная вспышка. Без анимаций (настройка/слабое ТВ) — ничего не делает,
 * статус всё равно обновляется обычным способом.
 */
class HomeConnectAnimator(
    private val blackHole: BlackHoleView,
    private val statusChip: View,
    private val button: View,
    private val animationsOn: () -> Boolean
) : ConnectAnimator {

    var state: ConnectState = ConnectState.IDLE
        private set

    private var pulse: ObjectAnimator? = null
    private var pulseY: ObjectAnimator? = null

    override fun play(state: ConnectState) {
        this.state = state
        if (!animationsOn()) {
            blackHole.stopConnect()
            stopPulse()
            return
        }
        when (state) {
            ConnectState.IDLE -> {
                blackHole.stopConnect()
                stopPulse()
            }
            ConnectState.CONNECTING -> {
                stopPulse()
                blackHole.playContract(0xFFFFFFFF.toInt())
            }
            ConnectState.CONNECTED -> {
                blackHole.playResult(GREEN)
                startPulse()
            }
            ConnectState.FAILED -> {
                stopPulse()
                blackHole.playResult(RED)
                val shake = ObjectAnimator.ofFloat(button, View.TRANSLATION_X, 0f, button.resources.displayMetrics.density * 10f)
                shake.interpolator = CycleInterpolator(3f)
                shake.duration = 420
                shake.start()
            }
        }
    }

    private fun startPulse() {
        stopPulse()
        val x = ObjectAnimator.ofFloat(statusChip, View.SCALE_X, 1f, 1.07f)
        val y = ObjectAnimator.ofFloat(statusChip, View.SCALE_Y, 1f, 1.07f)
        for (a in listOf(x, y)) {
            a.duration = 700
            a.repeatMode = ValueAnimator.REVERSE
            a.repeatCount = 5
            a.start()
        }
        pulse = x
        pulseY = y
    }

    private fun stopPulse() {
        pulse?.cancel()
        pulseY?.cancel()
        pulse = null
        pulseY = null
        statusChip.scaleX = 1f
        statusChip.scaleY = 1f
    }

    companion object {
        const val GREEN = 0xFF34D399.toInt()
        const val RED = 0xFFF87171.toInt()
    }
}
