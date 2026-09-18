package dev.koranipilot.manager;

import com.kakaomobility.knsdk.common.gps.KNKATECKt;
import com.kakaomobility.knsdk.common.util.DoublePoint;
import com.kakaomobility.knsdk.guidance.knguidance.common.KNLocation;
import org.json.JSONArray;
import org.json.JSONObject;

/** Original SDK locations only. Missing directed neighbors never become a heading. */
final class SafetyGeometry {
  private SafetyGeometry(){}
  static Object from(KNLocation location){
    if(location==null)return JSONObject.NULL;
    try{
      KNLocation before=location.locationAfterDist(-15),after=location.locationAfterDist(15);
      if(before==null||after==null)return JSONObject.NULL;
      JSONArray result=new JSONArray();
      for(KNLocation item:new KNLocation[]{before,location,after}){
        DoublePoint xy=item.getPos();if(xy==null||!KNKATECKt.IsValidKATEC(xy))return JSONObject.NULL;
        DoublePoint wgs=KNKATECKt.KATECToWGS84(xy.getX(),xy.getY());
        result.put(new JSONArray().put(wgs.getX()).put(wgs.getY()));
      }
      return valid(result)?result:JSONObject.NULL;
    }catch(Exception failure){return JSONObject.NULL;}
  }
  static boolean valid(JSONArray points){
    try{
      if(points.length()!=3)return false;
      for(int i=0;i<3;i++){
        JSONArray p=points.getJSONArray(i);double x=p.getDouble(0),y=p.getDouble(1);
        if(p.length()!=2||!Double.isFinite(x)||!Double.isFinite(y)||x<124||x>132||y<33||y>39.5)return false;
      }
      double[] first=vector(points.getJSONArray(0),points.getJSONArray(1)),last=vector(points.getJSONArray(1),points.getJSONArray(2));
      double a=Math.hypot(first[0],first[1]),b=Math.hypot(last[0],last[1]);
      return a>=8&&a<=25&&b>=8&&b<=25&&(first[0]*last[0]+first[1]*last[1])/(a*b)>=Math.cos(Math.toRadians(25));
    }catch(Exception error){return false;}
  }
  private static double[] vector(JSONArray a,JSONArray b)throws Exception{
    return new double[]{Math.toRadians(b.getDouble(0)-a.getDouble(0))*6371008.8*Math.cos(Math.toRadians(a.getDouble(1))),Math.toRadians(b.getDouble(1)-a.getDouble(1))*6371008.8};
  }
}
