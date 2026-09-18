package dev.koranipilot.manager;

import org.json.JSONArray;
import org.json.JSONObject;

/** A sent request is not proof that C4 accepted this particular snapshot. */
final class KakaoReceipt {
  static String describe(JSONObject response,long expectedSequence){
    Object sequence=response.opt("seq");
    JSONArray events=response.optJSONArray("events");
    if(!Boolean.TRUE.equals(response.opt("received"))||
        !Boolean.FALSE.equals(response.opt("control_enabled"))||
        !"sdk_observation".equals(response.optString("scope"))||
        !(sequence instanceof Number)||expectedSequence<=0||expectedSequence>=9007199254740992L||
        ((Number)sequence).doubleValue()!=expectedSequence||
        !(response.opt("location_fresh") instanceof Boolean)||events==null||events.length()>8){
      throw new IllegalStateException("C4가 이번 자료를 받았는지 확인하지 못했어");
    }
    return ("home_receive".equals(response.optString("connection_mode"))?"집 테스트 · 수신 전용\n":"")+
      "C4 수신 확인 #"+expectedSequence+" · "+
      (Boolean.TRUE.equals(response.opt("location_fresh"))?"GPS 유효":"GPS 대기 / 만료")+
      " · 안전 안내 "+events.length()+"개\n자동 감속 미연결";
  }
}
