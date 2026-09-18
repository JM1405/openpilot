package dev.koranipilot.manager;
import android.app.*;
import android.content.Intent;
import android.os.Bundle;
import android.view.*;
import android.widget.TextView;
import com.google.zxing.client.android.Intents;
import java.lang.reflect.*;
/** Real Android result/lifecycle flow; scanner result is synthetic, no camera-decoding claim. */
public final class QrPairingProbe extends Instrumentation {
 private int checks; private MainActivity activity;
 private void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;}
 private void main(Runnable task){Throwable[] failure={null};runOnMainSync(()->{try{task.run();}catch(Throwable t){failure[0]=t;}});if(failure[0]!=null)throw new AssertionError(failure[0]);waitForIdleSync();}
 private void call(String method){try{Method m=MainActivity.class.getDeclaredMethod(method);m.setAccessible(true);m.invoke(activity);}catch(Exception e){throw new RuntimeException(e);}}
 private boolean text(View v,String label){if(v instanceof TextView&&((TextView)v).getText().toString().contains(label))return true;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)if(text(g.getChildAt(i),label))return true;}return false;}
 @Override public void onCreate(Bundle args){super.onCreate(args);start();}
 @Override public void onStart(){Bundle result=new Bundle();try{
  activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();
  ManagerApp app=(ManagerApp)activity.getApplication();
  main(()->check(app.client==null,"opening app must not connect"));
  ActivityMonitor monitor=addMonitor(PhoneQrCaptureActivity.class.getName(),null,false);
  main(()->call("showPairing"));
  Activity scan=waitForMonitorWithTimeout(monitor,10000);check(scan!=null,"scanner opened");
  main(()->{check((scan.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0,"scanner screenshot protection");check(app.client==null,"opening camera does not connect");
   scan.setResult(Activity.RESULT_OK,new Intent().putExtra(Intents.Scan.RESULT,"KORANI1:10.209.29.93:7443:"+"AB".repeat(32)+":012345").putExtra(Intents.Scan.RESULT_FORMAT,"QR_CODE"));scan.finish();});
  waitForIdleSync();android.os.SystemClock.sleep(500);waitForIdleSync();
  main(()->{check(app.client==null,"scanned QR awaits explicit request");
   try{Field f=MainActivity.class.getDeclaredField("qrConfirmation");f.setAccessible(true);AlertDialog d=(AlertDialog)f.get(activity);check(d!=null&&d.isShowing(),"QR confirmation visible");check(text(d.getWindow().getDecorView(),"C4 연결 정보를 읽었어"),"confirmation text");check(text(d.getWindow().getDecorView(),"연결 요청"),"request action");check(!text(d.getWindow().getDecorView(),"ABABABABABAB"),"full pin not rendered");check((d.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0,"confirmation screenshot protection");d.getButton(AlertDialog.BUTTON_NEGATIVE).performClick();check(app.client==null,"cancel makes no network client");}catch(Exception e){throw new RuntimeException(e);}
  });
  result.putString("result","PASS: "+checks+" checks; scanner activity and synthetic scan result lifecycle, no physical camera scan or C4 connection");finish(Activity.RESULT_OK,result);
 }catch(Throwable e){result.putString("failure",android.util.Log.getStackTraceString(e));finish(Activity.RESULT_CANCELED,result);}}
}
