package dev.comma.companion;

import org.json.JSONObject;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLSocketFactory;

public final class PhoneClient {
  public static final class ApiException extends IllegalStateException {
    public final int status;
    public final String code;
    public ApiException(int status,String code,String message){super(message);this.status=status;this.code=code;}
  }
  public static final class TransportException extends java.io.IOException {
    public final String phase, reason;
    public TransportException(String phase,java.io.IOException cause){
      super("통신 확인 실패 · "+phase+"/"+transportReason(cause),cause);
      this.phase=phase;this.reason=transportReason(cause);
    }
  }
  // Return fixed labels only. Socket messages can contain addresses or credentials.
  private static String transportReason(Throwable error){
    for(int depth=0;error!=null&&depth<4;depth++,error=error.getCause()){
      if(error instanceof java.net.SocketTimeoutException)return "TIMEOUT";
      if(error instanceof javax.net.ssl.SSLException)return "TLS";
      if(error instanceof java.net.UnknownHostException)return "DNS";
      if(error instanceof java.io.EOFException)return "EOF";
      String message=error.getMessage();
      String m=message==null?"":message.toLowerCase(java.util.Locale.ROOT);
      if(m.contains("econnreset")||m.contains("connection reset"))return "RESET";
      if(m.contains("epipe")||m.contains("broken pipe"))return "BROKEN_PIPE";
      if(m.contains("econnaborted")||m.contains("connection abort"))return "ABORTED";
      if(m.contains("econnrefused")||m.contains("connection refused"))return "REFUSED";
      if(m.contains("enetunreach")||m.contains("ehostunreach")||m.contains("unreachable")||m.contains("no route to host"))return "UNREACHABLE";
      if(m.contains("eperm")||m.contains("eacces")||m.contains("permission denied"))return "DENIED";
      if(m.contains("socket closed")||m.contains("socket is closed"))return "CLOSED";
      if(m.contains("unexpected end")||m.contains("end of stream"))return "EOF";
    }
    return "IO";
  }
  private final URI endpoint;
  private final SSLSocketFactory tls;
  private volatile String cookie = "", csrf = "";
  private volatile boolean closed = false;
  public final String navigationStream = java.util.UUID.randomUUID().toString();
  public final java.util.concurrent.atomic.AtomicLong navigationSequence = new java.util.concurrent.atomic.AtomicLong();
  public PhoneClient(String url, String pin) throws Exception { endpoint = PinnedTls.endpoint(url); tls = PinnedTls.factory(pin); }
  public void clear() { closed=true; cookie=""; csrf=""; }
  public boolean connected() { return !closed && !csrf.isEmpty(); }
  public synchronized JSONObject call(String path, JSONObject body) throws Exception {
    if (closed || !path.matches("[a-z/-]+[a-zA-Z0-9_-]*")) throw new IllegalStateException("연결을 다시 확인해");
    HttpsURLConnection connection = (HttpsURLConnection) endpoint.resolve("/api/phone/"+path).toURL().openConnection();
    connection.setSSLSocketFactory(tls);
    connection.setInstanceFollowRedirects(false);
    connection.setConnectTimeout(1500); connection.setReadTimeout(1500);
    connection.setRequestProperty("Cookie", cookie);
    connection.setRequestProperty("Origin", endpoint.toString());
    connection.setRequestProperty("X-CSRF-Token", csrf);
    connection.setRequestProperty("Accept", "application/json");
    // The C4 HTTP/1.0 receiver closes after every response. Android's legacy
    // HTTP pool can otherwise reuse that socket before its FIN is observed.
    connection.setRequestProperty("Connection", "close");
    String phase="OPEN";
    try {
      if (body != null) {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        if (bytes.length>((path.equals("route")||path.equals("route/chunk"))?196608:4096)) throw new IllegalArgumentException("요청이 너무 커");
        connection.setRequestMethod("POST"); connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setFixedLengthStreamingMode(bytes.length);
        phase="UPLOAD_OPEN";
        try (java.io.OutputStream out=connection.getOutputStream()) {
          phase="UPLOAD_WRITE";out.write(bytes);phase="UPLOAD_CLOSE";
        }
      }
      phase="RESPONSE_HEADERS";
      int status = connection.getResponseCode();
      if (status == 401) { cookie=""; csrf=""; }
      if (status >= 300 && status < 400) throw new IllegalStateException("다른 주소로 이동할 수 없어");
      String contentType=connection.getContentType();
      if (contentType==null || !contentType.startsWith("application/json")) throw new IllegalStateException("기기 응답을 확인해");
      phase="RESPONSE_BODY";
      byte[] buffer=new byte[4096]; ByteArrayOutputStream bytes=new ByteArrayOutputStream();
      try (InputStream in=status<400?connection.getInputStream():connection.getErrorStream()) {
        if (in==null) throw new IllegalStateException("기기 응답이 없어");
        int n; while ((n=in.read(buffer))!=-1) { if (bytes.size()+n>65536) throw new IllegalStateException("응답이 너무 커"); bytes.write(buffer,0,n); }
      }
      JSONObject result = new JSONObject(bytes.toString("UTF-8"));
      if (closed) throw new IllegalStateException("종료된 연결의 응답이야");
      if (status>=400) throw new ApiException(status,result.optString("code", ""),result.optString("error", "연결을 다시 확인해"));
      String replacement=connection.getHeaderField("Set-Cookie");
      if (replacement!=null && replacement.startsWith("__Secure-korean_phone=")) cookie=replacement.split(";",2)[0];
      if (path.equals("session")) csrf=result.optString("csrf", "");
      if (path.equals("logout") || path.equals("cancel")) { cookie=""; csrf=""; }
      return result;
    } catch (java.io.IOException error) {
      if(error instanceof javax.net.ssl.SSLException)throw error;
      throw new TransportException(phase,error);
    } finally { connection.disconnect(); }
  }
}
