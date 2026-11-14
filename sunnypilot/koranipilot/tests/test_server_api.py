from __future__ import annotations

import http.client
import json
import socket
import threading

from openpilot.sunnypilot.koranipilot.server import KoraniBackend, KoraniServer, _make_handler


def _wire_request(backend: KoraniBackend, method: str, path: str, payload: dict | str | None = None) -> tuple[int, dict | str]:
  """Executes a real HTTP/1.1 request through KoraniRequestHandler over a local socketpair."""
  handler_cls = _make_handler(backend)
  srv_sock, cli_sock = socket.socketpair()
  errors: list[BaseException] = []

  def _serve() -> None:
    try:
      handler_cls(srv_sock, ("127.0.0.1", 50000), None)
    except BaseException as exc:
      errors.append(exc)
    finally:
      try:
        srv_sock.close()
      except OSError:
        pass

  try:
    if isinstance(payload, dict):
      body = json.dumps(payload).encode("utf-8")
      ctype = "application/json"
    elif isinstance(payload, str):
      body = payload.encode("utf-8")
      ctype = "application/json"
    else:
      body = b""
      ctype = ""

    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1:7000", "Connection: close"]
    if body:
      lines.append(f"Content-Type: {ctype}")
      lines.append(f"Content-Length: {len(body)}")
    raw_req = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    cli_sock.sendall(raw_req)
    cli_sock.shutdown(socket.SHUT_WR)

    resp = http.client.HTTPResponse(cli_sock)
    resp.begin()
    raw_resp = resp.read().decode("utf-8")
    status = resp.status
    ctype_resp = resp.getheader("Content-Type", "")
    thread.join(timeout=2.0)
    if errors:
      raise errors[0]
    if "application/json" in ctype_resp:
      return status, json.loads(raw_resp)
    return status, raw_resp
  finally:
    for sock in (srv_sock, cli_sock):
      try:
        sock.close()
      except OSError:
        pass


def test_korani_http_wire_endpoints_end_to_end(fake_params):
  backend = KoraniBackend(params=fake_params, port=7000)

  code, html = _wire_request(backend, "GET", "/")
  assert code == 200
  assert "고라니파일럿 리모컨" in html

  code, status = _wire_request(backend, "GET", "/api/status")
  assert code == 200
  assert status["service"] == "koranipilot"
  assert status["config"]["bump_speed_kph"] == 25

  code, cfg_res = _wire_request(backend, "POST", "/api/korani-config", {"bump_speed_kph": 30, "corner_vision_scale": 1.2})
  assert code == 200 and cfg_res["ok"] is True
  assert cfg_res["config"]["bump_speed_kph"] == 30

  code, rec_res = _wire_request(backend, "POST", "/api/korani-config", {"action": "recommended"})
  assert code == 200 and rec_res["ok"] is True
  assert fake_params.get_bool("SmartCruiseControlVision") is True
  assert fake_params.get_bool("SmartCruiseControlMap") is True

  code, cat_res = _wire_request(backend, "GET", "/api/settings")
  assert code == 200 and len(cat_res["rows"]) == 74

  code, upd_res = _wire_request(backend, "POST", "/api/settings", {"key": "SmartCruiseControlVision", "value": False})
  assert code == 200 and upd_res["ok"] is True
  assert fake_params.get_bool("SmartCruiseControlVision") is False

  fake_params.put("ModelManager_ModelsCache", {
    "bundles": [
      {"index": 12, "display_name": "Test <Model> 12", "short_name": "tm12", "generation": 7, "minimum_selector_version": 15},
      {"index": 3, "display_name": "Old Model", "short_name": "old", "generation": 5, "minimum_selector_version": 11},
    ]
  })
  code, models = _wire_request(backend, "GET", "/api/models")
  assert code == 200 and len(models["bundles"]) == 1
  assert models["bundles"][0]["index"] == 12

  code, sel_res = _wire_request(backend, "POST", "/api/models", {"action": "select", "index": 12})
  assert code == 200 and sel_res["ok"] is True
  assert fake_params.get("ModelManager_DownloadIndex") == 12

  code, nav_res = _wire_request(backend, "POST", "/api/nav", {
    "seq": 9,
    "active": True,
    "mode": "free_drive",
    "gps": {"valid": True, "lat": 37.5, "lon": 127.0, "bearing_deg": 0.0},
    "events": [{"id": "KNSafetyCode_Hump:7", "kind": "bump", "lat": 37.5005, "lon": 127.0}],
  })
  assert code == 200 and nav_res["ok"] is True and nav_res["seq"] == 9

  code, status_after = _wire_request(backend, "GET", "/api/status")
  assert code == 200
  assert status_after["nav_summary"]["fresh"] is True
  assert status_after["nav_summary"]["counts"]["bump"] == 1

  # Reboot blocked onroad, allowed offroad
  fake_params.put_bool("IsOnroad", True)
  code, reb_on = _wire_request(backend, "POST", "/api/reboot", {})
  assert code == 200 and reb_on["ok"] is False

  fake_params.put_bool("IsOnroad", False)
  code, reb_off = _wire_request(backend, "POST", "/api/reboot", {})
  assert code == 200 and reb_off["ok"] is True
  assert fake_params.get_bool("DoReboot") is True

  # Malformed JSON and missing route handling
  code_bad, bad_res = _wire_request(backend, "POST", "/api/nav", "{not-json")
  assert code_bad == 400 and bad_res["ok"] is False
  code_nf, nf_res = _wire_request(backend, "GET", "/nonexistent")
  assert code_nf == 404 and nf_res["ok"] is False


def test_korani_server_lifecycle(fake_params):
  srv = KoraniServer(params=fake_params, port=0, enable_beacon=False)
  srv.start()
  try:
    assert srv.port > 0
    assert srv.backend.get_status()["port"] == srv.port
  finally:
    srv.stop()
