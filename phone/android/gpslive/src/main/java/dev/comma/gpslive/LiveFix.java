package dev.comma.gpslive;

/** Immutable callback copy, with original boot-relative fix and receive clocks. */
public final class LiveFix {
  public final long fixNs, receivedNs;
  private final double lon, lat;
  private final Double speed, bearing, accuracy, bearingAccuracy;
  private final boolean mock, gps;

  public LiveFix(long fixNs, long receivedNs, double lon, double lat, Double speed, Double bearing,
      Double accuracy, Double bearingAccuracy, boolean mock, boolean gps) {
    this.fixNs=fixNs; this.receivedNs=receivedNs; this.lon=lon; this.lat=lat; this.speed=speed;
    this.bearing=bearing; this.accuracy=accuracy; this.bearingAccuracy=bearingAccuracy; this.mock=mock; this.gps=gps;
  }

  public String encode(String stream, String sync, long sequence, long sent) {
    if (!stream.matches("[a-f0-9-]{36}") || !sync.matches("[a-f0-9]{48}")) throw new IllegalArgumentException("Invalid session");
    return "{\"schema\":1,\"stream\":\""+stream+"\",\"sync_id\":\""+sync+"\",\"sequence\":"+sequence
        +",\"fix_elapsed_ns\":"+fixNs+",\"received_elapsed_ns\":"+receivedNs+",\"sent_elapsed_ns\":"+sent
        +",\"longitude\":"+number(lon)+",\"latitude\":"+number(lat)+",\"speed_mps\":"+number(speed)
        +",\"bearing_deg\":"+number(bearing)+",\"accuracy_m\":"+number(accuracy)+",\"bearing_accuracy_deg\":"+number(bearingAccuracy)
        +",\"mock\":"+mock+",\"provider\":\""+(gps?"gps":"other")+"\"}";
  }

  private static String number(Double value) { return value==null || !Double.isFinite(value)?"null":Double.toString(value); }
}
