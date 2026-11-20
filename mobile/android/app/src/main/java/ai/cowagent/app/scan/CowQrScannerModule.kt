package ai.cowagent.app.scan

import android.app.Activity
import android.content.Intent
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanIntentResult
import com.journeyapps.barcodescanner.ScanOptions

/**
 * Reads a QR code in ZXing's full-screen scanner. ZXing decodes on the device
 * and talks to no service, unlike the Play services scanners.
 */
class CowQrScannerModule(context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context), ActivityEventListener {
  private var pending: Promise? = null

  init {
    context.addActivityEventListener(this)
  }

  override fun getName() = "CowQrScanner"

  /** Resolves with the text read, or null when the user backs out. */
  @ReactMethod
  fun scan(prompt: String, promise: Promise) {
    val activity = reactApplicationContext.currentActivity
    if (activity == null) {
      promise.reject("no_activity", "No activity to show the scanner in")
      return
    }
    pending?.resolve(null)
    pending = promise
    val options = ScanOptions()
      .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
      .setPrompt(prompt)
      .setBeepEnabled(false)
      .setOrientationLocked(false)
    try {
      activity.startActivityForResult(ScanContract().createIntent(activity, options), REQUEST_CODE)
    } catch (e: Exception) {
      pending = null
      promise.reject("scan_failed", e.message, e)
    }
  }

  override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
    if (requestCode != REQUEST_CODE) {
      return
    }
    val promise = pending ?: return
    pending = null
    promise.resolve(ScanIntentResult.parseActivityResult(resultCode, data).contents)
  }

  override fun onNewIntent(intent: Intent) = Unit

  override fun invalidate() {
    reactApplicationContext.removeActivityEventListener(this)
    pending?.resolve(null)
    pending = null
    super.invalidate()
  }

  private companion object {
    const val REQUEST_CODE = 0x5c4
  }
}

class CowQrScannerPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
    listOf(CowQrScannerModule(context))

  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
