package dev.koranipilot.manager;

import org.junit.Test;
import static org.junit.Assert.*;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.util.List;

public class ObservationLogTest {
  private File target()throws Exception{return new File(Files.createTempDirectory("observation-test").toFile(),"input.jsonl");}
  @Test public void preservesRawTimesAndClosesWithoutControl()throws Exception{
    File file=target();ObservationLog log=new ObservationLog(file,1_000_000_000L);
    assertTrue(log.append("gps",new JSONObject().put("fix_elapsed_ns",500_000_000L),1_100_000_000L));
    log.stop("user_stop");assertFalse(log.append("gps",new JSONObject(),1_200_000_000L));assertTrue(log.await(2000));
    List<String> rows=Files.readAllLines(file.toPath());assertEquals(3,rows.size());
    assertFalse(new JSONObject(rows.get(0)).getBoolean("control_output"));
    assertEquals(500_000_000L,new JSONObject(rows.get(1)).getJSONObject("data").getLong("fix_elapsed_ns"));
    assertTrue(new JSONObject(rows.get(2)).getBoolean("complete"));assertEquals(1,log.rows());
  }
  @Test public void oldAndDurationLimitDoNotQueue()throws Exception{
    for(long now:new long[]{99,100+ObservationLog.MAX_NS}){
      ObservationLog log=new ObservationLog(target(),100);
      assertFalse(log.append("gps",new JSONObject(),now));assertTrue(log.await(2000));assertEquals(0,log.rows());
    }
  }
  @Test public void oversizedRowIsExplicitIncompleteRecording()throws Exception{
    File file=target();ObservationLog log=new ObservationLog(file,100);
    assertFalse(log.append("sdk_safety",new JSONObject().put("bad","x".repeat(17000)),101));assertTrue(log.await(2000));
    List<String> rows=Files.readAllLines(file.toPath());JSONObject end=new JSONObject(rows.get(rows.size()-1));
    assertFalse(end.getBoolean("complete"));assertEquals(1,end.getLong("dropped"));
  }
  @Test public void neverOverwritesExistingFile()throws Exception{
    File file=target();Files.write(file.toPath(),"original".getBytes(java.nio.charset.StandardCharsets.UTF_8));
    try{new ObservationLog(file,0);fail();}catch(java.io.IOException expected){}
    assertEquals("original",new String(Files.readAllBytes(file.toPath()),java.nio.charset.StandardCharsets.UTF_8));
  }
}
