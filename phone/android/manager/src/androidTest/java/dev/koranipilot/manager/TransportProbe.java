package dev.koranipilot.manager;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import dev.comma.companion.PhoneClient;
import org.json.JSONObject;

/** Emulator to desktop loopback TLS only. No SDK login, location permission or real C4. */
public final class TransportProbe extends Instrumentation {
  private Bundle args;
  private Object read(MainActivity activity,String name)throws Exception{
    java.lang.reflect.Field field=KakaoActivity.class.getDeclaredField(name);field.setAccessible(true);return field.get(activity);
  }
  @Override public void onCreate(Bundle arguments){super.onCreate(arguments);args=arguments;start();}
  @Override public void onStart(){
    Bundle out=new Bundle();String stage="pair";
    try{
      PhoneClient client=new PhoneClient(args.getString("url"),args.getString("pin"));
      client.call("pair",new JSONObject().put("code",args.getString("code")).put("name","Android fixture"));
      stage="approval";
      for(int i=0;i<20&&!client.connected();i++){SystemClock.sleep(100);client.call("session",null);}
      if(!client.connected())throw new AssertionError("fixture approval timed out");
      stage="overview";client.call("overview",null);
      KakaoObservation observation=new KakaoObservation();observation.start();
      stage="kakao challenge";String nonce=client.call("kakao",null).getString("challenge");
      long sequence=client.navigationSequence.incrementAndGet();
      if("reset".equals(args.getString("fault"))){
        stage="injected reset";
        try{client.call("kakao",observation.frame(nonce,sequence,SystemClock.elapsedRealtime()));throw new AssertionError("reset was accepted");}
        catch(PhoneClient.TransportException error){
          String diagnostic=KakaoTransferFailure.code(KakaoTransferFailure.Stage.SEND,error);
          if(!diagnostic.startsWith("K3 ")||!diagnostic.contains("/"))throw new AssertionError("missing transport diagnostic");
          out.putString("diagnostic",diagnostic);
        }
        client.call("session",null);
        out.putString("result","PASS: aborted upload reports transport phase; subsequent session is readable");
        finish(Activity.RESULT_OK,out);return;
      }
      stage="kakao send";JSONObject receipt=client.call("kakao",observation.frame(nonce,sequence,SystemClock.elapsedRealtime()));
      stage="kakao receipt";KakaoReceipt.describe(receipt,sequence);
      if("background".equals(args.getString("fault"))){
        stage="background service";
        ManagerApp app=(ManagerApp)getTargetContext().getApplicationContext();app.client=client;
        Intent open=new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
        MainActivity activity=(MainActivity)startActivitySync(open);waitForIdleSync();
        java.lang.reflect.Field running=KakaoActivity.class.getDeclaredField("running");running.setAccessible(true);
        java.lang.reflect.Method stop=KakaoActivity.class.getDeclaredMethod("stop");stop.setAccessible(true);
        runOnMainSync(()->{try{
          running.set(activity,true);((KakaoObservation)read(activity,"observation")).start();
          ReceptionService.begin(activity,()->{try{stop.invoke(activity);}catch(Exception error){throw new AssertionError(error);}});
          ((Runnable)read(activity,"poll")).run();
        }catch(Exception error){throw new AssertionError(error);}});
        SystemClock.sleep(1200);
        long epoch=(Long)read(activity,"generation");long before=client.navigationSequence.get();
        stage="home while receiving";
        getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        for(int i=0;i<50&&(Boolean)read(activity,"visible");i++)SystemClock.sleep(100);
        if((Boolean)read(activity,"visible"))throw new AssertionError("Activity did not leave foreground");
        SystemClock.sleep(3200);
        if(!(Boolean)running.get(activity)||client.navigationSequence.get()<before+4)throw new AssertionError("background reception stopped");
        stage="screen off while receiving";
        getUiAutomation().executeShellCommand("input keyevent KEYCODE_SLEEP").close();SystemClock.sleep(400);
        if(getTargetContext().getSystemService(android.os.PowerManager.class).isInteractive())throw new AssertionError("screen did not sleep");
        before=client.navigationSequence.get();SystemClock.sleep(3200);
        if(client.navigationSequence.get()<before+4)throw new AssertionError("screen off stopped sending");
        getUiAutomation().executeShellCommand("input keyevent KEYCODE_WAKEUP").close();
        getUiAutomation().executeShellCommand("wm dismiss-keyguard").close();
        getTargetContext().startActivity(open);
        for(int i=0;i<50&&!(Boolean)read(activity,"visible");i++)SystemClock.sleep(100);
        if(!(Boolean)running.get(activity)||(Long)read(activity,"generation")!=epoch)throw new AssertionError("return restarted reception");
        String[] text=new String[1];runOnMainSync(()->{try{text[0]=((android.widget.TextView)read(activity,"linkSummary")).getText().toString();}catch(Exception error){throw new AssertionError(error);}});
        if(!text[0].startsWith("집 수신 확인 #")||!text[0].contains("GPS 대기 / 만료"))throw new AssertionError("receipt/GPS status missing: "+text[0]);
        stage="notification stop";
        getTargetContext().startService(new Intent(getTargetContext(),ReceptionService.class).setAction(ReceptionService.STOP));
        SystemClock.sleep(1500);
        if((Boolean)running.get(activity)||app.receptionStop!=null)throw new AssertionError("notification did not stop reception");
        before=client.navigationSequence.get();SystemClock.sleep(1200);
        if(client.navigationSequence.get()!=before)throw new AssertionError("send continued after stop");
        app.client=null;runOnMainSync(activity::finish);
        out.putString("result","PASS: real home/screen-off/return keeps TLS reception; notification stops; GPS status stays unconfirmed");
      }else if("repeat".equals(args.getString("fault"))){
        RouteSnapshot route=new RouteSnapshot();
        for(int i=0;i<30;i++){
          stage="repeat "+i+" kakao challenge";nonce=client.call("kakao",null).getString("challenge");
          sequence=client.navigationSequence.incrementAndGet();
          stage="repeat "+i+" kakao send";receipt=client.call("kakao",observation.frame(nonce,sequence,SystemClock.elapsedRealtime()));
          KakaoReceipt.describe(receipt,sequence);
          stage="repeat "+i+" route";RouteTransfer.send(client,route,SystemClock::elapsedRealtime,()->true);
          client.call("session",null);client.call("overview",null);
        }
        out.putString("result","PASS: 30 repeated Android Kakao/route/session/overview TLS cycles");
      }else if("route".equals(args.getString("fault"))){
        stage="UI route failure after accepted Kakao receipt";
        ManagerApp app=(ManagerApp)getTargetContext().getApplicationContext();app.client=client;
        MainActivity activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();
        java.lang.reflect.Method send=KakaoActivity.class.getDeclaredMethod("send");send.setAccessible(true);
        runOnMainSync(()->{try{send.invoke(activity);}catch(Exception error){throw new AssertionError(error);}});
        for(int i=0;i<100&&(Boolean)read(activity,"busy");i++)SystemClock.sleep(100);
        waitForIdleSync();
        String[] texts=new String[2];runOnMainSync(()->{try{
          texts[0]=((android.widget.TextView)read(activity,"linkSummary")).getText().toString();
          texts[1]=((android.widget.TextView)read(activity,"transportStatus")).getText().toString();
        }catch(Exception error){throw new AssertionError(error);}});
        if(!texts[0].startsWith("집 수신 확인 #")||!texts[0].contains("경로 확인 실패")||!texts[1].contains("R1 HTTP 409/revision")){
          throw new AssertionError("honest partial receipt/diagnostic missing: "+texts[0]+" / "+texts[1]);
        }
        app.client=null;runOnMainSync(activity::finish);
        out.putString("result","PASS: actual Activity retains validated Kakao receipt and identifies route HTTP 409/revision");
      }else{
        stage="idle route";
        RouteSnapshot route=new RouteSnapshot();
        RouteTransfer.send(client,route,SystemClock::elapsedRealtime,()->true);
        stage="ended route";route.end();RouteTransfer.send(client,route,SystemClock::elapsedRealtime,()->true);
        stage="API diagnostic";
        try{client.call("kakao",new JSONObject());throw new AssertionError("invalid fixture accepted");}
        catch(PhoneClient.ApiException error){if(error.status!=400||!"invalid".equals(error.code))throw new AssertionError("HTTP code lost");}
        out.putString("result","PASS: Android TLS pairing, no-GPS Kakao, idle/ended route, HTTP error diagnostics");
      }
      out.putString("scope","Android emulator + desktop synthetic home telemetry; no SDK, physical phone, C4 or vehicle");
      client.call("logout",new JSONObject());
      finish(Activity.RESULT_OK,out);
    }catch(Throwable error){
      out.putString("result","FAIL");out.putString("stage",stage);
      // This fixture uses only generated credentials and synthetic payloads.
      out.putString("failure",error.getClass().getSimpleName()+": "+error.getMessage());
      out.putString("fixture_trace",android.util.Log.getStackTraceString(error));
      finish(Activity.RESULT_CANCELED,out);
    }
  }
}
