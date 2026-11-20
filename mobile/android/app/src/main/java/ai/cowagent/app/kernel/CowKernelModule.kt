package ai.cowagent.app.kernel

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

  private companion object {
    // Unpacking sources and booting Python take seconds on first launch.
    val starter = Executors.newSingleThreadExecutor()
  }
}

class CowKernelPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowKernelModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
