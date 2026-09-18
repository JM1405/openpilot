package dev.koranipilot.manager;

import android.app.Activity;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Native presentation for the selected Pulse concept; contains no device actions. */
final class PulseUi {
  static final int BG=0xff1c2320, SURFACE=0xff29332a, LINE=0xff3c493d;
  static final int TEXT=0xfff0f1e8, MUTED=0xffa4b39e, LIME=0xffd4ed86, INK=0xff243222;
  private PulseUi(){}
  static int dp(Context c,float value){return Math.round(value*c.getResources().getDisplayMetrics().density);}
  static LinearLayout column(Context c){LinearLayout v=new LinearLayout(c);v.setOrientation(LinearLayout.VERTICAL);return v;}
  static LinearLayout row(Context c){LinearLayout v=new LinearLayout(c);v.setGravity(Gravity.CENTER_VERTICAL);return v;}
  static GradientDrawable surface(Context c,int color,int radius){
    GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(c,radius));return d;
  }
  static TextView text(Context c,String value,int size,int color){
    TextView v=new TextView(c);v.setText(value);v.setTextSize(size);v.setTextColor(color);
    v.setFontFeatureSettings("kern");v.setIncludeFontPadding(false);return v;
  }
  static TextView label(LinearLayout parent,String value,int size,int color){
    TextView v=text(parent.getContext(),value,size,color);parent.addView(v);return v;
  }
  static void gap(LinearLayout parent,int height){parent.addView(new View(parent.getContext()),new LinearLayout.LayoutParams(1,dp(parent.getContext(),height)));}
  static void line(LinearLayout parent){View v=new View(parent.getContext());v.setBackgroundColor(LINE);parent.addView(v,new LinearLayout.LayoutParams(-1,dp(parent.getContext(),1)));}
  static Button button(Context c,String value,boolean primary,Runnable action){
    Button b=new Button(c);b.setText(value);b.setAllCaps(false);b.setTextSize(16);
    b.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
    b.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{MUTED,primary?INK:TEXT}));
    b.setBackgroundTintList(null);b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x304b6545),surface(c,primary?LIME:SURFACE,12),null));
    b.setMinHeight(dp(c,54));b.setMinimumHeight(dp(c,54));b.setPadding(dp(c,16),dp(c,10),dp(c,16),dp(c,10));
    b.setOnClickListener(v->action.run());return b;
  }
  static void action(LinearLayout parent,String value,boolean primary,Runnable action){
    Button b=button(parent.getContext(),value,primary,action);
    parent.addView(b,new LinearLayout.LayoutParams(-1,-2));
  }
  static EditText input(Context c,String hint,boolean secret){
    EditText v=new EditText(c);v.setHint(hint);v.setTextSize(15);v.setTextColor(TEXT);v.setHintTextColor(MUTED);
    v.setSingleLine(true);v.setSaveEnabled(false);v.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
    v.setInputType(secret?129:android.text.InputType.TYPE_CLASS_TEXT);
    v.setBackground(surface(c,BG,10));v.setPadding(dp(c,14),dp(c,14),dp(c,14),dp(c,14));
    return v;
  }
  static LinearLayout card(Context c){
    LinearLayout v=column(c);v.setPadding(dp(c,20),dp(c,20),dp(c,20),dp(c,20));v.setBackground(surface(c,SURFACE,14));return v;
  }
  static void menu(LinearLayout parent,String title,String value,Runnable action){
    Context c=parent.getContext();LinearLayout row=row(c);row.setPadding(0,dp(c,18),0,dp(c,18));row.setMinimumHeight(dp(c,62));
    TextView name=text(c,title,16,TEXT);row.addView(name,new LinearLayout.LayoutParams(0,-2,1));
    TextView detail=text(c,value+"  ›",13,MUTED);detail.setGravity(Gravity.END);detail.setMaxWidth(dp(c,190));row.addView(detail);
    row.setBackground(new RippleDrawable(ColorStateList.valueOf(0x304b6545),null,null));row.setOnClickListener(v->action.run());row.setFocusable(true);
    parent.addView(row,new LinearLayout.LayoutParams(-1,-2));line(parent);
  }
  static LinearLayout navigation(Context c,String selected,Runnable home,Runnable map,Runnable device){
    LinearLayout nav=row(c);nav.setPadding(0,dp(c,8),0,dp(c,8));
    String[] names={"홈","지도","기기"};String[] ids={"home","map","device"};Runnable[] actions={home,map,device};
    for(int i=0;i<3;i++){
      final Runnable action=actions[i];boolean active=ids[i].equals(selected);LinearLayout item=column(c);item.setGravity(Gravity.CENTER);item.setPadding(0,dp(c,8),0,dp(c,5));
      item.addView(new NavIcon(c,ids[i],active?LIME:MUTED),new LinearLayout.LayoutParams(dp(c,21),dp(c,21)));
      gap(item,6);label(item,names[i],11,active?LIME:MUTED).setGravity(Gravity.CENTER);item.setContentDescription(names[i]);item.setFocusable(true);item.setOnClickListener(v->action.run());
      nav.addView(item,new LinearLayout.LayoutParams(0,-2,1));
    }return nav;
  }
  static void window(Activity activity,View shell){
    activity.getWindow().setStatusBarColor(BG);activity.getWindow().setNavigationBarColor(BG);
    if(android.os.Build.VERSION.SDK_INT>=30){
      activity.getWindow().setDecorFitsSystemWindows(false);
      android.view.WindowInsetsController controller=activity.getWindow().getInsetsController();
      if(controller!=null)controller.setSystemBarsAppearance(0,android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
      shell.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets safe=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.ime());v.setPadding(safe.left,safe.top,safe.right,safe.bottom);return insets;});
      shell.requestApplyInsets();
    }
  }
  static final class SignalRing extends View {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);private final RectF arc=new RectF(35,35,225,225);private final boolean connected;private final String caption;
    SignalRing(Context c,boolean connected,String caption){super(c);this.connected=connected;this.caption=caption;setContentDescription("C4 · "+caption);}
    @Override protected void onDraw(Canvas c){
      super.onDraw(c);float size=Math.min(getWidth(),getHeight());c.save();c.translate((getWidth()-size)/2,(getHeight()-size)/2);c.scale(size/260,size/260);
      p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1);p.setColor(LINE);c.drawCircle(130,130,106,p);
      for(int i=0;i<60;i++){c.save();c.rotate(i*6,130,130);p.setColor(i<42&&connected?LIME:LINE);p.setStrokeWidth(i%5==0?2:1);c.drawLine(130,12,130,i%5==0?22:17,p);c.restore();}
      p.setStrokeWidth(3);p.setStrokeCap(Paint.Cap.ROUND);p.setColor(connected?LIME:0xff6d8063);c.drawArc(arc,-90,connected?260:45,false,p);
      p.setStrokeCap(Paint.Cap.BUTT);p.setStyle(Paint.Style.FILL);p.setColor(connected?0xffe1edcd:TEXT);p.setTextAlign(Paint.Align.CENTER);p.setTypeface(Typeface.create("sans-serif-light",Typeface.NORMAL));p.setTextSize(65);c.drawText("C4",130,141,p);
      p.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));p.setTextSize(12);p.setColor(MUTED);c.drawText(caption,130,170,p);c.restore();
    }
  }
  private static final class NavIcon extends View {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);private final String kind;
    NavIcon(Context c,String kind,int color){super(c);this.kind=kind;p.setColor(color);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1.6f);p.setStrokeJoin(Paint.Join.ROUND);p.setStrokeCap(Paint.Cap.ROUND);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
    @Override protected void onDraw(Canvas c){c.save();c.scale(getWidth()/24f,getHeight()/24f);android.graphics.Path path=new android.graphics.Path();
      if(kind.equals("home")){path.moveTo(3,10);path.lineTo(12,3);path.lineTo(21,10);path.lineTo(21,21);path.lineTo(3,21);path.close();c.drawPath(path,p);c.drawRect(9,14,15,21,p);}
      else if(kind.equals("map")){path.moveTo(3,5);path.lineTo(9,3);path.lineTo(15,6);path.lineTo(21,4);path.lineTo(21,19);path.lineTo(15,21);path.lineTo(9,18);path.lineTo(3,20);path.close();c.drawPath(path,p);c.drawLine(9,3,9,18,p);c.drawLine(15,6,15,21,p);}
      else {c.drawRoundRect(3,5,21,19,4,4,p);path.moveTo(8,14);path.lineTo(12,9);path.lineTo(16,14);c.drawPath(path,p);}
      c.restore();}
  }
}
