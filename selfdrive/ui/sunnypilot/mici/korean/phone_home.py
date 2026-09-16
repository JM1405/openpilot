"""Read-only home-test eligibility from real device/panda messages.

Missing carState is never parking evidence. No synthetic CAN, Params writes,
safety-mode changes, or actuator publication belong in this module.
"""
import math

HOME_MODE = 'home_receive'
VEHICLE_MODE = 'vehicle'
HOME_REASON = '집 테스트 · 수신 전용 · 설정/모델/제어 차단'
STATE_TTL = 1.5  # deviceState is published at 2 Hz; pandaStates at 10 Hz.


def home_state(snapshot, now, started_frame):
  def fresh(name):
    stamp = snapshot.recv_time.get(name, 0.)
    return (snapshot.seen.get(name) and snapshot.valid.get(name) and
            snapshot.recv_frame.get(name, -1) >= started_frame and
            type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= now - stamp < STATE_TTL)

  if not all(fresh(name) for name in ('deviceState', 'pandaStates')):
    return '장치/점화 상태가 없거나 만료됐어'
  device, pandas = snapshot.messages.get('deviceState'), snapshot.messages.get('pandaStates')
  if not isinstance(device, dict) or device.get('started') is not False:
    return '장치가 비주행 상태인지 확인해'
  if not isinstance(pandas, list) or not pandas:
    return '판다 연결 상태를 확인할 수 없어'
  for panda in pandas:
    if not isinstance(panda, dict) or panda.get('pandaType') not in (
        'whitePanda', 'greyPanda', 'blackPanda', 'uno', 'dos', 'redPanda', 'redPandaV2', 'tres', 'cuatro'):
      return '판다 종류를 확인할 수 없어'
    if any(panda.get(key) is not False for key in ('ignitionLine', 'ignitionCan')):
      return '점화가 꺼진 상태에서만 집 테스트를 켤 수 있어'
    if (panda.get('safetyModel') != 'noOutput' or
        any(panda.get(key) is not False for key in ('controlsAllowed', 'controlsAllowedLateral', 'controlsAllowedLongitudinal'))):
      return '차량 출력 차단 상태를 확인할 수 없어'
  # Contradictory fresh vehicle data is a veto, never a prerequisite.
  if fresh('carState'):
    car = snapshot.messages.get('carState', {})
    if car.get('canValid') is True:
      speed = car.get('vEgo')
      if (type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed < .1 or
          car.get('standstill') is not True or car.get('gearShifter') != 'park'):
        return '차량 이동/기어 상태가 집 테스트 조건과 달라'
  for name, fields in (('carControl', ('enabled', 'latActive', 'longActive')), ('selfdriveState', ('enabled',)),
                       ('selfdriveStateSP', ('enabled', 'active'))):
    if fresh(name):
      data = snapshot.messages.get(name, {})
      if name == 'selfdriveStateSP':
        data = data.get('mads', {})
      if any(data.get(key) for key in fields):
        return '조향/속도 보조가 켜져 있어'
  return ''
