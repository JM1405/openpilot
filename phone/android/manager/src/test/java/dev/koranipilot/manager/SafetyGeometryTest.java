package dev.koranipilot.manager;
import org.junit.Test;
import static org.junit.Assert.*;
import org.json.*;
import com.kakaomobility.knsdk.common.gps.KNKATECKt;
import com.kakaomobility.knsdk.common.util.DoublePoint;

public class SafetyGeometryTest {
  static JSONArray shape()throws Exception{return new JSONArray("[[127,37],[127.000169,37],[127.000338,37]]");}
  @Test public void originalDirectedNeighborsRequired()throws Exception{
    assertTrue(SafetyGeometry.valid(shape()));
    assertFalse(SafetyGeometry.valid(new JSONArray("[[127,37],[127,37],[127,37]]")));
    assertFalse(SafetyGeometry.valid(new JSONArray("[[127,37],[127.000169,37],[127,37]]")));
    assertFalse(SafetyGeometry.valid(new JSONArray("[[37,127],[37,127.000169],[37,127.000338]]")));
    assertFalse(SafetyGeometry.valid(new JSONArray("[[127,37],[127.1,37],[127.2,37]]")));
    assertEquals(JSONObject.NULL,SafetyGeometry.from(null));
  }
  @Test public void officialSdkCoordinateOrderRoundTrip(){
    DoublePoint k=KNKATECKt.WGS84ToKATEC(127.,37.);
    DoublePoint w=KNKATECKt.KATECToWGS84(k.getX(),k.getY());
    assertEquals(127.,w.getX(),.00001);assertEquals(37.,w.getY(),.00001);
  }
  @Test public void capabilityPreservesOldReceiverAndOriginalAge()throws Exception{
    KakaoObservation o=new KakaoObservation();o.start();
    JSONObject e=new JSONObject().put("id","camera-1").put("code","KNSafetyCode_SpeedViolationCamera").put("kind","camera")
      .put("distance_m",JSONObject.NULL).put("distance_basis","unknown").put("limit_kph",60).put("passed",false).put("variable",false).put("geometry",shape());
    o.safety(new JSONArray().put(e),100);
    JSONObject old=o.frame("x",1,100),fresh=o.frame("x",2,200,true);
    assertFalse(old.has("event_geometry_version"));assertFalse(old.getJSONArray("events").getJSONObject(0).has("geometry"));
    assertEquals(1,fresh.getInt("event_geometry_version"));assertTrue(fresh.getJSONArray("events").getJSONObject(0).has("geometry"));
    assertEquals(100,fresh.getLong("safety_age_ms"));assertEquals(0,o.frame("x",3,3100,true).getJSONArray("events").length());
  }
}
