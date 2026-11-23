package ai.cowagent.app.files

import android.content.Context
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.util.Log
import com.facebook.react.modules.network.OkHttpClientProvider
import com.reactnativecommunity.webview.RNCWebViewClient
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import okhttp3.internal.tls.OkHostnameVerifier

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
        val trusted = onlyUntrusted(error) && accepts(app, error)
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

  private val FATAL_ERRORS = intArrayOf(
    SslError.SSL_NOTYETVALID,
    SslError.SSL_EXPIRED,
    SslError.SSL_IDMISMATCH,
    SslError.SSL_DATE_INVALID,
    SslError.SSL_INVALID,
  )

  /**
   * Only "the platform does not know this authority" is ours to answer. [SslError.getPrimaryError]
   * reports the most severe error alone, so every other one has to be ruled out explicitly.
   */
  private fun onlyUntrusted(error: SslError): Boolean =
    error.hasError(SslError.SSL_UNTRUSTED) && FATAL_ERRORS.none { error.hasError(it) }

  /** The imports must anchor the leaf and the leaf must name the host that was asked for. */
  private fun accepts(app: Context, error: SslError): Boolean {
    val leaf = leafOf(error) ?: return false
    val host = error.url?.let { Uri.parse(it).host } ?: return false
    return CowTrustStore.accepts(app, leaf) && OkHostnameVerifier.verify(host, leaf)
  }

  private fun leafOf(error: SslError): X509Certificate? = runCatching {
    val cert = error.certificate ?: return null
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      cert.x509Certificate
    } else {
      // Older releases only expose the encoded certificate through the saved state.
      val encoded = SslCertificate.saveState(cert)?.getByteArray("x509-certificate") ?: return null
      CertificateFactory.getInstance("X.509").generateCertificate(encoded.inputStream()) as X509Certificate
    }
  }.getOrNull()
}
