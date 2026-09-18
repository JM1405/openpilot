package dev.koranipilot.manager;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.WindowManager;
import android.widget.*;
import androidx.appcompat.app.AppCompatActivity;
import com.kakaomobility.knsdk.*;
import com.kakaomobility.knsdk.common.gps.KNGPSData;
import com.kakaomobility.knsdk.common.objects.KNError;
import com.kakaomobility.knsdk.common.objects.KNPOI;
import com.kakaomobility.knsdk.common.objects.KNSearchPOI;
import com.kakaomobility.knsdk.common.util.IntPoint;
import com.kakaomobility.knsdk.trip.kntrip.KNTrip;
import com.kakaomobility.knsdk.api.objects.KNSearchResultObject;
import com.kakaomobility.knsdk.guidance.knguidance.*;
import com.kakaomobility.knsdk.guidance.knguidance.common.KNLocation;
import com.kakaomobility.knsdk.guidance.knguidance.locationguide.KNGuide_Location;
import com.kakaomobility.knsdk.guidance.knguidance.routeguide.KNGuide_Route;
import com.kakaomobility.knsdk.guidance.knguidance.routeguide.objects.KNMultiRouteInfo;
import com.kakaomobility.knsdk.guidance.knguidance.routeguide.objects.KNDirection;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.KNGuide_Safety;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.objects.*;
import com.kakaomobility.knsdk.guidance.knguidance.voiceguide.KNGuide_Voice;
import com.kakaomobility.knsdk.trip.kntrip.knroute.KNRoute;
import com.kakaomobility.knsdk.ui.view.*;
import dev.comma.companion.PhoneClient;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.HashSet;
import java.util.List;
import kotlin.Unit;

/** User-started SDK reception with a visible foreground service. No braking control. */
public class KakaoActivity extends AppCompatActivity implements
    KNGuidance_GuideStateDelegate, KNGuidance_LocationGuideDelegate,
    KNGuidance_SafetyGuideDelegate, KNGuidance_RouteGuideDelegate, KNGuidance_VoiceGuideDelegate {
  private ManagerApp app;
  private InputRecorder inputRecorder;
  private java.io.File pendingObservationExport;
  private androidx.appcompat.app.AlertDialog observationDetails;
  private static final int EXPORT_OBSERVATION=74;
  protected LinearLayout root;
  private LinearLayout setup;
  protected RoadGps roadGps;
  private boolean automaticRoadGps,roadGpsOptOut;
  private Button gpsStart;
  private FrameLayout mapHost;
  private TextView gpsSummary, safetySummary, linkSummary, roadSummary;
  private android.view.View mapPlaceholder;
  private EditText key;
  private TextView status, localStatus, transportStatus;
  private Button start, destinationButton, rerouteButton, endRouteButton;
  private TextView routeSummary, routeLink;
  private final RouteSnapshot routeState=new RouteSnapshot();
  private KNTrip activeTrip;
  private KNRoute activeRoute;
  private KNDirection turnDirection;
  private KNLocation turnLocation;
  private IntPoint origin;
  private long originTimestamp=-1,searchGeneration;
  private boolean routePending;
  private long rerouteGeneration;
  private androidx.appcompat.app.AlertDialog searchDialog;
  private KNNaviView navi;
  private KNDriveGuidance guidance;
  private final Handler ui=new Handler(Looper.getMainLooper());
  private final KakaoObservation observation=new KakaoObservation();
  private volatile long generation;
  private boolean visible, running, busy, notificationPermissionAsked, notificationStartPending;
  private final Runnable poll=new Runnable(){public void run(){if(running){refreshLocalStatus();send();ui.postDelayed(this,1000);}}};

  @Override public void onCreate(Bundle state){
    super.onCreate(state);app=(ManagerApp)getApplication();roadGps=new RoadGps(this,app);inputRecorder=new InputRecorder(this);
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    root=PulseUi.column(this);root.setBackgroundColor(PulseUi.BG);setContentView(root);PulseUi.window(this,root);
    LinearLayout header=PulseUi.row(this);header.setPadding(dp(24),dp(16),dp(24),dp(10));
    TextView title=PulseUi.text(this,"주변 수신",24,PulseUi.TEXT);header.addView(title,new LinearLayout.LayoutParams(0,-2,1));
    Button details=PulseUi.button(this,"상세",false,this::showDetails);header.addView(details);root.addView(header);
    LinearLayout controls=PulseUi.column(this);controls.setPadding(dp(24),0,dp(24),dp(12));
    setup=PulseUi.card(this);PulseUi.label(setup,"카카오 연결",18,PulseUi.TEXT);PulseUi.gap(setup,10);
    PulseUi.label(setup,"수신 중 카카오에 위치가 전송돼.",13,PulseUi.MUTED);PulseUi.gap(setup,12);
    key=PulseUi.input(this,"네이티브 앱 키",true);setup.addView(key,new LinearLayout.LayoutParams(-1,-2));controls.addView(setup);PulseUi.gap(controls,12);
    status=PulseUi.text(this,"카카오 연결 후 수신을 시작해",13,PulseUi.MUTED);status.setTextIsSelectable(true);controls.addView(status);PulseUi.gap(controls,12);
    LinearLayout stats=PulseUi.row(this);LinearLayout gps=PulseUi.column(this),safety=PulseUi.column(this);
    PulseUi.label(gps,"폰 GPS",10,PulseUi.MUTED);PulseUi.gap(gps,6);gpsSummary=PulseUi.label(gps,"수신 전",16,PulseUi.TEXT);
    PulseUi.label(safety,"안전 안내",10,PulseUi.MUTED);PulseUi.gap(safety,6);safetySummary=PulseUi.label(safety,"수신 전",16,PulseUi.TEXT);
    stats.addView(gps,new LinearLayout.LayoutParams(0,-2,1));stats.addView(safety,new LinearLayout.LayoutParams(0,-2,1));controls.addView(stats);PulseUi.gap(controls,12);
    linkSummary=PulseUi.label(controls,"C4 전송 전",12,PulseUi.MUTED);linkSummary.setOnClickListener(v->showDetails());PulseUi.gap(controls,8);
    roadSummary=PulseUi.label(controls,"GPS · 전송 전",12,PulseUi.MUTED);roadSummary.setOnClickListener(v->showDetails());PulseUi.gap(controls,12);
    LinearLayout actions=PulseUi.row(this);start=PulseUi.button(this,"수신 시작  →",true,()->{if(running)stop();else begin();});actions.addView(start,new LinearLayout.LayoutParams(0,-2,1));
    gpsStart=PulseUi.button(this,"GPS 전송",false,this::toggleRoadGps);LinearLayout.LayoutParams gpsLp=new LinearLayout.LayoutParams(0,-2,1);gpsLp.setMargins(dp(8),0,0,0);actions.addView(gpsStart,gpsLp);controls.addView(actions);PulseUi.gap(controls,12);
    destinationButton=PulseUi.button(this,"목적지 검색  ↗",false,this::searchDestination);controls.addView(destinationButton,new LinearLayout.LayoutParams(-1,-2));
    routeSummary=PulseUi.label(controls,"목적지를 검색해 봐",14,PulseUi.TEXT);
    routeLink=PulseUi.label(controls,"",11,PulseUi.MUTED);
    LinearLayout routeActions=PulseUi.row(this);
    rerouteButton=PulseUi.button(this,"재탐색",false,this::reroute);routeActions.addView(rerouteButton,new LinearLayout.LayoutParams(0,-2,1));
    endRouteButton=PulseUi.button(this,"안내 종료",false,this::endRoute);routeActions.addView(endRouteButton,new LinearLayout.LayoutParams(0,-2,1));controls.addView(routeActions);
    updateRouteUi();
    ScrollView controlScroll=new ScrollView(this);controlScroll.addView(controls);root.addView(controlScroll,new LinearLayout.LayoutParams(-1,-2));
    mapHost=new FrameLayout(this);mapHost.setBackgroundColor(PulseUi.SURFACE);root.addView(mapHost,new LinearLayout.LayoutParams(-1,0,1));
    TextView placeholder=PulseUi.text(this,"수신을 시작하면 지도가 표시돼",14,PulseUi.MUTED);placeholder.setGravity(android.view.Gravity.CENTER);mapPlaceholder=placeholder;mapHost.addView(placeholder,new FrameLayout.LayoutParams(-1,-1));
    TextView scope=PulseUi.text(this,"관찰 전용 · 다른 앱·화면 잠금 중에도 수신 유지",11,PulseUi.MUTED);scope.setGravity(android.view.Gravity.CENTER);scope.setPadding(0,dp(9),0,dp(9));root.addView(scope);
    PulseUi.line(root);root.addView(PulseUi.navigation(this,"map",()->returnTo("home"),()->{},()->returnTo("device")));
    localStatus=PulseUi.text(this,"폰 GPS·안전 안내 수신 전",14,PulseUi.TEXT);localStatus.setTextIsSelectable(true);
    transportStatus=PulseUi.text(this,"C4 전송 전 · 기기 연결은 선택 사항이야",14,PulseUi.TEXT);transportStatus.setTextIsSelectable(true);
    if(app.kakaoReady){showAuthenticatedScreen();status.setText("수신 대기");}
  }
  private int dp(int value){return PulseUi.dp(this,value);}
  protected void returnTo(String screen){
    startActivity(new android.content.Intent(this,MainActivity.class).addFlags(android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP|android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("screen",screen));finish();
  }
  protected LinearLayout receiverContent(){return root;}
  protected boolean receiving(){return running;}
  protected String receptionGps(){return running?gpsSummary.getText().toString():"수신 대기";}
  protected void screenVisibility(boolean receiverVisible){
    if(receiverVisible&&KakaoCapturePolicy.mustProtectKey(app.kakaoReady,key.getVisibility()==android.view.View.VISIBLE,key.length()>0))getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
  }
  private void toggleRoadGps(){
    if(roadGps.running()){roadGpsOptOut=true;automaticRoadGps=false;roadGps.stop("GPS 전송 중지");return;}
    if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},42);return;}
    roadGps.start();
  }
  private void updateRoadButton(){gpsStart.setText(roadGps.running()?"GPS 중지":"GPS 전송");roadSummary.setText("도로용 GPS · "+roadGps.status());}
  private final Runnable gpsPoll=new Runnable(){public void run(){updateRoadButton();ui.postDelayed(this,500);}};
  private void showDetails(){
    if(observationDetails!=null)observationDetails.dismiss();
    LinearLayout body=PulseUi.column(this);body.setPadding(dp(24),dp(12),dp(24),dp(20));
    TextView[] views={localStatus,transportStatus};String[] labels={"폰 카카오 GPS·안내","C4가 확인한 수신"};
    for(int i=0;i<views.length;i++){
      PulseUi.label(body,labels[i],13,PulseUi.LIME);PulseUi.gap(body,8);
      TextView view=views[i];if(view.getParent()!=null)((android.view.ViewGroup)view.getParent()).removeView(view);body.addView(view);PulseUi.gap(body,20);
    }
    PulseUi.label(body,"여기는 정보 수신 상태야. 실제 감속 적용 여부는 C4 주행 화면에서 확인해.",13,PulseUi.MUTED);
    PulseUi.label(body,"별도 도로용 GPS · "+roadGps.status(),14,PulseUi.LIME);PulseUi.gap(body,12);TextView roadDetail=PulseUi.label(body,roadGps.roadStatus(),13,PulseUi.MUTED);
    roadGps.refreshRoadStatus(()->roadDetail.setText(roadGps.roadStatus()));
    PulseUi.gap(body,20);
    PulseUi.label(body,"입력 검증 기록",15,PulseUi.LIME);
    PulseUi.label(body,"GPS 위치와 카카오 안내를 폰에 저장해. 자동 전송이나 차량 제어는 하지 않아. 정차 중 시작·종료해 줘.",13,PulseUi.MUTED);
    TextView recordState=PulseUi.label(body,inputRecorder.status(),14,PulseUi.TEXT);
    Button record=PulseUi.button(this,"기록 시작",false,()->{
      if(inputRecorder.active())inputRecorder.stop("user_stop");
      else if(!running)Toast.makeText(this,"먼저 카카오 수신을 시작해 줘",Toast.LENGTH_SHORT).show();
      else if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED)
        Toast.makeText(this,"정확한 위치 권한을 확인해 줘",Toast.LENGTH_SHORT).show();
      else inputRecorder.start();
    });body.addView(record);
    Button export=PulseUi.button(this,"기록 내보내기",false,this::exportObservation);body.addView(export);
    ScrollView scroll=new ScrollView(this);scroll.addView(body);
    androidx.appcompat.app.AlertDialog dialog=new androidx.appcompat.app.AlertDialog.Builder(this).setTitle("수신 상세").setView(scroll).setPositiveButton("닫기",null).create();
    Runnable refresh=new Runnable(){public void run(){recordState.setText(inputRecorder.status());record.setText(inputRecorder.active()?"기록 종료":"기록 시작");export.setEnabled(inputRecorder.exportable()!=null);if(dialog.isShowing())ui.postDelayed(this,500);}};
    observationDetails=dialog;
    dialog.setOnDismissListener(d->{ui.removeCallbacks(refresh);if(observationDetails==dialog)observationDetails=null;});dialog.show();ui.post(refresh);
  }

  private void exportObservation(){
    java.io.File file=inputRecorder.exportable();if(file==null)return;
    pendingObservationExport=file;
    android.content.Intent intent=new android.content.Intent(android.content.Intent.ACTION_CREATE_DOCUMENT)
      .setType("application/octet-stream").addCategory(android.content.Intent.CATEGORY_OPENABLE)
      .putExtra(android.content.Intent.EXTRA_TITLE,file.getName());
    startActivityForResult(intent,EXPORT_OBSERVATION);
  }
  @Override protected void onActivityResult(int request,int result,android.content.Intent data){
    super.onActivityResult(request,result,data);
    if(request!=EXPORT_OBSERVATION)return;
    java.io.File file=pendingObservationExport;pendingObservationExport=null;
    if(result!=RESULT_OK||data==null||data.getData()==null||file==null)return;
    android.net.Uri destination=data.getData();
    new Thread(()->{
      boolean ok=false;
      try(java.io.InputStream in=new java.io.FileInputStream(file);java.io.OutputStream out=getContentResolver().openOutputStream(destination)){
        if(out==null)throw new java.io.IOException();byte[] buffer=new byte[32768];int n;
        while((n=in.read(buffer))!=-1)out.write(buffer,0,n);ok=true;
      }catch(Exception ignored){}
      final boolean saved=ok;ui.post(()->{if(!isDestroyed())Toast.makeText(this,saved?"기록을 내보냈어":"내보내지 못했어. 다시 시도해 줘",Toast.LENGTH_LONG).show();});
    },"observation-export").start();
  }

  private void begin(){
    if(running||app.kakaoInitializing)return;
    if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED){
      requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},41);return;
    }
    if(android.os.Build.VERSION.SDK_INT>=33&&!notificationPermissionAsked&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){
      notificationPermissionAsked=true;requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},43);return;
    }
    if(app.kakaoReady){showAuthenticatedScreen();startGuidance();return;}
    String nativeKey=key.getText().toString().trim();if(!nativeKey.matches("[0-9a-fA-F]{32}")){status.setText("카카오 네이티브 앱 키 32자리를 입력해");return;}
    long attempt=++generation;start.setEnabled(false);app.kakaoInitializing=true;status.setText("카카오 SDK 인증 중");
    KakaoStartupFailure.Stage stage=KakaoStartupFailure.Stage.INSTALL;
    try{
      app.installKakao();
      stage=KakaoStartupFailure.Stage.INITIALIZE;
      // Both optional identifiers are omitted. Do not pass device IDs or C4 credentials.
      KNSDK.INSTANCE.initializeWithAppKey(nativeKey,"0.11",null,null,KNLanguageType.KNLanguageType_KOREAN,error->{
        ui.post(()->{app.kakaoInitializing=false;app.kakaoReady=error==null;
          if(isDestroyed())return;start.setEnabled(true);
          if(!visible||attempt!=generation)return;
          if(error!=null){
            String code=error.getCode();
            String safeCode=code!=null&&code.matches("(?:KNError_Code_)?[A-Z][0-9]{3}")?" ("+code+")":"";
            status.setText("카카오 인증 실패"+safeCode+" · 앱 등록·키·패키지·키 해시를 확인해");return;
          }
          showAuthenticatedScreen();startGuidance();});return Unit.INSTANCE;
      });
    }catch(RuntimeException|LinkageError error){app.kakaoInitializing=false;start.setEnabled(true);status.setText("SDK 초기화 실패\n"+KakaoStartupFailure.describe(stage,error));}
  }

  private void showAuthenticatedScreen(){
    key.setText("");key.clearFocus();key.setVisibility(android.view.View.GONE);setup.setVisibility(android.view.View.GONE);
    ((android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(key.getWindowToken(),0);
    if(KakaoCapturePolicy.mustProtectKey(app.kakaoReady,key.getVisibility()==android.view.View.VISIBLE,key.length()>0)){
      getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    }else{
      getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
    }
  }

  private void startGuidance(){startGuidance(null,null);}
  private void startGuidance(KNTrip trip,KNRoute initial){
    if(!visible)return;
    releaseGuidance();
    activeTrip=trip;activeRoute=initial;
    if(trip!=null&&initial!=null)installRoute(initial);
    KakaoStartupFailure.Stage stage=KakaoStartupFailure.Stage.GUIDANCE;
    try{
      guidance=KNSDK.INSTANCE.sharedGuidance();if(guidance==null)throw new IllegalStateException();
      stage=KakaoStartupFailure.Stage.VIEW;
      navi=new KNNaviView(this);mapHost.addView(navi,new FrameLayout.LayoutParams(-1,-1));mapPlaceholder.setVisibility(android.view.View.GONE);
      stage=KakaoStartupFailure.Stage.DELEGATES;
      guidance.setUseBackgroundUpdate(true);
      long callbackEpoch=generation;
      GuideCallbacks callbacks=new GuideCallbacks(callbackEpoch);
      guidance.setGuideStateDelegate(callbacks);guidance.setLocationGuideDelegate(callbacks);guidance.setSafetyGuideDelegate(callbacks);
      guidance.setRouteGuideDelegate(callbacks);guidance.setVoiceGuideDelegate(callbacks);
      navi.setGuideStateDelegate(new KNNaviView_GuideStateDelegate(){
        public void naviViewGuideState(KNGuideState state){}
        public void naviViewGuideEnded(){ui.post(()->{if(callbackEpoch==generation&&running)stop();});}
      });
      ReceptionService.begin(this,this::stop);
      roadGpsOptOut=false;
      running=true;start.setText("수신 중지  ■");start.setEnabled(true);observation.start();observation.routeMode(trip!=null);
      stage=KakaoStartupFailure.Stage.LIFECYCLE;
      KNSDK.INSTANCE.handleWillEnterForeground();KNSDK.INSTANCE.handleDidBecomeActive();
      // KNNaviView owns the SDK session for both free drive and a prepared trip.
      stage=KakaoStartupFailure.Stage.START;
      navi.initWithGuidance(guidance,trip,KNRoutePriority.KNRoutePriority_Recommand,0);
      status.setText(trip==null?"수신 중":"길 안내 중");updateRouteUi();ui.post(poll);
    }catch(RuntimeException|LinkageError error){
      String detail=KakaoStartupFailure.describe(stage,error);
      try{stop();}catch(RuntimeException|LinkageError cleanup){detail+="\n"+KakaoStartupFailure.describe(KakaoStartupFailure.Stage.CLEANUP,cleanup);}
      status.setText("카카오 안내 화면 시작 실패 · 아래 오류를 알려줘\n"+detail);
    }
  }

  private void refreshLocalStatus(){
    updateRouteUi();
    try{
      long now=SystemClock.elapsedRealtime();localStatus.setText(observation.diagnostics(now)+"\n"+observation.statusText(now));JSONObject frame=observation.frame("",0,now);
      gpsSummary.setText(observation.gpsSummary(now));
      safetySummary.setText(!running?"수신 전":frame.isNull("safety_age_ms")?"대기 / 만료":frame.getJSONArray("events").length()+"개");
    }
    catch(Exception error){localStatus.setText("폰 수신 상태를 읽지 못했어");}
  }

  private void send(){
    PhoneClient selected=app.client;if(busy)return;
    if(selected==null||!selected.connected()){routeLink.setText(routeState.hasDestination()?"경로 · 폰에서 안내 중":"");transportStatus.setText("C4 미연결 · 폰에서만 확인 중");linkSummary.setText("C4 미연결 · 폰에서 확인 중");return;}
    busy=true;long epoch=generation;
    app.network.execute(()->{
      String result=null,summary=null;Throwable failure=null;
      KakaoTransferFailure.Stage stage=KakaoTransferFailure.Stage.CHALLENGE;
      try{
        if(epoch!=generation||selected!=app.client)return;
        JSONObject capabilities=selected.call("kakao",null);String nonce=capabilities.getString("challenge");
        boolean drivingAllowed=capabilities.optBoolean("driving_input_allowed",false);
        ui.post(()->{if(epoch==generation&&selected==app.client)updateDrivingGps(drivingAllowed);});
        if(epoch!=generation||selected!=app.client)return;
        stage=KakaoTransferFailure.Stage.FRAME;
        long sequence=selected.navigationSequence.incrementAndGet();
        JSONObject body=observation.frame(nonce,sequence,SystemClock.elapsedRealtime(),capabilities.optInt("event_geometry_version",0)==1);
        stage=KakaoTransferFailure.Stage.SEND;
        long sentAt=SystemClock.elapsedRealtimeNanos();
        JSONObject receipt=selected.call("kakao",body);
        stage=KakaoTransferFailure.Stage.RECEIPT;result=KakaoReceipt.describe(receipt,sequence);
        if(epoch==generation&&selected==app.client)inputRecorder.receipt(receipt,SystemClock.elapsedRealtimeNanos()-sentAt);
        summary=("home_receive".equals(receipt.optString("connection_mode"))?"집 수신 확인 #":"C4 수신 확인 #")+sequence+" · "+(receipt.getBoolean("location_fresh")?"GPS 유효":"GPS 대기 / 만료");
        if(epoch!=generation||selected!=app.client)return;
        stage=KakaoTransferFailure.Stage.ROUTE;
        JSONObject routeReceipt=RouteTransfer.send(selected,routeState,SystemClock::elapsedRealtime,()->epoch==generation&&selected==app.client);
        if(routeReceipt==null)return;
        JSONObject upload=routeReceipt.getJSONObject("upload");
        String routeMessage=upload.optString("shape_id").isEmpty()||upload.getBoolean("complete")?"경로 · C4 수신 확인":"경로 전달 중 · "+upload.getInt("next_offset")+"점";
        ui.post(()->{if(epoch==generation&&selected==app.client)routeLink.setText(routeMessage);});
      }catch(Exception error){failure=error;}
      finally{
        String answer=result,brief=summary;Throwable error=failure;KakaoTransferFailure.Stage failedStage=stage;
        ui.post(()->{busy=false;if(epoch!=generation||selected!=app.client)return;
          if(error!=null){
            String detail=KakaoTransferFailure.detail(failedStage,error);
            routeLink.setText(failedStage==KakaoTransferFailure.Stage.ROUTE?"경로 확인 실패 · "+detail:"경로 · 전송 대기");
            String received=answer!=null&&selected.connected()?"확인된 응답: "+brief+"\n":"";
            transportStatus.setText(received+detail+"\n현재 유효성은 재확인 중 · 기존 자료는 3초 안에 만료돼");
            linkSummary.setText(KakaoTransferFailure.summary(failedStage,error,brief,selected.connected()));return;
          }
          if(answer!=null){transportStatus.setText(answer);linkSummary.setText(brief);}});
      }
    });
  }

  private void updateDrivingGps(boolean allowed){
    if(running&&allowed&&!roadGpsOptOut){
      if(!roadGps.running())roadGps.start();
      automaticRoadGps=true;
    }else if(automaticRoadGps){roadGps.stop("주행 입력 종료");automaticRoadGps=false;}
  }

  private void releaseGuidance(){
    generation++;ui.removeCallbacks(poll);running=false;observation.reset();
    if(guidance!=null){
      guidance.setGuideStateDelegate(null);guidance.setLocationGuideDelegate(null);guidance.setSafetyGuideDelegate(null);
      guidance.setRouteGuideDelegate(null);guidance.setVoiceGuideDelegate(null);guidance.stop();guidance=null;
    }
    if(navi!=null){mapHost.removeView(navi);navi=null;}mapPlaceholder.setVisibility(android.view.View.VISIBLE);
    getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    activeTrip=null;activeRoute=null;turnDirection=null;turnLocation=null;routePending=false;
  }
  private void stop(){
    if(inputRecorder!=null)inputRecorder.stop("reception_stop");
    ReceptionService.end(this);
    if(automaticRoadGps){roadGps.stop("수신 중지");automaticRoadGps=false;}
    boolean wasRunning=running;
    searchGeneration++;if(searchDialog!=null)searchDialog.dismiss();
    routeState.end();origin=null;originTimestamp=-1;
    releaseGuidance();start.setEnabled(!app.kakaoInitializing);start.setText("수신 시작  →");
    status.setText("수신 중지");refreshLocalStatus();transportStatus.setText("C4 전송 중지");linkSummary.setText("C4 전송 중지");routeLink.setText("");
    PhoneClient selected=app.client;
    try{
      // Capture before queueing. A later destination must never revive this ending frame.
      JSONObject ended=routeState.statusFrame("",0,SystemClock.elapsedRealtime());
      if(wasRunning&&selected!=null&&selected.connected())app.network.execute(()->{try{
        if(selected!=app.client||!selected.connected())return;
        String nonce=selected.call("kakao",null).getString("challenge");
        selected.call("kakao",new KakaoObservation().frame(nonce,selected.navigationSequence.incrementAndGet(),SystemClock.elapsedRealtime()));
        nonce=selected.call("route",null).getString("challenge");
        selected.call("route",ended.put("challenge",nonce).put("seq",selected.navigationSequence.incrementAndGet()));
      }catch(Exception ignored){/* Independent receiver expiry still clears old data. */}});
    }catch(Exception ignored){}
  }

  private void updateRouteUi(){
    if(routeSummary==null)return;
    routeSummary.setText(routeState.summary(SystemClock.elapsedRealtime()));
    boolean has=routeState.hasDestination();rerouteButton.setVisibility(has?android.view.View.VISIBLE:android.view.View.GONE);endRouteButton.setVisibility(has?android.view.View.VISIBLE:android.view.View.GONE);
    rerouteButton.setEnabled(activeTrip!=null&&!routePending);
    destinationButton.setText(has?"목적지 변경  ↗":"목적지 검색  ↗");
  }
  private void searchDestination(){
    if(!app.kakaoReady||!running){status.setText("수신을 시작한 뒤 목적지를 검색해 줘");return;}
    LinearLayout body=PulseUi.column(this);body.setPadding(dp(20),dp(8),dp(20),dp(12));
    EditText query=PulseUi.input(this,"장소 또는 주소",false);query.setSingleLine(true);body.addView(query);
    TextView message=PulseUi.label(body,"",12,PulseUi.MUTED);
    LinearLayout results=PulseUi.column(this);ScrollView scroll=new ScrollView(this);scroll.addView(results);body.addView(scroll,new LinearLayout.LayoutParams(-1,dp(260)));
    int[] page={1};String[] searched={""};boolean[] more={false};
    LinearLayout paging=PulseUi.row(this);Button prev=PulseUi.button(this,"이전",false,()->{}),next=PulseUi.button(this,"다음",false,()->{});paging.addView(prev,new LinearLayout.LayoutParams(0,-2,1));paging.addView(next,new LinearLayout.LayoutParams(0,-2,1));body.addView(paging);prev.setEnabled(false);next.setEnabled(false);
    Runnable search=()->{
      String words=query.getText().toString().trim();if(words.length()<2||words.length()>100){message.setText("검색어를 2~100자로 입력해 줘");return;}
      if(!words.equals(searched[0])){page[0]=1;searched[0]=words;}
      long request=++searchGeneration,epoch=generation;results.removeAllViews();message.setText("검색 중");prev.setEnabled(false);next.setEnabled(false);
      int x=origin==null?0:origin.getX(),y=origin==null?0:origin.getY();
      try{KNSDK.INSTANCE.reqSearch(words,page[0],10,KNSearchReqType.KNSearchReqType_1,x,y,(error,value)->{
        ui.post(()->{
          if(!visible||epoch!=generation||request!=searchGeneration||searchDialog==null||!searchDialog.isShowing())return;
          if(error!=null||value==null){message.setText("검색하지 못했어. 다시 시도해 줘");return;}
          java.util.ArrayList<KNSearchPOI> pois=new java.util.ArrayList<>();more[0]=false;
          for(KNSearchResultObject group:new KNSearchResultObject[]{value.getPlaceResult(),value.getAddressResult()})if(group!=null){pois.addAll(group.getPoiList());more[0]|=!group.isEnd();}
          message.setText(pois.isEmpty()?"검색 결과가 없어":page[0]+"페이지 · 목적지를 선택해 줘");
          for(KNSearchPOI poi:pois){
            String address=poi.getRnAddress()!=null&&!poi.getRnAddress().isEmpty()?poi.getRnAddress():poi.getAddress();
            Button row=PulseUi.button(this,poi.getName()+"\n"+(address==null?"":address),false,()->{
              KNPOI goal=poi.getGuidePoints()!=null&&!poi.getGuidePoints().isEmpty()?poi.getGuidePoints().get(0):new KNPOI(poi.getName(),poi.getPos());
              searchDialog.dismiss();planRoute(goal,poi.getName());
            });row.setAllCaps(false);results.addView(row,new LinearLayout.LayoutParams(-1,-2));
          }
          prev.setEnabled(page[0]>1);next.setEnabled(more[0]);
        });return Unit.INSTANCE;
      });}catch(RuntimeException error){message.setText("검색을 시작하지 못했어");}
    };
    prev.setOnClickListener(v->{if(page[0]>1){page[0]--;search.run();}});next.setOnClickListener(v->{if(more[0]){page[0]++;search.run();}});
    query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH);query.setOnEditorActionListener((v,action,event)->{if(action==android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH){search.run();return true;}return false;});
    searchDialog=new androidx.appcompat.app.AlertDialog.Builder(this).setTitle("목적지").setView(body).setPositiveButton("검색",null).setNegativeButton("닫기",null).create();
    searchDialog.setOnDismissListener(dialog->searchGeneration++);searchDialog.setOnShowListener(dialog->searchDialog.getButton(-1).setOnClickListener(v->search.run()));searchDialog.show();
  }
  private void planRoute(KNPOI goal,String name){
    long wall=System.currentTimeMillis();
    if(origin==null||originTimestamp<0||wall<originTimestamp||wall-originTimestamp>=3000){status.setText("현재 위치가 잡힌 뒤 다시 선택해 줘");return;}
    KNPOI startPoint=new KNPOI("현재 위치",origin);
    // End the previous SDK trip before requesting a new one; keep free-drive reception.
    startGuidance();if(!running)return;long token=routeState.begin(name);routePending=true;updateRouteUi();send();
    ui.postDelayed(()->{if(routeState.planning(token)){routePending=false;routeState.fail();updateRouteUi();}},25000);
    try{KNSDK.INSTANCE.makeTripWithStart(startPoint,goal,null,null,(error,trip)->{
      ui.post(()->{
        if(!visible||!routeState.planning(token))return;
        if(error!=null||trip==null){routePending=false;routeState.fail();updateRouteUi();return;}
        trip.setUseMultiRoute(false);
        try{trip.routeWithPriority(KNRoutePriority.KNRoutePriority_Recommand,0,(routeError,routes)->{
          ui.post(()->{
            if(!visible||!routeState.planning(token))return;
            routePending=false;
            if(routeError!=null||routes==null||routes.isEmpty()){routeState.fail();updateRouteUi();return;}
            startGuidance(trip,routes.get(0));
          });return Unit.INSTANCE;
        });}catch(RuntimeException failure){routePending=false;routeState.fail();updateRouteUi();}
      });return Unit.INSTANCE;
    });}catch(RuntimeException failure){routePending=false;routeState.fail();updateRouteUi();}
  }
  private void installRoute(KNRoute route){
    if(route==null||!routeState.hasDestination())return;
    activeRoute=route;turnDirection=null;turnLocation=null;routePending=false;
    try{routeState.install(route.routePolylineWGS84(),route.getTotalDist(),route.getTotalTime());}
    catch(RuntimeException error){routeState.fail();}catch(Exception error){routeState.fail();}
    updateRouteUi();
  }
  private void holdRoute(){
    routeState.hold();routePending=true;updateRouteUi();
    long request=++rerouteGeneration,epoch=generation;
    ui.postDelayed(()->{if(epoch==generation&&request==rerouteGeneration&&routePending){routePending=false;routeState.fail();updateRouteUi();}},25000);
  }
  private void reroute(){
    if(guidance==null||activeTrip==null||routePending)return;
    holdRoute();send();
    try{guidance.reRoute();}catch(RuntimeException failure){routePending=false;routeState.fail();updateRouteUi();}
  }
  private void endRoute(){stop();if(visible&&app.kakaoReady)startGuidance();}

  private void safety(List<? extends KNSafety> values){
    if(!running)return;
    try{
      JSONArray out=new JSONArray();HashSet<String> ids=new HashSet<>();
      if(values!=null)for(KNSafety value:values){
        if(value==null||value.getCode()==null)continue;
        String code=value.getCode().name(),id=code+":"+value.getSafetyId();if(!ids.add(id))continue;
        String kind=value instanceof KNSafety_Section?"section":value instanceof KNSafety_Camera?"camera":
          code.equals("KNSafetyCode_Hump")?"bump":code.equals("KNSafetyCode_SharpTurnSection")?"sharp_turn":"other";
        Object limit=JSONObject.NULL;boolean variable=false;
        if(value instanceof KNSafety_Camera){KNSafety_Camera camera=(KNSafety_Camera)value;int speed=camera.getSpeedLimit();if(speed>=1&&speed<=160)limit=speed;variable=camera.isVariableSpeedLimit();}
        out.put(new JSONObject().put("id",id).put("code",code).put("kind",kind).put("distance_m",JSONObject.NULL)
          .put("distance_basis","unknown").put("limit_kph",limit).put("passed",value.getPassed()).put("variable",variable)
          .put("geometry",kind.equals("camera")?SafetyGeometry.from(value.getLocation()):JSONObject.NULL));
        if(out.length()==8)break;
      }
      observation.safety(out,SystemClock.elapsedRealtime());
      inputRecorder.safety(out,activeTrip!=null);
    }catch(Exception error){status.setText("SDK 안전 안내 형식 확인 필요 · 감속에 사용하지 않아");}
  }

  @Override public void guidanceDidUpdateLocation(KNGuidance g,KNGuide_Location location){
    updateLocation(g,location,location.getGpsOrigin()==null?null:new KNGPSData(location.getGpsOrigin()),System.currentTimeMillis(),SystemClock.elapsedRealtime());
  }
  private void updateLocation(KNGuidance g,KNGuide_Location location,KNGPSData gps,long wall,long monotonic){
    if(!running||navi==null)return;navi.guidanceDidUpdateLocation(g,location);
    boolean simulation=location.isSimulationJump()||(gps!=null&&gps.getProvider()==KNGPSProvider.KNGPSProvider_Simulation);
    observation.location(gps!=null&&gps.getValid(),gps!=null&&gps.getPosTrust(),simulation,gpsSource(gps),
      gps==null||gps.getTimestamp()==null?0:gps.getTimestamp().getTimeInMillis(),wall,monotonic);
    inputRecorder.location(gps!=null&&gps.getValid(),gps!=null&&gps.getPosTrust(),simulation,
      gps==null||gps.getTimestamp()==null?0:gps.getTimestamp().getTimeInMillis(),wall,activeTrip!=null);
    // Stationary SDK positions can be valid before motion-based trust is established.
    // Use them only to choose the trip origin; C4 observations/matching stay strict.
    boolean position=gps!=null&&observation.positionAvailable(SystemClock.elapsedRealtime());
    boolean valid=position&&gps.getPosTrust();
    if(position){origin=new IntPoint((int)Math.round(gps.getPos().getX()),(int)Math.round(gps.getPos().getY()));originTimestamp=gps.getTimestamp().getTimeInMillis();}else{origin=null;originTimestamp=-1;}
    KNLocation matched=location.getLocationForPrimaryRoute();
    boolean onRoute=valid&&!routePending&&activeTrip!=null&&g.getTrip()==activeTrip&&activeRoute!=null&&matched!=null&&matched.getRoute()==activeRoute&&location.getLocation()!=null&&location.getLocation().getRoute()==activeRoute;
    routeState.location(onRoute,valid?originTimestamp:0,System.currentTimeMillis(),SystemClock.elapsedRealtime(),onRoute?activeRoute.remainDistFromLocation(matched):-1,onRoute?activeRoute.remainTimeFromLocation(matched):-1);
    turnLocation=onRoute?matched:null;updateTurn();
    updateRouteUi();
  }
  private static String gpsSource(KNGPSData gps){
    if(gps==null||gps.getProvider()==null)return "미확인";
    switch(gps.getProvider()){
      case KNGPSProvider_GPS:return "GPS";
      case KNGPSProvider_Fused:return "융합";
      case KNGPSProvider_FIN:case KNGPSProvider_Indoor:return "실내";
      case KNGPSProvider_Simulation:return "모의";
      case KNGPSProvider_External:return "외부";
      default:return "미확인";
    }
  }
  // No trip: around-safeties is authoritative; a null route-guide must not erase it.
  @Override public void guidanceDidUpdateSafetyGuide(KNGuidance g,KNGuide_Safety safety){if(navi!=null)navi.guidanceDidUpdateSafetyGuide(g,safety);}
  @Override public void guidanceDidUpdateAroundSafeties(KNGuidance g,List<? extends KNSafety> values){if(navi!=null)navi.guidanceDidUpdateAroundSafeties(g,values);safety(values);}
  @Override public void guidanceGuideStarted(KNGuidance g){if(navi!=null){navi.guidanceGuideStarted(g);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);}}
  @Override public void guidanceGuideEnded(KNGuidance g){stop();}
  @Override public void guidanceCheckingRouteChange(KNGuidance g){if(navi!=null)navi.guidanceCheckingRouteChange(g);if(activeTrip!=null){holdRoute();}}
  @Override public void guidanceRouteUnchanged(KNGuidance g){if(navi!=null)navi.guidanceRouteUnchanged(g);if(g.getTrip()==activeTrip&&activeRoute!=null)installRoute(activeRoute);}
  @Override public void guidanceRouteUnchangedWithError(KNGuidance g,KNError error){if(navi!=null)navi.guidanceRouteUnchangedWithError(g,error);routePending=false;routeState.fail();updateRouteUi();}
  @Override public void guidanceOutOfRoute(KNGuidance g){if(navi!=null)navi.guidanceOutOfRoute(g);if(activeTrip!=null){holdRoute();}}
  @Override public void guidanceRouteChanged(KNGuidance g,KNRoute old,KNLocation oldLocation,KNRoute next,KNLocation nextLocation,KNGuideRouteChangeReason reason){if(navi!=null)navi.guidanceRouteChanged(g);if(activeTrip!=null&&g.getTrip()==activeTrip)installRoute(next);}
  @Override public void guidanceDidUpdateRoutes(KNGuidance g,List<KNRoute> routes,KNMultiRouteInfo info){if(navi!=null)navi.guidanceDidUpdateRoutes(g,routes,info);if(activeTrip!=null&&g.getTrip()==activeTrip&&routes!=null&&!routes.isEmpty()&&routes.get(0)!=activeRoute)installRoute(routes.get(0));}
  @Override public void guidanceDidUpdateIndoorRoute(KNGuidance g,KNRoute route){if(navi!=null)navi.guidanceDidUpdateIndoorRoute(g,route);}
  @Override public void guidanceDidUpdateRouteGuide(KNGuidance g,KNGuide_Route route){if(navi!=null)navi.guidanceDidUpdateRouteGuide(g,route);turnDirection=route==null?null:route.getCurDirection();updateTurn();}
  @Override public boolean shouldPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice,List<byte[]> data){return navi!=null&&navi.shouldPlayVoiceGuide(g,voice,data);}
  @Override public void willPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice){if(navi!=null)navi.willPlayVoiceGuide(g,voice);}
  @Override public void didFinishPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice){if(navi!=null)navi.didFinishPlayVoiceGuide(g,voice);}
  private void updateTurn(){
    if(routePending||turnLocation==null||turnDirection==null||turnDirection.getLocation()==null||turnDirection.getRgCode()==null||turnLocation.getRoute()!=activeRoute||turnDirection.getLocation().getRoute()!=activeRoute){routeState.turn(null,-1);return;}
    routeState.turn(turnDirection.getRgCode().name(),turnLocation.distToLocation(turnDirection.getLocation()));
  }
  private final class GuideCallbacks implements KNGuidance_GuideStateDelegate,KNGuidance_LocationGuideDelegate,KNGuidance_SafetyGuideDelegate,KNGuidance_RouteGuideDelegate,KNGuidance_VoiceGuideDelegate {
    private final long epoch;
    GuideCallbacks(long epoch){this.epoch=epoch;}
    public void guidanceDidUpdateLocation(KNGuidance g,KNGuide_Location location){
      KNGPSData gps=location.getGpsOrigin()==null?null:new KNGPSData(location.getGpsOrigin());
      long wall=System.currentTimeMillis(),monotonic=SystemClock.elapsedRealtime();
      ui.post(()->{if(epoch==generation&&running)updateLocation(g,location,gps,wall,monotonic);});
    }
    public void guidanceDidUpdateSafetyGuide(KNGuidance g,KNGuide_Safety safety){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceDidUpdateSafetyGuide(g,safety);});}
    public void guidanceDidUpdateAroundSafeties(KNGuidance g,List<? extends KNSafety> values){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceDidUpdateAroundSafeties(g,values);});}
    public void guidanceGuideStarted(KNGuidance g){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceGuideStarted(g);});}
    public void guidanceGuideEnded(KNGuidance g){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceGuideEnded(g);});}
    public void guidanceCheckingRouteChange(KNGuidance g){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceCheckingRouteChange(g);});}
    public void guidanceRouteUnchanged(KNGuidance g){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceRouteUnchanged(g);});}
    public void guidanceRouteUnchangedWithError(KNGuidance g,KNError error){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceRouteUnchangedWithError(g,error);});}
    public void guidanceOutOfRoute(KNGuidance g){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceOutOfRoute(g);});}
    public void guidanceRouteChanged(KNGuidance g,KNRoute old,KNLocation oldLocation,KNRoute next,KNLocation nextLocation,KNGuideRouteChangeReason reason){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceRouteChanged(g,old,oldLocation,next,nextLocation,reason);});}
    public void guidanceDidUpdateRoutes(KNGuidance g,List<KNRoute> routes,KNMultiRouteInfo info){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceDidUpdateRoutes(g,routes,info);});}
    public void guidanceDidUpdateIndoorRoute(KNGuidance g,KNRoute route){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceDidUpdateIndoorRoute(g,route);});}
    public void guidanceDidUpdateRouteGuide(KNGuidance g,KNGuide_Route route){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.guidanceDidUpdateRouteGuide(g,route);});}
    public boolean shouldPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice,List<byte[]> data){return epoch==generation&&running&&KakaoActivity.this.shouldPlayVoiceGuide(g,voice,data);}
    public void willPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.willPlayVoiceGuide(g,voice);});}
    public void didFinishPlayVoiceGuide(KNGuidance g,KNGuide_Voice voice){ui.post(()->{if(epoch==generation&&running)KakaoActivity.this.didFinishPlayVoiceGuide(g,voice);});}
  }
  @Override protected void onResume(){super.onResume();visible=true;if(app.kakaoInstalled){KNSDK.INSTANCE.handleWillEnterForeground();KNSDK.INSTANCE.handleDidBecomeActive();}ui.post(gpsPoll);start.setEnabled(!app.kakaoInitializing);if(running)refreshLocalStatus();if(notificationStartPending){notificationStartPending=false;begin();}}
  @Override protected void onPause(){visible=false;ui.removeCallbacks(gpsPoll);if(roadGps.running()&&!(automaticRoadGps&&running))roadGps.stop("앱을 벗어나 도로용 GPS 전송 중지");if(app.kakaoInstalled){KNSDK.INSTANCE.handleWillResignActive();KNSDK.INSTANCE.handleDidEnterBackground();}super.onPause();}
  @Override protected void onDestroy(){if(observationDetails!=null)observationDetails.dismiss();stop();roadGps.close();super.onDestroy();}
  @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grants){super.onRequestPermissionsResult(code,permissions,grants);if(code==43){notificationStartPending=true;if(visible){notificationStartPending=false;begin();}return;}status.setText(code==42?"위치 권한을 허용한 뒤 GPS 전송을 눌러줘":"정확한 위치 권한을 허용한 뒤 수신 시작을 눌러줘");}
}
