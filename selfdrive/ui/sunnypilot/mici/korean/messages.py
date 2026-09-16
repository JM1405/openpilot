"""Read-only cereal -> HUD adapter. No subscriptions, Params writes or publishers.

The caller supplies the log's monotonic clock, never the PC wall clock. Legacy
controlsState alerts are opt-in for archives predating selfdriveState. Display
geometry is deliberately absent unless a caller explicitly requests a diagram.
"""
from dataclasses import dataclass
from math import isfinite

from openpilot.selfdrive.ui.sunnypilot.mici.korean.alerts import read_alert
from openpilot.selfdrive.ui.sunnypilot.mici.korean.state import Lead, Snapshot, fresh, speed_or_none

SERVICES = frozenset(('carState', 'carControl', 'carParams', 'controlsState', 'radarState',
                      'selfdriveState', 'selfdriveStateSP', 'longitudinalPlanSP',
                      'driverMonitoringState', 'driverMonitoringStateDEPRECATED'))


def number(value):
  return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


@dataclass(frozen=True)
class Sample:
  timestamp: float
  valid: bool
  data: dict


class MessageAdapter:
  def __init__(self, *, legacy_controls=False):
    self.legacy_controls = legacy_controls
    self.samples: dict[str, Sample] = {}

  def consume(self, event):
    service = event.which()
    if service not in SERVICES:
      return
    timestamp = event.logMonoTime / 1e9
    previous = self.samples.get(service)
    if previous is None or timestamp >= previous.timestamp:
      self.samples[service] = Sample(timestamp, bool(event.valid), getattr(event, service).to_dict())

  def get(self, service, now):
    sample = self.samples.get(service)
    if sample is None or not sample.valid or sample.timestamp > now:
      return None
    # carParams is route configuration, not a periodic sensor stream.
    if service != 'carParams' and not fresh(sample.timestamp, now, 0.5):
      return None
    return sample.data

  def adapt(self, now, *, diagram=False):
    cs = self.get('carState', now)
    if cs is not None and (not cs.get('canValid') or number(cs.get('vEgo')) is None or cs['vEgo'] < 0):
      cs = None
    cc = self.get('carControl', now) if cs is not None else None
    cp = self.get('carParams', now)
    owner = ('openpilot' if cp['openpilotLongitudinalControl'] else 'stock') if cp else 'unknown'
    ss = self.get('selfdriveState', now)
    ss_source = 'selfdriveState'
    # Once a current service exists, a stale/invalid sample must never be replaced by legacy defaults.
    if self.legacy_controls and 'selfdriveState' not in self.samples:
      controls = self.get('controlsState', now)
      ss = controls.get('deprecated') if controls else None
      ss_source = 'controlsState.deprecated'

    lateral = bool(cc and cc.get('latActive'))
    cruise = cs.get('cruiseState', {}) if cs else {}
    longitudinal = bool(cc and cc.get('longActive')) if owner == 'openpilot' else (
      bool(cs and cruise.get('enabled') and not cruise.get('nonAdaptive')) if owner == 'stock' else False)
    mode = 'SCC' if owner == 'stock' else '—'
    plan = self.get('longitudinalPlanSP', now)
    if owner == 'openpilot' and ss and ss_source == 'selfdriveState':
      mode = 'E2E' if ss.get('experimentalMode') else 'ACC'
      if plan and plan.get('dec', {}).get('active'):
        mode = 'E2E' if plan['dec']['state'] == 'blended' else 'ACC'
    sp = self.get('selfdriveStateSP', now)
    if sp and sp.get('mads', {}).get('enabled') and lateral and not longitudinal:
      mode = 'MADS'

    set_speed, speed_source = None, None
    if cs:
      # Current MICI uses cluster set speed, never ego speed. A nonzero sentinel
      # (e.g. 255/unset) hides the number rather than resurrecting an older value.
      value = cs.get('vCruiseCluster', 0)
      speed_source = 'carState.vCruiseCluster'
      if value == 0:
        controls = self.get('controlsState', now)
        value = controls.get('deprecated', {}).get('vCruise') if controls else None
        speed_source = 'controlsState.deprecated.vCruise'
      set_speed = speed_or_none(number(value))

    dm = self.get('driverMonitoringState', now)
    attentive = None
    if dm:
      if dm.get('activePolicy') == 'vision':
        policy = dm.get('visionPolicyState', {})
        attentive = bool(policy.get('faceDetected') and not policy.get('isDistracted') and dm.get('alertLevel') == 'none')
      # Wheeltouch is not a camera attention measurement: retain unknown.
    elif self.legacy_controls and 'driverMonitoringState' not in self.samples:
      old_dm = self.get('driverMonitoringStateDEPRECATED', now)
      if old_dm and old_dm.get('isActiveMode'):
        attentive = bool(old_dm.get('faceDetected') and not old_dm.get('isDistracted'))

    radar = self.get('radarState', now) if cs else None
    raw_lead = radar.get('leadOne', {}) if radar else {}
    distance, relative = number(raw_lead.get('dRel')), number(raw_lead.get('vRel'))
    present = bool(raw_lead.get('present') and distance is not None and 0 < distance <= 200 and relative is not None)
    lead = None
    if present and diagram:
      # Fixed schematic slot, explicitly NOT a camera projection or object box.
      lead = Lead('leadOne', self.samples['radarState'].timestamp, distance, relative)

    alert_sample = self.samples.get('controlsState' if ss_source == 'controlsState.deprecated' else 'selfdriveState')
    alert, alert_available = read_alert(ss, alert_sample.timestamp if alert_sample else now, ss_source)
    intervention = bool(alert and alert.alertStatus == 'critical')
    torque = number(cc.get('actuators', {}).get('torque')) if cc and cp and cp.get('steerControlType') == 'torque' else None
    snapshot = Snapshot(
      timestamp=self.samples['carState'].timestamp if cs else now - 1,
      ego_speed=cs['vEgo'] if cs else 0,
      lateral_active=lateral, longitudinal_active=longitudinal, set_speed=set_speed,
      mode=mode, driver_attentive=attentive, steering_usage=torque if torque is not None and lateral else 0,
      lead=lead, intervention=intervention, alert=alert, alert_available=alert_available,
    )
    evidence = {
      'vehicle_state_valid': cs is not None, 'longitudinal_owner': owner,
      'lateral_source': 'carControl.latActive',
      'longitudinal_source': 'carState.cruiseState.enabled' if owner == 'stock' else 'carControl.longActive' if owner == 'openpilot' else None,
      'set_speed_source': speed_source, 'alert_source': ss_source,
      'alert': {key: getattr(alert, key) for key in ('alertType', 'alertStatus', 'alertSize', 'alertText1', 'alertText2',
                                                  'alertHudVisual', 'alertSound')} if alert else None,
      'alert_available': alert_available,
      'lead_present': present, 'lead_distance': distance if present else None,
      'lead_relative_speed': relative if present else None,
      'lead_geometry': 'fixed_diagram' if diagram and present else 'unavailable',
      'driver_attention_known': attentive is not None,
      'steering_bar_source': 'carControl.actuators.torque (command)' if torque is not None else None,
      'services': {name: {'timestamp': sample.timestamp, 'valid': sample.valid,
                          'fresh': self.get(name, now) is not None} for name, sample in self.samples.items()},
    }
    return snapshot, evidence
