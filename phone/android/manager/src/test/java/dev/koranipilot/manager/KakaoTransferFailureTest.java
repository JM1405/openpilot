package dev.koranipilot.manager;

import dev.comma.companion.PhoneClient;
import java.net.SocketTimeoutException;
import org.junit.Test;
import static org.junit.Assert.*;

public class KakaoTransferFailureTest {
  @Test public void apiStatusAndKnownCodeSurviveWithoutRawMessage(){
    Throwable error=new PhoneClient.ApiException(409,"stale","cookie=secret url=https://private/ gps=37.123");
    String text=KakaoTransferFailure.detail(KakaoTransferFailure.Stage.SEND,error);
    assertTrue(text.contains("K3 HTTP 409/stale"));
    assertFalse(text.contains("secret"));assertFalse(text.contains("https://"));assertFalse(text.contains("37.123"));
  }
  @Test public void unknownCodesCannotExposePayloads(){
    Throwable error=new PhoneClient.ApiException(400,"private_token_value","secret");
    assertEquals("K1 HTTP 400/unknown",KakaoTransferFailure.code(KakaoTransferFailure.Stage.CHALLENGE,error));
  }
  @Test public void onlyExactKnownServerReasonsAreDisplayed(){
    String reason="안전 안내 식별자를 확인해";
    assertTrue(KakaoTransferFailure.detail(KakaoTransferFailure.Stage.SEND,new PhoneClient.ApiException(400,"invalid",reason)).endsWith(reason));
    String untrusted=KakaoTransferFailure.detail(KakaoTransferFailure.Stage.SEND,new PhoneClient.ApiException(400,"invalid",reason+" token=secret"));
    assertFalse(untrusted.contains(reason));assertFalse(untrusted.contains("secret"));
  }
  @Test public void timeoutKeepsStageAndDropsAddress(){
    String text=KakaoTransferFailure.detail(KakaoTransferFailure.Stage.SEND,new SocketTimeoutException("https://private:7443"));
    assertTrue(text.contains("K3 SocketTimeoutException"));assertFalse(text.contains("private"));
  }
  @Test public void routeFailureDoesNotEraseValidatedKakaoReceipt(){
    String text=KakaoTransferFailure.summary(KakaoTransferFailure.Stage.ROUTE,new PhoneClient.ApiException(409,"revision",""),"집 수신 확인 #7",true);
    assertTrue(text.startsWith("집 수신 확인 #7 · 경로 확인 실패"));assertTrue(text.contains("R1 HTTP 409/revision"));
    assertFalse(text.contains("C4 수신 확인 실패"));
  }
  @Test public void failedReceiptNeverBecomesConfirmed(){
    assertTrue(KakaoTransferFailure.summary(KakaoTransferFailure.Stage.RECEIPT,new IllegalStateException(),null,true).startsWith("C4 수신 확인 실패 · K4"));
  }
  @Test public void revokedSessionDoesNotRetainSuccess(){
    String text=KakaoTransferFailure.summary(KakaoTransferFailure.Stage.ROUTE,new PhoneClient.ApiException(401,"unauthorized",""),"집 수신 확인 #7",false);
    assertTrue(text.startsWith("C4 연결 만료"));assertFalse(text.contains("집 수신 확인"));
  }
  @Test public void socketFailureKeepsPhaseAndFixedReasonOnly(){
    PhoneClient.TransportException error=new PhoneClient.TransportException("UPLOAD_WRITE",new java.net.SocketException("write failed: EPIPE (Broken pipe) private=secret"));
    assertEquals("K3 UPLOAD_WRITE/BROKEN_PIPE",KakaoTransferFailure.code(KakaoTransferFailure.Stage.SEND,error));
    assertFalse(error.getMessage().contains("secret"));
  }
  @Test public void responseResetAndUnknownMessagesStayPrivate(){
    PhoneClient.TransportException reset=new PhoneClient.TransportException("RESPONSE_HEADERS",new java.net.SocketException("Connection reset by peer https://private secret"));
    assertEquals("K3 RESPONSE_HEADERS/RESET",KakaoTransferFailure.code(KakaoTransferFailure.Stage.SEND,reset));
    PhoneClient.TransportException unknown=new PhoneClient.TransportException("UPLOAD_OPEN",new java.net.SocketException("secret 37.123"));
    assertEquals("K3 UPLOAD_OPEN/IO",KakaoTransferFailure.code(KakaoTransferFailure.Stage.SEND,unknown));
  }
  @Test public void timeoutTlsAndClosedAreDistinct(){
    assertEquals("TIMEOUT",new PhoneClient.TransportException("RESPONSE_BODY",new SocketTimeoutException("secret")).reason);
    assertEquals("TLS",new PhoneClient.TransportException("UPLOAD_OPEN",new javax.net.ssl.SSLHandshakeException("secret")).reason);
    assertEquals("CLOSED",new PhoneClient.TransportException("UPLOAD_OPEN",new java.net.SocketException("Socket is closed")).reason);
  }
}
