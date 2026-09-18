package dev.koranipilot.manager;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import dev.comma.companion.PhoneClient;
import dev.comma.gpslive.LiveFix;
import dev.comma.gpslive.LiveSession;
import org.json.JSONObject;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/** Manual GPS for the unified foreground Activity. No background service or saved positions. */
final class RoadGps implements LocationListener {
  private final Context context;
  private final ManagerApp app;
  private final LocationManager locations;
  private final Handler ui=new Handler(Looper.getMainLooper());
  private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
  private ScheduledFuture<?> ticks;
  private LiveSession session;
  private volatile long epoch;
  private volatile boolean running;
  private volatile String status="GPS 전송 전",roadStatus="도로 판별 대기";
  private volatile long lastFix;

  RoadGps(Context context,ManagerApp app){this.context=context;this.app=app;locations=(LocationManager)context.getSystemService(Context.LOCATION_SERVICE);}
  boolean running(){return running;}
  String status(){return status;}
  String roadStatus(){return roadStatus;}
  String gpsStatus(){return running&&lastFix>0&&SystemClock.elapsedRealtimeNanos()-lastFix<200_000_000L?"위치 수신 중":"새 위치 대기";}

  void start(){
    if(running)return;
    PhoneClient selected=app.client;
    if(selected==null||!selected.connected()){status="C4 연결 승인이 필요해";return;}
    if(context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED){status="정확한 위치 권한이 필요해";return;}
    if(!locations.isProviderEnabled(LocationManager.GPS_PROVIDER)){status="폰의 위치 기능을 켜줘";return;}
    long attempt=++epoch;running=true;status="도로 입력 확인 중";
    worker.execute(()->{
      String error=null;
      try{
        JSONObject overview=selected.call("overview",null);
        if("home_receive".equals(overview.getJSONObject("connection").optString("mode")))error="집 테스트는 카카오 수신만 가능해";
        else if(!"observation_only".equals(overview.getJSONObject("road_input").optString("scope")))error="C4의 도로 입력이 꺼져 있어";
      }catch(Exception failure){error="C4 도로 입력을 확인하지 못했어";}
      String failure=error;
      ui.post(()->{if(!running||epoch!=attempt||app.client!=selected)return;if(failure!=null){stop(failure);return;}subscribe(selected,attempt);});
    });
  }

  @SuppressWarnings("MissingPermission")
  private void subscribe(PhoneClient selected,long attempt){
    LiveSession next=new LiveSession((path,json)->{
      // Retired sessions still send their own stop token; they cannot send fixes.
      if((epoch!=attempt&&!"road/stop".equals(path))||app.client!=selected)throw new LiveSession.AuthorizationRequired();
      try{JSONObject result=selected.call(path,new JSONObject(json));return new LiveSession.Reply(result.optString("status"),result.optString("sync_id"));}
      catch(Exception error){if(!selected.connected())throw new LiveSession.AuthorizationRequired();throw error;}
    },SystemClock::elapsedRealtimeNanos);
    session=next;
    try{
      locations.requestLocationUpdates(LocationManager.GPS_PROVIDER,100L,0f,this,Looper.getMainLooper());
      status="새 GPS 위치 대기";
      ticks=worker.scheduleWithFixedDelay(()->{
        if(epoch!=attempt)return;next.tick();if(epoch!=attempt)return;status=next.status();
        if(!selected.connected())ui.post(()->{if(epoch==attempt)stop("폰 승인이 만료됐어 · 다시 연결해");});
      },0,50,TimeUnit.MILLISECONDS);
    }catch(RuntimeException error){stop("GPS 전송을 시작하지 못했어");}
  }

  void refreshRoadStatus(Runnable refreshed){
    PhoneClient selected=app.client;if(!running||selected==null)return;long attempt=epoch;
    app.network.execute(()->{
      String summary;
      try{
        JSONObject result=selected.call("road/status",null);
        summary=!result.optBoolean("fresh")?"도로 서비스 대기":result.optBoolean("input_available")?"도로 입력 확인됨":"도로 입력 보류 · "+result.optString("input_status");
      }catch(Exception error){summary="도로 상태 확인 대기";}
      String latest=summary;
      ui.post(()->{if(attempt==epoch&&selected==app.client){roadStatus=latest;refreshed.run();}});
    });
  }

  void stop(String reason){
    epoch++;running=false;lastFix=0;status=reason;roadStatus="도로 판별 대기";
    try{locations.removeUpdates(this);}catch(RuntimeException ignored){}
    LiveSession old=session;session=null;if(old!=null)old.stop();
    if(ticks!=null){ticks.cancel(false);ticks=null;}
    if(old!=null)worker.execute(old::finish);
  }
  @SuppressWarnings("deprecation")
  @Override public void onLocationChanged(Location value){
    if(!running||session==null)return;long received=SystemClock.elapsedRealtimeNanos();lastFix=value.getElapsedRealtimeNanos();
    session.offer(new LiveFix(lastFix,received,value.getLongitude(),value.getLatitude(),
      value.hasSpeed()?(double)value.getSpeed():null,value.hasBearing()?(double)value.getBearing():null,
      value.hasAccuracy()?(double)value.getAccuracy():null,value.hasBearingAccuracy()?(double)value.getBearingAccuracyDegrees():null,
      Build.VERSION.SDK_INT>=31?value.isMock():value.isFromMockProvider(),LocationManager.GPS_PROVIDER.equals(value.getProvider())));
  }
  @Override public void onProviderDisabled(String provider){stop("GPS가 꺼져 전송 중지");}
  @Override public void onProviderEnabled(String provider){}
  @Override public void onStatusChanged(String provider,int state,android.os.Bundle extras){}
  void close(){stop("GPS 전송 중지");worker.shutdown();}
}
