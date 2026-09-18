package dev.koranipilot.manager;

import android.app.Instrumentation;
import android.app.Dialog;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.SeekBar;
import android.widget.TextView;
import dev.comma.companion.PhoneClient;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Actual native screens + pinned TLS; the server uses synthetic parked input. */
public final class SettingsProbe extends Instrumentation {
  private Bundle args;
  private MainActivity activity;
  private SettingsSheet sheet;
  private PhoneClient client;
  private int checks;
  @Override public void onCreate(Bundle arguments){super.onCreate(arguments);args=arguments;start();}
  private Object get(Object target,String name){try{Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(target);}catch(Exception e){throw new RuntimeException(e);}}
  private void call(Object target,String name){try{Method method=target.getClass().getDeclaredMethod(name);method.setAccessible(true);method.invoke(target);}catch(Exception e){throw new RuntimeException(e);}}
  private void check(boolean pass,String label){if(!pass)throw new AssertionError(label);checks++;}
  private void main(Runnable action){Throwable[] failure={null};runOnMainSync(()->{try{action.run();}catch(Throwable error){failure[0]=error;}});waitForIdleSync();if(failure[0]!=null)throw new AssertionError(failure[0]);}
  private View find(View root,String value){
    if(root instanceof TextView&&!(root instanceof EditText)&&value.contentEquals(((TextView)root).getText()))return root;
    if(root instanceof ViewGroup){ViewGroup group=(ViewGroup)root;for(int i=0;i<group.getChildCount();i++){View v=find(group.getChildAt(i),value);if(v!=null)return v;}}
    return null;
  }
  private <T> T type(View root,Class<T> kind){if(kind.isInstance(root))return kind.cast(root);if(root instanceof ViewGroup){ViewGroup group=(ViewGroup)root;for(int i=0;i<group.getChildCount();i++){T v=type(group.getChildAt(i),kind);if(v!=null)return v;}}return null;}
  private View root(){return ((Dialog)get(sheet,"dialog")).getWindow().getDecorView();}
  private AlertDialog editor(){return (AlertDialog)get(sheet,"editor");}
  private void row(String title){View found=find(root(),title);check(found!=null,"row exists: "+title);View click=found;while(!click.isClickable())click=(View)click.getParent();check(click.performClick(),"open: "+title);}
  private void search(String value){((EditText)get(sheet,"search")).setText(value);}
  private void screenshot(String name)throws Exception{
    waitForIdleSync();SystemClock.sleep(200);Bitmap bitmap=getUiAutomation().takeScreenshot();check(bitmap!=null,"screenshot");
    File folder=new File(getTargetContext().getExternalFilesDir(null),"settings-probe");folder.mkdirs();try(FileOutputStream output=new FileOutputStream(new File(folder,name+".png"))){bitmap.compress(Bitmap.CompressFormat.PNG,100,output);}bitmap.recycle();
  }
  private void waitReady()throws Exception{for(int i=0;i<100;i++){final boolean[] ready={false};main(()->ready[0]=(Boolean)get(sheet,"ready")&&!(Boolean)get(sheet,"waiting")&&get(activity,"uncertain")==null);if(ready[0])return;SystemClock.sleep(100);}throw new AssertionError("catalog ready");}
  @Override public void onStart(){
    Bundle result=new Bundle();
    try{
      activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();
      main(()->{call(activity,"showSettings");sheet=(SettingsSheet)get(activity,"settingsSheet");check(((JSONObject)get(sheet,"catalog")).optJSONArray("rows").length()==74,"offline full catalog");check(!(Boolean)get(sheet,"ready"),"offline not editable");});
      screenshot("01-categories-offline");
      main(()->{row("조향 · MADS");check(find(root(),"조향·속도 분리")!=null,"steering navigation");search("마찰");row("마찰 보정");check(!find(editor().getWindow().getDecorView(),"저장").isEnabled(),"offline numeric write disabled");editor().dismiss();search("");sheet.dismiss();});
      client=new PhoneClient(args.getString("url"),args.getString("pin"));client.call("pair",new JSONObject().put("code",args.getString("code")).put("name","Settings probe"));
      for(int i=0;i<50;i++){if("connected".equals(client.call("session",null).optString("state")))break;SystemClock.sleep(100);}
      check(client.connected(),"server approved synthetic session");
      main(()->{((ManagerApp)activity.getApplication()).client=client;call(activity,"refresh");});
      for(int i=0;i<50;i++){if(get(activity,"overview")!=null)break;SystemClock.sleep(100);}
      main(()->{call(activity,"showSettings");sheet=(SettingsSheet)get(activity,"settingsSheet");});waitReady();
      screenshot("02-categories-connected");
      main(()->row("조향 · MADS"));screenshot("03-steering");
      main(()->{search("브레이크");row("브레이크 시 조향");check(find(editor().getWindow().getDecorView(),"유지")!=null,"enum labels");editor().dismiss();search("학습");check(find(root(),"자동 학습")!=null&&find(root(),"학습 조건 완화")!=null,"search across categories");});
      screenshot("04-search");
      main(()->{search("짧게");row("짧게 누를 때");SeekBar slider=type(editor().getWindow().getDecorView(),SeekBar.class);check(slider!=null&&slider.isEnabled(),"numeric slider enabled");slider.setProgress(3);});
      screenshot("05-number");
      main(()->{find(editor().getWindow().getDecorView(),"저장").performClick();check(editor().getButton(AlertDialog.BUTTON_POSITIVE)!=null,"explicit confirmation");editor().getButton(AlertDialog.BUTTON_POSITIVE).performClick();});
      waitReady();
      JSONObject catalog=client.call("catalog",null);boolean saved=false;for(int i=0;i<catalog.getJSONArray("rows").length();i++){JSONObject row=catalog.getJSONArray("rows").getJSONObject(i);if(row.getString("id").equals("CustomAccShortPressIncrement")){saved=row.getInt("saved")==4;check(row.isNull("current"),"save never invents runtime application");}}
      check(saved,"numeric value reached server as integer");
      main(()->{search("마찰");row("마찰 보정");SeekBar slider=type(editor().getWindow().getDecorView(),SeekBar.class);check(slider!=null&&slider.isEnabled(),"decimal slider");slider.setProgress(14);});screenshot("06-decimal");
      main(()->{find(editor().getWindow().getDecorView(),"저장").performClick();editor().getButton(AlertDialog.BUTTON_POSITIVE).performClick();});waitReady();
      catalog=client.call("catalog",null);saved=false;for(int i=0;i<catalog.getJSONArray("rows").length();i++){JSONObject row=catalog.getJSONArray("rows").getJSONObject(i);if(row.getString("id").equals("TorqueParamsOverrideFriction"))saved=Math.abs(row.getDouble("saved")-.15)<.00001;}check(saved,"decimal value reached server");
      main(()->{search("차로 변경 방식");row("차로 변경 방식");check(!find(editor().getWindow().getDecorView(),"즉시").isEnabled(),"deferred feature locked");editor().dismiss();search("토크 바");row("조향 토크 바");check(!find(editor().getWindow().getDecorView(),"켬").isEnabled(),"unsupported C4 feature locked");editor().dismiss();search("전원");row("시동 종료 후 전원");check(find(editor().getWindow().getDecorView(),"30시간")!=null,"mapped values");editor().dismiss();search("MADS");});
      // Pause invalidates open editors and permissions, without touching reception.
      getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));SystemClock.sleep(500);
      main(()->check(!(Boolean)get(sheet,"ready"),"pause invalidates catalog authorization"));
      result.putString("result","PASS: "+checks+" native settings checks; real TLS to synthetic C4");finish(ActivityResult.OK,result);
    }catch(Throwable error){result.putString("result","FAIL: "+error);android.util.Log.e("SettingsProbe","failure",error);finish(ActivityResult.FAIL,result);}
  }
  private static final class ActivityResult{static final int OK=-1,FAIL=0;}
}
