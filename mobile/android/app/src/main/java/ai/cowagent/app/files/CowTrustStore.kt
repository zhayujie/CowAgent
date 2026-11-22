package ai.cowagent.app.files

import android.content.Context
import com.facebook.react.modules.network.OkHttpClientFactory
import com.facebook.react.modules.network.OkHttpClientProvider
import okhttp3.OkHttpClient
import java.io.File
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Trusts the CA certificates the user imported from the app, on top of the system store.
 *
 * Android 11+ no longer lets an app install a CA certificate into the user store (the KeyChain
 * flow only accepts credentials that carry a private key), so a self-hosted HTTPS endpoint such
 * as a personal tunnel would otherwise be unreachable. Instead the certificates live in the app's
 * private directory and are added to the TLS trust chain of React Native's own HTTP client.
 */
object CowTrustStore {
  /** Imported CA certificates live here, one PEM per file, so a raw .crt can be dropped in. */
  fun dir(context: Context): File = File(context.filesDir, "ca").apply { mkdirs() }

  fun files(context: Context): List<File> =
    dir(context).listFiles { f -> f.isFile && f.length() > 0 }?.sortedBy { it.name } ?: emptyList()

  /** Parses a PEM/DER file into certificates, throwing when the content is not X.509. */
  fun read(file: File): List<X509Certificate> =
    file.inputStream().use { input ->
      CertificateFactory.getInstance("X.509").generateCertificates(input).map { it as X509Certificate }
    }

  /** Imports a chosen certificate file, replacing one with the same name. Returns the file used. */
  fun import(context: Context, bytes: ByteArray, baseName: String): File {
    val certs = CertificateFactory.getInstance("X.509").generateCertificates(bytes.inputStream())
    require(certs.isNotEmpty()) { "No certificate found" }
    val safe = baseName.replace(Regex("[^A-Za-z0-9._-]"), "_").ifEmpty { "ca-cert" }
    val target = File(dir(context), if (safe.endsWith(".pem")) safe else "$safe.pem")
    val pem = buildString {
      certs.forEach { cert ->
        append("-----BEGIN CERTIFICATE-----\n")
        append(android.util.Base64.encodeToString(cert.encoded, android.util.Base64.NO_WRAP).chunked(64).joinToString("\n"))
        append("\n-----END CERTIFICATE-----\n")
      }
    }
    target.writeText(pem)
    invalidate()
    return target
  }

  /**
   * The system trust manager plus one built from the imported files. A handshake succeeds when
   * either accepts the chain, so this only ever adds trust and never removes it.
   */
  private fun managers(context: Context): List<X509TrustManager> {
    val result = mutableListOf<X509TrustManager>()
    TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
      init(null as KeyStore?)
    }.trustManagers.filterIsInstance<X509TrustManager>().forEach { result += it }

    val certs = files(context).flatMap { runCatching { read(it) }.getOrDefault(emptyList()) }
    if (certs.isNotEmpty()) {
      val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
        load(null, null)
        certs.forEachIndexed { i, cert -> setCertificateEntry("cow-ca-$i", cert) }
      }
      TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
        init(store)
      }.trustManagers.filterIsInstance<X509TrustManager>().forEach { result += it }
    }
    return result
  }

  /** Wraps the managers together; falls back to the last error so failure messages stay useful. */
  private class Combined(private val all: List<X509TrustManager>) : X509TrustManager {
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
      all.firstOrNull { runCatching { it.checkClientTrusted(chain, authType) }.isSuccess }
        ?: throw java.security.cert.CertificateException("No trust manager accepted the client chain")
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
      var last: Exception? = null
      for (m in all) {
        try {
          m.checkServerTrusted(chain, authType)
          return
        } catch (e: Exception) {
          last = e
        }
      }
      throw last ?: java.security.cert.CertificateException("No trust manager accepted the server chain")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = all.flatMap { it.acceptedIssuers.toList() }.toTypedArray()
  }

  /** Drops the cached React Native client so a just-imported certificate is used right away. */
  fun invalidate() {
    runCatching {
      val f = OkHttpClientProvider::class.java.getDeclaredField("client")
      f.isAccessible = true
      // OkHttpClientProvider is a Kotlin object, so the field lives on its single instance.
      f.set(OkHttpClientProvider, null)
    }
  }

  /** Registers the factory once, before React Native makes its first request. */
  fun install(context: Context) {
    val app = context.applicationContext
    OkHttpClientProvider.setOkHttpClientFactory {
      // One trust manager for both the socket factory and OkHttp, as OkHttp verifies with the
      // instance it is given rather than the one inside the SSLContext.
      val trust = Combined(managers(app))
      val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
      OkHttpClientProvider.createClientBuilder(app).apply {
        sslSocketFactory(ssl.socketFactory, trust)
        // Endpoints that come and go (tunnels, laptops on a LAN) are common here.
        retryOnConnectionFailure(true)
      }.build()
    }
    invalidate()
  }
}
