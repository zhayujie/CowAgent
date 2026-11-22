package ai.cowagent.app.files

import android.app.Activity
import android.content.Intent
import android.security.KeyChain
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.BaseActivityEventListener
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

/**
 * Installs a user-chosen CA certificate into Android's user certificate store through the
 * system KeyChain flow. Apps that opt in to user certificates (networkSecurityConfig) then
 * trust self-hosted HTTPS endpoints such as personal tunnels without repackaging.
 */
class CowCertModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private var pending: Promise? = null

  private val listener: ActivityEventListener = object : BaseActivityEventListener() {
    override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
      if (requestCode != PICK_CERT) return
      val promise = pending ?: return
      pending = null
      if (resultCode != Activity.RESULT_OK || data?.data == null) {
        promise.resolve("cancelled")
        return
      }
      try {
        val bytes = context.contentResolver.openInputStream(data.data!!)?.use { it.readBytes() }
          ?: throw IllegalArgumentException("Cannot read the chosen file")
        val cert = CertificateFactory.getInstance("X.509")
          .generateCertificate(bytes.inputStream()) as X509Certificate
        val name = data.data!!.lastPathSegment?.substringAfterLast('/')?.substringBeforeLast('.')
          ?.ifEmpty { null } ?: "CowAgent CA"
        val install = KeyChain.createInstallIntent().apply {
          putExtra(KeyChain.EXTRA_CERTIFICATE, cert.encoded)
          putExtra(KeyChain.EXTRA_NAME, name)
          addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(install)
        promise.resolve("prompted")
      } catch (e: Exception) {
        promise.reject("cert_invalid", "Not a valid X.509 certificate", e)
      }
    }
  }

  init {
    context.addActivityEventListener(listener)
  }

  override fun getName() = "CowCert"

  /** Opens a document picker for a .crt/.pem file; resolves "prompted" or "cancelled". */
  @ReactMethod
  fun install(promise: Promise) {
    val activity = reactApplicationContext.currentActivity
    if (activity == null) {
      promise.reject("cert_no_activity", "No foreground activity")
      return
    }
    if (pending != null) {
      promise.reject("cert_busy", "An install is already in progress")
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

  companion object {
    private const val PICK_CERT = 0xC3A7
  }
}
