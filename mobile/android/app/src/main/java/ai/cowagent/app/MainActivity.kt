package ai.cowagent.app

import ai.cowagent.app.notify.CowNotify
import ai.cowagent.app.notify.PendingSession
import android.content.Intent
import android.os.Build
import android.os.Bundle
import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

class MainActivity : ReactActivity() {

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "CowAgentMobile"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate =
      DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    // A notification tap that started the app: keep its conversation for the JS side.
    // A rotation restores the same intent, and must not reopen anything.
    if (savedInstanceState == null) {
      PendingSession.put(intent?.getStringExtra(CowNotify.EXTRA_SESSION))
    }
    // Android 15+ runs pages under the navigation bar, and they keep clear of it themselves.
    // Some ROMs (MIUI) paint an opaque strip there when contrast is enforced, even with gestures.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      window.isNavigationBarContrastEnforced = false
    }
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    // The app was already running: the same hand-off, through the event the resume path reads.
    setIntent(intent)
    PendingSession.put(intent.getStringExtra(CowNotify.EXTRA_SESSION))
  }
}
