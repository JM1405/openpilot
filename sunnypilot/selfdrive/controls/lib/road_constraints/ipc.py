"""Same-device IPC for authenticated GPS and derived road input.

No clock rebasing, persistent cache, activation or network fallback. Each hop has
a 150ms process lease, bounded by the original GPS deadline. Epoch ordering and
sequence checks reject packets from a retired publisher. Socket readers conflate
to one packet per tick so a producer cannot block the planning loop by flooding.
"""

import time
from dataclasses import replace
from uuid import uuid4

from cereal import messaging
from .contract import RoadConstraint, RoadContext, RoadInput, RoadInputValidator, RoadKind, RoadLink, RoadSnapshot
from .live import FIX_AGE_NS, NS, LiveSample, identifier
from .offline import Fix
from .measurements import parse_measurements
from .dataset import DatasetInfo
from .route_hint import RouteHint

LOCATION = "phoneRoadLocationSP"
CONSTRAINTS = "roadConstraintsSP"
LEASE_NS = 150_000_000
MAX_PACKET_BYTES = 64 * 1024


class IpcError(ValueError):
  pass


class Publisher:
  def __init__(self, service, *, clock=time.monotonic, socket=None):
    self.service, self.clock = service, clock
    self.epoch, self.started, self.sequence = str(uuid4()), int(clock() * NS), 0
    self.socket = socket if socket is not None else messaging.pub_sock(service)

  def message(self):
    self.sequence += 1
    msg = messaging.new_message(self.service, valid=True, logMonoTime=int(self.clock() * NS))
    body = getattr(msg, self.service)
    body.publisherEpoch, body.publisherStartedNs = self.epoch, self.started
    body.publishSequence, body.schemaVersion = self.sequence, 1
    return msg, body

  def send(self, msg):
    self.socket.send(msg.to_bytes())

  def close(self):
    self.socket = None  # msgq releases the publisher handle on destruction.


class LocationPublisher(Publisher):
  def __init__(self, **kwargs):
    super().__init__(LOCATION, **kwargs)

  def publish(self, sample, route=None):
    msg, b = self.message()
    b.routeHintJson = route.wire() if route is not None else ""
    b.sampleRevision, b.generation, b.status = sample.revision, sample.generation, sample.status
    b.hasFix = sample.fix is not None
    if sample.fix is not None:
      b.validUntilNs, b.uncertaintyNs = sample.valid_until_ns, sample.uncertainty_ns
      f = sample.fix
      b.fix = {
        "longitude": f.lon,
        "latitude": f.lat,
        "hasBearing": f.bearing_deg is not None and f.bearing_accuracy_deg is not None,
        "bearingDeg": f.bearing_deg or 0.0,
        "speedMps": f.speed_mps,
        "accuracyM": f.accuracy_m,
        "bearingAccuracyDeg": f.bearing_accuracy_deg or 0.0,
        "observedAt": f.observed_at,
      }
    self.send(msg)


def pack_road(road):
  s, c = road.snapshot, road.context

  def link(value):
    return {"roadId": value.road_id, "direction": value.direction}

  return {
    "snapshot": {
      "source": s.source,
      "session": s.session,
      "pathVersion": s.path_version,
      "sequence": s.sequence,
      "hasSourceAt": s.source_at is not None,
      "sourceAt": s.source_at or 0.0,
      "receivedAt": s.received_at,
      "referenceProgressM": s.reference_progress_m,
      "constraints": [
        {"eventId": e.event_id, "kind": e.kind.value, "link": link(e.link), "startM": e.start_m, "endM": e.end_m, "targetSpeed": e.target_speed}
        for e in s.constraints
      ],
    },
    "context": {
      "session": c.session,
      "pathVersion": c.path_version,
      "path": [link(value) for value in c.path],
      "progressM": c.progress_m,
      "observedAt": c.observed_at,
      "confirmed": c.confirmed,
    },
  }


def unpack_road(b):
  s, c = b.snapshot, b.context
  if len(s.constraints) > 32 or len(c.path) > 64:
    raise IpcError("inputTooLarge")

  def link(value):
    if len(value.roadId) > 256 or len(value.direction) > 256:
      raise IpcError("invalidLink")
    return RoadLink(value.roadId, value.direction)

  constraints = tuple(RoadConstraint(e.eventId, RoadKind(e.kind), link(e.link), e.startM, e.endM, e.targetSpeed) for e in s.constraints)
  return RoadInput(
    RoadSnapshot(s.source, s.session, s.pathVersion, s.sequence, s.sourceAt if s.hasSourceAt else None, s.receivedAt, s.referenceProgressM, constraints),
    RoadContext(c.session, c.pathVersion, tuple(link(v) for v in c.path), c.progressM, c.observedAt, c.confirmed),
  )


class RoadPublisher(Publisher):
  def __init__(self, **kwargs):
    super().__init__(CONSTRAINTS, **kwargs)

  def publish(self, road, status, deadline=0, dataset=None):
    msg, b = self.message()
    b.hasInput, b.status = road is not None, status
    if dataset is not None:
      b.dataset = dataset.wire()
    if road is not None:
      b.validUntilNs, b.input = deadline, pack_road(road)
    self.send(msg)


class EnvelopeGuard:
  def __init__(self, now):
    self.created = self.last_poll = int(now * NS)
    self.epoch, self.started, self.sequence, self.stamp = None, -1, 0, 0

  def accept(self, msg, b, now):
    at = int(now * NS)
    if at < self.last_poll:
      raise IpcError("consumerClockJump")
    self.last_poll = at
    if not msg.valid or b.schemaVersion != 1:
      raise IpcError("invalidEnvelope")
    identifier(b.publisherEpoch)
    # The planner captures now just before polling; a concurrent publisher can
    # commit a few microseconds later. Keep the shared 10ms future tolerance.
    if not self.created <= msg.logMonoTime <= at + 10_000_000 or at - msg.logMonoTime > LEASE_NS:
      raise IpcError("publisherStale")
    if not 0 < b.publisherStartedNs <= msg.logMonoTime or b.publishSequence < 1:
      raise IpcError("publisherClock")
    changed = b.publisherEpoch != self.epoch
    if changed:
      if b.publisherStartedNs <= self.started:
        raise IpcError("retiredPublisher")
    elif b.publisherStartedNs != self.started or b.publishSequence <= self.sequence or msg.logMonoTime < self.stamp:
      raise IpcError("packetReplay")
    self.epoch, self.started = b.publisherEpoch, b.publisherStartedNs
    self.sequence, self.stamp = b.publishSequence, msg.logMonoTime
    return changed


class Reader:
  def __init__(self, service, *, clock=time.monotonic, socket=None):
    self.clock, self.service = clock, service
    self.guard = EnvelopeGuard(clock())
    self.socket = socket if socket is not None else messaging.sub_sock(service, conflate=True)

  def read(self, now):
    data = self.socket.receive(non_blocking=True)
    if data is None:
      return None
    if len(data) > MAX_PACKET_BYTES:
      raise IpcError("packetTooLarge")
    # Use Cap'n Proto's bounded traversal, unlike the general log replay reader.
    with messaging.log.Event.from_bytes(data, traversal_limit_in_words=MAX_PACKET_BYTES // 8) as msg:
      if msg.which() != self.service:
        raise IpcError("wrongService")
      body = getattr(msg, self.service)
      changed = self.guard.accept(msg, body, now)
      return self.decode(body, changed, now)

  def close(self):
    self.socket = None


class LocationReader(Reader):
  def __init__(self, **kwargs):
    super().__init__(LOCATION, **kwargs)
    self.remote = None
    self.route_hint = RouteHint()
    self.revision = self.generation = 0
    self.latest = LiveSample(0, 0, "awaitingPublisher")
    self.invalid = True

  def clear(self, reason):
    self.route_hint = RouteHint("pending", self.route_hint.identity, reason=reason)
    if not self.invalid or self.latest.status != reason:
      self.revision += 1
      self.generation += 1
      self.latest = LiveSample(self.revision, self.generation, reason)
    self.invalid = True

  def decode(self, b, changed, now):
    if len(b.status) > 128:
      raise IpcError("invalidStatus")
    hint = RouteHint.parse(b.routeHintJson, now)
    fix = None
    if b.hasFix:
      f = b.fix
      values = parse_measurements(
        (f.longitude, f.latitude, f.bearingDeg if f.hasBearing else None, f.speedMps, f.accuracyM, f.bearingAccuracyDeg if f.hasBearing else None)
      )
      observed = f.observedAt
      if not 0 <= observed <= now:
        raise IpcError("uncertainFix")
      if not (0 <= b.uncertaintyNs <= 52_000_000 and now * NS < b.validUntilNs <= round(observed * NS) - b.uncertaintyNs + FIX_AGE_NS + 2):
        raise IpcError("invalidFixDeadline")
      fix = Fix(*values, observed)
    remote = LiveSample(b.sampleRevision, b.generation, b.status, fix, b.validUntilNs, b.uncertaintyNs)
    if not changed and self.remote is not None:
      if (
        remote.revision < self.remote.revision
        or remote.generation < self.remote.generation
        or (remote.revision == self.remote.revision and remote != self.remote)
      ):
        raise IpcError("sampleReplay")
    if changed or self.invalid or remote != self.remote:
      if changed or self.invalid or (self.remote and remote.generation != self.remote.generation):
        self.generation += 1
      self.revision += 1
      self.latest = replace(remote, revision=self.revision, generation=self.generation)
    self.remote, self.invalid = remote, False
    self.route_hint = hint
    return self.latest

  def sample(self):
    now = self.clock()
    try:
      self.read(now)
      if int(now * NS) < self.guard.last_poll:
        raise IpcError("consumerClockJump")
      self.guard.last_poll = int(now * NS)
      if now * NS - self.guard.stamp > LEASE_NS:
        self.clear("publisherLost")
      elif self.latest.fix is not None and now * NS >= self.latest.valid_until_ns:
        self.clear("inputExpired")
    except Exception:
      self.clear("invalidLocationIpc")
    return self.latest

  @property
  def deadline(self):
    return min(self.latest.valid_until_ns, self.guard.stamp + LEASE_NS)


class RoadReader(Reader):
  def __init__(self, **kwargs):
    super().__init__(CONSTRAINTS, **kwargs)
    self.road = None
    self.deadline = 0
    self.status = "awaitingRoadService"
    self.dataset = DatasetInfo('unknown')
    self.validator = RoadInputValidator()

  @property
  def valid_until(self):
    # Downstream diagnostic reports may shorten this lease, never renew it.
    return min(self.deadline, self.guard.stamp + LEASE_NS) / NS if self.road is not None else 0.0

  def decode(self, b, changed, now):
    if len(b.status) > 128:
      raise IpcError("invalidStatus")
    if changed:
      self.validator = RoadInputValidator()
    d = b.dataset
    if (d.state not in ('', 'unknown', 'ready', 'loading', 'missing', 'invalid') or len(d.datasetId) > 64
        or len(d.latestRoadDate) > 10 or d.links > 10_000_000 or d.verifiedEvents > 10_000_000):
      raise IpcError('invalidDatasetStatus')
    dataset = DatasetInfo(d.state or 'unknown', d.datasetId, d.revision, d.latestRoadDate, d.links, d.verifiedEvents)
    if not changed and dataset.revision < self.dataset.revision:
      raise IpcError('datasetRevisionReplay')
    road = unpack_road(b.input) if b.hasInput else None
    if road is not None:
      error = self.validator.validate(road, now)
      if error:
        raise IpcError(error)
      if dataset.state == 'ready' and road.snapshot.source != 'offline-derived:' + dataset.dataset_id:
        raise IpcError('datasetSourceMismatch')
      if not now * NS < b.validUntilNs <= round(road.context.observed_at * NS) + FIX_AGE_NS + 2:
        raise IpcError("invalidRoadDeadline")
    self.road, self.deadline, self.status = road, b.validUntilNs, b.status
    self.dataset = dataset
    return road

  def __call__(self, now):
    try:
      self.read(now)
      if now * NS < self.guard.last_poll:
        raise IpcError("consumerClockJump")
      self.guard.last_poll = int(now * NS)
      if now * NS - self.guard.stamp > LEASE_NS or (self.road is not None and now * NS >= self.deadline):
        self.road, self.status = None, "roadServiceExpired"
    except Exception:
      self.road, self.status = None, "invalidRoadIpc"
      self.dataset = DatasetInfo('unknown')
    return self.road
