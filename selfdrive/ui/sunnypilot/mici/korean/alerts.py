"""Read-only upstream alert contract and deterministic PC presentation.

The message owner chooses the alert and its duration. This module does not
generate driver-monitoring, collision, control, or hardware timeout events.
"""
from dataclasses import dataclass, asdict
from math import isfinite

FIELDS = ('alertType', 'alertStatus', 'alertSize', 'alertText1', 'alertText2', 'alertHudVisual', 'alertSound')
COLORS = {'normal': (0, 0, 0), 'userPrompt': (255, 115, 0), 'critical': (255, 0, 21)}


@dataclass(frozen=True)
class DrivingAlert:
  timestamp: float
  source: str
  alertType: str = ''
  alertStatus: str = 'normal'
  alertSize: str = 'none'
  alertText1: str = ''
  alertText2: str = ''
  alertHudVisual: str = 'none'
  alertSound: str = 'none'

  def fresh(self, now):
    return isfinite(self.timestamp) and isfinite(now) and 0 <= now - self.timestamp <= 0.5


def read_alert(data, timestamp, source):
  """Return (active alert, feed valid). A fresh explicit 'none' is a clear."""
  if data is None:
    return None, False
  size, status = data.get('alertSize', 'none'), data.get('alertStatus', 'normal')
  if size not in ('none', 'small', 'mid', 'full') or status not in COLORS:
    return None, False
  if size == 'none':
    return None, True
  values = {key: data.get(key, 'none' if key in ('alertHudVisual', 'alertSound') else '') for key in FIELDS}
  values.update(alertSize=size, alertStatus=status)
  # Archive messages name the sound field alertSound2.
  if source == 'controlsState.deprecated':
    values['alertSound'] = data.get('alertSound2', 'none')
  if not all(isinstance(value, str) for value in values.values()):
    return None, False
  return DrivingAlert(timestamp, source, **values), True


class AlertPresentation:
  """MICI alpha filter (rc=.05), evaluated in source/playback time at 20 Hz.

  Keep the previous content until alpha <= .01 after an explicit clear.
  An unavailable feed is distinct from clear; discard untrustworthy content
  immediately and let the PC readout report unavailable. Hardware watchdogs
  still belong to the original on-device renderer, outside this preview.
  """
  def __init__(self, hz=20):
    self.previous = None
    self.alpha = 0.0
    self.gain = (1 / hz) / (0.05 + 1 / hz)

  def update(self, alert, available=True):
    if not available:
      self.previous, self.alpha = None, 0.0
      return None
    self.alpha += self.gain * (int(alert is not None) - self.alpha)
    if alert is not None:
      self.previous = alert
    elif self.alpha <= 0.01:
      self.previous = None
    if self.previous is None:
      return None
    return {'alert': asdict(self.previous), 'alpha': self.alpha, 'clearing': alert is None}
