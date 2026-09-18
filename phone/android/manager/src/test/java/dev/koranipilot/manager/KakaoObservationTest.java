package dev.koranipilot.manager;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class KakaoObservationTest {
  @Test public void stationaryLocationIsAvailableWithoutBecomingTrustedC4Input()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();
    state.location(true,false,false,"융합",10000,10000,0);
    assertTrue(state.positionAvailable(100));
    assertEquals("수신 · 신뢰 대기",state.gpsSummary(100));
    assertFalse(frame(state,100).getBoolean("gps_valid"));
    assertFalse(state.positionAvailable(3000));
    assertEquals("위치 만료",state.gpsSummary(3000));
  }
  @Test public void missingInvalidFutureAndSimulatedInputsHaveDistinctReasons()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();
    assertEquals("위치 미수신",state.gpsSummary(0));
    state.location(false,false,false,"GPS",10000,10000,0);
    assertEquals("위치 무효",state.gpsSummary(0));
    state.location(true,true,true,"모의",11000,11000,1000);
    assertEquals("모의 위치",state.gpsSummary(1000));
    assertFalse(state.positionAvailable(1000));assertFalse(frame(state,1000).getBoolean("gps_valid"));
    state.location(true,true,false,"GPS",9999999,12000,2000);
    assertEquals("시각 불일치",state.gpsSummary(2000));
    state.location(true,true,false,"GPS",12000,12000,2000);
    assertTrue(frame(state,2000).getBoolean("gps_valid"));
    state.location(true,true,false,"GPS",11000,12000,2001);
    assertEquals("지난 위치",state.gpsSummary(2001));assertFalse(state.positionAvailable(2001));
  }
  private JSONObject frame(KakaoObservation state,long now)throws Exception{return state.frame("challenge",1,now);}

  @Test public void repeatedGpsCallbacksCannotRenewStaleLocation()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();state.location(true,10000,10000,0);
    assertTrue(frame(state,0).getBoolean("gps_valid"));
    state.location(true,10000,14000,4000);
    assertFalse(frame(state,4000).getBoolean("gps_valid"));
    state.location(true,14000,14000,4000);
    assertTrue(frame(state,4000).getBoolean("gps_valid"));
  }
  @Test public void oldFutureAndOutOfOrderGpsAreNotFresh()throws Exception{
    for(long timestamp:new long[]{1000,21000}){
      KakaoObservation state=new KakaoObservation();state.start();state.location(true,timestamp,20000,0);
      assertFalse(frame(state,0).getBoolean("gps_valid"));
    }
    KakaoObservation state=new KakaoObservation();state.start();state.location(true,20000,20000,0);
    state.location(true,19000,20000,1);
    assertFalse(frame(state,1).getBoolean("gps_valid"));
  }
  @Test public void absentLocationAndRouteAreNeverInferred()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();JSONObject body=frame(state,0);
    assertFalse(body.getBoolean("gps_valid"));assertFalse(body.getBoolean("route_matched"));
    assertTrue(body.isNull("location_age_ms"));assertTrue(body.isNull("speed_kph"));
    assertEquals("free_drive",body.getString("mode"));
  }
  @Test public void safetyExpiresEvenWhileLocationUpdates()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();state.safety(new JSONArray().put(new JSONObject().put("id","corner")),0);
    assertEquals(1,frame(state,1000).getJSONArray("events").length());
    state.location(true,14000,14000,4000);
    assertTrue(frame(state,4000).getBoolean("gps_valid"));
    assertEquals(0,frame(state,4000).getJSONArray("events").length());
  }
  @Test public void stoppingOrRestartingDropsPreviousData()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();state.location(true,10000,10000,0);
    state.safety(new JSONArray().put(new JSONObject().put("id","camera")),0);state.reset();
    assertFalse(frame(state,1).getBoolean("active"));assertEquals(0,frame(state,1).getJSONArray("events").length());
    state.start();assertFalse(frame(state,2).getBoolean("gps_valid"));assertEquals(0,frame(state,2).getJSONArray("events").length());
  }
  @Test public void callbackAndRequestCopiesCannotMutateState()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();JSONArray values=new JSONArray().put(new JSONObject().put("id","corner"));
    state.safety(values,0);values.getJSONObject(0).put("id","changed");
    JSONObject copy=frame(state,1);copy.getJSONArray("events").getJSONObject(0).put("id","changed-again");
    assertEquals("corner",frame(state,2).getJSONArray("events").getJSONObject(0).getString("id"));
  }
  @Test public void standaloneStatusDoesNotNeedConnectionAndPreservesExpiry()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();state.location(true,10000,10000,0);
    state.safety(new JSONArray().put(new JSONObject().put("kind","sharp_turn")),0);
    String text=state.statusText(1000);
    assertTrue(text.contains("GPS 유효"));assertTrue(text.contains("급커브 1"));
    assertFalse(text.contains("C4"));assertFalse(text.contains("challenge"));
    text=state.statusText(3000);
    assertTrue(text.contains("GPS 대기 / 만료"));assertFalse(text.contains("급커브 1"));
    state.reset();assertEquals("폰 수신 중지",state.statusText(4000));
  }
  @Test public void emptyCallbackAndNoCallbackRemainDistinctOnPhone()throws Exception{
    KakaoObservation state=new KakaoObservation();state.start();
    assertTrue(state.statusText(0).contains("콜백 대기 / 만료"));
    state.safety(new JSONArray(),0);
    assertTrue(state.statusText(0).contains("안전 안내 0개"));
    assertFalse(state.statusText(0).contains("GPS 유효"));
  }
}
