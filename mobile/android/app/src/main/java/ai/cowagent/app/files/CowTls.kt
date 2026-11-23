package ai.cowagent.app.files

import android.content.Context
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.util.Log
import com.facebook.react.modules.network.OkHttpClientProvider
import com.reactnativecommunity.webview.RNCWebViewClient
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection

/**
 * The one place TLS trust is wired. The certificates a user imports have to reach every transport
 * the app can use, and Android offers three that never see each other: OkHttp (React Native's
 * fetch), `java.net` (the downloader's HttpURLConnection, and anything else opening a URL) and the
 * WebView's own stack for the HTML preview. A new transport therefore needs no code of its own:
 * it picks up the imports by being one of these three.
 *
 * [CowTrustStore] holds the anchors and evaluates a chain; this only registers it.
 */
object CowTls {
  private const val TAG = "CowTls"

  fun install(context: Context) {
    val app = context.applicationContext
    installOkHttp(app)
    installJavaNet(app)
    installWebView(app)
  }

  /** React Native builds its client once at startup, so the factory has to be in place first. */
  private fun installOkHttp(app: Context) {
    OkHttpClientProvider.setOkHttpClientFactory { CowTrustStore.okHttpClient(app) }
  }

  /**
   * Process-wide, which is the point: a library that opens its own connection has no seam to
   * inject into. System anchors stay in force, so this only ever adds trust.
   */
  private fun installJavaNet(app: Context) {
    runCatching {
      HttpsURLConnection.setDefaultSSLSocketFactory(CowTrustStore.socketFactory(app))
    }.onFailure { Log.w(TAG, "Cannot set the java.net socket factory: ${it.message}") }
  }

  /**
   * A WebView reports a failing chain and expects a decision; react-native-webview cancels
   * unconditionally unless a host app claims the chain (see patches/react-native-webview).
   */
  private fun installWebView(app: Context) {
    runCatching {
      RNCWebViewClient.sslErrorAcceptor = RNCWebViewClient.SslErrorAcceptor { error ->
        // Only "the platform does not know this authority" is ours to answer. An expired
        // certificate or a hostname mismatch stays fatal, as it should.
        val unknownIssuer = error.primaryError == SslError.SSL_UNTRUSTED
        val trusted = unknownIssuer && CowTrustStore.accepts(app, leafOf(error))
        if (!trusted) {
          Log.w(TAG, "Rejected ${error.url}: ${error.primaryError}")
        }
        trusted
      }
    }.onFailure {
      // The installed library version exposes no hook; pages then stay platform-only.
      Log.w(TAG, "Cannot hook the WebView: ${it.message}")
    }
  }

  /**
   * [SslError] only carries a summary, so the certificate itself has to be recovered from it, and
   * the platform offers it in two shapes. From API 29 the parsed form is available directly.
   * Below that - and on any version where the platform kept only the encoding -
   * [SslCertificate.saveState] stores the DER bytes under `x509-certificate`; note that this is a
   * byte array, not a certificate object, which is why it is parsed here rather than cast.
   */
  private fun leafOf(error: SslError): X509Certificate? = runCatching {
    val certificate = error.certificate ?: return null
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      certificate.x509Certificate?.let { return it }
    }
    val state = SslCertificate.saveState(certificate) ?: return null
    val der = state.getByteArray("x509-certificate") ?: return null
    CertificateFactory.getInstance("X.509").generateCertificate(der.inputStream()) as? X509Certificate
  }.getOrNull()
}
