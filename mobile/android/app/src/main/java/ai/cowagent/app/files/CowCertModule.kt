package ai.cowagent.app.files

import android.app.Activity
import android.content.Intent
import android.net.Uri
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.BaseActivityEventListener
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableArray
import com.facebook.react.uimanager.ViewManager
import java.io.File

/**
 * Manages the CA certificates the app trusts on top of the system store.
 *
 * Certificates are kept in the app's private directory and added to the TLS trust chain by
 * [CowTrustStore]. Installing into the system user store from an app is no longer possible on
 * Android 11+, which only accepts credentials that carry a private key.
 */
class CowCertModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private var pending: Promise? = null

  private val listener: ActivityEventListener = object : BaseActivityEventListener() {
    override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
      if (requestCode != PICK_CERT) return
      val promise = pending ?: return
      pending = null
      if (resultCode != Activity.RESULT_OK || data?.data == null) {
        promise.resolve(null)
        return
      }
      val uri: Uri = data.data!!
      try {
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
          ?: throw IllegalArgumentException("Cannot read the chosen file")
        val name = uri.lastPathSegment?.substringAfterLast('/')?.substringBeforeLast('.')?.ifEmpty { null }
          ?: "ca-cert"
        promise.resolve(describe(CowTrustStore.import(context, bytes, name)))
      } catch (e: Exception) {
        promise.reject("cert_invalid", "Not a valid X.509 certificate", e)
      }
    }
  }

  init {
    context.addActivityEventListener(listener)
  }

  override fun getName() = "CowCert"

  /** Opens a document picker; resolves the imported entry, or null when the user cancels. */
  @ReactMethod
  fun pick(promise: Promise) {
    val activity = reactApplicationContext.currentActivity
    if (activity == null) {
      promise.reject("cert_no_activity", "No foreground activity")
      return
    }
    if (pending != null) {
      promise.reject("cert_busy", "A picker is already open")
      return
    }
    pending = promise
    val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
      addCategory(Intent.CATEGORY_OPENABLE)
      type = "*/*"
      putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/x-x509-ca-cert", "application/x-pem-file", "application/octet-stream"))
    }
    activity.startActivityForResult(Intent.createChooser(pick, null), PICK_CERT)
  }

  /** Lists the imported certificates so the settings screen can show and remove them. */
  @ReactMethod
  fun list(promise: Promise) {
    try {
      val out: WritableArray = Arguments.createArray()
      for (file in CowTrustStore.files(context)) {
        runCatching { describe(file) }.getOrNull()?.let { out.pushMap(it) }
      }
      promise.resolve(out)
    } catch (e: Exception) {
      promise.reject("cert_list_failed", e.message, e)
    }
  }

  /** Removes an imported certificate by its file name; the system store is untouched. */
  @ReactMethod
  fun remove(name: String, promise: Promise) {
    try {
      val file = CowTrustStore.files(context).firstOrNull { it.nameWithoutExtension == name }
      if (file == null) {
        promise.resolve(false)
        return
      }
      val removed = file.delete()
      CowTrustStore.invalidate()
      promise.resolve(removed)
    } catch (e: Exception) {
      promise.reject("cert_remove_failed", e.message, e)
    }
  }

  private fun describe(file: File) = Arguments.createMap().apply {
    val cert = CowTrustStore.read(file).firstOrNull()
    putString("name", file.nameWithoutExtension)
    putString("subject", cert?.subjectX500Principal?.name ?: file.name)
    putString("expires", cert?.notAfter?.toString())
    putBoolean("expired", cert?.let { it.notAfter.before(java.util.Date()) } ?: false)
  }

  companion object {
    private const val PICK_CERT = 0xC3A7
  }
}

class CowCertPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowCertModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
