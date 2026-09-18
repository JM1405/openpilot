package dev.koranipilot.manager;

/** Strict, offline parser. Scanning never connects or approves a device. */
public final class PairingQr {
  public final String url, pin, code;
  private PairingQr(String url, String pin, String code) {
    this.url=url; this.pin=pin; this.code=code;
  }
  public static PairingQr parse(String value) {
    if(value==null || value.length()>160) throw new IllegalArgumentException("C4의 고라니 연결 QR을 스캔해줘");
    String[] parts=value.split(":",-1);
    if(parts.length!=5 || !parts[0].equals("KORANI1") ||
       !parts[2].matches("[1-9][0-9]{0,4}") || !parts[3].matches("[A-F0-9]{64}") ||
       !parts[4].matches("[0-9]{6}")) throw new IllegalArgumentException("고라니 연결 QR 형식이 아니야");
    String[] octets=parts[1].split("\\.",-1);
    if(octets.length!=4) throw new IllegalArgumentException("C4 주소 형식이 달라");
    int[] ip=new int[4];
    for(int i=0;i<4;i++) {
      if(!octets[i].matches("0|[1-9][0-9]{0,2}")) throw new IllegalArgumentException("C4 주소 형식이 달라");
      ip[i]=Integer.parseInt(octets[i]);
      if(ip[i]>255) throw new IllegalArgumentException("C4 주소 형식이 달라");
    }
    if(!(ip[0]==10 || (ip[0]==172 && ip[1]>=16 && ip[1]<=31) || (ip[0]==192 && ip[1]==168)))
      throw new IllegalArgumentException("같은 Wi-Fi의 C4 주소만 연결할 수 있어");
    int port=Integer.parseInt(parts[2]);
    if(port>65535) throw new IllegalArgumentException("C4 연결 주소를 확인해줘");
    return new PairingQr("https://"+parts[1]+":"+port,parts[3],parts[4]);
  }
}
