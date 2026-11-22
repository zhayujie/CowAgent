package ai.cowagent.app

import ai.cowagent.app.files.SharedIntake
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
    // Android 15+ runs pages under the navigation bar, and they keep clear of it themselves.
    // Some ROMs (MIUI) paint an opaque strip there when contrast is enforced, even with gestures.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      window.isNavigationBarContrastEnforced = false
    }
    // A recreated activity already handed its share over.
    if (savedInstanceState == null) SharedIntake.receive(intent)
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    SharedIntake.receive(intent)
  }

  override fun onStart() {
    super.onStart()
    visible = true
  }

  override fun onStop() {
    visible = false
    super.onStop()
  }

  companion object {
    /** On screen, where the chat shows a scheduled delivery itself and a reminder would repeat it. */
    @Volatile var visible = false
  }
}
