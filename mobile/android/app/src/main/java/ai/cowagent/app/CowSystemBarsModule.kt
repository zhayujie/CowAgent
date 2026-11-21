package ai.cowagent.app

import androidx.core.view.WindowInsetsControllerCompat
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager

/** Colours the navigation bar below the page, which React Native's StatusBar does not reach. */
class CowSystemBarsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  override fun getName() = "CowSystemBars"

  /** Android 15 and later draw the page under the bar and ignore the colour. */
  @ReactMethod
  fun setNavigationBar(color: Double, darkIcons: Boolean) {
    val activity = reactApplicationContext.currentActivity ?: return
    activity.runOnUiThread {
      val window = activity.window
      @Suppress("DEPRECATION")
      window.navigationBarColor = color.toInt()
      WindowInsetsControllerCompat(window, window.decorView).isAppearanceLightNavigationBars = darkIcons
    }
  }
}

class CowSystemBarsPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
    listOf(CowSystemBarsModule(context))

  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
