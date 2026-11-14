package dev.koranipilot.manager;

import android.app.Application;
import com.kakaomobility.knsdk.KNSDK;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class KoraniApp extends Application {
  public final ExecutorService network = Executors.newSingleThreadExecutor();
  public Runnable guidanceStop;
  public long guidanceToken;
  public boolean kakaoInstalled;
  public boolean kakaoReady;
  public boolean kakaoInitializing;

  public synchronized void installKakao() {
    if (!kakaoInstalled) {
      KNSDK.INSTANCE.install(this, getFilesDir().getAbsolutePath() + "/kakao");
      kakaoInstalled = true;
    }
  }
}
