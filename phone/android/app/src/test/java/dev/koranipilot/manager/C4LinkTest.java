package dev.koranipilot.manager;

import static org.junit.Assert.*;

import org.junit.Test;

public class C4LinkTest {
  @Test
  public void normalizesManualHostInputs() {
    C4Link.HostPort hp1 = C4Link.normalizeHostInput("192.168.43.10");
    assertNotNull(hp1);
    assertEquals("192.168.43.10", hp1.host);
    assertEquals(7000, hp1.port);

    C4Link.HostPort hp2 = C4Link.normalizeHostInput("http://172.20.10.5:7001/");
    assertNotNull(hp2);
    assertEquals("172.20.10.5", hp2.host);
    assertEquals(7001, hp2.port);
    assertEquals("http://172.20.10.5:7001", hp2.baseUrl());

    assertNull(C4Link.normalizeHostInput("   "));
  }

  @Test
  public void parsesBeaconPayloadAndSenderFallback() {
    C4Link.HostPort fromBody = C4Link.parseBeaconJson(
        "{\"service\":\"koranipilot\",\"ip\":\"192.168.1.44\",\"port\":7000}",
        "192.168.1.99");
    assertNotNull(fromBody);
    assertEquals("192.168.1.44", fromBody.host);
    assertEquals(7000, fromBody.port);

    C4Link.HostPort fallback = C4Link.parseBeaconJson(
        "{\"service\":\"koranipilot\"}",
        "192.168.43.128");
    assertNotNull(fallback);
    assertEquals("192.168.43.128", fallback.host);
    assertEquals(7000, fallback.port);

    assertNull(C4Link.parseBeaconJson("{\"service\":\"other\"}", "192.168.1.1"));
  }

  @Test
  public void parsesDeepLinkConnectUri() {
    C4Link.HostPort dl = C4Link.parseDeepLink("koranipilot://connect?ip=192.168.43.15&port=7000");
    assertNotNull(dl);
    assertEquals("192.168.43.15", dl.host);
    assertEquals(7000, dl.port);

    assertNull(C4Link.parseDeepLink("https://example.com/?ip=1.2.3.4"));
  }
}
