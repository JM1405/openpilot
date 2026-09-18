package dev.koranipilot.manager;

import org.junit.Test;
import static org.junit.Assert.*;

public class KakaoStartupFailureTest {
  @Test public void includesStageAndCauseButNeverMessages(){
    Throwable cause=new ClassNotFoundException("native_key=secret location=37.123,127.456");
    Throwable error=new NoClassDefFoundError("https://example.invalid/?key=secret");
    error.initCause(cause);
    String detail=KakaoStartupFailure.describe(KakaoStartupFailure.Stage.VIEW,error);
    assertTrue(detail.startsWith("G2 지도 화면 생성 · NoClassDefFoundError"));
    assertTrue(detail.contains("ClassNotFoundException"));
    assertFalse(detail.contains("secret"));assertFalse(detail.contains("37.123"));
    assertFalse(detail.contains("https://"));
  }
  @Test public void includesSdkFrameWithoutFilenameOrMethod(){
    Throwable error=new IllegalStateException();
    error.setStackTrace(new StackTraceElement[]{
      new StackTraceElement("other.Provider","secret","secret",1),
      new StackTraceElement("com.kakaomobility.knsdk.ui.view.KNNaviView","secret","secret",42)});
    String detail=KakaoStartupFailure.describe(KakaoStartupFailure.Stage.VIEW,error);
    assertTrue(detail.endsWith("@ KNNaviView:42"));assertFalse(detail.contains("secret"));
  }
  @Test public void causeCycleIsBounded(){
    Throwable first=new IllegalStateException(),second=new IllegalArgumentException();
    first.initCause(second);second.initCause(first);
    String detail=KakaoStartupFailure.describe(KakaoStartupFailure.Stage.START,first);
    assertEquals(3,detail.split(" @ ",-1).length-1);
    assertTrue(detail.length()<400);
  }
  @Test public void usesOnlyKnownStageWhenErrorAbsent(){
    assertEquals("I1 SDK 설치",KakaoStartupFailure.describe(KakaoStartupFailure.Stage.INSTALL,null));
  }
}
