package dev.koranipilot.manager;

import static org.junit.Assert.*;

import org.json.JSONObject;
import org.junit.Test;

public class SafetyExtractorTest {
  @Test
  public void classifiesBumpAndSharpTurnAndCameraAndSection() {
    assertEquals("bump", SafetyExtractor.classifyKind(false, false, "KNSafetyCode_Hump"));
    assertEquals("sharp_turn", SafetyExtractor.classifyKind(false, false, "KNSafetyCode_SharpTurnSection"));
    assertEquals("camera", SafetyExtractor.classifyKind(false, true, "KNSafetyCode_SpeedViolationCamera"));
    assertEquals("section", SafetyExtractor.classifyKind(true, true, "KNSafetyCode_SpeedViolationSection"));
    assertEquals("other", SafetyExtractor.classifyKind(false, false, "KNSafetyCode_FogArea"));
  }

  @Test
  public void preservesCoordinatesWhenBearingAndDistanceAreNull() throws Exception {
    JSONObject ev = SafetyExtractor.buildEventJson(
        "KNSafetyCode_Hump:42",
        "bump",
        "KNSafetyCode_Hump",
        37.501234,
        127.039876,
        null,
        null,
        null,
        false,
        false);
    assertEquals("bump", ev.getString("kind"));
    assertEquals(37.501234, ev.getDouble("lat"), 1e-6);
    assertEquals(127.039876, ev.getDouble("lon"), 1e-6);
    assertTrue(ev.isNull("bearing_deg"));
    assertTrue(ev.isNull("distance_m"));
    assertFalse(ev.getBoolean("passed"));
  }

  @Test
  public void computesCardinalBearingsAccurately() {
    Double north = SafetyExtractor.computeBearingDeg(37.5000, 127.0000, 37.5005, 127.0000);
    assertNotNull(north);
    assertTrue(north < 1.0 || north > 359.0);

    Double east = SafetyExtractor.computeBearingDeg(37.5000, 127.0000, 37.5000, 127.0005);
    assertNotNull(east);
    assertEquals(90.0, east, 1.0);

    Double south = SafetyExtractor.computeBearingDeg(37.5005, 127.0000, 37.5000, 127.0000);
    assertNotNull(south);
    assertEquals(180.0, south, 1.0);
  }

  @Test
  public void viewBindingRuntimeIsPresentForKnNaviView() throws Exception {
    assertTrue(Class.forName("androidx.viewbinding.ViewBinding").isInterface());
    Class.forName("androidx.viewbinding.ViewBindings");
  }
}
