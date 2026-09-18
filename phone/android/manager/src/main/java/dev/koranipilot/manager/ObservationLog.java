package dev.koranipilot.manager;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Bounded local diagnostic sink. No network, authentication, or control APIs. */
final class ObservationLog {
  static final long MAX_BYTES=32L*1024*1024, MAX_NS=2L*60*60*1_000_000_000;
  private final ArrayBlockingQueue<String> queue=new ArrayBlockingQueue<>(128);
  private final File file;
  private final long startNs;
  private final Thread worker;
  private volatile boolean accepting=true,finished;
  private volatile String reason="recording";
  private long sequence,dropped,lastSeenNs,endedNs;
  private volatile long written;

  ObservationLog(File file,long now)throws IOException{
    this.file=file;startNs=now;lastSeenNs=endedNs=now;
    if(!file.createNewFile())throw new IOException("Existing recording");
    worker=new Thread(this::writeLoop,"input-observation");worker.start();
  }
  boolean active(){return accepting;}
  boolean finished(){return finished;}
  long rows(){return written;}
  String reason(){return reason;}
  File file(){return file;}
  synchronized boolean append(String type,JSONObject data,long now){
    if(!accepting)return false;
    if(now<startNs||now-startNs>=MAX_NS){stop("duration_limit",now);return false;}
    lastSeenNs=Math.max(lastSeenNs,now);
    if(!type.equals("gps")&&!type.equals("sdk_location")&&!type.equals("sdk_safety")&&!type.equals("receipt"))throw new IllegalArgumentException("Unknown row");
    try{
      String row=new JSONObject().put("schema",1).put("type",type).put("sequence",++sequence)
        .put("elapsed_ns",now).put("data",data).toString();
      if(row.length()>16384||!queue.offer(row)){dropped++;stop("queue_limit");return false;}
      return true;
    }catch(Exception failure){stop("encode_error");return false;}
  }
  synchronized void stop(String why){stop(why,lastSeenNs);}
  synchronized void stop(String why,long now){if(accepting){reason=why;endedNs=Math.max(lastSeenNs,now);accepting=false;}}
  boolean await(long millis)throws InterruptedException{worker.join(millis);return finished;}
  private void writeLoop(){
    try(BufferedWriter out=new BufferedWriter(new OutputStreamWriter(new FileOutputStream(file),StandardCharsets.UTF_8))){
      String header=new JSONObject().put("schema",1).put("type","start").put("session",UUID.randomUUID().toString())
        .put("elapsed_ns",startNs).put("control_output",false).put("scope","phone_local_observation").toString();
      out.write(header);out.newLine();out.flush();long bytes=header.getBytes(StandardCharsets.UTF_8).length+1;
      while(accepting||!queue.isEmpty()){
        String row=queue.poll(200,TimeUnit.MILLISECONDS);if(row==null)continue;
        int size=row.getBytes(StandardCharsets.UTF_8).length+1;
        if(bytes+size>MAX_BYTES){stop("size_limit");synchronized(this){dropped+=queue.size()+1;queue.clear();}break;}
        out.write(row);out.newLine();out.flush();bytes+=size;written++;
      }
      out.write(new JSONObject().put("schema",1).put("type","end").put("rows",written)
        .put("reason",reason).put("elapsed_ns",endedNs).put("dropped",dropped).put("complete",dropped==0&&!reason.equals("encode_error")).toString());out.newLine();
    }catch(Exception error){accepting=false;reason="storage_error";}
    finally{finished=true;}
  }
}
