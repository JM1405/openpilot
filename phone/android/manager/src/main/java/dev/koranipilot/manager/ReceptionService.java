package dev.koranipilot.manager;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;

/** Visible lifetime for a user-started Kakao session. Never restarts a killed session. */
public final class ReceptionService extends Service {
  static final String STOP="dev.koranipilot.manager.STOP_RECEPTION";
  private static final String CHANNEL="reception";
  private static final int NOTIFICATION=41;
  private final Handler main=new Handler(Looper.getMainLooper());
  private PowerManager.WakeLock wake;
  private long ownedToken=-1;
  private final Runnable renew=new Runnable(){public void run(){
    if(wake!=null){wake.acquire(10*60*1000L);main.postDelayed(this,60_000);}
  }};
  static void begin(Context context,Runnable stop){
    ManagerApp app=(ManagerApp)context.getApplicationContext();
    app.receptionStop=stop;long token=++app.receptionToken;
    try{context.startForegroundService(new Intent(context,ReceptionService.class).putExtra("token",token));}
    catch(RuntimeException error){app.receptionStop=null;app.receptionToken++;throw error;}
  }
  static void end(Context context){
    ManagerApp app=(ManagerApp)context.getApplicationContext();
    app.receptionStop=null;app.receptionToken++;context.stopService(new Intent(context,ReceptionService.class));
  }
  private void stopSession(){
    ManagerApp app=(ManagerApp)getApplication();Runnable stop=app.receptionStop;
    app.receptionStop=null;app.receptionToken++;
    if(stop!=null)stop.run();
  }
  @Override public int onStartCommand(Intent intent,int flags,int startId){
    ManagerApp app=(ManagerApp)getApplication();
    if(intent==null||STOP.equals(intent.getAction())){stopSession();stopSelf();return START_NOT_STICKY;}
    if(app.receptionStop==null){stopSelf();return START_NOT_STICKY;}
    if(intent.getLongExtra("token",-1)!=app.receptionToken)return START_NOT_STICKY;
    ownedToken=app.receptionToken;
    try{
      NotificationManager manager=getSystemService(NotificationManager.class);
      manager.createNotificationChannel(new NotificationChannel(CHANNEL,"카카오 수신",NotificationManager.IMPORTANCE_LOW));
      PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("screen","map"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
      PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,ReceptionService.class).setAction(STOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
      Notification notification=new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_pulse)
        .setContentTitle("고라니파일럿 수신 중").setContentText("다른 앱·화면 잠금 중에도 유지 · 눌러서 상태 확인")
        .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
        .addAction(new Notification.Action.Builder(null,"수신 중지",stop).build()).build();
      if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
      else startForeground(NOTIFICATION,notification);
      if(wake==null){
        wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"Koranipilot:reception");
        wake.setReferenceCounted(false);main.post(renew);
      }
    }catch(RuntimeException error){stopSession();stopSelf();}
    return START_NOT_STICKY;
  }
  @Override public void onTaskRemoved(Intent rootIntent){stopSession();stopSelf();}
  @Override public void onDestroy(){
    main.removeCallbacks(renew);if(wake!=null){if(wake.isHeld())wake.release();wake=null;}
    if(((ManagerApp)getApplication()).receptionToken==ownedToken)stopSession();
    stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();
  }
  @Override public IBinder onBind(Intent intent){return null;}
}
