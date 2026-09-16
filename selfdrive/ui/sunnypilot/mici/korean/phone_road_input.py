"""Existing phone approval/HTTPS authentication, with a separate SDK-free input API."""

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.live import LiveError, LiveReceiver, NS

FIELDS = {
  "sync": {"stream", "sync_sequence", "phone_send_ns"},
  "commit": {"sync_id", "phone_receive_ns"},
  "stop": {"sync_id"},
  "fix": {
    "sync_id",
    "stream",
    "sequence",
    "fix_elapsed_ns",
    "received_elapsed_ns",
    "sent_elapsed_ns",
    "longitude",
    "latitude",
    "bearing_deg",
    "speed_mps",
    "accuracy_m",
    "bearing_accuracy_deg",
    "mock",
    "provider",
  },
}


class PhoneRoadInput:
  def __init__(self, service, *, clock):
    self.service, self.clock = service, clock
    self.receiver = LiveReceiver()

  def _expire(self):
    self.service._expire()
    active = {s['id'] for s in self.service.sessions.values()}
    if self.receiver.owner is not None and self.receiver.owner not in active:
      # Keep monotonic sample revision/generation across authenticated sessions.
      old = self.receiver
      self.receiver = LiveReceiver()
      self.receiver.revision, self.receiver.generation = old.revision, old.generation
      self.receiver.clear("authorizationEnded", unsync=True)

  def accept(self, token, csrf, action, data):
    with self.service.lock:
      self._expire()
      owner = self.service.authorize_write(token, csrf)['id']
      receiver = self.receiver
      if receiver.owner is not None and owner != receiver.owner:
        raise PhoneError('다른 폰의 입력 연결을 먼저 해제해', 'anotherPhoneOwnsInput', 409)
      try:
        if not isinstance(data, dict) or set(data) != FIELDS[action] | {"schema"} or type(data.get("schema")) is not int or data["schema"] != 1:
          raise LiveError("invalidLiveRecord")
        now = int(self.clock() * NS)
        if action == "sync":
          return receiver.begin(owner, data, now)
        if receiver.owner != owner:
          raise LiveError("syncRequired")
        if action == "commit":
          return receiver.commit(data, now)
        if action == "fix":
          return receiver.accept(data, now)
        if not receiver.mapping or data["sync_id"] != receiver.mapping[0]:
          raise LiveError("unknownSync")
        receiver.clear("phoneStopped", unsync=True)
        return {"status": "phoneStopped"}
      except LiveError as exc:
        # Any rejected record from the owning phone clears its preceding input.
        receiver.clear(str(exc))
        raise PhoneError('도로 입력을 다시 동기화해', str(exc), 409) from exc

  def sample(self):
    with self.service.lock:
      self._expire()
      try:
        return self.receiver.sample(int(self.clock() * NS))
      except LiveError:
        return self.receiver.latest

  def view(self):
    item = self.sample()
    return {"status": item.status, "valid": item.fix is not None, "uncertainty_ms": item.uncertainty_ns / 1e6, "scope": "observation_only", "control_enabled": False}
