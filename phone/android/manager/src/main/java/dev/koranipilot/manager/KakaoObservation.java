package dev.koranipilot.manager;

import org.json.JSONArray;
import org.json.JSONObject;

/** Pure, clock-injected snapshot. No SDK objects, coordinates, credentials or control outputs. */
final class KakaoObservation {
  private boolean active, gpsValid, routeMode, received, sdkValid, trusted, simulated;
  private String source="미확인", rejected="";
  private long locationAt=-1, gpsTimestamp=-1, safetyAt=-1;
  private long sourceAge;
  private JSONArray events=new JSONArray();

  synchronized void start(){reset();active=true;}
  synchronized void routeMode(boolean value){routeMode=value;}
  synchronized void reset(){active=false;gpsValid=false;routeMode=false;locationAt=-1;gpsTimestamp=-1;safetyAt=-1;events=new JSONArray();received=false;sdkValid=false;trusted=false;simulated=false;source="미확인";rejected="";}

  synchronized void location(boolean valid,long timestampMs,long wallMs,long monotonicMs){
    location(valid,valid,false,"SDK",timestampMs,wallMs,monotonicMs);
  }

  synchronized void location(boolean valid,boolean trust,boolean simulation,String provider,long timestampMs,long wallMs,long monotonicMs){
    if(!active)return;
    received=true;sdkValid=valid;trusted=trust;simulated=simulation;source=provider;rejected="";
    // Do not let one future/missing sample poison the ordering watermark forever.
    if(timestampMs<=0||timestampMs>wallMs){gpsValid=false;rejected=timestampMs<=0?"시각 없음":"시각 불일치";return;}
    if(timestampMs<gpsTimestamp){gpsValid=false;rejected="지난 위치";return;}
    // A repeated GPS sample must age even when the SDK calls back repeatedly.
    if(timestampMs>gpsTimestamp){
      gpsTimestamp=timestampMs;locationAt=monotonicMs;
      sourceAge=wallMs>=timestampMs?wallMs-timestampMs:Long.MAX_VALUE;
    }
    gpsValid=valid&&trust&&!simulation&&timestampMs==gpsTimestamp&&sourceAge<3000;
  }

  private long locationAge(long now){
    if(locationAt<0||now<locationAt||sourceAge>Long.MAX_VALUE-(now-locationAt))return Long.MAX_VALUE;
    return sourceAge+now-locationAt;
  }

  synchronized boolean positionAvailable(long now){
    return active&&received&&sdkValid&&!simulated&&rejected.isEmpty()&&locationAge(now)<3000;
  }

  synchronized String gpsSummary(long now){
    if(!active)return "수신 전";
    if(!received)return "위치 미수신";
    if(!rejected.isEmpty())return rejected;
    if(simulated)return "모의 위치";
    if(locationAge(now)>=3000)return "위치 만료";
    if(!sdkValid)return "위치 무효";
    return trusted?"유효":"수신 · 신뢰 대기";
  }

  synchronized String diagnostics(long now){
    long age=locationAge(now);
    return "위치 · "+gpsSummary(now)+"\n공급 · "+source+" / SDK · "+(sdkValid?"유효":"대기")
      +" / 신뢰 · "+(trusted?"확인":"대기")+"\n원본 나이 · "+(age==Long.MAX_VALUE?"미확인":String.format(java.util.Locale.ROOT,"%.1f초",age/1000.));
  }

  synchronized void safety(JSONArray values,long monotonicMs)throws Exception{
    if(!active)return;
    events=new JSONArray(values.toString());safetyAt=monotonicMs;
  }

  synchronized String statusText(long monotonicMs)throws Exception{
    // Display uses the same expiry rules as the wire snapshot, without a C4 session.
    JSONObject current=frame("",0,monotonicMs,true);
    if(!current.getBoolean("active"))return "폰 수신 중지";
    String gps=current.getBoolean("gps_valid")?"GPS 유효":"GPS 대기 / 만료";
    if(current.isNull("safety_age_ms"))return gps+" · 안전 안내 콜백 대기 / 만료";
    JSONArray rows=current.getJSONArray("events");
    int cameras=0,sections=0,bumps=0,corners=0,positionedCameras=0;
    for(int i=0;i<rows.length();i++){
      String kind=rows.getJSONObject(i).optString("kind");
      if(kind.equals("camera")){cameras++;if(!rows.getJSONObject(i).isNull("geometry"))positionedCameras++;}
      if(kind.equals("section"))sections++;
      if(kind.equals("bump"))bumps++;
      if(kind.equals("sharp_turn"))corners++;
    }
    return gps+" · 안전 안내 "+rows.length()+"개\n단속 "+cameras+" / 구간 "+sections+" / 방지턱 "+bumps+" / 급커브 "+corners
      +"\n단속 위치·방향 좌표 "+positionedCameras+"개 수신";
  }

  synchronized JSONObject frame(String challenge,long seq,long monotonicMs)throws Exception{
    return frame(challenge,seq,monotonicMs,false);
  }

  synchronized JSONObject frame(String challenge,long seq,long monotonicMs,boolean geometry)throws Exception{
    long age=locationAge(monotonicMs);
    if(age<0)age=Long.MAX_VALUE;
    long safetyAge=safetyAt<0||monotonicMs<safetyAt?Long.MAX_VALUE:monotonicMs-safetyAt;
    JSONArray rows=active&&safetyAge<3000?new JSONArray(events.toString()):new JSONArray();
    for(int i=0;i<rows.length();i++){
      JSONObject row=rows.getJSONObject(i);
      if(!geometry)row.remove("geometry");else if(!row.has("geometry"))row.put("geometry",JSONObject.NULL);
    }
    JSONObject result=new JSONObject().put("challenge",challenge).put("seq",seq).put("mode",routeMode?"route":"free_drive")
      .put("active",active).put("gps_valid",active&&gpsValid&&age<3000)
      .put("location_age_ms",age<3000?age:JSONObject.NULL)
      // The public documentation's speed unit is not part of this receiver's contract yet.
      .put("speed_kph",JSONObject.NULL).put("route_matched",false)
      .put("safety_age_ms",safetyAge<3000?safetyAge:JSONObject.NULL)
      .put("events",rows);
    if(geometry)result.put("event_geometry_version",1).put("sdk_simulation",simulated);
    return result;
  }
}
