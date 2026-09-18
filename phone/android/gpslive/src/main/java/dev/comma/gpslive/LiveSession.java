package dev.comma.gpslive;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.LongSupplier;

/** One serial network worker and one latest-only mailbox. No GPS replay queue. */
public final class LiveSession {
  public interface Wire { Reply post(String path, String json) throws Exception; }
  public static final class AuthorizationRequired extends Exception {}
  public static final class Reply {
    public final String status, sync;
    public Reply(String status, String sync) { this.status=status; this.sync=sync; }
  }
  private final Wire wire;
  private final LongSupplier clock;
  private final String stream=UUID.randomUUID().toString();
  private final AtomicReference<LiveFix> latest=new AtomicReference<>();
  private volatile boolean stopped=false;
  private volatile String status="시각 동기화 대기";
  private String sync="";
  private long syncSequence=0, sequence=0, renewAt=0, retryAt=0, minimumFix=0;
  private long retryDelay=1_000_000_000L;

  public LiveSession(Wire wire, LongSupplier clock) { this.wire=wire; this.clock=clock; }
  public String status() { return status; }
  public void offer(LiveFix fix) { if (!stopped) latest.set(fix); }
  public void stop() { stopped=true; latest.set(null); status="전송 중지"; }

  public void tick() {
    if (stopped || clock.getAsLong()<retryAt) return;
    try {
      long now=clock.getAsLong();
      if (sync.isEmpty() || now>=renewAt) {
        boolean reconnect=sync.isEmpty();
        sync="";
        long sent=clock.getAsLong();
        Reply probe=wire.post("road/sync", "{\"schema\":1,\"stream\":\""+stream
            +"\",\"sync_sequence\":"+(++syncSequence)+",\"phone_send_ns\":"+sent+"}");
        long received=clock.getAsLong();
        if (stopped) return;
        if (received<sent || received-sent>100_000_000L || !probe.sync.matches("[a-f0-9]{48}"))
          throw new IllegalStateException("시각 오차가 커");
        Reply committed=wire.post("road/commit", "{\"schema\":1,\"sync_id\":\""+probe.sync
            +"\",\"phone_receive_ns\":"+received+"}");
        if (!committed.status.equals("synchronized") || !committed.sync.equals(probe.sync))
          throw new IllegalStateException("시각 확인 실패");
        sync=probe.sync;
        // Periodic renewal must not drop a still-fresh 1Hz callback. After a
        // failure/reconnect require a new fix; the receiver checks clock epochs.
        if (reconnect) minimumFix=received;
        renewAt=sent+3_000_000_000L;
        status="연결됨 · 새 GPS 위치 대기";
        return;
      }
      LiveFix fix=latest.getAndSet(null);
      if (fix==null || stopped) return;
      long sent=clock.getAsLong();
      if (fix.fixNs<minimumFix || fix.fixNs>fix.receivedNs || fix.receivedNs>sent || sent-fix.fixNs>200_000_000L) {
        status="오래된 위치 보류 · 새 GPS 대기"; return;
      }
      Reply answer=wire.post("road/fix",fix.encode(stream,sync,++sequence,sent));
      if (!answer.status.equals("liveFix")) throw new IllegalStateException("위치 수신 미확인");
      retryDelay=1_000_000_000L;
      if (!stopped) status="실시간 위치 전송 중";
    } catch (AuthorizationRequired error) {
      sync=""; latest.set(null); stopped=true;
      status="폰 승인이 만료됐어 · 연결 해제 후 다시 연결해";
    } catch (Exception error) {
      sync=""; latest.set(null);
      retryAt=clock.getAsLong()+retryDelay; retryDelay=Math.min(4_000_000_000L,retryDelay*2);
      if (!stopped) status="입력 보류 · 연결과 시각 다시 확인 중";
    }
  }

  /** Run on the same serial worker after stop(); silence still expires on receiver. */
  public void finish() {
    if (!stopped) throw new IllegalStateException("Stop before finish");
    try { if (!sync.isEmpty()) wire.post("road/stop", "{\"schema\":1,\"sync_id\":\""+sync+"\"}"); }
    catch (Exception ignored) { /* Receiver TTL covers an unreachable stop packet. */ }
    sync="";
  }
}
