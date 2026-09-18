package dev.koranipilot.manager;

import android.content.Context;
import android.location.*;
import android.os.*;
import java.io.File;
import java.util.UUID;
import org.json.*;

/** Explicit local recording, independent of RoadGps and C4 permissions. */
final class InputRecorder implements LocationListener {
  private final Context context;
  private final LocationManager locations;
  private final Handler main=new Handler(Looper.getMainLooper());
  private volatile ObservationLog log;
  private File latest;
  private String error="";
  InputRecorder(Context context){
    this.context=context;locations=(LocationManager)context.getSystemService(Context.LOCATION_SERVICE);
    String name=context.getSharedPreferences("input-observation",0).getString("latest","");
    if(name.matches("input-[a-f0-9-]+\\.jsonl"))latest=new File(context.getFilesDir(),name);
  }
  boolean active(){return log!=null&&log.active();}
  File exportable(){return (log==null||log.finished())&&latest!=null&&latest.isFile()?latest:null;}
  String status(){return active()?"기록 중 · "+log.rows()+"개":log!=null&&!log.finished()?"저장 마무리 중":!error.isEmpty()?error:log!=null?(log.reason().equals("storage_error")||log.reason().equals("encode_error")||log.reason().equals("queue_limit")?"저장 오류 · 기록 종료":"기록 종료 · "+log.rows()+"개"):"기록 대기";}
  @SuppressWarnings("MissingPermission")
  void start(){
    if(log!=null&&!log.finished())return;
    error="";
    try{
      if(!locations.isProviderEnabled(LocationManager.GPS_PROVIDER)){error="폰의 위치 기능을 켜줘";return;}
      latest=new File(context.getFilesDir(),"input-"+UUID.randomUUID()+".jsonl");
      startedAt=SystemClock.elapsedRealtimeNanos();log=new ObservationLog(latest,startedAt);
      context.getSharedPreferences("input-observation",0).edit().putString("latest",latest.getName()).apply();
      locations.requestLocationUpdates(LocationManager.GPS_PROVIDER,100L,0f,this,Looper.getMainLooper());
      main.post(limitCheck);
    }catch(Exception failure){error="기록을 시작하지 못했어";stop("start_error");}
  }
  private final Runnable limitCheck=new Runnable(){public void run(){
    ObservationLog current=log;if(current==null)return;
    if(current.active()){
      if(SystemClock.elapsedRealtimeNanos()-startedAt>=ObservationLog.MAX_NS){stop("duration_limit");return;}
      main.postDelayed(this,1000);
    }else stop(current.reason());
  }};
  private long startedAt;
  void stop(String reason){
    main.removeCallbacks(limitCheck);startedAt=0;
    try{locations.removeUpdates(this);}catch(RuntimeException ignored){}
    if(log!=null)log.stop(reason,SystemClock.elapsedRealtimeNanos());
  }
  private void put(String type,JSONObject data){ObservationLog current=log;if(current!=null)current.append(type,data,SystemClock.elapsedRealtimeNanos());}
  @SuppressWarnings("deprecation")
  @Override public void onLocationChanged(Location p){
    if(!active())return;
    try{put("gps",new JSONObject().put("fix_elapsed_ns",p.getElapsedRealtimeNanos()).put("utc_ms",p.getTime())
      .put("longitude",p.getLongitude()).put("latitude",p.getLatitude())
      .put("accuracy_m",p.hasAccuracy()?p.getAccuracy():JSONObject.NULL)
      .put("speed_mps",p.hasSpeed()?p.getSpeed():JSONObject.NULL).put("bearing_deg",p.hasBearing()?p.getBearing():JSONObject.NULL)
      .put("bearing_accuracy_deg",p.hasBearingAccuracy()?p.getBearingAccuracyDegrees():JSONObject.NULL)
      .put("gps_provider",LocationManager.GPS_PROVIDER.equals(p.getProvider()))
      .put("mock",Build.VERSION.SDK_INT>=31?p.isMock():p.isFromMockProvider()));}catch(Exception error){stop("encode_error");}
  }
  void location(boolean valid,boolean trusted,boolean simulated,long sourceMs,long wallMs,boolean route){
    if(!active())return;
    try{put("sdk_location",new JSONObject().put("valid",valid).put("trusted",trusted).put("simulated",simulated)
      .put("source_utc_ms",sourceMs).put("received_utc_ms",wallMs).put("route_mode",route));}catch(Exception error){stop("encode_error");}
  }
  void safety(JSONArray events,boolean route){
    if(!active())return;
    try{
      JSONArray clean=new JSONArray();
      for(int i=0;i<Math.min(8,events.length());i++){
        JSONObject e=events.getJSONObject(i),r=new JSONObject();
        for(String key:new String[]{"code","kind","limit_kph","passed","variable","geometry"})r.put(key,e.opt(key));
        clean.put(r);
      }
      put("sdk_safety",new JSONObject().put("route_mode",route).put("events",clean));
    }catch(Exception error){stop("encode_error");}
  }
  void receipt(JSONObject reply,long roundTripNs){
    if(!active())return;
    try{put("receipt",new JSONObject().put("round_trip_ns",roundTripNs)
      .put("location_fresh",reply.optBoolean("location_fresh")).put("home_receive","home_receive".equals(reply.optString("connection_mode")))
      .put("control_enabled",reply.optBoolean("control_enabled")));}catch(Exception error){stop("encode_error");}
  }
  @Override public void onProviderDisabled(String provider){stop("gps_disabled");}
  @Override public void onProviderEnabled(String provider){}
  @Override public void onStatusChanged(String provider,int state,Bundle extras){}
}
