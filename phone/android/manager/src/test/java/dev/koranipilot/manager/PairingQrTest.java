package dev.koranipilot.manager;
import org.junit.Test;
import static org.junit.Assert.*;
public class PairingQrTest {
  private final String pin="AB".repeat(32);
  private String qr(String host,String port){return "KORANI1:"+host+":"+port+":"+pin+":012345";}
  @Test public void preservesFullPinAndLeadingZeroCode(){PairingQr p=PairingQr.parse(qr("10.209.29.93","7443"));assertEquals("https://10.209.29.93:7443",p.url);assertEquals(pin,p.pin);assertEquals("012345",p.code);}
  @Test public void acceptsRfc1918Only(){for(String ip:new String[]{"10.0.0.1","172.16.0.1","172.31.255.254","192.168.1.2"})assertNotNull(PairingQr.parse(qr(ip,"443")));}
  @Test public void rejectsExternalOrAmbiguousHosts(){for(String ip:new String[]{"8.8.8.8","127.0.0.1","169.254.1.1","172.15.0.1","172.32.0.1","localhost","10.01.2.3","10.0.0.999","10.0.0.1@example.com","10.0.0.1/path","10.0.0.1?x=1"})bad(qr(ip,"7443"));}
  @Test public void rejectsMalformedOrVersionedData(){bad(null);bad("");bad(qr("10.0.0.1","7443")+":extra");bad(qr("10.0.0.1","7443").replace("KORANI1","KORANI2"));bad(qr("10.0.0.1","7443").replace(pin,"AB"));bad(qr("10.0.0.1","7443").replace("012345","12345x"));bad(" "+qr("10.0.0.1","7443"));bad(qr("10.0.0.1","7443")+"\n");bad("A".repeat(161));}
  @Test public void rejectsInvalidPort(){for(String p:new String[]{"0","-1","65536","999999999","07443","443/path"})bad(qr("10.0.0.1",p));}
  private void bad(String value){try{PairingQr.parse(value);fail("accepted invalid QR");}catch(IllegalArgumentException expected){}}
}
