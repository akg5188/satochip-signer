package io.arbitrum.wallet

import android.app.Application
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner

private object AppLockState : DefaultLifecycleObserver {
    private var installed = false
    private var unlocked = false

    fun install(application: Application) {
        if (installed) return
        installed = true
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    fun isUnlocked(): Boolean = unlocked

    fun markUnlocked() {
        unlocked = true
    }

    override fun onStop(owner: LifecycleOwner) {
        unlocked = false
    }
}

abstract class BiometricGateActivity : FragmentActivity() {
    private var biometricPrompt: BiometricPrompt? = null
    private var authInProgress = false
    private var lockOverlay: FrameLayout? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppLockState.install(application)
    }

    override fun onPostCreate(savedInstanceState: Bundle?) {
        super.onPostCreate(savedInstanceState)
        ensureLockOverlayVisible()
    }

    override fun onStart() {
        super.onStart()
        ensureUnlocked()
    }

    protected open fun biometricTitle(): String = "解锁钱包"

    protected open fun biometricSubtitle(): String = "请验证指纹以进入 Satochip"

    protected open fun onBiometricUnlocked() = Unit

    private fun ensureUnlocked() {
        if (AppLockState.isUnlocked()) {
            dismissLockOverlay()
            return
        }
        ensureLockOverlayVisible()
        if (authInProgress) return

        val authenticators =
            BiometricManager.Authenticators.BIOMETRIC_STRONG or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
        val biometricManager = BiometricManager.from(this)
        when (biometricManager.canAuthenticate(authenticators)) {
            BiometricManager.BIOMETRIC_SUCCESS -> showBiometricPrompt(authenticators)
            else -> {
                Toast.makeText(this, "当前设备未配置可用的指纹或锁屏凭证", Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun showBiometricPrompt(authenticators: Int) {
        authInProgress = true
        biometricPrompt = BiometricPrompt(
            this,
            ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    authInProgress = false
                    AppLockState.markUnlocked()
                    dismissLockOverlay()
                    onBiometricUnlocked()
                }

                override fun onAuthenticationFailed() {
                    ensureLockOverlayVisible()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    authInProgress = false
                    if (AppLockState.isUnlocked()) return
                    when (errorCode) {
                        BiometricPrompt.ERROR_CANCELED -> {
                            if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) return
                            finish()
                        }
                        BiometricPrompt.ERROR_USER_CANCELED,
                        BiometricPrompt.ERROR_NEGATIVE_BUTTON,
                        BiometricPrompt.ERROR_NO_BIOMETRICS,
                        BiometricPrompt.ERROR_NO_DEVICE_CREDENTIAL,
                        BiometricPrompt.ERROR_HW_NOT_PRESENT,
                        BiometricPrompt.ERROR_HW_UNAVAILABLE,
                        BiometricPrompt.ERROR_LOCKOUT,
                        BiometricPrompt.ERROR_LOCKOUT_PERMANENT,
                        BiometricPrompt.ERROR_TIMEOUT,
                        -> {
                            Toast.makeText(this@BiometricGateActivity, errString, Toast.LENGTH_SHORT).show()
                            finish()
                        }
                        else -> {
                            if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
                                Toast.makeText(this@BiometricGateActivity, errString, Toast.LENGTH_SHORT).show()
                                finish()
                            }
                        }
                    }
                }
            },
        )
        biometricPrompt?.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle(biometricTitle())
                .setSubtitle(biometricSubtitle())
                .setAllowedAuthenticators(authenticators)
                .build(),
        )
    }

    private fun ensureLockOverlayVisible() {
        if (AppLockState.isUnlocked()) {
            dismissLockOverlay()
            return
        }
        val root = findViewById<ViewGroup>(android.R.id.content) ?: return
        val overlay = lockOverlay ?: buildLockOverlay().also {
            lockOverlay = it
            root.addView(
                it,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        overlay.visibility = View.VISIBLE
        overlay.bringToFront()
    }

    private fun dismissLockOverlay() {
        lockOverlay?.visibility = View.GONE
    }

    private fun buildLockOverlay(): FrameLayout {
        return FrameLayout(this).apply {
            setBackgroundColor(0xFF07111C.toInt())
            isClickable = true
            isFocusable = true

            val card = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                background = GradientDrawable().apply {
                    shape = GradientDrawable.RECTANGLE
                    cornerRadius = dp(28).toFloat()
                    setColor(0xFF0F172A.toInt())
                }
                setPadding(dp(24), dp(24), dp(24), dp(24))
            }
            card.addView(TextView(context).apply {
                text = "Satochip"
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 28f
                typeface = Typeface.DEFAULT_BOLD
                gravity = Gravity.CENTER
            })
            card.addView(space(dp(10)))
            card.addView(TextView(context).apply {
                text = "请按指纹进入钱包"
                setTextColor(0xFFE2E8F0.toInt())
                textSize = 16f
                gravity = Gravity.CENTER
            })
            card.addView(space(dp(18)))
            card.addView(TextView(context).apply {
                text = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) "指纹 / 锁屏凭证" else "锁屏凭证"
                setTextColor(0xFF67E8F9.toInt())
                textSize = 14f
                gravity = Gravity.CENTER
            })

            addView(
                card,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.CENTER,
                ).apply {
                    marginStart = dp(20)
                    marginEnd = dp(20)
                },
            )
        }
    }

    private fun space(height: Int): View {
        return View(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                height,
            )
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density + 0.5f).toInt()
}
