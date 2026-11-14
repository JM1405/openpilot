package dev.koranipilot.manager;

import com.kakaomobility.knsdk.common.gps.KNKATECKt;
import com.kakaomobility.knsdk.common.util.DoublePoint;
import com.kakaomobility.knsdk.guidance.knguidance.common.KNLocation;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.objects.KNSafety;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.objects.KNSafety_Camera;
import com.kakaomobility.knsdk.guidance.knguidance.safetyguide.objects.KNSafety_Section;
import com.kakaomobility.knsdk.trip.kntrip.knroute.KNRoute;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class SafetyExtractor {
  private static final int MAX_EVENTS = 16;

  private SafetyExtractor() {}

  static String classifyKind(boolean isSection, boolean isCamera, String codeName) {
    if (isSection) return "section";
    if (isCamera) return "camera";
    if ("KNSafetyCode_Hump".equals(codeName)) return "bump";
    if ("KNSafetyCode_SharpTurnSection".equals(codeName)) return "sharp_turn";
    return "other";
  }

  static Double computeBearingDeg(double lat1, double lon1, double lat2, double lon2) {
    double meanLatRad = Math.toRadians((lat1 + lat2) * 0.5);
    double dx = Math.toRadians(lon2 - lon1) * 6371008.8 * Math.cos(meanLatRad);
    double dy = Math.toRadians(lat2 - lat1) * 6371008.8;
    double dist = Math.hypot(dx, dy);
    if (dist < 1.0 || !Double.isFinite(dist)) return null;
    double deg = Math.toDegrees(Math.atan2(dx, dy)) % 360.0;
    if (deg < 0.0) deg += 360.0;
    return Math.round(deg * 10.0) / 10.0;
  }

  static JSONObject buildEventJson(
      String id,
      String kind,
      String code,
      Double lat,
      Double lon,
      Double bearingDeg,
      Double distanceM,
      Integer limitKph,
      boolean passed,
      boolean inSection) throws Exception {
    JSONObject obj = new JSONObject();
    obj.put("id", id);
    obj.put("kind", kind);
    obj.put("code", code);
    obj.put("lat", lat != null && Double.isFinite(lat) ? lat : JSONObject.NULL);
    obj.put("lon", lon != null && Double.isFinite(lon) ? lon : JSONObject.NULL);
    obj.put("bearing_deg", bearingDeg != null && Double.isFinite(bearingDeg) ? bearingDeg : JSONObject.NULL);
    obj.put("distance_m", distanceM != null && Double.isFinite(distanceM) ? distanceM : JSONObject.NULL);
    obj.put("limit_kph", limitKph != null ? limitKph : JSONObject.NULL);
    obj.put("passed", passed);
    obj.put("in_section", inSection);
    return obj;
  }

  static JSONArray extract(
      List<? extends KNSafety> around,
      List<? extends KNSafety> onGuide,
      KNLocation egoMatched,
      KNRoute activeRoute) {
    JSONArray out = new JSONArray();
    HashSet<String> seen = new HashSet<>();
    List<KNSafety> merged = new ArrayList<>();
    if (onGuide != null) merged.addAll(onGuide);
    if (around != null) merged.addAll(around);

    for (KNSafety item : merged) {
      if (item == null || item.getCode() == null) continue;
      String code = item.getCode().name();
      String id = code + ":" + item.getSafetyId();
      if (!seen.add(id)) continue;

      boolean isSection = item instanceof KNSafety_Section;
      boolean isCamera = item instanceof KNSafety_Camera;
      String kind = classifyKind(isSection, isCamera, code);
      boolean passed = item.getPassed();

      Integer limitKph = null;
      if (isCamera) {
        int spd = ((KNSafety_Camera) item).getSpeedLimit();
        if (spd >= 1 && spd <= 160) limitKph = spd;
      }

      Double lat = null;
      Double lon = null;
      Double bearingDeg = null;
      Double distanceM = null;

      KNLocation loc = item.getLocation();
      if (loc != null) {
        double[] ll = katecToWgs84(loc);
        if (ll != null) {
          lat = ll[0];
          lon = ll[1];
        }
        bearingDeg = estimateLocationBearing(loc);
        if (activeRoute != null
            && egoMatched != null
            && egoMatched.getRoute() == activeRoute
            && loc.getRoute() == activeRoute) {
          try {
            distanceM = (double) egoMatched.distToLocation(loc);
          } catch (Exception ignored) {}
        }
      }

      boolean inSection = false;
      if (isSection && !passed) {
        KNSafety_Section sec = (KNSafety_Section) item;
        if (sec.getSectionAvrSpeed() > 0 || (distanceM != null && distanceM <= 0.0)) {
          inSection = true;
        }
      }

      try {
        out.put(buildEventJson(id, kind, code, lat, lon, bearingDeg, distanceM, limitKph, passed, inSection));
      } catch (Exception ignored) {}

      if (out.length() >= MAX_EVENTS) break;
    }
    return out;
  }

  private static double[] katecToWgs84(KNLocation loc) {
    try {
      DoublePoint xy = loc.getPos();
      if (xy == null || !KNKATECKt.IsValidKATEC(xy)) return null;
      DoublePoint wgs = KNKATECKt.KATECToWGS84(xy.getX(), xy.getY());
      if (wgs == null) return null;
      double lon = wgs.getX();
      double lat = wgs.getY();
      if (!Double.isFinite(lat) || !Double.isFinite(lon)) return null;
      if (lat < 32.5 || lat > 39.5 || lon < 124.0 || lon > 132.0) return null;
      return new double[] {lat, lon};
    } catch (Exception ignored) {
      return null;
    }
  }

  private static Double estimateLocationBearing(KNLocation loc) {
    try {
      KNLocation before = loc.locationAfterDist(-8);
      KNLocation after = loc.locationAfterDist(8);
      if (before == null || after == null) return null;
      double[] a = katecToWgs84(before);
      double[] b = katecToWgs84(after);
      if (a == null || b == null) return null;
      return computeBearingDeg(a[0], a[1], b[0], b[1]);
    } catch (Exception ignored) {
      return null;
    }
  }
}
