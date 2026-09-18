package dev.comma.companion;

import java.net.URI;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** Trust one certificate whose full SHA256 the user reads on the device screen.
 * HttpsURLConnection still performs its normal hostname check. */
public final class PinnedTls {
  public static URI endpoint(String value) throws Exception {
    URI uri = new URI(value.trim());
    if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null ||
        uri.getQuery() != null || uri.getFragment() != null ||
        !(uri.getPath().isEmpty() || uri.getPath().equals("/")) || uri.getPort() == 0)
      throw new IllegalArgumentException("C4 화면의 https 연결 주소를 입력해");
    return new URI("https", null, uri.getHost(), uri.getPort(), null, null, null);
  }
  public static SSLSocketFactory factory(String fingerprint) throws Exception {
    String pin = fingerprint.replace(":", "").replace(" ", "").toLowerCase(java.util.Locale.ROOT);
    if (!pin.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("기기 인증값 64자리를 확인해");
    byte[] expected = new byte[32];
    for (int i=0; i<32; i++) expected[i]=(byte)Integer.parseInt(pin.substring(i*2,i*2+2),16);
    X509TrustManager trust = new X509TrustManager() {
      public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
      public void checkClientTrusted(X509Certificate[] c, String a) throws CertificateException { throw new CertificateException(); }
      public void checkServerTrusted(X509Certificate[] chain, String auth) throws CertificateException {
        try {
          if (chain == null || chain.length == 0) throw new CertificateException("인증서 없음");
          chain[0].checkValidity();
          if (!MessageDigest.isEqual(expected, MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded())))
            throw new CertificateException("기기 인증값이 달라");
        } catch (CertificateException e) { throw e; }
        catch (Exception e) { throw new CertificateException(e); }
      }
    };
    SSLContext context = SSLContext.getInstance("TLS");
    context.init(null, new TrustManager[]{trust}, null);
    return context.getSocketFactory();
  }
  private PinnedTls() {}
}
