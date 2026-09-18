package dev.koranipilot.manager;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class KakaoReceiptTest {
  private JSONObject receipt()throws Exception{
    return new JSONObject().put("received",true).put("seq",7).put("control_enabled",false)
      .put("scope","sdk_observation").put("location_fresh",true).put("events",new JSONArray());
  }
  private void reject(JSONObject value){
    assertThrows(IllegalStateException.class,()->KakaoReceipt.describe(value,7));
  }
  @Test public void matchingReceiptShowsReceiverNotJustLocalState()throws Exception{
    String text=KakaoReceipt.describe(receipt(),7);
    assertTrue(text.contains("C4 수신 확인 #7"));assertTrue(text.contains("GPS 유효"));
    assertTrue(text.contains("안전 안내 0개"));assertTrue(text.contains("자동 감속 미연결"));
  }
  @Test public void staleReceiverGpsIsNeverDisplayedAsFresh()throws Exception{
    String text=KakaoReceipt.describe(receipt().put("location_fresh",false),7);
    assertTrue(text.contains("GPS 대기 / 만료"));assertFalse(text.contains("GPS 유효"));
  }
  @Test public void homeSessionClearlyLabelsReceiveOnly()throws Exception{
    assertTrue(KakaoReceipt.describe(receipt().put("connection_mode","home_receive"),7).startsWith("집 테스트 · 수신 전용"));
    assertFalse(KakaoReceipt.describe(receipt().put("connection_mode","vehicle"),7).contains("집 테스트"));
  }
  @Test public void wrongMissingOrStringSequenceIsRejected()throws Exception{
    for(Object value:new Object[]{6,8,"7",JSONObject.NULL})reject(receipt().put("seq",value));
  }
  @Test public void expiredOrWrongScopeOrControlEnabledIsRejected()throws Exception{
    reject(receipt().put("received",false));reject(receipt().put("control_enabled",true));
    reject(receipt().put("control_enabled","false"));reject(receipt().put("scope","control"));
  }
  @Test public void incompleteResponseIsNotAccepted()throws Exception{
    reject(new JSONObject());reject(receipt().put("location_fresh","true"));
    reject(receipt().put("events",JSONObject.NULL));
    JSONArray oversized=new JSONArray();for(int i=0;i<9;i++)oversized.put(new JSONObject());
    reject(receipt().put("events",oversized));
  }
}
