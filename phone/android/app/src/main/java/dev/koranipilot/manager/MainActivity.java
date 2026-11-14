package dev.koranipilot.manager;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import com.kakaomobility.knsdk.*;
import com.kakaomobility.knsdk.api.objects.*;
import com.kakaomobility.knsdk.common.gps.*;
import com.kakaomobility.knsdk.common.objects.*;
import com.kakaomobility.knsdk.common.util.*;
import com.kakaomobility.knsdk.guidance.knguidance.*;
import com.kakaomobility.knsdk.guidance.knguidance.common.*;
import com.kakaomobility.knsdk.guidance.knguidance.locationguide.*;
import com.kakaomobility.knsdk.guidance.knguidance.routeguide.*;
import com.kakaomobility.knsdk.guidance.knguidance.routeguide.objects.*;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.*;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.objects.*;
import com.kakaomobility.knsdk.guidance.knguidance.voiceguide.*;
import com.kakaomobility.knsdk.trip.kntrip.*;
import com.kakaomobility.knsdk.trip.kntrip.knroute.*;
import com.kakaomobility.knsdk.ui.view.*;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import kotlin.Unit;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends AppCompatActivity {
  private static final String PREF_NAME = "korani_prefs";
  private static final String KEY_KAKAO_KEY = "kakao_native_key";
  private static final int REQ_LOC_PERM = 101;
  private static final int REQ_NOTIF_PERM = 102;

  private static final int BG = Color.parseColor("#0D1412");
  private static final int CARD = Color.parseColor("#16221E");
  private static final int CARD2 = Color.parseColor("#1D2C27");
  private static final int ACCENT = Color.parseColor("#5CE0A8");
  private static final int TEXT = Color.parseColor("#F2F6F4");
  private static final int MUTED = Color.parseColor("#9CB2A8");
  private static final int WARN = Color.parseColor("#F5B942");

  private KoraniApp app;
  private SharedPreferences prefs;
  private C4Link c4Link;
  private final Handler ui = new Handler(Looper.getMainLooper());
  private final AtomicLong seqCounter = new AtomicLong(0);

  private TextView c4StatusText;
  private TextView navStatusText;
  private TextView decelText;
  private LinearLayout keySetupCard;
  private Button toggleKeyCardBtn;
  private EditText keyInput;
  private Button startBtn;
  private Button searchBtn;
  private Button endRouteBtn;
  private Button webBtn;
  private FrameLayout mapHost;
  private TextView mapPlaceholder;

  private KNNaviView naviView;
  private KNDriveGuidance guidance;
  private KNTrip activeTrip;
  private KNRoute activeRoute;
  private KNLocation latestMatchedLoc;
  private IntPoint originKatec;
  private long originTimestampMs = -1L;

  private volatile List<? extends KNSafety> aroundSafeties = new ArrayList<>();
  private volatile List<? extends KNSafety> guideSafeties = new ArrayList<>();
  private volatile double gpsLat = Double.NaN;
  private volatile double gpsLon = Double.NaN;
  private volatile Double gpsBearing = null;
  private volatile Double gpsSpeedMps = null;
  private volatile Double gpsAccuracyM = null;
  private volatile boolean gpsValid = false;
  private volatile boolean gpsMock = false;
  private volatile long gpsMonoMs = 0L;

  private volatile boolean running = false;
  private volatile boolean visible = false;
  private volatile boolean busySending = false;
  private volatile long generation = 0L;
  private volatile long searchGeneration = 0L;
  private boolean notifPermissionAsked = false;
  private boolean pendingStartAfterPerm = false;
  private AlertDialog searchDialog;
  private LocationManager locationManager;
  private boolean locationListening = false;

  private final LocationListener androidLocListener = new LocationListener() {
    @Override public void onLocationChanged(Location loc) {
      if (loc == null) return;
      gpsLat = loc.getLatitude();
      gpsLon = loc.getLongitude();
      gpsBearing = loc.hasBearing() ? (double) loc.getBearing() : null;
      gpsSpeedMps = loc.hasSpeed() ? (double) loc.getSpeed() : null;
      gpsAccuracyM = loc.hasAccuracy() ? (double) loc.getAccuracy() : null;
      gpsMock = Build.VERSION.SDK_INT >= 31 ? loc.isMock() : loc.isFromMockProvider();
      gpsValid = Double.isFinite(gpsLat) && Double.isFinite(gpsLon);
      gpsMonoMs = SystemClock.elapsedRealtime();
    }
    @Override public void onProviderEnabled(String provider) {}
    @Override public void onProviderDisabled(String provider) {}
    @Override @SuppressWarnings("deprecation") public void onStatusChanged(String p, int s, Bundle b) {}
  };

  private final Runnable pushLoop = new Runnable() {
    @Override public void run() {
      pushNavTick();
      if (running) {
        ui.postDelayed(this, 500L);
      }
    }
  };

  private final Runnable discoveryLoop = new Runnable() {
    @Override public void run() {
      if (!running && visible) {
        app.network.execute(() -> {
          c4Link.ensureConnected();
          ui.post(() -> {
            if (visible) updateConnectionBanner();
          });
        });
      }
      if (visible) {
        ui.postDelayed(this, 3000L);
      }
    }
  };

  @Override protected void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    app = (KoraniApp) getApplication();
    prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE);
    c4Link = new C4Link(this);
    locationManager = (LocationManager) getSystemService(LOCATION_SERVICE);

    buildUi();
    loadSavedKeyUi();
    handleIncomingIntent(getIntent());
    c4Link.start();
  }

  @Override protected void onNewIntent(Intent intent) {
    super.onNewIntent(intent);
    setIntent(intent);
    handleIncomingIntent(intent);
  }

  private void handleIncomingIntent(Intent intent) {
    if (intent == null || intent.getData() == null) return;
    C4Link.HostPort parsed = C4Link.parseDeepLink(intent.getData().toString());
    if (parsed != null) {
      c4Link.setManualTarget(parsed);
      updateConnectionBanner();
      Toast.makeText(this, "콤마4 주소를 연결했어요 (" + parsed.host + ")", Toast.LENGTH_SHORT).show();
    }
  }

  private void buildUi() {
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    root.setBackgroundColor(BG);
    root.setPadding(dp(12), dp(10), dp(12), dp(10));

    // Top C4 Connection Card
    LinearLayout connCard = card();
    LinearLayout connRow = row();
    c4StatusText = label(15, TEXT, true);
    c4StatusText.setText("콤마4 찾는 중...");
    connRow.addView(c4StatusText, new LinearLayout.LayoutParams(0, -2, 1f));

    Button ipBtn = smallBtn("IP 입력", false, this::promptManualIp);
    connRow.addView(ipBtn, marginEnd(dp(6)));

    webBtn = smallBtn("웹 리모컨 ↗", true, this::openWebRemote);
    connRow.addView(webBtn);
    connCard.addView(connRow);

    navStatusText = label(13, MUTED, false);
    navStatusText.setPadding(0, dp(6), 0, 0);
    navStatusText.setText("핫스팟을 켜고 [주행 연동 시작]을 누르면 방지턱 · 커브 · 단속이 연동돼요.");
    connCard.addView(navStatusText);

    decelText = label(14, ACCENT, true);
    decelText.setPadding(0, dp(4), 0, 0);
    decelText.setText("감속 안내 대기 중");
    connCard.addView(decelText);
    root.addView(connCard, marginBottom(dp(8)));

    // Key Setup Toggle + Card
    LinearLayout keyHdrRow = row();
    toggleKeyCardBtn = smallBtn("카카오 키 설정 ▾", false, () -> {
      boolean show = keySetupCard.getVisibility() != View.VISIBLE;
      keySetupCard.setVisibility(show ? View.VISIBLE : View.GONE);
    });
    keyHdrRow.addView(toggleKeyCardBtn, marginEnd(dp(8)));
    toggleKeyCardBtn.setVisibility(View.GONE);

    startBtn = bigBtn("주행 연동 시작 ▶", true, () -> {
      if (running) stopGuidance(true);
      else startGuidanceFlow();
    });
    keyHdrRow.addView(startBtn, new LinearLayout.LayoutParams(0, -2, 1f));
    root.addView(keyHdrRow, marginBottom(dp(8)));

    // Collapsible Kakao Key Setup Card (shown until valid 32-char key saved)
    keySetupCard = card();
    TextView keyTitle = label(14, TEXT, true);
    keyTitle.setText("최초 1회 카카오 네이티브 앱 키 등록");
    keySetupCard.addView(keyTitle);

    TextView keyHelp = label(12, MUTED, false);
    keyHelp.setPadding(0, dp(4), 0, dp(6));
    keyHelp.setText("카카오 디벨로퍼스(앱 설정 → Android 플랫폼)에 아래 패키지명과 키 해시를 등록한 뒤 32자리 네이티브 앱 키를 넣으세요. 한 번 저장하면 다음엔 바로 시작돼요.");
    keySetupCard.addView(keyHelp);

    LinearLayout copyRow = row();
    copyRow.addView(smallBtn("패키지명 복사", false, () -> {
      KeyHashUtil.copyToClipboard(this, "package", getPackageName());
      Toast.makeText(this, "복사됨: " + getPackageName(), Toast.LENGTH_SHORT).show();
    }), new LinearLayout.LayoutParams(0, -2, 1f));
    View spacer = new View(this);
    copyRow.addView(spacer, new LinearLayout.LayoutParams(dp(8), 1));
    String keyHash = KeyHashUtil.getSha1KeyHash(this);
    copyRow.addView(smallBtn("키 해시 복사", false, () -> {
      KeyHashUtil.copyToClipboard(this, "keyHash", keyHash);
      Toast.makeText(this, "키 해시 복사됨: " + keyHash, Toast.LENGTH_LONG).show();
    }), new LinearLayout.LayoutParams(0, -2, 1f));
    keySetupCard.addView(copyRow, marginBottom(dp(8)));

    keyInput = new EditText(this);
    keyInput.setHint("카카오 네이티브 앱 키 (32자리)");
    keyInput.setHintTextColor(MUTED);
    keyInput.setTextColor(TEXT);
    keyInput.setSingleLine(true);
    keyInput.setBackgroundColor(CARD2);
    keyInput.setPadding(dp(10), dp(8), dp(10), dp(8));
    keyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
    keySetupCard.addView(keyInput, marginBottom(dp(8)));

    Button saveKeyBtn = bigBtn("키 저장하기", true, this::saveEnteredKey);
    keySetupCard.addView(saveKeyBtn);
    root.addView(keySetupCard, marginBottom(dp(8)));

    // Route Control Row (destination search & cancel)
    LinearLayout routeRow = row();
    searchBtn = bigBtn("목적지 검색 (선택) 🔍", false, this::openSearchDialog);
    searchBtn.setEnabled(false);
    routeRow.addView(searchBtn, new LinearLayout.LayoutParams(0, -2, 1f));

    endRouteBtn = smallBtn("안내 종료", false, this::endRouteBackToFreeDrive);
    endRouteBtn.setVisibility(View.GONE);
    routeRow.addView(endRouteBtn, marginStart(dp(8)));
    root.addView(routeRow, marginBottom(dp(8)));

    // Live Kakao Navi Map Container
    mapHost = new FrameLayout(this);
    mapHost.setBackgroundColor(Color.parseColor("#0A100E"));
    mapPlaceholder = label(14, MUTED, false);
    mapPlaceholder.setGravity(Gravity.CENTER);
    mapPlaceholder.setPadding(dp(16), dp(16), dp(16), dp(16));
    mapPlaceholder.setText("위 [주행 연동 시작] 버튼을 누르면\n카카오내비 안전운전 화면이 열리고\n방지턱 · 커브 · 단속 정보가 실시간 전달돼요.");
    mapHost.addView(mapPlaceholder, new FrameLayout.LayoutParams(-1, -1));
    root.addView(mapHost, new LinearLayout.LayoutParams(-1, 0, 1f));

    setContentView(root);
    updateConnectionBanner();
  }

  private void loadSavedKeyUi() {
    String saved = prefs.getString(KEY_KAKAO_KEY, "");
    keyInput.setText(saved);
    if (saved.matches("[0-9a-fA-F]{32}")) {
      keySetupCard.setVisibility(View.GONE);
      toggleKeyCardBtn.setVisibility(View.VISIBLE);
    } else {
      keySetupCard.setVisibility(View.VISIBLE);
      toggleKeyCardBtn.setVisibility(View.GONE);
    }
  }

  private void saveEnteredKey() {
    String k = keyInput.getText().toString().trim();
    if (!k.matches("[0-9a-fA-F]{32}")) {
      Toast.makeText(this, "영문/숫자 32자리 네이티브 앱 키를 확인해 주세요.", Toast.LENGTH_SHORT).show();
      return;
    }
    prefs.edit().putString(KEY_KAKAO_KEY, k).apply();
    app.kakaoReady = false;
    keySetupCard.setVisibility(View.GONE);
    toggleKeyCardBtn.setVisibility(View.VISIBLE);
    Toast.makeText(this, "카카오 키를 저장했어요! 이제 [주행 연동 시작]을 누르세요.", Toast.LENGTH_SHORT).show();
  }

  private void updateConnectionBanner() {
    C4Link.HostPort target = c4Link.currentTarget();
    if (target != null) {
      c4StatusText.setText("콤마4 연결: " + target.host + ":" + target.port);
      c4StatusText.setTextColor(ACCENT);
      webBtn.setEnabled(true);
    } else {
      c4StatusText.setText("콤마4 찾는 중 (핫스팟/Wi-Fi 확인)");
      c4StatusText.setTextColor(WARN);
      webBtn.setEnabled(false);
    }
  }

  private void openWebRemote() {
    String url = c4Link.currentWebUrl();
    if (url == null) {
      Toast.makeText(this, "먼저 콤마4를 찾거나 IP를 입력해 주세요.", Toast.LENGTH_SHORT).show();
      return;
    }
    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
  }

  private void promptManualIp() {
    EditText input = new EditText(this);
    input.setHint("예: 192.168.43.10");
    C4Link.HostPort cur = c4Link.currentTarget();
    if (cur != null) input.setText(cur.host);
    input.setSingleLine(true);

    new AlertDialog.Builder(this)
        .setTitle("콤마4 IP 주소 연결")
        .setMessage("콤마4 설정 → [korani qr] 화면에 보이는 주소를 입력해 주세요. 비우면 자동 검색으로 돌아가요.")
        .setView(input)
        .setPositiveButton("연결", (d, w) -> {
          String raw = input.getText().toString().trim();
          if (raw.isEmpty()) {
            c4Link.clearManualTarget();
            updateConnectionBanner();
            return;
          }
          C4Link.HostPort hp = C4Link.normalizeHostInput(raw);
          if (hp == null) {
            Toast.makeText(this, "올바른 IP 주소를 입력해 주세요.", Toast.LENGTH_SHORT).show();
            return;
          }
          c4Link.setManualTarget(hp);
          updateConnectionBanner();
          app.network.execute(() -> {
            c4Link.ensureConnected();
            ui.post(this::updateConnectionBanner);
          });
        })
        .setNegativeButton("취소", null)
        .show();
  }

  private void startGuidanceFlow() {
    if (running || app.kakaoInitializing) return;
    if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
      pendingStartAfterPerm = true;
      requestPermissions(new String[]{
          Manifest.permission.ACCESS_FINE_LOCATION,
          Manifest.permission.ACCESS_COARSE_LOCATION
      }, REQ_LOC_PERM);
      return;
    }
    if (Build.VERSION.SDK_INT >= 33
        && !notifPermissionAsked
        && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
      notifPermissionAsked = true;
      pendingStartAfterPerm = true;
      requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF_PERM);
      return;
    }

    if (app.kakaoReady) {
      launchGuidanceSession(null, null);
      return;
    }

    String savedKey = prefs.getString(KEY_KAKAO_KEY, "").trim();
    if (!savedKey.matches("[0-9a-fA-F]{32}")) {
      keySetupCard.setVisibility(View.VISIBLE);
      Toast.makeText(this, "카카오 네이티브 앱 키 32자리를 먼저 저장해 주세요.", Toast.LENGTH_SHORT).show();
      return;
    }

    long attempt = ++generation;
    app.kakaoInitializing = true;
    startBtn.setEnabled(false);
    navStatusText.setText("카카오 내비 인증 중...");

    try {
      app.installKakao();
      KNSDK.INSTANCE.initializeWithAppKey(
          savedKey,
          "2.0.0",
          null,
          null,
          KNLanguageType.KNLanguageType_KOREAN,
          error -> {
            ui.post(() -> {
              app.kakaoInitializing = false;
              startBtn.setEnabled(true);
              if (isDestroyed() || attempt != generation) return;
              if (error != null) {
                app.kakaoReady = false;
                keySetupCard.setVisibility(View.VISIBLE);
                navStatusText.setText("카카오 인증 실패 (" + error.getCode() + ") · 키 해시와 앱 키를 확인해 주세요.");
                return;
              }
              app.kakaoReady = true;
              launchGuidanceSession(null, null);
            });
            return Unit.INSTANCE;
          });
    } catch (RuntimeException | LinkageError err) {
      app.kakaoInitializing = false;
      startBtn.setEnabled(true);
      navStatusText.setText("카카오 초기화 오류: " + err.getMessage());
    }
  }

  private void launchGuidanceSession(KNTrip trip, KNRoute initialRoute) {
    releaseGuidanceViewOnly();
    activeTrip = trip;
    activeRoute = initialRoute;
    latestMatchedLoc = null;

    try {
      guidance = KNSDK.INSTANCE.sharedGuidance();
      if (guidance == null) throw new IllegalStateException("sharedGuidance null");

      naviView = new KNNaviView(this);
      mapPlaceholder.setVisibility(View.GONE);
      mapHost.addView(naviView, new FrameLayout.LayoutParams(-1, -1));

      guidance.setUseBackgroundUpdate(true);
      long epoch = ++generation;
      GuideCallbacks cb = new GuideCallbacks(epoch);
      guidance.setGuideStateDelegate(cb);
      guidance.setLocationGuideDelegate(cb);
      guidance.setSafetyGuideDelegate(cb);
      guidance.setRouteGuideDelegate(cb);
      guidance.setVoiceGuideDelegate(cb);
      naviView.setGuideStateDelegate(new KNNaviView_GuideStateDelegate() {
        @Override public void naviViewGuideState(KNGuideState state) {}
        @Override public void naviViewGuideEnded() {
          ui.post(() -> {
            if (epoch == generation && running) stopGuidance(true);
          });
        }
      });

      GuidanceService.begin(this, () -> ui.post(() -> {
        if (running) stopGuidance(true);
      }));

      startAndroidLocation();
      running = true;
      startBtn.setText("연동 중지 ■");
      startBtn.setEnabled(true);
      searchBtn.setEnabled(true);
      endRouteBtn.setVisibility(trip != null ? View.VISIBLE : View.GONE);

      KNSDK.INSTANCE.handleWillEnterForeground();
      KNSDK.INSTANCE.handleDidBecomeActive();
      naviView.initWithGuidance(guidance, trip, KNRoutePriority.KNRoutePriority_Recommand, 0);

      navStatusText.setText(trip == null ? "안전운전 모드 실행 중 (방지턱·커브·카메라 감지)" : "목적지 길안내 연동 중");
      ui.removeCallbacks(pushLoop);
      ui.post(pushLoop);
    } catch (RuntimeException | LinkageError err) {
      stopGuidance(false);
      navStatusText.setText("안내 시작 실패: " + err.getMessage());
    }
  }

  private void releaseGuidanceViewOnly() {
    generation++;
    ui.removeCallbacks(pushLoop);
    aroundSafeties = new ArrayList<>();
    guideSafeties = new ArrayList<>();
    if (guidance != null) {
      try {
        guidance.setGuideStateDelegate(null);
        guidance.setLocationGuideDelegate(null);
        guidance.setSafetyGuideDelegate(null);
        guidance.setRouteGuideDelegate(null);
        guidance.setVoiceGuideDelegate(null);
        guidance.stop();
      } catch (Exception ignored) {}
      guidance = null;
    }
    if (naviView != null) {
      mapHost.removeView(naviView);
      naviView = null;
    }
    mapPlaceholder.setVisibility(View.VISIBLE);
    getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    activeTrip = null;
    activeRoute = null;
    latestMatchedLoc = null;
  }

  private void stopGuidance(boolean sendIdlePacket) {
    running = false;
    GuidanceService.end(this);
    stopAndroidLocation();
    searchGeneration++;
    if (searchDialog != null && searchDialog.isShowing()) {
      searchDialog.dismiss();
    }
    releaseGuidanceViewOnly();
    startBtn.setText("주행 연동 시작 ▶");
    startBtn.setEnabled(!app.kakaoInitializing);
    searchBtn.setEnabled(false);
    endRouteBtn.setVisibility(View.GONE);
    navStatusText.setText("주행 연동 중지됨");
    decelText.setText("감속 안내 대기 중");

    if (sendIdlePacket) {
      app.network.execute(() -> {
        try {
          JSONObject idle = new JSONObject()
              .put("seq", seqCounter.incrementAndGet())
              .put("active", false)
              .put("mode", "free_drive")
              .put("gps", new JSONObject().put("valid", false))
              .put("events", new JSONArray());
          c4Link.postNav(idle);
        } catch (Exception ignored) {}
      });
    }
  }

  private void endRouteBackToFreeDrive() {
    if (running && app.kakaoReady) {
      launchGuidanceSession(null, null);
    }
  }

  private void pushNavTick() {
    if (!running || busySending) return;
    busySending = true;

    final JSONObject packet = buildNavPacket();
    final int evCount = packet.optJSONArray("events") != null ? packet.optJSONArray("events").length() : 0;

    app.network.execute(() -> {
      try {
        JSONObject resp = c4Link.postNav(packet);
        JSONObject dec = resp.optJSONObject("active_decel");
        ui.post(() -> {
          busySending = false;
          updateConnectionBanner();
          if (!running) return;
          navStatusText.setText("연동 정상 · 전방 위험요소 " + evCount + "개 전달 중 (#" + packet.optLong("seq") + ")");
          if (dec != null && dec.optBoolean("active", false)) {
            String lbl = dec.optString("label", "감속 중");
            double dm = dec.optDouble("distance_m", -1.0);
            decelText.setText(dm >= 0.0 ? (lbl + " (" + Math.round(dm) + "m)") : lbl);
            decelText.setTextColor(ACCENT);
          } else {
            decelText.setText("감속 안내 없음 (정속 주행 중)");
            decelText.setTextColor(MUTED);
          }
        });
      } catch (Exception err) {
        ui.post(() -> {
          busySending = false;
          updateConnectionBanner();
          if (running) {
            navStatusText.setText("C4 연결 대기 중 · 내비 감지는 정상 (" + evCount + "개)");
            decelText.setText("폰과 콤마4가 같은 핫스팟/Wi-Fi인지 확인해 주세요.");
            decelText.setTextColor(WARN);
          }
        });
      }
    });
  }

  private JSONObject buildNavPacket() {
    JSONObject root = new JSONObject();
    try {
      root.put("seq", seqCounter.incrementAndGet());
      root.put("active", running);
      root.put("mode", activeTrip != null ? "route" : "free_drive");

      boolean freshGps = gpsValid && (SystemClock.elapsedRealtime() - gpsMonoMs) < 5000L;
      JSONObject gps = new JSONObject();
      gps.put("valid", freshGps);
      gps.put("mock", gpsMock);
      gps.put("lat", freshGps && Double.isFinite(gpsLat) ? gpsLat : JSONObject.NULL);
      gps.put("lon", freshGps && Double.isFinite(gpsLon) ? gpsLon : JSONObject.NULL);
      gps.put("bearing_deg", freshGps && gpsBearing != null ? gpsBearing : JSONObject.NULL);
      gps.put("speed_mps", freshGps && gpsSpeedMps != null ? gpsSpeedMps : JSONObject.NULL);
      gps.put("accuracy_m", freshGps && gpsAccuracyM != null ? gpsAccuracyM : JSONObject.NULL);
      root.put("gps", gps);

      JSONArray events = SafetyExtractor.extract(aroundSafeties, guideSafeties, latestMatchedLoc, activeRoute);
      root.put("events", events);
    } catch (Exception ignored) {}
    return root;
  }

  @SuppressLint("MissingPermission")
  private void startAndroidLocation() {
    if (locationManager == null || locationListening) return;
    try {
      if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
        locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 400L, 0f, androidLocListener, Looper.getMainLooper());
        Location last = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER);
        if (last != null) androidLocListener.onLocationChanged(last);
      }
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && locationManager.isProviderEnabled(LocationManager.FUSED_PROVIDER)) {
        locationManager.requestLocationUpdates(LocationManager.FUSED_PROVIDER, 400L, 0f, androidLocListener, Looper.getMainLooper());
      } else if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
        locationManager.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 400L, 0f, androidLocListener, Looper.getMainLooper());
      }
      locationListening = true;
    } catch (Exception ignored) {}
  }

  private void stopAndroidLocation() {
    if (locationManager != null && locationListening) {
      try { locationManager.removeUpdates(androidLocListener); } catch (Exception ignored) {}
    }
    locationListening = false;
  }

  private void openSearchDialog() {
    if (!app.kakaoReady || !running) {
      Toast.makeText(this, "먼저 [주행 연동 시작]을 눌러주세요.", Toast.LENGTH_SHORT).show();
      return;
    }
    LinearLayout box = new LinearLayout(this);
    box.setOrientation(LinearLayout.VERTICAL);
    box.setPadding(dp(18), dp(8), dp(18), dp(10));

    EditText query = new EditText(this);
    query.setHint("목적지 이름 또는 주소");
    query.setSingleLine(true);
    query.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
    box.addView(query);

    TextView msg = label(13, MUTED, false);
    msg.setPadding(0, dp(6), 0, dp(6));
    box.addView(msg);

    LinearLayout results = new LinearLayout(this);
    results.setOrientation(LinearLayout.VERTICAL);
    ScrollView sv = new ScrollView(this);
    sv.addView(results);
    box.addView(sv, new LinearLayout.LayoutParams(-1, dp(240)));

    long reqGen = ++searchGeneration;
    long epoch = generation;
    Runnable doSearch = () -> {
      String words = query.getText().toString().trim();
      if (words.length() < 2) {
        msg.setText("2글자 이상 입력해 주세요.");
        return;
      }
      msg.setText("검색 중...");
      results.removeAllViews();
      int x = originKatec == null ? 0 : originKatec.getX();
      int y = originKatec == null ? 0 : originKatec.getY();
      KNSDK.INSTANCE.reqSearch(words, 1, 10, KNSearchReqType.KNSearchReqType_1, x, y, (error, value) -> {
        ui.post(() -> {
          if (!visible || epoch != generation || reqGen != searchGeneration || searchDialog == null || !searchDialog.isShowing()) {
            return;
          }
          if (error != null || value == null) {
            msg.setText("검색에 실패했어요. 다시 시도해 주세요.");
            return;
          }
          List<KNSearchPOI> pois = new ArrayList<>();
          for (KNSearchResultObject group : new KNSearchResultObject[]{value.getPlaceResult(), value.getAddressResult()}) {
            if (group != null && group.getPoiList() != null) pois.addAll(group.getPoiList());
          }
          if (pois.isEmpty()) {
            msg.setText("검색 결과가 없어요.");
            return;
          }
          msg.setText("목적지를 선택하세요");
          for (KNSearchPOI poi : pois) {
            String addr = (poi.getRnAddress() != null && !poi.getRnAddress().isEmpty()) ? poi.getRnAddress() : poi.getAddress();
            Button rowBtn = smallBtn(poi.getName() + "\n" + (addr == null ? "" : addr), false, () -> {
              KNPOI goal = (poi.getGuidePoints() != null && !poi.getGuidePoints().isEmpty())
                  ? poi.getGuidePoints().get(0)
                  : new KNPOI(poi.getName(), poi.getPos());
              searchDialog.dismiss();
              startTrip(goal, poi.getName());
            });
            rowBtn.setAllCaps(false);
            rowBtn.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
            results.addView(rowBtn, marginBottom(dp(6)));
          }
        });
        return Unit.INSTANCE;
      });
    };

    query.setOnEditorActionListener((v, actionId, ev) -> {
      if (actionId == EditorInfo.IME_ACTION_SEARCH) {
        doSearch.run();
        return true;
      }
      return false;
    });

    searchDialog = new AlertDialog.Builder(this)
        .setTitle("목적지 검색")
        .setView(box)
        .setPositiveButton("검색", null)
        .setNegativeButton("닫기", null)
        .create();
    searchDialog.setOnShowListener(d -> searchDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> doSearch.run()));
    searchDialog.show();
  }

  private void startTrip(KNPOI goal, String name) {
    if (originKatec == null || originTimestampMs < 0L || (System.currentTimeMillis() - originTimestampMs) > 5000L) {
      Toast.makeText(this, "현재 GPS 위치를 잡은 뒤 다시 선택해 주세요.", Toast.LENGTH_SHORT).show();
      return;
    }
    KNPOI startPoint = new KNPOI("현재 위치", originKatec);
    navStatusText.setText("경로 계산 중 (" + name + ")...");
    long epoch = generation;
    KNSDK.INSTANCE.makeTripWithStart(startPoint, goal, null, null, (err, trip) -> {
      ui.post(() -> {
        if (!visible || epoch != generation || err != null || trip == null) {
          navStatusText.setText("경로를 찾지 못했어요.");
          return;
        }
        trip.setUseMultiRoute(false);
        trip.routeWithPriority(KNRoutePriority.KNRoutePriority_Recommand, 0, (rErr, routes) -> {
          ui.post(() -> {
            if (!visible || epoch != generation || rErr != null || routes == null || routes.isEmpty()) {
              navStatusText.setText("경로 탐색 실패");
              return;
            }
            launchGuidanceSession(trip, routes.get(0));
          });
          return Unit.INSTANCE;
        });
      });
      return Unit.INSTANCE;
    });
  }

  private final class GuideCallbacks implements
      KNGuidance_GuideStateDelegate,
      KNGuidance_LocationGuideDelegate,
      KNGuidance_SafetyGuideDelegate,
      KNGuidance_RouteGuideDelegate,
      KNGuidance_VoiceGuideDelegate {
    private final long epoch;

    GuideCallbacks(long epoch) {
      this.epoch = epoch;
    }

    @Override public void guidanceDidUpdateLocation(KNGuidance g, KNGuide_Location location) {
      KNGPSData gps = location.getGpsOrigin() != null ? new KNGPSData(location.getGpsOrigin()) : null;
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceDidUpdateLocation(g, location);
        latestMatchedLoc = location.getLocationForPrimaryRoute() != null
            ? location.getLocationForPrimaryRoute()
            : location.getLocation();
        if (gps != null && gps.getPos() != null) {
          DoublePoint xy = gps.getPos();
          originKatec = new IntPoint((int) Math.round(xy.getX()), (int) Math.round(xy.getY()));
          originTimestampMs = System.currentTimeMillis();
          if ((!gpsValid || (SystemClock.elapsedRealtime() - gpsMonoMs) > 2000L) && KNKATECKt.IsValidKATEC(xy)) {
            DoublePoint wgs = KNKATECKt.KATECToWGS84(xy.getX(), xy.getY());
            if (wgs != null && Double.isFinite(wgs.getX()) && Double.isFinite(wgs.getY())) {
              gpsLon = wgs.getX();
              gpsLat = wgs.getY();
              gpsBearing = gps.getAngleTrust() ? (double) gps.getAngle() : null;
              gpsMock = location.isSimulationJump()
                  || gps.getProvider() == KNGPSProvider.KNGPSProvider_Simulation;
              gpsValid = gps.getValid();
              gpsMonoMs = SystemClock.elapsedRealtime();
            }
          }
        }
      });
    }

    @Override public void guidanceDidUpdateSafetyGuide(KNGuidance g, KNGuide_Safety safety) {
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceDidUpdateSafetyGuide(g, safety);
        guideSafeties = (safety != null && safety.getSafetiesOnGuide() != null)
            ? new ArrayList<>(safety.getSafetiesOnGuide())
            : new ArrayList<>();
      });
    }

    @Override public void guidanceDidUpdateAroundSafeties(KNGuidance g, List<? extends KNSafety> values) {
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceDidUpdateAroundSafeties(g, values);
        aroundSafeties = values != null ? new ArrayList<>(values) : new ArrayList<>();
      });
    }

    @Override public void guidanceGuideStarted(KNGuidance g) {
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceGuideStarted(g);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
      });
    }

    @Override public void guidanceGuideEnded(KNGuidance g) {
      ui.post(() -> {
        if (epoch == generation && running) stopGuidance(true);
      });
    }

    @Override public void guidanceCheckingRouteChange(KNGuidance g) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceCheckingRouteChange(g); });
    }

    @Override public void guidanceRouteUnchanged(KNGuidance g) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceRouteUnchanged(g); });
    }

    @Override public void guidanceRouteUnchangedWithError(KNGuidance g, KNError error) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceRouteUnchangedWithError(g, error); });
    }

    @Override public void guidanceOutOfRoute(KNGuidance g) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceOutOfRoute(g); });
    }

    @Override public void guidanceRouteChanged(KNGuidance g, KNRoute o, KNLocation ol, KNRoute n, KNLocation nl, KNGuideRouteChangeReason r) {
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceRouteChanged(g);
        if (n != null) activeRoute = n;
      });
    }

    @Override public void guidanceDidUpdateRoutes(KNGuidance g, List<KNRoute> routes, KNMultiRouteInfo info) {
      ui.post(() -> {
        if (epoch != generation || !running) return;
        if (naviView != null) naviView.guidanceDidUpdateRoutes(g, routes, info);
        if (routes != null && !routes.isEmpty()) activeRoute = routes.get(0);
      });
    }

    @Override public void guidanceDidUpdateIndoorRoute(KNGuidance g, KNRoute route) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceDidUpdateIndoorRoute(g, route); });
    }

    @Override public void guidanceDidUpdateRouteGuide(KNGuidance g, KNGuide_Route route) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.guidanceDidUpdateRouteGuide(g, route); });
    }

    @Override public boolean shouldPlayVoiceGuide(KNGuidance g, KNGuide_Voice voice, List<byte[]> data) {
      return epoch == generation && running && naviView != null && naviView.shouldPlayVoiceGuide(g, voice, data);
    }

    @Override public void willPlayVoiceGuide(KNGuidance g, KNGuide_Voice voice) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.willPlayVoiceGuide(g, voice); });
    }

    @Override public void didFinishPlayVoiceGuide(KNGuidance g, KNGuide_Voice voice) {
      ui.post(() -> { if (epoch == generation && naviView != null) naviView.didFinishPlayVoiceGuide(g, voice); });
    }
  }

  @Override protected void onResume() {
    super.onResume();
    visible = true;
    if (app.kakaoInstalled) {
      KNSDK.INSTANCE.handleWillEnterForeground();
      KNSDK.INSTANCE.handleDidBecomeActive();
    }
    ui.removeCallbacks(discoveryLoop);
    ui.post(discoveryLoop);
    if (pendingStartAfterPerm) {
      pendingStartAfterPerm = false;
      startGuidanceFlow();
    }
  }

  @Override protected void onPause() {
    visible = false;
    ui.removeCallbacks(discoveryLoop);
    if (app.kakaoInstalled) {
      KNSDK.INSTANCE.handleWillResignActive();
      KNSDK.INSTANCE.handleDidEnterBackground();
    }
    super.onPause();
  }

  @Override protected void onDestroy() {
    c4Link.stop();
    stopGuidance(false);
    super.onDestroy();
  }

  @Override public void onRequestPermissionsResult(int code, String[] perms, int[] grants) {
    super.onRequestPermissionsResult(code, perms, grants);
    if (code == REQ_LOC_PERM) {
      if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) {
        if (visible) startGuidanceFlow();
        else pendingStartAfterPerm = true;
      } else {
        pendingStartAfterPerm = false;
        Toast.makeText(this, "정확한 위치 권한이 필요해요.", Toast.LENGTH_LONG).show();
      }
    } else if (code == REQ_NOTIF_PERM) {
      if (visible) startGuidanceFlow();
      else pendingStartAfterPerm = true;
    }
  }

  private int dp(int v) {
    return Math.round(v * getResources().getDisplayMetrics().density);
  }

  private LinearLayout card() {
    LinearLayout l = new LinearLayout(this);
    l.setOrientation(LinearLayout.VERTICAL);
    l.setPadding(dp(12), dp(10), dp(12), dp(10));
    GradientDrawable bg = new GradientDrawable();
    bg.setColor(CARD);
    bg.setCornerRadius(dp(12));
    bg.setStroke(dp(1), Color.parseColor("#293D36"));
    l.setBackground(bg);
    return l;
  }

  private LinearLayout row() {
    LinearLayout l = new LinearLayout(this);
    l.setOrientation(LinearLayout.HORIZONTAL);
    l.setGravity(Gravity.CENTER_VERTICAL);
    return l;
  }

  private TextView label(int sp, int color, boolean bold) {
    TextView tv = new TextView(this);
    tv.setTextSize(sp);
    tv.setTextColor(color);
    if (bold) tv.setTypeface(tv.getTypeface(), android.graphics.Typeface.BOLD);
    return tv;
  }

  private Button bigBtn(String text, boolean primary, Runnable onClick) {
    return styledButton(text, primary, dp(11), 15, onClick);
  }

  private Button smallBtn(String text, boolean primary, Runnable onClick) {
    return styledButton(text, primary, dp(7), 13, onClick);
  }

  private Button styledButton(String text, boolean primary, int padV, int sp, Runnable onClick) {
    Button b = new Button(this);
    b.setText(text);
    b.setTextSize(sp);
    b.setAllCaps(false);
    b.setTypeface(b.getTypeface(), android.graphics.Typeface.BOLD);
    b.setTextColor(primary ? Color.parseColor("#092117") : TEXT);
    b.setPadding(dp(12), padV, dp(12), padV);
    GradientDrawable bg = new GradientDrawable();
    bg.setColor(primary ? ACCENT : CARD2);
    bg.setCornerRadius(dp(10));
    if (!primary) bg.setStroke(dp(1), Color.parseColor("#293D36"));
    b.setBackground(bg);
    b.setOnClickListener(v -> onClick.run());
    return b;
  }

  private LinearLayout.LayoutParams marginBottom(int px) {
    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
    lp.bottomMargin = px;
    return lp;
  }

  private LinearLayout.LayoutParams marginEnd(int px) {
    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
    lp.rightMargin = px;
    return lp;
  }

  private LinearLayout.LayoutParams marginStart(int px) {
    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
    lp.leftMargin = px;
    return lp;
  }
}
