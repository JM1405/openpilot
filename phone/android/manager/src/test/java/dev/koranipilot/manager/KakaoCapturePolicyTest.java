package dev.koranipilot.manager;

import org.junit.Test;
import static org.junit.Assert.*;

public class KakaoCapturePolicyTest {
  @Test public void beforeAuthenticationCaptureRemainsBlocked(){
    assertTrue(KakaoCapturePolicy.mustProtectKey(false,true,false));
    assertTrue(KakaoCapturePolicy.mustProtectKey(false,false,false));
  }
  @Test public void visibleKeyInputRemainsProtected(){
    assertTrue(KakaoCapturePolicy.mustProtectKey(true,true,false));
    assertTrue(KakaoCapturePolicy.mustProtectKey(true,true,true));
  }
  @Test public void hiddenButUnclearedKeyRemainsProtected(){
    assertTrue(KakaoCapturePolicy.mustProtectKey(true,false,true));
  }
  @Test public void authenticatedClearedMapScreenAllowsCapture(){
    assertFalse(KakaoCapturePolicy.mustProtectKey(true,false,false));
  }
}
