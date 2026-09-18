package dev.koranipilot.manager;

import android.app.Activity;
import android.app.Instrumentation;
import android.location.Location;
import android.os.Bundle;
import com.kakaomobility.knsdk.common.gps.KNGPSData;

/** Real bundled SDK conversion, synthetic positions. No SDK key or real location. */
public final class GpsStationaryProbe extends Instrumentation {
  @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
  private int checks;
  private void check(boolean value,String name){if(!value)throw new AssertionError(name);checks++;}
  @Override public void onStart(){
    Bundle result=new Bundle();
    try{
      KakaoObservation state=new KakaoObservation();state.start();
      KNGPSData gps=null;
      for(int i=0;i<12;i++){
        Location location=new Location("fused");location.setLatitude(37.5);location.setLongitude(127.0);
        location.setAccuracy(5);location.setSpeed(0);location.setBearing(0);location.setTime(10000+i*1000);
        gps=new KNGPSData(location,true);
        check(gps.getValid(),"SDK accepts synthetic stationary fix");
        check(!gps.getPosTrust(),"SDK stationary fix has no motion trust");
        state.location(gps.getValid(),gps.getPosTrust(),false,"융합",location.getTime(),location.getTime(),i*1000);
      }
      check(state.positionAvailable(11000),"stationary fix available for destination origin");
      check(state.gpsSummary(11000).equals("수신 · 신뢰 대기"),"received is distinct from trusted");
      check(!state.frame("",1,11000).getBoolean("gps_valid"),"C4 trust unchanged");
      check(!state.positionAvailable(14000),"old stationary fix still expires");
      KNGPSData snapshot=new KNGPSData(gps);
      gps.getTimestamp().setTimeInMillis(9999999);
      check(snapshot.getTimestamp().getTimeInMillis()==21000,"queued SDK timestamp snapshot is independent");
      MainActivity activity=(MainActivity)startActivitySync(new android.content.Intent(getTargetContext(),MainActivity.class).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK));
      final Throwable[] uiError={null};
      runOnMainSync(()->{try{
        java.lang.reflect.Field field=KakaoActivity.class.getDeclaredField("observation");field.setAccessible(true);
        KakaoObservation actual=(KakaoObservation)field.get(activity);actual.start();
        long wall=System.currentTimeMillis(),now=android.os.SystemClock.elapsedRealtime();
        actual.location(true,false,false,"융합",wall,wall,now);
        java.lang.reflect.Method refresh=KakaoActivity.class.getDeclaredMethod("refreshLocalStatus");refresh.setAccessible(true);refresh.invoke(activity);
        field=KakaoActivity.class.getDeclaredField("gpsSummary");field.setAccessible(true);
        check(((android.widget.TextView)field.get(activity)).getText().toString().equals("수신 · 신뢰 대기"),"real Activity shows stationary receipt");
        field=KakaoActivity.class.getDeclaredField("localStatus");field.setAccessible(true);
        String detail=((android.widget.TextView)field.get(activity)).getText().toString();
        check(detail.contains("공급 · 융합")&&detail.contains("신뢰 · 대기"),"detail exposes cause without coordinates");
        check(!detail.contains("37.5")&&!detail.contains("127.0"),"no coordinates in diagnostics");
        actual.reset();refresh.invoke(activity);
        field=KakaoActivity.class.getDeclaredField("gpsSummary");field.setAccessible(true);
        check(((android.widget.TextView)field.get(activity)).getText().toString().equals("수신 전"),"stopped UI clears location state");
      }catch(Throwable error){uiError[0]=error;}finally{activity.finish();}});
      if(uiError[0]!=null)throw new AssertionError(uiError[0]);
      result.putString("result","PASS");result.putInt("checks",checks);
      result.putString("scope","Bundled SDK with synthetic stationary locations; not physical phone or C4 GPS");
      finish(Activity.RESULT_OK,result);
    }catch(Throwable error){result.putString("result","FAIL");result.putString("failure",error.toString());result.putInt("checks",checks);finish(Activity.RESULT_CANCELED,result);}
  }
}
