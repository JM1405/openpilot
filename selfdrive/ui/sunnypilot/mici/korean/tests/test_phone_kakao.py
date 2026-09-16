import copy
import unittest

from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM


def frame(challenge, seq=1):
  return {'challenge': challenge, 'seq': seq, 'mode': 'free_drive', 'active': True, 'location_age_ms': 10,
          'gps_valid': True, 'speed_kph': None, 'route_matched': False, 'safety_age_ms': 20,
          'events': [{'id': 'sharp-1', 'code': 'KNSafetyCode_SharpTurnSection', 'kind': 'sharp_turn',
                      'distance_m': None, 'distance_basis': 'unknown', 'limit_kph': None,
                      'passed': False, 'variable': False}]}


class PhoneKakaoTest(unittest.TestCase):
  def setUp(self):
    self.now=100.
    self.store=Store()
    self.runtime=PhoneRuntime(self.store, clock=lambda:self.now)
    self.runtime.update(SM(self.now),10,True)
    self.addCleanup(self.runtime.close)
    self.service=self.runtime.service
    ticket=self.service.pair(self.service.device_open()['window']['code'],'Android')
    self.service.device_decide(self.service.pending['id'],True)
    state,self.token=self.service.status(ticket)
    self.csrf=state['csrf']
    self.kakao=self.service.kakao
    self.payload=frame(self.kakao.challenge(self.token)['challenge'])

  def accept(self, data=None):
    return self.kakao.accept(self.token,self.csrf,self.payload if data is None else data)

  def test_receives_curve_but_never_writes_control(self):
    result=self.accept()
    self.assertTrue(result['received'])
    self.assertTrue(result['location_fresh'])
    self.assertEqual(result['events'][0]['kind'],'sharp_turn')
    self.assertFalse(result['control_enabled'])
    self.assertFalse(result['events'][0]['control_eligible'])
    self.assertEqual(self.store.writes,[])

  def test_replay_is_rejected_even_with_new_challenge(self):
    self.accept()
    with self.assertRaises(PhoneError):self.accept()
    self.payload['challenge']=self.kakao.challenge(self.token)['challenge']
    with self.assertRaises(PhoneError):self.accept()
    self.payload['seq']=2
    self.assertTrue(self.accept()['received'])

  def test_challenge_deadline_and_expiry_use_c4_clock(self):
    self.now+=2.995
    result=self.accept()
    self.assertFalse(result['location_fresh'])  # source age + transit bound
    self.now+=.02
    self.assertFalse(self.kakao.view()['received'])
    with self.assertRaises(PhoneError):self.accept()

  def test_delayed_challenge_is_not_accepted(self):
    self.now+=3
    with self.assertRaises(PhoneError):self.accept()

  def test_wrong_session_csrf_and_revocation(self):
    with self.assertRaises(PhoneError):self.kakao.challenge('wrong')
    with self.assertRaises(PhoneError):self.kakao.accept(self.token,'wrong',self.payload)
    self.accept()
    self.service.device_revoke(self.service.session(self.token)['id'])
    self.assertFalse(self.kakao.view()['received'])
    with self.assertRaises(PhoneError):self.accept()

  def test_source_age_is_not_refreshed_by_repeated_network_frames(self):
    self.payload['location_age_ms']=4000
    self.payload['safety_age_ms']=4000
    result=self.accept()
    self.assertFalse(result['location_fresh'])
    self.assertEqual(result['events'],[])

  def test_stop_clears_events(self):
    self.payload['active']=False
    result=self.accept()
    self.assertFalse(result['location_fresh'])
    self.assertEqual(result['events'],[])
    self.assertEqual(result['reason'],'카카오 수신 중지')

  def test_free_drive_cannot_claim_route_match(self):
    self.payload['route_matched']=True
    with self.assertRaises(PhoneError):self.accept()

  def test_unknown_distance_cannot_be_filled_with_straight_line(self):
    self.payload['events'][0]['distance_m']=100
    with self.assertRaises(PhoneError):self.accept()

  def test_curve_and_bump_cannot_receive_invented_limit(self):
    for kind in ('sharp_turn','bump'):
      self.payload['events'][0].update(kind=kind,limit_kph=30)
      with self.assertRaises(PhoneError):self.accept()

  def test_route_camera_is_still_observation_only(self):
    self.payload.update(mode='route',route_matched=True)
    self.payload['events'][0].update(kind='camera',distance_basis='same_route',distance_m=300,limit_kph=60)
    result=self.accept()
    self.assertEqual(result['events'][0]['limit_kph'],60)
    self.assertFalse(result['events'][0]['control_eligible'])
    self.assertEqual(self.store.writes,[])

  def test_invalid_values_rejected(self):
    changes=[('seq',True),('seq',0),('active',1),('gps_valid','true'),('speed_kph',float('nan')),
             ('location_age_ms',-1),('safety_age_ms',float('inf')),('events',None),('mode','simulation')]
    for key,value in changes:
      with self.subTest(key=key,value=value):
        changed=copy.deepcopy(self.payload);changed[key]=value
        with self.assertRaises(PhoneError):self.accept(changed)
    changed=copy.deepcopy(self.payload);changed['events'][0]['kind']=[]
    with self.assertRaises(PhoneError):self.accept(changed)

  def test_oversized_duplicate_or_extra_fields_rejected(self):
    for change in ('duplicate','oversized','extra'):
      changed=copy.deepcopy(self.payload)
      if change=='duplicate':changed['events']*=2
      if change=='oversized':changed['events']*=9
      if change=='extra':changed['brake']=True
      with self.assertRaises(PhoneError):self.accept(changed)

  def test_caller_cannot_mutate_saved_snapshot(self):
    answer=self.accept()
    self.payload['events'][0]['kind']='other'
    answer['events'][0]['kind']='other'
    self.assertEqual(self.kakao.view()['events'][0]['kind'],'sharp_turn')


if __name__=='__main__':unittest.main()
