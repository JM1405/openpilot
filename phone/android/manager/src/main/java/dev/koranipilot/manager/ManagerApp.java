package dev.koranipilot.manager;

import android.app.Application;
import com.kakaomobility.knsdk.KNSDK;
import dev.comma.companion.PhoneClient;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class ManagerApp extends Application {
  public final ExecutorService network=Executors.newSingleThreadExecutor();
  public volatile PhoneClient client;
  Runnable receptionStop;
  long receptionToken;
  public boolean kakaoInstalled, kakaoReady, kakaoInitializing;
  public void installKakao(){
    if(!kakaoInstalled){KNSDK.INSTANCE.install(this,getFilesDir().getAbsolutePath()+"/kakao");kakaoInstalled=true;}
  }
  public synchronized void disconnect(){if(client!=null)client.clear();client=null;}
  public synchronized PhoneClient detach(){PhoneClient selected=client;client=null;return selected;}
}
