package dev.koranipilot.manager;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.DhcpInfo;
import android.net.wifi.WifiManager;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URI;
import java.net.URL;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

final class C4Link {
  static final int DEFAULT_PORT = 7000;
  static final int BEACON_PORT = 7705;
  private static final String PREF_NAME = "korani_prefs";
  private static final String KEY_MANUAL_HOST = "manual_ip";
  private static final String KEY_MANUAL_PORT = "manual_port";
  private static final String KEY_LAST_HOST = "last_ip";
  private static final String KEY_LAST_PORT = "last_port";

  static final class HostPort {
    final String host;
    final int port;

    HostPort(String host, int port) {
      this.host = host;
      this.port = port;
    }

    String baseUrl() {
      return buildBaseUrl(host, port);
    }
  }

  private final Context appContext;
  private final SharedPreferences prefs;
  private volatile HostPort activeTarget;
  private volatile boolean running;
  private Thread beaconThread;
  private DatagramSocket udpSocket;
  private WifiManager.MulticastLock multicastLock;
  private volatile long lastScanMs = 0L;
  private int consecutiveFailures = 0;

  C4Link(Context context) {
    this.appContext = context.getApplicationContext();
    this.prefs = appContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
    String manualIp = prefs.getString(KEY_MANUAL_HOST, null);
    int manualPort = prefs.getInt(KEY_MANUAL_PORT, DEFAULT_PORT);
    if (manualIp != null && !manualIp.isEmpty()) {
      this.activeTarget = new HostPort(manualIp, manualPort);
    } else {
      String lastIp = prefs.getString(KEY_LAST_HOST, null);
      int lastPort = prefs.getInt(KEY_LAST_PORT, DEFAULT_PORT);
      if (lastIp != null && !lastIp.isEmpty()) {
        this.activeTarget = new HostPort(lastIp, lastPort);
      }
    }
  }

  static String buildBaseUrl(String host, int port) {
    return "http://" + host + ":" + port;
  }

  static HostPort normalizeHostInput(String raw) {
    if (raw == null) return null;
    String s = raw.trim();
    if (s.isEmpty()) return null;
    if (!s.contains("://")) {
      s = "http://" + s;
    }
    try {
      URI uri = URI.create(s);
      String host = uri.getHost();
      if (host == null || host.trim().isEmpty()) return null;
      int port = uri.getPort();
      if (port <= 0 || port > 65535) port = DEFAULT_PORT;
      return new HostPort(host.trim(), port);
    } catch (Exception ignored) {
      return null;
    }
  }

  static HostPort parseDeepLink(String rawUri) {
    if (rawUri == null || rawUri.trim().isEmpty()) return null;
    try {
      URI uri = URI.create(rawUri.trim());
      if (!"koranipilot".equalsIgnoreCase(uri.getScheme())) return null;
      String query = uri.getRawQuery();
      if (query == null) return null;
      String ip = null;
      int port = DEFAULT_PORT;
      for (String pair : query.split("&")) {
        int eq = pair.indexOf('=');
        if (eq <= 0) continue;
        String k = URLDecoder.decode(pair.substring(0, eq), "UTF-8");
        String v = URLDecoder.decode(pair.substring(eq + 1), "UTF-8");
        if ("ip".equals(k)) ip = v.trim();
        else if ("port".equals(k)) {
          try {
            int p = Integer.parseInt(v.trim());
            if (p > 0 && p <= 65535) port = p;
          } catch (NumberFormatException ignored) {}
        }
      }
      return (ip == null || ip.isEmpty()) ? null : new HostPort(ip, port);
    } catch (Exception ignored) {
      return null;
    }
  }

  static HostPort parseBeaconJson(String rawJson, String senderIp) {
    if (rawJson == null || rawJson.trim().isEmpty()) return null;
    try {
      JSONObject obj = new JSONObject(rawJson);
      if (!"koranipilot".equals(obj.optString("service"))) return null;
      String ip = obj.optString("ip", "").trim();
      if (ip.isEmpty() && senderIp != null) ip = senderIp.trim();
      if (ip.isEmpty()) return null;
      int port = obj.optInt("port", DEFAULT_PORT);
      if (port <= 0 || port > 65535) port = DEFAULT_PORT;
      return new HostPort(ip, port);
    } catch (Exception ignored) {
      return null;
    }
  }

  synchronized void start() {
    if (running) return;
    running = true;
    beaconThread = new Thread(this::listenBeaconLoop, "korani-udp-discovery");
    beaconThread.start();
  }

  synchronized void stop() {
    running = false;
    DatagramSocket sock = udpSocket;
    udpSocket = null;
    if (sock != null) {
      try { sock.close(); } catch (Exception ignored) {}
    }
    WifiManager.MulticastLock lock = multicastLock;
    multicastLock = null;
    if (lock != null) {
      try { if (lock.isHeld()) lock.release(); } catch (Exception ignored) {}
    }
  }

  void setManualTarget(HostPort hp) {
    if (hp == null) return;
    prefs.edit()
        .putString(KEY_MANUAL_HOST, hp.host)
        .putInt(KEY_MANUAL_PORT, hp.port)
        .putString(KEY_LAST_HOST, hp.host)
        .putInt(KEY_LAST_PORT, hp.port)
        .apply();
    activeTarget = hp;
    consecutiveFailures = 0;
  }

  void clearManualTarget() {
    prefs.edit().remove(KEY_MANUAL_HOST).remove(KEY_MANUAL_PORT).apply();
  }

  HostPort currentTarget() {
    return activeTarget;
  }

  String currentWebUrl() {
    HostPort hp = activeTarget;
    return hp == null ? null : hp.baseUrl();
  }

  private void recordDiscovered(HostPort hp) {
    activeTarget = hp;
    consecutiveFailures = 0;
    prefs.edit().putString(KEY_LAST_HOST, hp.host).putInt(KEY_LAST_PORT, hp.port).apply();
  }

  private void listenBeaconLoop() {
    try {
      WifiManager wm = (WifiManager) appContext.getSystemService(Context.WIFI_SERVICE);
      if (wm != null) {
        multicastLock = wm.createMulticastLock("koranipilot-beacon");
        multicastLock.setReferenceCounted(false);
        multicastLock.acquire();
      }
    } catch (Exception ignored) {}

    byte[] buf = new byte[1024];
    try {
      DatagramSocket sock = new DatagramSocket(null);
      sock.setReuseAddress(true);
      sock.bind(new InetSocketAddress(BEACON_PORT));
      sock.setSoTimeout(2000);
      udpSocket = sock;

      while (running) {
        try {
          DatagramPacket packet = new DatagramPacket(buf, buf.length);
          sock.receive(packet);
          String body = new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8);
          String senderIp = packet.getAddress() != null ? packet.getAddress().getHostAddress() : null;
          HostPort discovered = parseBeaconJson(body, senderIp);
          if (discovered != null) {
            recordDiscovered(discovered);
          }
        } catch (Exception ignored) {}
      }
    } catch (Exception ignored) {
    } finally {
      DatagramSocket sock = udpSocket;
      udpSocket = null;
      if (sock != null) {
        try { sock.close(); } catch (Exception ignored) {}
      }
    }
  }

  HostPort ensureConnected() {
    HostPort target = activeTarget;
    if (target != null && probeStatus(target, 450)) {
      recordDiscovered(target);
      return target;
    }

    long now = System.currentTimeMillis();
    if (now - lastScanMs < 4000L) {
      return activeTarget;
    }
    lastScanMs = now;

    LinkedHashSet<String> quickHosts = new LinkedHashSet<>();
    String manualIp = prefs.getString(KEY_MANUAL_HOST, null);
    if (manualIp != null && !manualIp.isEmpty()) quickHosts.add(manualIp);
    String lastIp = prefs.getString(KEY_LAST_HOST, null);
    if (lastIp != null && !lastIp.isEmpty()) quickHosts.add(lastIp);
    String gw = getWifiGatewayIp();
    if (gw != null) quickHosts.add(gw);
    quickHosts.add("192.168.43.1");
    quickHosts.add("172.20.10.1");

    for (String host : quickHosts) {
      HostPort cand = new HostPort(host, DEFAULT_PORT);
      if (probeStatus(cand, 350)) {
        recordDiscovered(cand);
        return cand;
      }
    }

    HostPort swept = scanLocalSubnets();
    if (swept != null) {
      recordDiscovered(swept);
      return swept;
    }
    return activeTarget;
  }

  JSONObject postNav(JSONObject frame) throws Exception {
    HostPort target = activeTarget;
    if (target == null) {
      target = ensureConnected();
    }
    if (target == null) {
      throw new IllegalStateException("콤마4 찾는 중");
    }

    HttpURLConnection conn = null;
    try {
      URL url = new URL(target.baseUrl() + "/api/nav");
      conn = (HttpURLConnection) url.openConnection();
      conn.setRequestMethod("POST");
      conn.setConnectTimeout(1100);
      conn.setReadTimeout(1200);
      conn.setDoOutput(true);
      conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");

      byte[] payload = frame.toString().getBytes(StandardCharsets.UTF_8);
      try (OutputStream os = conn.getOutputStream()) {
        os.write(payload);
      }

      int code = conn.getResponseCode();
      InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
      String text = readStream(is);
      if (code < 200 || code >= 300) {
        throw new IllegalStateException("HTTP " + code);
      }
      consecutiveFailures = 0;
      return new JSONObject(text);
    } catch (Exception err) {
      consecutiveFailures++;
      if (consecutiveFailures >= 3) {
        HostPort rediscovered = ensureConnected();
        if (rediscovered == null && prefs.getString(KEY_MANUAL_HOST, null) == null) {
          activeTarget = null;
        }
      }
      throw err;
    } finally {
      if (conn != null) conn.disconnect();
    }
  }

  private boolean probeStatus(HostPort target, int timeoutMs) {
    HttpURLConnection conn = null;
    try {
      URL url = new URL(target.baseUrl() + "/api/status");
      conn = (HttpURLConnection) url.openConnection();
      conn.setRequestMethod("GET");
      conn.setConnectTimeout(timeoutMs);
      conn.setReadTimeout(timeoutMs);
      if (conn.getResponseCode() != 200) return false;
      JSONObject obj = new JSONObject(readStream(conn.getInputStream()));
      return "koranipilot".equals(obj.optString("service"));
    } catch (Exception ignored) {
      return false;
    } finally {
      if (conn != null) conn.disconnect();
    }
  }

  private String getWifiGatewayIp() {
    try {
      WifiManager wm = (WifiManager) appContext.getSystemService(Context.WIFI_SERVICE);
      if (wm == null) return null;
      DhcpInfo info = wm.getDhcpInfo();
      if (info == null || info.gateway == 0) return null;
      int gw = info.gateway;
      return String.format(Locale.US, "%d.%d.%d.%d",
          (gw & 0xFF), ((gw >> 8) & 0xFF), ((gw >> 16) & 0xFF), ((gw >> 24) & 0xFF));
    } catch (Exception ignored) {
      return null;
    }
  }

  private HostPort scanLocalSubnets() {
    List<String> prefixes = getHotspotOrWifiPrefixes();
    if (prefixes.isEmpty()) return null;

    AtomicReference<HostPort> hit = new AtomicReference<>(null);
    ExecutorService pool = Executors.newFixedThreadPool(12);
    try {
      List<Future<?>> tasks = new ArrayList<>();
      for (String prefix : prefixes) {
        for (int i = 1; i <= 254; i++) {
          final String ip = prefix + i;
          tasks.add(pool.submit(() -> {
            if (hit.get() != null || !running) return;
            try (Socket s = new Socket()) {
              s.connect(new InetSocketAddress(ip, DEFAULT_PORT), 90);
            } catch (Exception ignored) {
              return;
            }
            HostPort cand = new HostPort(ip, DEFAULT_PORT);
            if (probeStatus(cand, 350)) {
              hit.compareAndSet(null, cand);
            }
          }));
        }
      }
      long deadline = System.currentTimeMillis() + 2600L;
      for (Future<?> f : tasks) {
        if (hit.get() != null) break;
        long rem = deadline - System.currentTimeMillis();
        if (rem <= 0) break;
        try {
          f.get(Math.min(250L, rem), java.util.concurrent.TimeUnit.MILLISECONDS);
        } catch (Exception ignored) {}
      }
    } finally {
      pool.shutdownNow();
    }
    return hit.get();
  }

  private List<String> getHotspotOrWifiPrefixes() {
    LinkedHashSet<String> prefixes = new LinkedHashSet<>();
    try {
      Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
      if (ifaces == null) return Collections.emptyList();
      while (ifaces.hasMoreElements()) {
        NetworkInterface iface = ifaces.nextElement();
        if (!iface.isUp() || iface.isLoopback()) continue;
        String name = iface.getName().toLowerCase(Locale.US);
        if (!(name.startsWith("wlan") || name.startsWith("swlan") || name.startsWith("ap")
            || name.startsWith("rndis") || name.startsWith("usb"))) {
          continue;
        }
        Enumeration<InetAddress> addrs = iface.getInetAddresses();
        while (addrs.hasMoreElements()) {
          InetAddress addr = addrs.nextElement();
          if (addr instanceof Inet4Address && addr.isSiteLocalAddress()) {
            String host = addr.getHostAddress();
            int dot = host.lastIndexOf('.');
            if (dot > 0) {
              prefixes.add(host.substring(0, dot + 1));
            }
          }
        }
      }
    } catch (Exception ignored) {}
    return new ArrayList<>(prefixes);
  }

  private static String readStream(InputStream is) throws Exception {
    if (is == null) return "";
    StringBuilder sb = new StringBuilder();
    try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
      String line;
      while ((line = br.readLine()) != null) {
        sb.append(line);
      }
    }
    return sb.toString();
  }
}
