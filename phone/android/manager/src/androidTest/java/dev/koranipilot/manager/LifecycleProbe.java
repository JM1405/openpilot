package dev.koranipilot.manager;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import java.lang.reflect.Field;

/** Real Android Activity/service lifecycle, synthetic receiver flags; no SDK key/GPS/C4. */
public final class LifecycleProbe extends Instrumentation {
  private int checks;
  private MainActivity activity;
  @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
  private static Field field(Class<?> type,String name){try{Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}catch(Exception e){throw new RuntimeException(e);}}
  private Object read(Class<?> type,Object value,String name){try{return field(type,name).get(value);}catch(Exception e){throw new RuntimeException(e);}}
  private void put(Class<?> type,Object value,String name,Object data){try{field(type,name).set(value,data);}catch(Exception e){throw new RuntimeException(e);}}
  private Object callbacks(long epoch){try{Class<?> type=Class.forName("dev.koranipilot.manager.KakaoActivity$GuideCallbacks");java.lang.reflect.Constructor<?> ctor=type.getDeclaredConstructor(KakaoActivity.class,long.class);ctor.setAccessible(true);return ctor.newInstance(activity,epoch);}catch(Exception e){throw new RuntimeException(e);}}
  private void check(boolean pass,String name){if(!pass)throw new AssertionError(name);checks++;}
  private void main(Runnable task){Throwable[] failure={null};runOnMainSync(()->{try{task.run();}catch(Throwable e){failure[0]=e;}});if(failure[0]!=null)throw new AssertionError(failure[0]);waitForIdleSync();}
  private View find(View view,String description){
    if(view.isShown()&&description.contentEquals(view.getContentDescription()==null?"":view.getContentDescription()))return view;
    if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int i=0;i<group.getChildCount();i++){View result=find(group.getChildAt(i),description);if(result!=null)return result;}}
    return null;
  }
  private void tab(String name){View view=find(activity.getWindow().getDecorView(),name);check(view!=null,"tab exists: "+name);check(view.performClick(),"tab click: "+name);}
  private boolean secure(){return (activity.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0;}
  @Override public void onStart(){
    Bundle result=new Bundle();
    try{
      Intent intent=new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
      activity=(MainActivity)startActivitySync(intent);waitForIdleSync();
      String idleGps=activity.roadGps.status();
      getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      for(int i=0;i<50&&(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->{
        check(!(Boolean)read(KakaoActivity.class,activity,"visible"),"idle app really paused");
        check(idleGps.equals(activity.roadGps.status()),"unused road GPS does not claim transmission stopped");
      });
      getTargetContext().startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP));
      for(int i=0;i<50&&!(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->check(!activity.roadGps.running()&&idleGps.equals(activity.roadGps.status()),"unused road GPS remains unused on return"));
      final long[] generation={0};final long[] epoch={0};final long[] routeToken={0};
      main(()->{
        check(!activity.receiving()&&!activity.roadGps.running(),"cold start never auto receives");
        check(!secure(),"home can be captured without visible secrets");
        // Only session flags are injected. Starting providers/SDK is deliberately outside this test.
        put(KakaoActivity.class,activity,"running",true);put(RoadGps.class,activity.roadGps,"running",true);
        ReceptionService.begin(activity,()->{try{java.lang.reflect.Method stop=KakaoActivity.class.getDeclaredMethod("stop");stop.setAccessible(true);stop.invoke(activity);}catch(Exception e){throw new RuntimeException(e);}});
        RouteSnapshot route=(RouteSnapshot)read(KakaoActivity.class,activity,"routeState");routeToken[0]=route.begin("합성 목적지");
        generation[0]=(Long)read(KakaoActivity.class,activity,"generation");epoch[0]=(Long)read(RoadGps.class,activity.roadGps,"epoch");
      });
      SystemClock.sleep(500);
      main(()->check(((ManagerApp)activity.getApplication()).receptionStop!=null,"foreground session registered"));
      for(String name:new String[]{"지도","기기","홈","지도"})main(()->{
        tab(name);check(activity.receiving()&&activity.roadGps.running(),"both sessions survive "+name);
        check(generation[0]==(Long)read(KakaoActivity.class,activity,"generation")&&epoch[0]==(Long)read(RoadGps.class,activity.roadGps,"epoch"),"session identities unchanged "+name);
        check(((RouteSnapshot)read(KakaoActivity.class,activity,"routeState")).current(routeToken[0]),"destination session survives "+name);
        check(secure()==name.equals("지도"),"only visible key entry protects window "+name);
      });
      getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      for(int i=0;i<50&&(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->{
        check(!(Boolean)read(KakaoActivity.class,activity,"visible"),"Home causes real onPause");
        check(activity.receiving()&&!activity.roadGps.running(),"leaving app keeps Kakao; manual road GPS remains separate");
        check(((RouteSnapshot)read(KakaoActivity.class,activity,"routeState")).current(routeToken[0]),"leaving app preserves trip session");
        check(((RouteSnapshot)read(KakaoActivity.class,activity,"routeState")).hasDestination(),"leaving app preserves destination");
        check((Long)read(RoadGps.class,activity.roadGps,"epoch")>epoch[0],"leaving app invalidates queued GPS work");
      });
      getTargetContext().startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP));
      for(int i=0;i<50&&!(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->{check((Boolean)read(KakaoActivity.class,activity,"visible"),"same Activity resumes");check(activity.receiving()&&!activity.roadGps.running(),"return keeps Kakao without restart");check(generation[0]==(Long)read(KakaoActivity.class,activity,"generation"),"return does not create a new session");});
      main(()->{
        put(KakaoActivity.class,activity,"automaticRoadGps",true);put(RoadGps.class,activity.roadGps,"running",true);
        epoch[0]=(Long)read(RoadGps.class,activity.roadGps,"epoch");
      });
      getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      for(int i=0;i<50&&(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->check(activity.receiving()&&activity.roadGps.running()&&epoch[0]==(Long)read(RoadGps.class,activity.roadGps,"epoch"),"automatic driving GPS survives actual Home pause"));
      getTargetContext().startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP));
      for(int i=0;i<50&&!(Boolean)read(KakaoActivity.class,activity,"visible");i++)SystemClock.sleep(100);
      main(()->{
        try{
          java.lang.reflect.Method update=KakaoActivity.class.getDeclaredMethod("updateDrivingGps",boolean.class);update.setAccessible(true);update.invoke(activity,false);
          check(!activity.roadGps.running()&&!(Boolean)read(KakaoActivity.class,activity,"automaticRoadGps"),"home/disabled capability revokes automatic GPS");
          put(KakaoActivity.class,activity,"automaticRoadGps",true);put(RoadGps.class,activity.roadGps,"running",true);
          java.lang.reflect.Method toggle=KakaoActivity.class.getDeclaredMethod("toggleRoadGps");toggle.setAccessible(true);toggle.invoke(activity);
          update.invoke(activity,true);
          check(!activity.roadGps.running()&&(Boolean)read(KakaoActivity.class,activity,"roadGpsOptOut"),"manual GPS stop is not undone by next capability receipt");
        }catch(Exception e){throw new RuntimeException(e);}
      });
      main(()->{
        put(KakaoActivity.class,activity,"running",true);
        ((com.kakaomobility.knsdk.guidance.knguidance.KNGuidance_GuideStateDelegate)callbacks(generation[0]-1)).guidanceGuideEnded(null);
      });
      main(()->{
        check(activity.receiving(),"old SDK delegate cannot stop new session");
        ((com.kakaomobility.knsdk.guidance.knguidance.KNGuidance_GuideStateDelegate)callbacks((Long)read(KakaoActivity.class,activity,"generation"))).guidanceGuideEnded(null);
      });
      main(()->check(!activity.receiving(),"current SDK end stops session"));
      main(()->{
        put(KakaoActivity.class,activity,"running",true);
        ReceptionService.begin(activity,()->{try{java.lang.reflect.Method stop=KakaoActivity.class.getDeclaredMethod("stop");stop.setAccessible(true);stop.invoke(activity);}catch(Exception e){throw new RuntimeException(e);}});
      });
      main(()->{put(KakaoActivity.class,activity,"automaticRoadGps",true);put(RoadGps.class,activity.roadGps,"running",true);});
      SystemClock.sleep(300);
      getTargetContext().startService(new Intent(getTargetContext(),ReceptionService.class).setAction(ReceptionService.STOP));
      SystemClock.sleep(300);
      main(()->check(!activity.receiving()&&!activity.roadGps.running()&&((ManagerApp)activity.getApplication()).receptionStop==null,"notification stop ends receiver and service ownership"));
      result.putString("result","PASS");result.putInt("checks",checks);result.putString("scope","Android lifecycle with synthetic receiving flags; no SDK authentication, real GPS or C4");
      main(()->activity.finish());finish(Activity.RESULT_OK,result);
    }catch(Throwable failure){result.putString("result","FAIL");result.putString("failure",failure.toString());result.putInt("checks",checks);finish(Activity.RESULT_CANCELED,result);}
  }
}
