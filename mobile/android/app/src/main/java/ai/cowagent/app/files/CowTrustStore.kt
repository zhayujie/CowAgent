package ai.cowagent.app.files

import android.content.Context
import com.facebook.react.modules.network.OkHttpClientProvider
import okhttp3.OkHttpClient
import java.io.File
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
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

  /** Bumped on every import or removal so [Live] knows its managers are stale. */
  private val version = AtomicInteger()

  /** Must follow every change to [dir]; the next handshake then sees the new set. */
  fun invalidate() {
    version.incrementAndGet()
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
    importedManager(context)?.let { result += it }
    return result
  }

  /** Null when nothing is imported, as some providers refuse an empty anchor set. */
  private fun importedManager(context: Context): X509TrustManager? {
    val certs = files(context).flatMap { runCatching { read(it) }.getOrDefault(emptyList()) }
    if (certs.isEmpty()) {
      return null
    }
    val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null, null) }
    certs.forEachIndexed { i, cert -> store.setCertificateEntry("cow-ca-$i", cert) }
    val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
    factory.init(store)
    return factory.trustManagers.filterIsInstance<X509TrustManager>().first()
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

  /**
   * React Native hands its OkHttpClient to NetworkingModule once at startup and the java.net
   * factory is process-wide, so neither can be rebuilt after an import. This trust manager sits
   * inside both and swaps the managers it delegates to whenever [version] moves.
   */
  private class Live(private val context: Context) : X509TrustManager {
    @Volatile private var built: Pair<Int, Combined>? = null

    private fun current(): Combined {
      val v = CowTrustStore.version.get()
      built?.let { (at, combined) -> if (at == v) return combined }
      return Combined(CowTrustStore.managers(context)).also { built = v to it }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
      current().checkClientTrusted(chain, authType)

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) =
      current().checkServerTrusted(chain, authType)

    override fun getAcceptedIssuers(): Array<X509Certificate> = current().getAcceptedIssuers()
  }

  @Volatile private var live: Live? = null

  private fun trustManager(context: Context): X509TrustManager =
    live ?: synchronized(this) { live ?: Live(context.applicationContext).also { live = it } }

  /**
   * For connections that never reach OkHttp - the downloader opens its own
   * `HttpURLConnection`, which otherwise verifies against the platform store alone.
   */
  fun socketFactory(context: Context): SSLSocketFactory =
    SSLContext.getInstance("TLS").apply { init(null, arrayOf(trustManager(context)), null) }.socketFactory

  /**
   * True when the imports alone accept [leaf]. A WebView hands over the leaf certificate of a
   * failing chain and nothing more, which is enough here: a tunnel's CA signs the leaf directly.
   */
  fun accepts(context: Context, leaf: X509Certificate?): Boolean {
    if (leaf == null) {
      return false
    }
    val trust = importedManager(context) ?: return false
    // The authType only steers key-usage checks; one of these covers every key we may meet.
    return listOf(leaf.publicKey.algorithm, "RSA", "EC").any { type ->
      runCatching { trust.checkServerTrusted(arrayOf(leaf), type) }.isSuccess
    }
  }

  /**
   * React Native's client, with the imports in its trust chain. [CowTls] is what registers it;
   * nothing else should build a client for the app's own requests.
   */
  fun okHttpClient(context: Context): OkHttpClient {
    // One trust manager for both the socket factory and OkHttp, as OkHttp verifies with the
    // instance it is given rather than the one inside the SSLContext.
    val trust = trustManager(context)
    val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
    return OkHttpClientProvider.createClientBuilder(context).apply {
      sslSocketFactory(ssl.socketFactory, trust)
      // Endpoints that come and go (tunnels, laptops on a LAN) are common here.
      retryOnConnectionFailure(true)
    }.build()
  }
}
