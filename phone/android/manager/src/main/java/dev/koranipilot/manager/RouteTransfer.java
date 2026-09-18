package dev.koranipilot.manager;
import dev.comma.companion.PhoneClient;
import org.json.JSONObject;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;

/** At most one bounded chunk per polling turn; raw GPS work can run between turns. */
final class RouteTransfer {
  static JSONObject send(PhoneClient client,RouteSnapshot state,LongSupplier clock,BooleanSupplier current)throws Exception{
    if(!current.getAsBoolean())return null;
    String nonce=client.call("route",null).getString("challenge");
    if(!current.getAsBoolean())return null;
    long seq=client.navigationSequence.incrementAndGet();
    JSONObject body=state.statusFrame(nonce,seq,clock.getAsLong());long revision=body.getLong("revision");
    JSONObject receipt=client.call("route",body);check(receipt,seq,revision);
    JSONObject upload=receipt.getJSONObject("upload");
    if(!body.getString("shape_id").isEmpty()&&!upload.getBoolean("complete")){
      if(!current.getAsBoolean()||revision!=state.revision())return null;
      nonce=client.call("route",null).getString("challenge");
      if(!current.getAsBoolean())return null;
      seq=client.navigationSequence.incrementAndGet();
      JSONObject chunk=state.chunk(nonce,seq,revision,upload.getInt("next_offset"));
      if(chunk==null)return null;
      JSONObject ack=client.call("route/chunk",chunk);check(ack,seq,revision);
      receipt.put("upload",ack.getJSONObject("upload"));
    }
    return current.getAsBoolean()&&revision==state.revision()?receipt:null;
  }
  private static void check(JSONObject receipt,long seq,long revision)throws Exception{
    if(receipt.getLong("seq")!=seq||receipt.getLong("revision")!=revision||!"route_observation".equals(receipt.getString("scope"))||receipt.getBoolean("control_enabled"))throw new IllegalStateException("경로 수신 응답을 확인해");
  }
}
