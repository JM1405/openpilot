package dev.koranipilot.manager;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.List;
import java.util.Map;

/** Ephemeral route snapshot. Full SDK geometry only; no resampling or control output. */
final class RouteSnapshot {
  static final int MAX_POINTS=65536;
  static final int CHUNK_POINTS=2048;
  private long epoch,revision,locationAt=-1,timestamp=-1,sourceAge;
  private String state="idle",destination="",geometryStatus="unavailable";
  private JSONArray geometry=new JSONArray();
  private String shapeId="";
  private int totalM,totalS,remainingM,remainingS;
  private boolean matched;
  private String turnCode="",turnLabel="";
  private int turnDistance=-1;

  synchronized long begin(String name){epoch++;destination=clean(name,120);transition("planning");return epoch;}
  synchronized boolean current(long token){return token==epoch&&!state.equals("ended")&&!state.equals("idle");}
  synchronized boolean hasDestination(){return !state.equals("idle")&&!state.equals("ended");}
  synchronized void hold(){if(hasDestination())transition("rerouting");}
  synchronized void fail(){if(hasDestination()){epoch++;transition("error");}}
  synchronized boolean planning(long token){return token==epoch&&state.equals("planning");}
  synchronized void end(){epoch++;destination="";transition("ended");}
  private void transition(String next){revision++;turnCode=turnLabel="";turnDistance=-1;state=next;shapeId="";geometry=new JSONArray();geometryStatus="unavailable";matched=false;locationAt=-1;}
  synchronized void install(List<Map<String,Number>> points,int meters,int seconds)throws Exception{
    if(!hasDestination())return;
    if(meters<0||meters>3000000||seconds<0||seconds>604800){fail();return;}
    transition("active");totalM=meters;totalS=seconds;
    if(points==null||points.size()<2)return;
    if(points.size()>MAX_POINTS){geometryStatus="too_large";return;}
    JSONArray result=new JSONArray();
    java.security.MessageDigest digest=java.security.MessageDigest.getInstance("SHA-256");
    java.nio.ByteBuffer bytes=java.nio.ByteBuffer.allocate(16);
    for(Map<String,Number> point:points){
      Number x=point.get("x"),y=point.get("y");
      if(x==null||y==null||!Double.isFinite(x.doubleValue())||!Double.isFinite(y.doubleValue())||Math.abs(x.doubleValue())>180||Math.abs(y.doubleValue())>90)return;
      result.put(new JSONArray().put(x.doubleValue()).put(y.doubleValue()));
      bytes.clear();bytes.putDouble(x.doubleValue()).putDouble(y.doubleValue());digest.update(bytes.array());
    }
    geometry=result;geometryStatus="full";StringBuilder hash=new StringBuilder();for(byte b:digest.digest())hash.append(String.format(java.util.Locale.ROOT,"%02x",b&255));shapeId=hash.toString();
  }
  synchronized void location(boolean onRoute,long sample,long wall,long monotonic,int meters,int seconds){
    if(!state.equals("active"))return;
    if(sample>timestamp){timestamp=sample;sourceAge=wall>=sample?wall-sample:Long.MAX_VALUE;locationAt=monotonic;}
    // Changing routes may reuse a GPS timestamp; derive its original age, never renew it.
    if(sample==timestamp&&locationAt<0){sourceAge=wall>=sample?wall-sample:Long.MAX_VALUE;locationAt=monotonic;}
    matched=onRoute&&sample==timestamp&&sourceAge<3000&&meters>=0&&meters<=3000000&&seconds>=0&&seconds<=604800;
    remainingM=meters;remainingS=seconds;
  }
  synchronized void turn(String code,int distance){
    turnCode=code==null?"":code;turnLabel=TurnHint.label(turnCode);turnDistance=distance;
    if(turnLabel.isEmpty()||distance<0||distance>3000000){turnCode=turnLabel="";turnDistance=-1;}
  }
  synchronized long revision(){return revision;}
  synchronized JSONObject frame(String nonce,long seq,long now)throws Exception{return snapshot(nonce,seq,now,true);}
  synchronized JSONObject statusFrame(String nonce,long seq,long now)throws Exception{return snapshot(nonce,seq,now,false);}
  private JSONObject snapshot(String nonce,long seq,long now,boolean legacy)throws Exception{
    long age=locationAt<0||now<locationAt||sourceAge>=3000?Long.MAX_VALUE:sourceAge+now-locationAt;
    boolean fresh=state.equals("active")&&matched&&age>=0&&age<3000,active=state.equals("active");
    JSONObject result=new JSONObject().put("challenge",nonce).put("seq",seq).put("revision",revision).put("state",state)
      .put("destination",destination).put("geometry_status",geometryStatus)
      .put("total_m",active?totalM:JSONObject.NULL).put("total_s",active?totalS:JSONObject.NULL)
      .put("remaining_m",fresh?remainingM:JSONObject.NULL).put("remaining_s",fresh?remainingS:JSONObject.NULL)
      .put("location_age_ms",fresh?age:JSONObject.NULL).put("matched",fresh);
    if(legacy)return result.put("geometry",new JSONArray(geometry.toString()));
    return result.put("protocol",2).put("shape_id",shapeId).put("point_count",geometry.length())
      .put("turn",fresh&&turnDistance>=0?new JSONObject().put("code",turnCode).put("label",turnLabel).put("distance_m",turnDistance):JSONObject.NULL);
  }
  synchronized JSONObject chunk(String nonce,long seq,long expectedRevision,int offset)throws Exception{
    if(revision!=expectedRevision||!state.equals("active")||!geometryStatus.equals("full")||offset<0||offset>=geometry.length())return null;
    JSONArray points=new JSONArray();for(int i=offset;i<Math.min(offset+CHUNK_POINTS,geometry.length());i++)points.put(new JSONArray(geometry.getJSONArray(i).toString()));
    return new JSONObject().put("challenge",nonce).put("seq",seq).put("revision",revision).put("shape_id",shapeId).put("offset",offset).put("points",points);
  }
  synchronized String summary(long now){
    switch(state){
      case "planning":return destination+" · 경로 탐색 중";
      case "rerouting":return destination+" · 재탐색 중";
      case "error":return destination+" · 다시 탐색해 줘";
      case "active":
        try{JSONObject frame=statusFrame("",0,now);if(frame.getBoolean("matched"))return destination+" · "+String.format(java.util.Locale.KOREA,"%.1f km · %d분",remainingM/1000.,(remainingS+59)/60);}catch(Exception ignored){}
        return destination+" · 위치 확인 중";
      default:return "목적지를 검색해 봐";
    }
  }
  static String clean(String text,int limit){if(text==null)return "";String clean=text.replaceAll("[\\p{Cntrl}]"," ").trim();return clean.substring(0,Math.min(limit,clean.length()));}
}
