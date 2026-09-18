package dev.koranipilot.manager;
import org.junit.Test;
import org.json.JSONObject;
import java.util.*;
import static org.junit.Assert.*;

public class RouteSnapshotTest {
  private List<Map<String,Number>> points(){return Arrays.asList(Map.<String,Number>of("x",127.,"y",37.),Map.<String,Number>of("x",127.01,"y",37.01));}
  private RouteSnapshot active()throws Exception{RouteSnapshot s=new RouteSnapshot();s.begin("서울역");s.install(points(),1200,200);s.location(true,10000,10000,100,1000,150);return s;}
  @Test public void completionCannotRestartAnAlreadyInstalledTrip()throws Exception{RouteSnapshot s=new RouteSnapshot();long token=s.begin("집");assertTrue(s.planning(token));s.install(points(),100,10);assertFalse(s.planning(token));}
  @Test public void failureInvalidatesLateTripCompletion(){RouteSnapshot s=new RouteSnapshot();long token=s.begin("집");s.fail();assertFalse(s.planning(token));assertFalse(s.current(token));}
  @Test public void longShapeHeartbeatIsSmallAndChunksAreVersionBound()throws Exception{
    RouteSnapshot s=new RouteSnapshot();s.begin("집");s.install(Collections.nCopies(6001,Map.<String,Number>of("x",127.,"y",37.)),10000,1000);
    JSONObject frame=s.statusFrame("nonce",1,0);assertFalse(frame.has("geometry"));assertEquals(6001,frame.getInt("point_count"));assertTrue(frame.toString().length()<1500);
    long version=s.revision();assertEquals(2048,s.chunk("n",1,version,0).getJSONArray("points").length());assertEquals(1905,s.chunk("n",2,version,4096).getJSONArray("points").length());
    s.end();assertNull(s.chunk("n",3,version,2048));
  }
  @Test public void turnOnlyExistsWithFreshMatchedLocation()throws Exception{RouteSnapshot s=active();s.turn("KNRGCode_RightOutHighway",300);assertEquals("오른쪽 진출",s.statusFrame("",0,100).getJSONObject("turn").getString("label"));assertTrue(s.statusFrame("",0,3100).isNull("turn"));s.hold();assertTrue(s.statusFrame("",0,100).isNull("turn"));}
  @Test public void unknownAndPassedTurnAreOmitted()throws Exception{RouteSnapshot s=active();s.turn("KNRGCode_UnexpectedLeft",300);assertTrue(s.statusFrame("",0,100).isNull("turn"));s.turn("KNRGCode_LeftTurn",-1);assertTrue(s.statusFrame("",0,100).isNull("turn"));}
  @Test public void destinationStartsWithoutOldGeometry()throws Exception{RouteSnapshot s=active();s.begin("시청");JSONObject f=s.frame("n",1,101);assertEquals("planning",f.getString("state"));assertEquals(0,f.getJSONArray("geometry").length());assertFalse(f.getBoolean("matched"));assertTrue(f.isNull("total_m"));}
  @Test public void routeContainsExactOriginalGeometry()throws Exception{JSONObject f=active().frame("n",3,100);assertEquals(127.01,f.getJSONArray("geometry").getJSONArray(1).getDouble(0),0);assertEquals(37.01,f.getJSONArray("geometry").getJSONArray(1).getDouble(1),0);assertEquals("full",f.getString("geometry_status"));assertEquals(1000,f.getInt("remaining_m"));}
  @Test public void repeatedLocationDoesNotRenewAge()throws Exception{RouteSnapshot s=active();s.location(true,10000,13000,3100,1000,150);assertFalse(s.frame("n",1,3100).getBoolean("matched"));}
  @Test public void routeSwitchPreservesSampleAge()throws Exception{RouteSnapshot s=active();s.hold();s.install(points(),1200,200);s.location(true,10000,14000,4100,1000,150);assertFalse(s.frame("n",1,4100).getBoolean("matched"));}
  @Test public void callbackCannotRenewInvalidLocation()throws Exception{RouteSnapshot s=active();s.location(false,10001,10001,101,900,140);assertTrue(s.frame("n",1,101).isNull("remaining_m"));}
  @Test public void endInvalidatesAsyncTokenAndClearsDestination()throws Exception{RouteSnapshot s=new RouteSnapshot();long token=s.begin("집");s.end();assertFalse(s.current(token));s.install(points(),10,10);JSONObject f=s.frame("",0,0);assertEquals("ended",f.getString("state"));assertEquals("",f.getString("destination"));assertEquals(0,f.getJSONArray("geometry").length());}
  @Test public void destinationReplacementInvalidatesOldCallback(){RouteSnapshot s=new RouteSnapshot();long old=s.begin("집");long next=s.begin("회사");assertFalse(s.current(old));assertTrue(s.current(next));}
  @Test public void rerouteWithholdsOldShape()throws Exception{RouteSnapshot s=active();long version=s.frame("",0,100).getLong("revision");s.hold();JSONObject f=s.frame("",0,101);assertEquals("rerouting",f.getString("state"));assertTrue(f.getLong("revision")>version);assertEquals(0,f.getJSONArray("geometry").length());assertTrue(f.isNull("remaining_s"));}
  @Test public void failureWithholdsOldShape()throws Exception{RouteSnapshot s=active();s.fail();assertEquals("error",s.frame("",0,100).getString("state"));assertEquals(0,s.frame("",0,100).getJSONArray("geometry").length());}
  @Test public void longRouteIsNotResampled()throws Exception{RouteSnapshot s=new RouteSnapshot();s.begin("부산");s.install(Collections.nCopies(RouteSnapshot.MAX_POINTS+1,Map.<String,Number>of("x",127.,"y",37.)),300000,10000);JSONObject f=s.frame("",0,0);assertEquals("too_large",f.getString("geometry_status"));assertEquals(0,f.getJSONArray("geometry").length());assertEquals(300000,f.getInt("total_m"));}
  @Test public void malformedGeometryIsWithheld()throws Exception{for(List<Map<String,Number>> points:Arrays.asList(Arrays.asList(Map.<String,Number>of("x",127.,"y",37.),Map.<String,Number>of("x",Double.NaN,"y",37.)),Arrays.asList(Map.<String,Number>of("x",127.,"y",37.),Map.<String,Number>of("x",127.)),Collections.nCopies(2,Map.<String,Number>of("x",999,"y",37)))){RouteSnapshot s=new RouteSnapshot();s.begin("집");s.install(points,100,100);assertEquals("unavailable",s.frame("",0,0).getString("geometry_status"));assertEquals(0,s.frame("",0,0).getJSONArray("geometry").length());}}
  @Test public void futureAndBackwardClocksAreWithheld()throws Exception{RouteSnapshot s=active();assertFalse(s.frame("",0,99).getBoolean("matched"));s.location(true,20000,10000,101,900,140);assertFalse(s.frame("",0,101).getBoolean("matched"));}
  @Test public void snapshotCannotBeMutatedExternally()throws Exception{RouteSnapshot s=active();JSONObject f=s.frame("",0,100);f.getJSONArray("geometry").getJSONArray(0).put(0,0);assertEquals(127,s.frame("",0,100).getJSONArray("geometry").getJSONArray(0).getDouble(0),0);}
}
