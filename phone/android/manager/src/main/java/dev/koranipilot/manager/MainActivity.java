package dev.koranipilot.manager;

import android.app.AlertDialog;
import android.content.Intent;
import android.view.View;
import android.view.WindowManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.widget.*;
import dev.comma.companion.PhoneClient;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.UUID;
import androidx.activity.result.ActivityResultLauncher;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

/** Same-network Koranipilot management with an optional Kakao reception screen. */
public final class MainActivity extends KakaoActivity {
  interface Work { JSONObject run(PhoneClient client) throws Exception; }
  interface Done { void run(JSONObject data) throws Exception; }

  private ManagerApp app;
  private LinearLayout root, content, navigation;
  private LinearLayout receiverRoot;
  private String screen="home", rendered="";
  private JSONObject overview;
  private AlertDialog modelDialog;
  private LinearLayout modelBody;
  private String modelRendered="";
  private SettingsSheet settingsSheet;
  private int catalogLoad;
  private TextView connectionChip, pairingError;
  private AlertDialog pairingDialog, qrConfirmation;
  private EditText url, pin, code, name;
  private TextView status;
  private final Handler ui=new Handler(Looper.getMainLooper());
  private boolean visible=false, busy=false, pairing=false;
  private JSONObject uncertain;
  private String uncertainResultPath;
  private PhoneClient uncertainClient;
  private final Runnable poll=new Runnable(){public void run(){if(visible){refresh();ui.postDelayed(this,2000);}}};

  @Override public void onCreate(Bundle state){
    super.onCreate(state);app=(ManagerApp)getApplication();
    receiverRoot=receiverContent();((android.view.ViewGroup)receiverRoot.getParent()).removeView(receiverRoot);
    root=PulseUi.column(this);root.setBackgroundColor(PulseUi.BG);FrameLayout stage=new FrameLayout(this);stage.addView(root);stage.addView(receiverRoot);setContentView(stage);PulseUi.window(this,root);
    LinearLayout header=PulseUi.row(this);header.setPadding(dp(24),dp(22),dp(24),dp(12));
    TextView brand=PulseUi.text(this,"KORANIPILOT",13,PulseUi.TEXT);brand.setLetterSpacing(.13f);header.addView(brand,new LinearLayout.LayoutParams(0,-2,1));
    connectionChip=PulseUi.text(this,"연결 전",12,PulseUi.LIME);header.addView(connectionChip);root.addView(header);
    ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setClipToPadding(false);
    LinearLayout body=PulseUi.column(this);body.setPadding(dp(26),dp(16),dp(26),dp(22));scroll.addView(body);
    status=PulseUi.text(this,"",13,PulseUi.MUTED);status.setPadding(0,0,0,dp(14));status.setVisibility(View.GONE);status.setTextIsSelectable(true);body.addView(status);
    content=PulseUi.column(this);body.addView(content);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
    PulseUi.line(root);navigation=PulseUi.column(this);root.addView(navigation);
    if(state!=null)screen=state.getString("screen","home");
    if("device".equals(getIntent().getStringExtra("screen")))screen="device";
    showScreen(screen);
  }

  private int dp(int value){return PulseUi.dp(this,value);}
  private TextView label(LinearLayout parent,String value,int size){TextView v=PulseUi.label(parent,value,size,PulseUi.TEXT);v.setPadding(0,dp(7),0,dp(7));return v;}
  private void button(LinearLayout parent,String text,Runnable action){PulseUi.action(parent,text,false,action);PulseUi.gap(parent,8);}
  private void message(String value){status.setText(value);status.setVisibility(value.isEmpty()?View.GONE:View.VISIBLE);}
  private void openMap(){showScreen("map");}
  @Override protected void returnTo(String screen){showScreen(screen);}
  private boolean linked(){return overview!=null&&app.client!=null&&app.client.connected();}
  private boolean homeMode(){JSONObject c=overview==null?null:overview.optJSONObject("connection");return c!=null&&"home_receive".equals(c.optString("mode"));}

  private void showScreen(String next){screen=next;root.setVisibility(next.equals("map")?View.GONE:View.VISIBLE);receiverRoot.setVisibility(next.equals("map")?View.VISIBLE:View.GONE);screenVisibility(next.equals("map"));rendered="";renderScreen();}
  private void renderScreen(){
    updateModels();
    if(screen.equals("map"))return;
    String fingerprint=screen+"|"+String.valueOf(overview)+"|"+pairing+"|"+(uncertain!=null)+"|"+app.kakaoReady+"|"+receiving()+"|"+receptionGps()+"|"+roadGps.status()+"|"+roadGps.gpsStatus();
    if(fingerprint.equals(rendered))return;rendered=fingerprint;
    content.removeAllViews();navigation.removeAllViews();
    boolean connected=linked();connectionChip.setText(connected?"● 연결됨":pairing?"승인 대기":"연결 전");connectionChip.setTextColor(connected?PulseUi.LIME:PulseUi.MUTED);
    navigation.addView(PulseUi.navigation(this,screen,()->showScreen("home"),this::openMap,()->showScreen("device")));
    if(screen.equals("device")){renderDevice();return;}
    TextView eyebrow=PulseUi.label(content,"COMMA FOUR",10,PulseUi.MUTED);eyebrow.setLetterSpacing(.18f);PulseUi.gap(content,10);
    TextView title=PulseUi.label(content,connected?"연결 완료.":pairing?"승인 대기.":"연결 전.",36,PulseUi.TEXT);title.setLetterSpacing(-.04f);
    PulseUi.gap(content,14);
    content.addView(new PulseUi.SignalRing(this,connected,connected?(homeMode()?"집 테스트 · 수신 전용":"기기 연결됨"):pairing?"C4에서 승인해 줘":"연결 전"),new LinearLayout.LayoutParams(-1,dp(250)));
    PulseUi.gap(content,18);PulseUi.line(content);PulseUi.gap(content,18);
    LinearLayout stats=PulseUi.row(this);LinearLayout gps=PulseUi.column(this),kakao=PulseUi.column(this);
    PulseUi.label(gps,"GPS",10,PulseUi.MUTED);PulseUi.gap(gps,8);PulseUi.label(gps,roadGps.running()?roadGps.gpsStatus():receptionGps(),17,PulseUi.TEXT);
    PulseUi.label(kakao,"카카오",10,PulseUi.MUTED);PulseUi.gap(kakao,8);PulseUi.label(kakao,app.kakaoReady?"인증 완료":"연결 전",17,PulseUi.TEXT);
    stats.addView(gps,new LinearLayout.LayoutParams(0,-2,1));stats.addView(kakao,new LinearLayout.LayoutParams(0,-2,1));content.addView(stats);
    PulseUi.gap(content,18);PulseUi.line(content);PulseUi.gap(content,24);
    PulseUi.action(content,"지도 · 수신 열기  →",true,this::openMap);PulseUi.gap(content,12);
    PulseUi.menu(content,connected?"내 기기":"C4 연결하기",connected?(homeMode()?"집 수신":"연결됨"):"",connected?()->showScreen("device"):this::showPairing);
  }

  private void renderDevice(){
    label(content,"내 기기",30);PulseUi.gap(content,18);LinearLayout card=PulseUi.card(this);
    label(card,"comma four",24);PulseUi.label(card,linked()?(homeMode()?"집 테스트 · 수신 전용":"연결됨"):pairing?"C4 승인 대기":"연결 전",13,PulseUi.LIME);content.addView(card);PulseUi.gap(content,26);
    if(!linked()){
      PulseUi.action(content,pairing?"승인 상태 확인":"C4 연결하기",true,pairing?this::refresh:this::showPairing);
      PulseUi.gap(content,12);button(content,"이전 C4 버전 · 직접 입력",this::showManualPairing);
      PulseUi.gap(content,20);PulseUi.menu(content,"설정 둘러보기","",this::showSettings);
      if(app.client!=null){PulseUi.gap(content,12);button(content,"연결 취소",this::disconnect);}return;
    }
    JSONObject settings=overview.optJSONObject("settings"),models=overview.optJSONObject("models");
    PulseUi.label(content,"기기 관리",11,PulseUi.MUTED);
    PulseUi.menu(content,"기기 정보",overview.optJSONObject("device").optString("version"),this::showDeviceInfo);
    PulseUi.menu(content,"설정",homeMode()?"수신 전용":settings.optBoolean("parked")?"주차 확인":"상태 확인",this::showSettings);
    JSONObject current=models.optJSONObject("current");
    PulseUi.menu(content,"주행 모델",current==null?"확인 전":current.optString("name"),this::showModels);
    PulseUi.menu(content,"도로 입력",roadGps.running()?"관찰 중":"대기",this::openMap);
    PulseUi.gap(content,24);
    if(uncertain!=null)button(content,"변경 결과 확인",this::recover);
    button(content,"상태 새로고침",this::refresh);button(content,"연결 해제",this::disconnect);
  }

  private final ActivityResultLauncher<ScanOptions> qrScanner=registerForActivityResult(new ScanContract(),result->{
    if(result.getContents()==null){message("QR 스캔을 취소했어");return;}
    try { showQrConfirmation(PairingQr.parse(result.getContents())); }
    catch(IllegalArgumentException error){message(error.getMessage());}
  });

  private void showPairing(){
    if(pairing||(app.client!=null&&app.client.connected())){showScreen("device");return;}
    if(busy){message("현재 연결 확인이 끝난 뒤 다시 시도해줘");return;}
    ScanOptions options=new ScanOptions();
    options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
    options.setCaptureActivity(PhoneQrCaptureActivity.class);
    options.setPrompt("C4에서 ‘QR로 폰 연결’을 누르고 스캔해줘");
    options.setBeepEnabled(false);options.setBarcodeImageEnabled(false);options.setOrientationLocked(false);
    qrScanner.launch(options);
  }

  private void showQrConfirmation(PairingQr data){
    if(pairing||(app.client!=null&&app.client.connected())||busy){showScreen("device");return;}
    LinearLayout form=detailContent();
    PulseUi.label(form,"C4 연결 정보를 읽었어",22,PulseUi.TEXT);PulseUi.gap(form,16);
    PulseUi.label(form,data.url,16,PulseUi.MUTED);PulseUi.gap(form,16);
    EditText phoneName=PulseUi.input(this,"폰 이름",false);phoneName.setText("내 안드로이드");form.addView(phoneName);
    PulseUi.gap(form,16);PulseUi.label(form,"요청을 보낸 뒤 C4에서 승인해줘.",16,PulseUi.MUTED);
    AlertDialog dialog=new AlertDialog.Builder(this).setTitle("C4 연결")
      .setView(form).setNegativeButton("취소",null)
      .setPositiveButton("연결 요청",(d,w)->pair(data.url,data.pin,data.code,phoneName.getText().toString())).create();
    qrConfirmation=dialog;dialog.setOnDismissListener(d->qrConfirmation=null);
    dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);dialog.show();
  }

  private void showManualPairing(){
    if(pairing||(app.client!=null&&app.client.connected())){showScreen("device");return;}
    LinearLayout form=PulseUi.column(this);form.setPadding(dp(24),dp(8),dp(24),dp(8));
    PulseUi.label(form,"같은 Wi-Fi에서 C4의 연결 정보를 입력해.",14,PulseUi.MUTED);PulseUi.gap(form,18);
    url=PulseUi.input(this,"https://C4주소:7443",false);url.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);
    pin=PulseUi.input(this,"기기 인증값 64자리",true);name=PulseUi.input(this,"폰 이름",false);name.setText("내 안드로이드");
    code=PulseUi.input(this,"연결 코드 6자리",false);code.setInputType(InputType.TYPE_CLASS_NUMBER);
    for(EditText field:new EditText[]{url,pin,name,code}){form.addView(field,new LinearLayout.LayoutParams(-1,-2));PulseUi.gap(form,10);}
    pairingError=PulseUi.label(form,"",13,PulseUi.LIME);pairingError.setVisibility(View.GONE);
    ScrollView scroll=new ScrollView(this);scroll.addView(form);
    pairingDialog=new AlertDialog.Builder(this).setTitle("C4 연결").setView(scroll).setNegativeButton("닫기",null).setPositiveButton("연결 요청",null).create();
    pairingDialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);pairingDialog.show();
    pairingDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->pair());
    pairingDialog.setOnDismissListener(d->{pin.setText("");code.setText("");pairingDialog=null;});
  }

  private void showDeviceInfo(){
    if(!linked())return;JSONObject d=overview.optJSONObject("device");
    new AlertDialog.Builder(this).setTitle("기기 정보").setMessage(d.optString("hardware")+" · "+d.optString("identifier")+"\n\n버전  "+d.optString("version")+"\n브랜치  "+d.optString("branch")+"\n커밋  "+d.optString("commit")).setPositiveButton("닫기",null).show();
  }
  private LinearLayout detailContent(){LinearLayout body=PulseUi.column(this);body.setPadding(dp(24),dp(8),dp(24),dp(16));return body;}
  private AlertDialog detail(String title,LinearLayout body){ScrollView scroll=new ScrollView(this);scroll.addView(body);return new AlertDialog.Builder(this).setTitle(title).setView(scroll).setNegativeButton("닫기",null).create();}
  private void showSettings(){
    if(settingsSheet!=null)settingsSheet.dismiss();
    settingsSheet=new SettingsSheet(this,new SettingsSheet.Actions(){
      public void refresh(){loadCatalog();}
      public void recover(){MainActivity.this.recover();}
      public void save(JSONObject row,Object value,String revision){
        try{
          JSONObject body=new JSONObject().put("request_id",UUID.randomUUID().toString()).put("id",row.getString("id"))
            .put("value",value==null?JSONObject.NULL:value).put("revision",revision).put("acknowledged",true);
          submit(body,"catalog-changes","catalog-changes/"+body.getString("request_id"));
        }catch(Exception error){Toast.makeText(MainActivity.this,"설정값 확인 필요",Toast.LENGTH_SHORT).show();}
      }
    });
    settingsSheet.show();settingsSheet.pending(uncertain!=null);loadCatalog();
  }
  private void loadCatalog(){
    SettingsSheet selectedSheet=settingsSheet;if(selectedSheet==null||!selectedSheet.showing())return;
    PhoneClient selected=app.client;
    if(selected==null||!selected.connected()){selectedSheet.unavailable("연결 전");return;}
    if(overview!=null&&overview.optInt("catalog_schema")!=1){selectedSheet.unavailable("C4 업데이트 필요");return;}
    final int generation=++catalogLoad;selectedSheet.loading();
    app.network.execute(()->{
      JSONObject answer=null;String error=null;
      try{answer=selected.call("catalog",null);if(answer.optInt("schema")!=1)throw new IllegalStateException("C4 업데이트 필요");}
      catch(PhoneClient.ApiException failure){error=failure.status==404?"C4 업데이트 필요":"연결 확인 필요";}
      catch(Exception failure){error="설정 수신 실패";}
      final JSONObject data=answer;final String failure=error;
      ui.post(()->{
        if(isDestroyed()||!visible||selected!=app.client||selectedSheet!=settingsSheet||generation!=catalogLoad)return;
        if(failure==null)selectedSheet.update(data);else selectedSheet.unavailable(failure);
        selectedSheet.pending(uncertain!=null);
      });
    });
  }
  private void showModels(){
    if(!linked())return;
    if(modelDialog!=null)modelDialog.dismiss();
    modelBody=detailContent();modelDialog=detail("주행 모델",modelBody);modelRendered="";
    modelDialog.setOnDismissListener(d->{modelDialog=null;modelBody=null;modelRendered="";});
    modelDialog.show();updateModels();
  }

  private void updateModels(){
    if(modelDialog==null||modelBody==null)return;
    JSONObject models=linked()&&visible?overview.optJSONObject("models"):null;
    String fingerprint=String.valueOf(models)+"|"+(uncertain!=null)+"|"+homeMode();
    if(fingerprint.equals(modelRendered))return;modelRendered=fingerprint;
    modelBody.removeAllViews();
    if(models==null){label(modelBody,"연결 상태 확인 중 · 변경할 수 없어",15);return;}
    if(models.optInt("schema")!=2){label(modelBody,"C4 모델 관리 업데이트 필요",18);label(modelBody,"이 C4 설치본은 실제 실행 모델 확인과 새 변경 기능을 지원하지 않아",14);return;}
    JSONObject current=models.optJSONObject("current"),configured=models.optJSONObject("configured");
    PulseUi.label(modelBody,"현재 실행",13,PulseUi.LIME);
    label(modelBody,current==null?"확인 대기":current.optString("name","확인 대기"),24);
    PulseUi.gap(modelBody,12);
    label(modelBody,"다음 기동 · "+(configured==null?"확인 대기":configured.optString("name")),16);
    label(modelBody,models.optString("message","실행 상태 확인 대기"),14);
    JSONObject requested=models.optJSONObject("requested");
    if(requested!=null)label(modelBody,"요청 · "+requested.optString("name"),15);
    if(!models.isNull("progress"))label(modelBody,"다운로드 · "+models.optDouble("progress")+"%",14);
    if(homeMode()){label(modelBody,"집 테스트에서는 모델을 변경할 수 없어",14);return;}
    if(!models.optString("blocked_reason").isEmpty())label(modelBody,models.optString("blocked_reason"),14);
    if(uncertain!=null)button(modelBody,"요청 결과 확인",this::recover);
    JSONArray available=models.optJSONArray("available");if(available==null)return;
    PulseUi.gap(modelBody,12);
    for(int i=0;i<available.length();i++){
      JSONObject model=available.optJSONObject(i);if(model==null)continue;
      String ref=model.optString("ref");
      Button button=PulseUi.button(this,model.optString("name"),false,()->{
        modelDialog.dismiss();confirmModel(model,models.optString("revision"));
      });
      boolean allowed=ref.isEmpty()?models.optBoolean("can_restore_default"):models.optBoolean("editable");
      boolean same=configured!=null&&ref.equals(configured.optString("ref"));
      boolean retry="failed".equals(models.optString("state"));
      button.setEnabled(allowed&&uncertain==null&&(!same||requested!=null||retry));
      modelBody.addView(button);PulseUi.gap(modelBody,8);
    }
  }

  private void pair(){
    pair(url.getText().toString(),pin.getText().toString(),code.getText().toString(),name.getText().toString());
  }

  private void pair(String address,String fingerprint,String pairingCode,String phoneName){
    if(busy||pairing||(app.client!=null&&app.client.connected())){message("현재 연결을 먼저 확인하거나 해제해");return;}
    try{
      PhoneClient next=new PhoneClient(address,fingerprint);
      JSONObject body=new JSONObject().put("code",pairingCode).put("name",phoneName);
      app.disconnect();app.client=next;
      if(pairingDialog!=null)pairingDialog.dismiss();
      message("C4에 연결을 요청하고 있어");
      request(c->c.call("pair",body),d->{pairing=true;message("C4 화면에서 이 폰을 승인해");renderScreen();});
    }catch(Exception error){message("연결 정보를 확인하지 못했어. C4의 QR을 다시 스캔해줘");}
  }

  private void request(Work work,Done done){
    PhoneClient selected=app.client;if(busy||selected==null){if(selected==null)message("기기에 먼저 연결해");return;}
    busy=true;app.network.execute(()->{JSONObject answer=null;String failure=null;
      try{answer=work.run(selected);}catch(Exception error){failure=error.getMessage()==null?"연결을 확인하지 못했어":error.getMessage();}
      JSONObject result=answer;String message=failure;ui.post(()->{busy=false;if(app.client!=selected||isDestroyed())return;
        if(message!=null){if(settingsSheet!=null){settingsSheet.unavailable("연결 확인 필요");settingsSheet.pending(uncertain!=null);}overview=null;if(!selected.connected())pairing=false;renderScreen();message(message+" · 같은 Wi-Fi와 승인/만료 상태를 확인해");return;}
        try{done.run(result);}catch(Exception error){overview=null;renderScreen();message("기기 응답 형식을 확인하지 못했어");}});});
  }

  private void refresh(){
    renderScreen();if(app.client==null||busy)return;
    request(c->{JSONObject session=c.call("session",null);if(session.optString("state").equals("connected"))session.put("overview",c.call("overview",null));return session;},data->{
      String state=data.getString("state");if(!state.equals("connected")){overview=null;pairing=!state.equals("rejected");renderScreen();message(state.equals("rejected")?"C4에서 연결을 거절했어":"C4의 연결 승인을 기다리고 있어");if(state.equals("rejected"))pairing=false;return;}
      pairing=false;render(data.getJSONObject("overview"));
    });
  }

  private void render(JSONObject data)throws Exception{
    // Validate required sections before allowing the device controls to appear.
    data.getJSONObject("device");data.getJSONObject("settings");data.getJSONObject("models");
    overview=data;message(uncertain==null?"":"변경 결과 확인이 필요해");renderScreen();
  }

  private String choice(JSONObject row,String key,JSONArray options)throws Exception{return row.isNull(key)?"확인 불가":options.getString(row.getBoolean(key)?1:0);}
  private String notices(JSONObject row,boolean value)throws Exception{JSONArray values=row.getJSONArray("notices").getJSONArray(value?1:0);StringBuilder text=new StringBuilder();for(int i=0;i<values.length();i++)text.append(values.getString(i)).append('\n');return text.toString();}

  private void confirmSetting(JSONObject row,boolean value,String revision){
    try{new AlertDialog.Builder(this).setTitle(row.getString("title")+" 변경").setMessage(notices(row,value)).setNegativeButton("취소",null).setPositiveButton("확인·저장",(d,w)->{
      try{JSONObject body=new JSONObject().put("request_id",UUID.randomUUID().toString()).put("id",row.getString("id")).put("value",value).put("revision",revision).put("acknowledged",true);submit(body,"changes","changes/"+body.optString("request_id"));}catch(Exception error){message("변경 요청을 만들지 못했어");}
    }).show();}catch(Exception error){message("변경 내용을 다시 확인해");}
  }

  private void confirmModel(JSONObject model,String revision){
    try{new AlertDialog.Builder(this).setTitle("주행 모델 변경").setMessage(model.getString("name")+" 모델을 요청해. P단·정차·보조 해제 상태에서 다운로드하고, 다음 기동에서 실행을 확인해. 기본 모델 복귀는 진행 중인 요청도 취소해.").setNegativeButton("취소",null).setPositiveButton("확인·요청",(d,w)->{
      try{JSONObject body=new JSONObject().put("request_id",UUID.randomUUID().toString()).put("ref",model.getString("ref")).put("revision",revision).put("acknowledged",true);submit(body,"models","model-changes/"+body.optString("request_id"));}catch(Exception error){message("모델 요청을 만들지 못했어");}
    }).show();}catch(Exception error){message("모델 정보를 다시 확인해");}
  }

  private void submit(JSONObject body,String path,String resultPath){
    if(busy){Toast.makeText(this,"상태 확인 중 · 다시 눌러줘",Toast.LENGTH_SHORT).show();return;}
    if(uncertain!=null||app.client==null)return;uncertain=body;uncertainResultPath=resultPath;uncertainClient=app.client;
    if(settingsSheet!=null)settingsSheet.pending(true);
    request(c->c.call(path,body),receipt->{message(receipt.getString("message"));Toast.makeText(this,receipt.getString("message"),Toast.LENGTH_LONG).show();uncertain=null;uncertainResultPath=null;uncertainClient=null;loadCatalog();refresh();});
  }

  private void recover(){
    if(uncertain==null){refresh();return;}if(app.client!=uncertainClient){message("이전 연결의 결과는 현재 상태로 확인해. 자동 재전송하지 않아.");uncertain=null;uncertainResultPath=null;uncertainClient=null;return;}
    String path=uncertainResultPath;request(c->c.call(path,null),result->{JSONObject receipt=result.getJSONObject("receipt");message(receipt.getString("message"));uncertain=null;uncertainResultPath=null;uncertainClient=null;loadCatalog();refresh();});
  }

  private void disconnect(){
    catalogLoad++;if(settingsSheet!=null)settingsSheet.unavailable("연결 전");
    roadGps.stop("기기 연결 해제");
    PhoneClient selected=app.detach();if(selected==null){overview=null;pairing=false;renderScreen();message("연결 해제됨");return;}
    app.network.execute(()->{try{selected.call(selected.connected()?"logout":"cancel",new JSONObject());}catch(Exception ignored){}finally{selected.clear();}});
    pairing=false;uncertain=null;uncertainResultPath=null;uncertainClient=null;overview=null;renderScreen();message("연결 해제됨");
  }

  @Override protected void onResume(){super.onResume();visible=true;renderScreen();ui.post(poll);if(settingsSheet!=null&&settingsSheet.showing())loadCatalog();}
  @Override protected void onPause(){visible=false;catalogLoad++;if(settingsSheet!=null)settingsSheet.unavailable("다시 확인 필요");ui.removeCallbacks(poll);overview=null;rendered="";updateModels();super.onPause();}
  @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);showScreen("device".equals(intent.getStringExtra("screen"))?"device":"home");}
  @Override protected void onSaveInstanceState(Bundle state){state.putString("screen",screen);super.onSaveInstanceState(state);}
  @Override protected void onDestroy(){if(modelDialog!=null)modelDialog.dismiss();if(qrConfirmation!=null)qrConfirmation.dismiss();if(settingsSheet!=null)settingsSheet.dismiss();disconnect();super.onDestroy();}
}
