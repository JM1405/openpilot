package dev.koranipilot.manager;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.util.Locale;

/** Compact settings browser. Values and permission come from the C4 catalog. */
final class SettingsSheet {
  interface Actions {
    void refresh();
    void save(JSONObject row,Object value,String revision);
    void recover();
  }
  private final Activity activity;
  private final Actions actions;
  private final Dialog dialog;
  private final LinearLayout list;
  private final TextView title, state;
  private EditText search;
  private JSONObject catalog;
  private String group="", query="", availability="연결 전";
  private boolean ready, waiting, uncertain;
  private int version;
  private AlertDialog editor;

  SettingsSheet(Activity activity,Actions actions){
    this.activity=activity;this.actions=actions;
    try(InputStream input=activity.getAssets().open("settings_catalog.json")){
      ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;
      while((n=input.read(buffer))!=-1)bytes.write(buffer,0,n);
      catalog=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
    }catch(Exception error){catalog=new JSONObject();}
    dialog=new Dialog(activity);dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
    LinearLayout shell=PulseUi.column(activity);shell.setBackgroundColor(PulseUi.BG);
    LinearLayout header=PulseUi.row(activity);header.setPadding(dp(18),dp(16),dp(18),dp(10));
    TextView back=PulseUi.text(activity,"‹",32,PulseUi.LIME);back.setGravity(Gravity.CENTER);back.setContentDescription("설정 뒤로");
    header.addView(back,new LinearLayout.LayoutParams(dp(48),dp(48)));back.setOnClickListener(v->{if(!group.isEmpty()||!query.isEmpty()){group="";search.setText("");render();}else dialog.dismiss();});
    title=PulseUi.text(activity,"설정",26,PulseUi.TEXT);header.addView(title,new LinearLayout.LayoutParams(0,-2,1));
    TextView refresh=PulseUi.text(activity,"↻",28,PulseUi.LIME);refresh.setGravity(Gravity.CENTER);refresh.setContentDescription("설정 새로고침");header.addView(refresh,new LinearLayout.LayoutParams(dp(48),dp(48)));refresh.setOnClickListener(v->actions.refresh());shell.addView(header);
    LinearLayout filters=PulseUi.column(activity);filters.setPadding(dp(26),dp(4),dp(26),dp(14));
    state=PulseUi.text(activity,"연결 전",12,PulseUi.MUTED);state.setPadding(0,dp(6),0,dp(14));filters.addView(state);state.setOnClickListener(v->{if(uncertain)actions.recover();});
    search=PulseUi.input(activity,"설정 검색",false);search.setBackground(PulseUi.surface(activity,PulseUi.SURFACE,12));filters.addView(search);shell.addView(filters);
    search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int count,int after){}public void onTextChanged(CharSequence s,int st,int before,int count){query=s.toString().trim();render();}public void afterTextChanged(Editable e){}});
    ScrollView scroll=new ScrollView(activity);list=PulseUi.column(activity);list.setPadding(dp(26),0,dp(26),dp(30));scroll.addView(list);shell.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
    dialog.setContentView(shell);
    if(android.os.Build.VERSION.SDK_INT>=30){
      dialog.getWindow().setDecorFitsSystemWindows(false);
      shell.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets safe=insets.getInsets(android.view.WindowInsets.Type.systemBars()|android.view.WindowInsets.Type.ime());v.setPadding(safe.left,safe.top,safe.right,safe.bottom);return insets;});
    }
    dialog.setOnDismissListener(d->{if(editor!=null)editor.dismiss();});
  }
  private int dp(int value){return PulseUi.dp(activity,value);}
  boolean showing(){return dialog.isShowing();}
  void show(){dialog.show();dialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);dialog.getWindow().setLayout(-1,-1);render();}
  void dismiss(){dialog.dismiss();}
  void unavailable(String reason){ready=false;waiting=false;availability=reason;version++;if(editor!=null)editor.dismiss();render();}
  void loading(){waiting=true;render();}
  void pending(boolean value){uncertain=value;render();}
  void update(JSONObject value){catalog=value;ready=true;waiting=false;version++;if(editor!=null)editor.dismiss();availability=shortReason(value.optString("reason"));render();}
  private static String shortReason(String reason){
    if(reason.isEmpty())return "주차 확인";
    if(reason.contains("집 테스트")||reason.contains("수신 전용"))return "집 수신 · 읽기 전용";
    if(reason.contains("주차")||reason.contains("P단"))return "주차 필요";
    if(reason.contains("상태")||reason.contains("차량·"))return "차량 확인 필요";
    return reason;
  }
  static String valueLabel(JSONObject row,Object value){
    if(value==null||value==JSONObject.NULL)return row.optBoolean("nullable")?"기본":"미설정";
    JSONArray options=row.optJSONArray("options");
    if(options!=null)for(int i=0;i<options.length();i++){JSONObject option=options.optJSONObject(i);Object candidate=option.opt("value");if(equal(value,candidate))return option.optString("label");}
    String label=value instanceof Number?new BigDecimal(value.toString()).stripTrailingZeros().toPlainString():String.valueOf(value);
    String unit=row.optString("unit");return label+(unit.isEmpty()?"":" "+unit);
  }
  private static boolean equal(Object a,Object b){return a instanceof Number&&b instanceof Number?Double.compare(((Number)a).doubleValue(),((Number)b).doubleValue())==0:a==null?b==null:a.equals(b);}
  private String rowValue(JSONObject row){
    if(!ready)return "—";
    if(row.optBoolean("read_error"))return "확인 필요";
    return valueLabel(row,row.opt("saved"));
  }
  private void render(){
    if(list==null)return;list.removeAllViews();
    title.setText(!query.isEmpty()?"검색":group.isEmpty()?"설정":groupTitle(group));
    state.setText(uncertain?"저장 결과 확인  ›":waiting?"불러오는 중":availability);
    state.setTextColor(uncertain?PulseUi.LIME:PulseUi.MUTED);
    JSONArray rows=catalog.optJSONArray("rows"),groups=catalog.optJSONArray("groups");if(rows==null||groups==null)return;
    if(group.isEmpty()&&query.isEmpty()){
      for(int i=0;i<groups.length();i++){JSONObject section=groups.optJSONObject(i);String id=section.optString("id");int count=0;for(int n=0;n<rows.length();n++)if(id.equals(rows.optJSONObject(n).optString("group")))count++;
        PulseUi.menu(list,section.optString("title"),String.valueOf(count),()->{group=id;render();});
      }return;
    }
    int count=0;
    for(int i=0;i<rows.length();i++){
      JSONObject row=rows.optJSONObject(i);
      if(query.isEmpty()&&!group.equals(row.optString("group")))continue;
      String haystack=(row.optString("title")+" "+row.optString("id")+" "+groupTitle(row.optString("group"))).toLowerCase(Locale.ROOT);
      if(!query.isEmpty()&&!haystack.contains(query.toLowerCase(Locale.ROOT)))continue;
      count++;LinearLayout item=PulseUi.row(activity);item.setPadding(0,dp(18),0,dp(18));item.setMinimumHeight(dp(72));
      LinearLayout text=PulseUi.column(activity);PulseUi.label(text,row.optString("title"),16,PulseUi.TEXT);
      String support=ready?row.optString("support_reason"):"";
      if(!support.isEmpty()){PulseUi.gap(text,7);PulseUi.label(text,support,11,PulseUi.MUTED);}
      item.addView(text,new LinearLayout.LayoutParams(0,-2,1));
      TextView value=PulseUi.text(activity,rowValue(row)+"  ›",14,ready&&row.optBoolean("editable")?PulseUi.LIME:PulseUi.MUTED);value.setGravity(Gravity.END);value.setMaxWidth(dp(132));value.setPadding(dp(14),0,0,0);item.addView(value);
      item.setContentDescription(row.optString("title")+" · "+rowValue(row));item.setFocusable(true);item.setOnClickListener(v->edit(row));list.addView(item);PulseUi.line(list);
    }
    if(count==0){PulseUi.gap(list,24);PulseUi.label(list,"검색 결과 없음",16,PulseUi.MUTED);}
  }
  private String groupTitle(String id){JSONArray groups=catalog.optJSONArray("groups");if(groups!=null)for(int i=0;i<groups.length();i++){JSONObject g=groups.optJSONObject(i);if(id.equals(g.optString("id")))return g.optString("title");}return "설정";}
  private void edit(JSONObject row){
    final int openedVersion=version;
    LinearLayout body=PulseUi.column(activity);body.setPadding(dp(24),dp(12),dp(24),dp(16));
    PulseUi.label(body,"저장  "+rowValue(row),14,PulseUi.MUTED);PulseUi.gap(body,8);
    if(ready&&!row.isNull("current")){PulseUi.label(body,"현재  "+valueLabel(row,row.opt("current")),14,PulseUi.LIME);PulseUi.gap(body,8);}
    if(row.optBoolean("restart")){PulseUi.label(body,"재시작 후 적용",12,PulseUi.MUTED);PulseUi.gap(body,8);}
    String reason=!ready?availability:uncertain?"이전 저장 결과 확인 필요":row.optString("blocked_reason");
    if(!reason.isEmpty()){PulseUi.label(body,reason,14,PulseUi.MUTED);PulseUi.gap(body,14);}
    boolean enabled=ready&&!waiting&&!uncertain&&row.optBoolean("editable");
    final Object[] selected={row.opt("saved")};
    JSONArray options=row.optJSONArray("options");
    if(options!=null){
      for(int i=0;i<options.length();i++){JSONObject option=options.optJSONObject(i);Object value=option.opt("value");
        Button button=PulseUi.button(activity,option.optString("label"),ready&&equal(value,row.opt("saved")),()->confirm(row,value,openedVersion));
        button.setEnabled(enabled&&option.optBoolean("enabled",true));body.addView(button,new LinearLayout.LayoutParams(-1,-2));PulseUi.gap(body,8);
        if(!option.optString("reason").isEmpty())PulseUi.label(body,option.optString("reason"),12,PulseUi.MUTED);
      }
    }else if("number".equals(row.optString("type"))){
      double min=row.optDouble("min"),max=row.optDouble("max"),step=row.optDouble("step",1);
      double initial=row.isNull("saved")?row.optDouble("default",min):row.optDouble("saved",min);
      int steps=(int)Math.round((max-min)/step);int initialStep=(int)Math.round((initial-min)/step);
      SeekBar slider=new SeekBar(activity);slider.setMax(steps);slider.setProgress(Math.max(0,Math.min(steps,initialStep)));slider.setEnabled(enabled);slider.setProgressTintList(android.content.res.ColorStateList.valueOf(PulseUi.LIME));
      TextView value=PulseUi.label(body,"",30,PulseUi.TEXT);value.setGravity(Gravity.CENTER);PulseUi.gap(body,18);
      java.util.function.IntConsumer update=p->{BigDecimal result=BigDecimal.valueOf(min).add(BigDecimal.valueOf(step).multiply(BigDecimal.valueOf(p)));selected[0]=step%1==0&&min%1==0?(Object)result.intValueExact():result.doubleValue();value.setText(valueLabel(row,selected[0]));};
      update.accept(slider.getProgress());body.addView(slider,new LinearLayout.LayoutParams(-1,dp(48)));
      slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){public void onProgressChanged(SeekBar bar,int progress,boolean user){update.accept(progress);}public void onStartTrackingTouch(SeekBar bar){}public void onStopTrackingTouch(SeekBar bar){}});
      LinearLayout stepper=PulseUi.row(activity);Button minus=PulseUi.button(activity,"−",false,()->slider.setProgress(Math.max(0,slider.getProgress()-1)));Button plus=PulseUi.button(activity,"+",false,()->slider.setProgress(Math.min(steps,slider.getProgress()+1)));minus.setEnabled(enabled);plus.setEnabled(enabled);LinearLayout.LayoutParams minusLayout=new LinearLayout.LayoutParams(0,-2,1);minusLayout.setMargins(0,0,dp(8),0);stepper.addView(minus,minusLayout);stepper.addView(plus,new LinearLayout.LayoutParams(0,-2,1));body.addView(stepper);PulseUi.gap(body,16);
      Button save=PulseUi.button(activity,"저장",true,()->confirm(row,selected[0],openedVersion));save.setEnabled(enabled);body.addView(save,new LinearLayout.LayoutParams(-1,-2));
    }
    ScrollView scroll=new ScrollView(activity);scroll.addView(body);editor=new AlertDialog.Builder(activity).setTitle(row.optString("title")).setView(scroll).setNegativeButton("닫기",null).create();showEditor();
  }
  private void confirm(JSONObject row,Object value,int openedVersion){
    if(!ready||waiting||uncertain||openedVersion!=version||!row.optBoolean("editable"))return;
    if(editor!=null)editor.dismiss();
    String notice=row.optString("notice");JSONArray notices=row.optJSONArray("notices");
    if(notices!=null&&value instanceof Boolean){JSONArray lines=notices.optJSONArray((Boolean)value?1:0);if(lines!=null){StringBuilder result=new StringBuilder();for(int i=0;i<lines.length();i++){if(i>0)result.append('\n');result.append(lines.optString(i));}notice=result.toString();}}
    String text=valueLabel(row,row.opt("saved"))+" → "+valueLabel(row,value)+(notice.isEmpty()?"":"\n\n"+notice);
    editor=new AlertDialog.Builder(activity).setTitle(row.optString("title")).setMessage(text).setNegativeButton("취소",null).setPositiveButton("저장",(d,w)->{
      if(ready&&!waiting&&!uncertain&&openedVersion==version)actions.save(row,value,catalog.optString("revision"));
    }).create();showEditor();
  }
  private void showEditor(){editor.show();editor.getWindow().setBackgroundDrawable(PulseUi.surface(activity,PulseUi.BG,20));}
}
