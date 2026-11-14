package dev.koranipilot.manager;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

public final class GuidanceService extends Service {
  static final String ACTION_STOP = "dev.koranipilot.manager.STOP_GUIDANCE";
  private static final String CHANNEL_ID = "koranipilot_guidance";
  private static final int NOTIFICATION_ID = 70;

  private final Handler main = new Handler(Looper.getMainLooper());
  private PowerManager.WakeLock wakeLock;
  private long ownedToken = -1L;

  private final Runnable renewWakeLock = new Runnable() {
    @Override public void run() {
      if (wakeLock != null) {
        wakeLock.acquire(10 * 60 * 1000L);
        main.postDelayed(this, 60_000L);
      }
    }
  };

  static void begin(Context context, Runnable stopAction) {
    KoraniApp app = (KoraniApp) context.getApplicationContext();
    app.guidanceStop = stopAction;
    long token = ++app.guidanceToken;
    Intent intent = new Intent(context, GuidanceService.class).putExtra("token", token);
    try {
      context.startForegroundService(intent);
    } catch (RuntimeException err) {
      app.guidanceStop = null;
      app.guidanceToken++;
      throw err;
    }
  }

  static void end(Context context) {
    KoraniApp app = (KoraniApp) context.getApplicationContext();
    app.guidanceStop = null;
    app.guidanceToken++;
    context.stopService(new Intent(context, GuidanceService.class));
  }

  private void stopSession() {
    KoraniApp app = (KoraniApp) getApplication();
    Runnable cb = app.guidanceStop;
    app.guidanceStop = null;
    app.guidanceToken++;
    if (cb != null) cb.run();
  }

  @Override public int onStartCommand(Intent intent, int flags, int startId) {
    KoraniApp app = (KoraniApp) getApplication();
    if (intent == null || ACTION_STOP.equals(intent.getAction())) {
      stopSession();
      stopSelf();
      return START_NOT_STICKY;
    }
    if (app.guidanceStop == null || intent.getLongExtra("token", -1L) != app.guidanceToken) {
      stopSelf();
      return START_NOT_STICKY;
    }
    ownedToken = app.guidanceToken;

    try {
      NotificationManager nm = getSystemService(NotificationManager.class);
      if (nm != null) {
        nm.createNotificationChannel(new NotificationChannel(
            CHANNEL_ID, "고라니파일럿 주행 연동", NotificationManager.IMPORTANCE_LOW));
      }
      PendingIntent openIntent = PendingIntent.getActivity(
          this,
          0,
          new Intent(this, MainActivity.class)
              .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP),
          PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
      PendingIntent stopIntent = PendingIntent.getService(
          this,
          1,
          new Intent(this, GuidanceService.class).setAction(ACTION_STOP),
          PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

      Notification notification = new Notification.Builder(this, CHANNEL_ID)
          .setSmallIcon(R.drawable.ic_korani)
          .setContentTitle("고라니파일럿 연동 중")
          .setContentText("방지턱 · 커브 · 단속 정보를 콤마4로 전달 중")
          .setContentIntent(openIntent)
          .setOngoing(true)
          .setOnlyAlertOnce(true)
          .addAction(new Notification.Action.Builder(null, "연동 중지", stopIntent).build())
          .build();

      if (Build.VERSION.SDK_INT >= 29) {
        startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
      } else {
        startForeground(NOTIFICATION_ID, notification);
      }

      if (wakeLock == null) {
        PowerManager pm = getSystemService(PowerManager.class);
        if (pm != null) {
          wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Koranipilot:Guidance");
          wakeLock.setReferenceCounted(false);
          main.post(renewWakeLock);
        }
      }
    } catch (RuntimeException err) {
      stopSession();
      stopSelf();
    }
    return START_NOT_STICKY;
  }

  @Override public void onTaskRemoved(Intent rootIntent) {
    stopSession();
    stopSelf();
  }

  @Override public void onDestroy() {
    main.removeCallbacks(renewWakeLock);
    if (wakeLock != null) {
      try { if (wakeLock.isHeld()) wakeLock.release(); } catch (Exception ignored) {}
      wakeLock = null;
    }
    KoraniApp app = (KoraniApp) getApplication();
    if (app.guidanceToken == ownedToken) {
      stopSession();
    }
    stopForeground(STOP_FOREGROUND_REMOVE);
    super.onDestroy();
  }

  @Override public IBinder onBind(Intent intent) {
    return null;
  }
}
