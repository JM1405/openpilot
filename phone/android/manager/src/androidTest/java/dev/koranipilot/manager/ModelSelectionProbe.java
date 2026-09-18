package dev.koranipilot.manager;

import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.TextView;
import dev.comma.companion.PhoneClient;
import org.json.JSONObject;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Android UI with synthetic server responses. No vehicle, provider, or model execution. */
public final class ModelSelectionProbe extends Instrumentation {
  private MainActivity activity;
  private int checks;
  private Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
  private void set(Object o,String n,Object v)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
  private void call(String n)throws Exception{Method m=MainActivity.class.getDeclaredMethod(n);m.setAccessible(true);m.invoke(activity);}
  private void check(boolean pass,String n){if(!pass)throw new AssertionError(n);checks++;}
  private boolean text(View v,String text){if(v instanceof TextView&&((TextView)v).getText().toString().contains(text))return true;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)if(text(((ViewGroup)v).getChildAt(i),text))return true;return false;}
  private int enabled(View v){int n=v instanceof Button&&v.isEnabled()?1:0;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)n+=enabled(((ViewGroup)v).getChildAt(i));return n;}
  @Override public void onCreate(Bundle b){super.onCreate(b);start();}
  @Override public void onStart(){Bundle result=new Bundle();try{
    activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();
    Throwable[] failure={null};
    runOnMainSync(()->{try{
      ((Handler)get(activity,"ui")).removeCallbacks((Runnable)get(activity,"poll"));set(activity,"busy",true);
      ManagerApp app=(ManagerApp)activity.getApplication();
      PhoneClient client=new PhoneClient("https://127.0.0.1:7443","0".repeat(64));set(client,"csrf","synthetic-ui-fixture");app.client=client;
      JSONObject models=new JSONObject("{\"current\":{\"ref\":\"\",\"name\":\"CD210\"},\"configured\":{\"ref\":\"new\",\"name\":\"새 모델\"},\"requested\":null,\"progress\":null,\"message\":\"다음 기동 모델 준비됨 · 실행 확인 대기\",\"state\":\"ready\",\"editable\":true,\"can_restore_default\":true,\"revision\":\"fixture\",\"available\":[{\"ref\":\"\",\"name\":\"CD210 (기본)\"},{\"ref\":\"new\",\"name\":\"새 모델\"},{\"ref\":\"other\",\"name\":\"다른 모델\"}]}");
      models.put("schema",2);
      JSONObject overview=new JSONObject().put("models",models).put("connection",new JSONObject().put("mode","vehicle"));set(activity,"overview",overview);call("showModels");
      View body=(View)get(activity,"modelBody");AlertDialog dialog=(AlertDialog)get(activity,"modelDialog");
      check(text(body,"현재 실행")&&text(body,"CD210"),"actual model shown");check(text(body,"다음 기동 · 새 모델"),"configured separate");check(enabled(body)==2,"current configured entry disabled");
      models.put("state","downloading").put("message","모델 다운로드 중").put("editable",false).put("requested",new JSONObject().put("name","새 모델")).put("progress",42.5);call("updateModels");
      check(dialog==get(activity,"modelDialog"),"poll updates existing dialog");check(text(body,"42.5%"),"progress refreshes");check(enabled(body)==1,"only default cancellation enabled");
      models.put("editable",false).put("can_restore_default",false).put("blocked_reason","P단에 주차한 뒤 변경할 수 있어");call("updateModels");check(enabled(body)==0,"driving blocks all model controls");
      models.put("state","failed").put("message","다운로드 실패 · 기존 모델 유지").put("requested",JSONObject.NULL).put("progress",JSONObject.NULL).put("editable",true).put("can_restore_default",true).put("blocked_reason","");call("updateModels");
      check(text(body,"기존 모델 유지"),"failure remains visible");check(enabled(body)==3,"failure permits retry");
      set(activity,"overview",null);call("updateModels");check(enabled(body)==0&&text(body,"변경할 수 없어"),"connection loss disables stale buttons");
      set(activity,"overview",overview);set(activity,"visible",false);call("updateModels");check(enabled(body)==0,"background view cannot change model");
      set(activity,"visible",true);overview.getJSONObject("connection").put("mode","home_receive");call("updateModels");check(enabled(body)==0&&text(body,"집 테스트"),"home mode stays read-only");
      overview.getJSONObject("connection").put("mode","vehicle");models.remove("schema");call("updateModels");check(enabled(body)==0&&text(body,"C4 모델 관리 업데이트 필요"),"old server cannot claim actual inference");
      dialog.dismiss();app.client=null;
    }catch(Throwable e){failure[0]=e;}});
    if(failure[0]!=null)throw new AssertionError(failure[0]);result.putString("result","PASS");result.putInt("checks",checks);finish(0,result);
  }catch(Throwable e){result.putString("result","FAIL "+e);finish(1,result);}}
}
