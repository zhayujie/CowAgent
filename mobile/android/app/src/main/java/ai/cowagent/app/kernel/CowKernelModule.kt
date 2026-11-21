package ai.cowagent.app.kernel

import android.content.Context
import android.os.Build
import android.provider.Settings
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import java.util.concurrent.Executors

class CowKernelModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  override fun getName() = "CowKernel"

  /** Resolves with `{port, password}` once the kernel thread is started; it binds shortly after. */
  @ReactMethod
  fun start(promise: Promise) {
    starter.execute {
      try {
        val endpoint = CowKernel.start(reactApplicationContext.applicationContext)
        promise.resolve(
          Arguments.createMap().apply {
            putInt("port", endpoint.port)
            putString("password", endpoint.password)
          },
        )
      } catch (e: Exception) {
        promise.reject("kernel_start_failed", e.message, e)
      }
    }
  }

  /** What the owner calls this phone, for naming the local agent; never leaves the device. */
  @ReactMethod(isBlockingSynchronousMethod = true)
  fun deviceName(): String = friendlyDeviceName(reactApplicationContext.applicationContext)

  private companion object {
    // Unpacking sources and booting Python take seconds on first launch.
    val starter = Executors.newSingleThreadExecutor()
  }
}

/**
 * The name set in the phone's settings (shown over Bluetooth), else the
 * marketing name, else maker and model. Several vendors leave the global
 * device name as the bare model code, so a value equal to the model is skipped.
 */
internal fun friendlyDeviceName(context: Context): String {
  val resolver = context.contentResolver
  val candidates = sequenceOf(
    { Settings.Secure.getString(resolver, "bluetooth_name") },
    // Where MIUI keeps the user's name once newer Android stops apps reading the Bluetooth one.
    { systemProperty("persist.sys.device_name") },
    { Settings.Global.getString(resolver, Settings.Global.DEVICE_NAME) },
    { systemProperty("ro.product.marketname") },
  )
  val model = Build.MODEL.orEmpty()
  return candidates
    .map { read -> runCatching(read).getOrNull()?.trim().orEmpty() }
    .firstOrNull { it.isNotEmpty() && !it.equals(model, ignoreCase = true) }
    ?: listOf(Build.MANUFACTURER.orEmpty().replaceFirstChar { it.uppercase() }, model)
      .filter { it.isNotEmpty() }
      .joinToString(" ")
}

private fun systemProperty(key: String): String? =
  Class.forName("android.os.SystemProperties").getMethod("get", String::class.java).invoke(null, key) as? String

class CowKernelPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowKernelModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
