package dev.koranipilot.manager;

import android.app.*;
import android.content.Intent;
import android.location.Location;
import android.os.*;
import java.io.File;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.util.List;
import org.json.*;

/** Real Android recording/lifecycle; synthetic callbacks, no SDK key or C4. */
public final class ObservationProbe extends Instrumentation {
  private int checks;
  private void check(boolean value,String label){if(!value)throw new AssertionError(label);checks++;}
  private void main(Runnable task){runOnMainSync(task);waitForIdleSync();}
  @Override public void onCreate(Bundle args){super.onCreate(args);start();}
  @Override public void onStart(){
    Bundle report=new Bundle();MainActivity activity=null;InputRecorder recorder=null;
    try{
      activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      Field f=KakaoActivity.class.getDeclaredField("inputRecorder");f.setAccessible(true);recorder=(InputRecorder)f.get(activity);
      InputRecorder current=recorder;
      check(!current.active(),"recording never starts automatically");
      main(current::start);check(current.active(),"explicit local recording starts");
      main(()->{
        Location location=new Location("gps");location.setLatitude(37);location.setLongitude(127);location.setAccuracy(4);
        location.setElapsedRealtimeNanos(SystemClock.elapsedRealtimeNanos()-500_000_000L);location.setTime(System.currentTimeMillis()-500);
        location.setSpeed(10);location.setBearing(90);location.setBearingAccuracyDegrees(5);current.onLocationChanged(location);
        try{
          current.location(true,true,false,System.currentTimeMillis()-500,System.currentTimeMillis(),false);
          current.safety(new JSONArray().put(new JSONObject().put("kind","camera").put("code","synthetic")
            .put("geometry",JSONObject.NULL).put("challenge","do-not-record").put("csrf","do-not-record")),false);
          current.receipt(new JSONObject().put("location_fresh",true).put("connection_mode","home_receive")
            .put("token","do-not-record").put("csrf","do-not-record"),25_000_000);
        }catch(Exception e){throw new RuntimeException(e);}
      });
      check(current.exportable()==null,"active file cannot be exported");
      MainActivity owner=activity;
      main(()->{try{Method stop=KakaoActivity.class.getDeclaredMethod("stop");stop.setAccessible(true);stop.invoke(owner);}catch(Exception e){throw new RuntimeException(e);}});
      for(int i=0;i<40&&current.exportable()==null;i++)SystemClock.sleep(50);
      check(!current.active(),"reception stop also stops recording");
      File file=current.exportable();check(file!=null,"closed recording can be exported");
      List<String> rows=Files.readAllLines(file.toPath());check(rows.size()>=6,"all observation kinds written");
      check(!new JSONObject(rows.get(0)).getBoolean("control_output"),"observation scope only");
      check(new JSONObject(rows.get(rows.size()-1)).getBoolean("complete"),"recording closes cleanly");
      String text=String.join("\n",rows);check(!text.contains("do-not-record")&&!text.contains("csrf")&&!text.contains("challenge"),"credentials never recorded");
      long count=rows.size();main(()->current.location(true,true,false,1,2,true));SystemClock.sleep(100);
      check(Files.readAllLines(file.toPath()).size()==count,"stopped callbacks cannot append");
      main(()->{try{Method show=KakaoActivity.class.getDeclaredMethod("showDetails");show.setAccessible(true);show.invoke(owner);}catch(Exception e){throw new RuntimeException(e);}});
      check(!current.active(),"opening details never restarts recording");
      report.putString("result","PASS");report.putInt("checks",checks);report.putString("scope","Android storage/lifecycle with synthetic callbacks; no real GPS/SDK/C4 proof");
      report.putString("recording",file.getName());main(activity::finish);finish(Activity.RESULT_OK,report);
    }catch(Throwable error){
      if(recorder!=null){InputRecorder current=recorder;main(()->current.stop("test_error"));}
      if(activity!=null)main(activity::finish);
      report.putString("result","FAIL");report.putString("error",error.toString());report.putInt("checks",checks);finish(Activity.RESULT_CANCELED,report);
    }
  }
}
