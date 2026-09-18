"""Live phone clock/sequence contract; never use the FILE replay time adapter here.

For phone send A0, receiver reply B1, phone receive A2, the clock offset
B-A lies in [B1-A2, B1-A0]. No symmetric network-delay assumption is made.
The interval is widened for drift. Its earliest possible fix time determines
expiry; the midpoint is used only for distance projection after freshness checks.
All methods run under the owner's service lock. This module starts no services.
"""

import secrets
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

from .offline import Fix, Observation
from .measurements import parse_measurements

NS = 1_000_000_000
MAX_RTT_NS = 100_000_000
SYNC_TTL_NS = 5 * NS
PROBE_TTL_NS = 500_000_000
FIX_AGE_NS = 200_000_000
ANCHOR_AGE_NS = 1_250_000_000
DRIFT_PPM = 200  # Development assumption, not a measured phone/C4 oscillator bound.


class LiveError(ValueError):
  pass


def integer(data, key, minimum=0):
  value = data.get(key)
  if type(value) is not int or not minimum <= value <= 2**63 - 1:
    raise LiveError("invalidClockOrSequence")
  return value


def identifier(value):
  try:
    if not isinstance(value, str) or str(UUID(value)) != value:
      raise LiveError("invalidStream")
  except ValueError as exc:
    raise LiveError("invalidStream") from exc
  return value


@dataclass(frozen=True)
class LiveSample:
  revision: int
  generation: int
  status: str
  fix: Fix | None = None
  valid_until_ns: int = 0
  uncertainty_ns: int = 0
  anchor: Fix | None = None
  anchor_until_ns: int = 0
  anchor_accepted_ns: int = 0
  anchor_uncertainty_ns: int = 0


class LiveReceiver:
  def __init__(self):
    self.owner = self.stream = None
    self.sync_sequence = self.sequence = 0
    self.last_fix = self.last_sent = -1
    self.pending = self.mapping = None
    self.revision = self.generation = 0
    self.last_now = -1
    self.latest = LiveSample(0, 0, "disconnected")

  def clear(self, status, *, unsync=False):
    self.revision += 1
    self.generation += 1
    if unsync:
      self.pending = self.mapping = None
    self.latest = LiveSample(self.revision, self.generation, status)

  def check_clock(self, now):
    if type(now) is not int or now < self.last_now or now < 0:
      self.clear("receiverClockJump", unsync=True)
      raise LiveError("receiverClockJump")
    self.last_now = now

  def begin(self, owner, data, now):
    self.check_clock(now)
    stream = identifier(data.get("stream"))
    seq, sent = integer(data, "sync_sequence", 1), integer(data, "phone_send_ns")
    if self.owner is not None and self.owner != owner:
      raise LiveError("anotherPhoneOwnsInput")
    if self.stream is not None and self.stream != stream:
      raise LiveError("streamChangedReauthorize")
    if seq <= self.sync_sequence or sent < self.last_sent:
      raise LiveError("syncReplay")
    self.owner, self.stream, self.sync_sequence = owner, stream, seq
    if self.mapping is None or now-self.mapping[3] >= SYNC_TTL_NS:
      self.clear("synchronizing", unsync=True)
    # Same-owner renewal keeps the previous clock and its absolute deadlines
    # until a compatible new clock interval is committed. Nothing is renewed.
    challenge = secrets.token_hex(24)
    self.pending = (challenge, sent, now)
    return {"sync_id": challenge, "receiver_reply_ns": now, "sync_sequence": seq}

  def commit(self, data, now):
    self.check_clock(now)
    if not self.pending or data.get("sync_id") != self.pending[0]:
      raise LiveError("unknownSync")
    challenge, sent, replied = self.pending
    self.pending = None  # Single-use, including rejected/delayed commits.
    received = integer(data, "phone_receive_ns")
    if not 0 <= now - replied <= PROBE_TTL_NS or not 0 <= received - sent <= MAX_RTT_NS:
      self.clear("uncertainClock", unsync=True)
      raise LiveError("uncertainClock")
    old = self.mapping
    mapping = (challenge, replied - received, replied - sent, replied, received)
    drift = 1_000_000 + (max(0, now-old[3])*DRIFT_PPM//1_000_000) if old else 0
    compatible = old is not None and now-old[3] < SYNC_TTL_NS and max(old[1]-drift, mapping[1]) <= min(old[2]+drift, mapping[2])
    self.mapping = mapping
    if not compatible:
      self.clear("waitingForFix" if old is None else "clockMappingChanged")
    return {
      "status": "synchronized",
      "sync_id": challenge,
      "valid_for_ms": SYNC_TTL_NS // 1_000_000,
      "offset_min_ns": replied - received,
      "offset_max_ns": replied - sent,
    }

  def accept(self, data, now):
    self.check_clock(now)
    self.expire_samples(now)
    mapping = self.mapping
    if not mapping or data.get("sync_id") != mapping[0] or now - mapping[3] > SYNC_TTL_NS:
      self.clear("syncRequired", unsync=True)
      raise LiveError("syncRequired")
    if data.get("stream") != self.stream:
      raise LiveError("streamMismatch")
    seq = integer(data, "sequence", 1)
    fix_at, received, sent = (integer(data, key) for key in ("fix_elapsed_ns", "received_elapsed_ns", "sent_elapsed_ns"))
    if seq <= self.sequence or fix_at <= self.last_fix or sent <= self.last_sent:
      raise LiveError("fixReplay")
    if not mapping[4] <= fix_at <= received <= sent:
      raise LiveError("invalidFixClock")
    gap = seq != self.sequence + 1
    # Consume new packets even if their measurements fail, never retry old fixes.
    self.sequence, self.last_fix, self.last_sent = seq, fix_at, sent
    drift = 1_000_000 + ((now - mapping[3]) * DRIFT_PPM // 1_000_000)
    low, high = fix_at + mapping[1] - drift, fix_at + mapping[2] + drift
    if low < 0 or high > now + 10_000_000 or sent + mapping[1] - drift > now + 10_000_000:
      raise LiveError("futureFix")
    if now - low > FIX_AGE_NS:
      raise LiveError("staleFix")
    if data.get("provider") != "gps" or data.get("mock") is not False:
      raise LiveError("untrustedLocation")
    values = [data.get(k) for k in ("longitude", "latitude", "bearing_deg", "speed_mps", "accuracy_m", "bearing_accuracy_deg")]
    try:
      values = parse_measurements(values)
    except ValueError as exc:
      raise LiveError(str(exc)) from exc
    if gap:
      self.clear("sequenceGap")
    self.revision += 1
    deadline = min(low + FIX_AGE_NS, mapping[3] + SYNC_TTL_NS)
    fix = Fix(*values, (low + high) / (2 * NS))
    uncertainty = (high - low + 1) // 2
    self.latest = LiveSample(self.revision, self.generation, "liveFix", fix, deadline, uncertainty,
      fix, min(low+ANCHOR_AGE_NS, mapping[3]+SYNC_TTL_NS), now, uncertainty)
    return {"status": "liveFix", "sequence": seq, "age_upper_ms": (now - low) / 1e6, "uncertainty_ms": self.latest.uncertainty_ns / 1e6}

  def expire_samples(self, now):
    if self.latest.anchor is not None and now >= self.latest.anchor_until_ns:
      self.clear("inputExpired")
    elif self.latest.fix is not None and now >= self.latest.valid_until_ns:
      self.revision += 1
      self.latest = replace(self.latest, revision=self.revision, status="awaitingNextFix", fix=None, valid_until_ns=0, uncertainty_ns=0)

  def sample(self, now):
    self.check_clock(now)
    if self.mapping and now - self.mapping[3] > SYNC_TTL_NS:
      self.clear("syncExpired", unsync=True)
    else:
      self.expire_samples(now)
    return self.latest


class LiveRoadAdapter:
  """Consumer-thread adapter: SQLite stays off HTTPS workers; polling cannot renew GPS.

  Pass an authenticated sample getter and a consumer-owned OfflineProvider. Call
  on each planning tick even when packets stop. No activation/Params/IPC writes.
  """

  def __init__(self, sample, provider, *, today=date.today, route=None):
    self.sample, self.provider, self.today = sample, provider, today
    self.route, self.route_identity = route, None
    self.revision = self.generation = -1
    self.observation = Observation("disconnected")
    self.route_blocked = False

  def __call__(self, now):
    item = self.sample()
    hint = self.route() if self.route is not None else None
    identity = (hint.state, hint.identity) if hint is not None else ('none', '')
    changed = self.route_identity is not None and self.route_identity != identity
    self.route_identity = identity
    blocked = hint is not None and (hint.state == 'pending' or (hint.state == 'active' and now >= hint.valid_until))
    availability_changed = self.route_blocked != blocked
    self.route_blocked = blocked
    if changed:
      self.provider.set_route(hint)
      self.observation = Observation('routeChanged')
    if item.revision != self.revision:
      if item.generation != self.generation:
        self.provider.reset(item.status)
      self.revision, self.generation = item.revision, item.generation
      if item.fix is None or now * NS > item.valid_until_ns:
        self.observation = self.provider.reset(item.status if item.fix is None else "inputExpired")
      else:
        try:
          self.observation = self.provider.observe(item.fix, now=now, today=self.today(), **({"route": hint} if hint is not None else {}))
        except Exception:
          self.observation = self.provider.reset("providerError")
          raise
    elif (changed or availability_changed) and item.fix is not None and now * NS < item.valid_until_ns:
      # Rebuild against this route; retain the existing GPS timestamp/deadline.
      self.observation = self.provider.revalidate_route(now=now, today=self.today(), route=hint)
    if item.fix is None or now * NS > item.valid_until_ns:
      return None
    return self.observation.road_input
