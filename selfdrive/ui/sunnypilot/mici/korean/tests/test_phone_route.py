import copy
import unittest
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM

class PhoneRouteTest(unittest.TestCase):
  def setUp(self):
    self.now=100.
    self.store=Store()
    self.runtime=PhoneRuntime(self.store,clock=lambda:self.now,allow_settings_change=False)
    self.runtime.update(SM(self.now),10,True)
    self.addCleanup(self.runtime.close)
    self.service=self.runtime.service
    self.connect()
    self.route=self.service.route
    self.data={'challenge':'','seq':1,'revision':1,'state':'active','destination':'시청',
      'geometry':[[127.,37.],[127.01,37.01]],'geometry_status':'full','total_m':2000,'total_s':200,
      'remaining_m':1900,'remaining_s':190,'location_age_ms':10,'matched':True}
  def connect(self):
    ticket=self.service.pair(self.service.device_open()['window']['code'],'test')
    self.service.device_decide(self.service.pending['id'],True)
    state,self.token=self.service.status(ticket);self.csrf=state['csrf']
  def send(self,data=None):
    data=copy.deepcopy(self.data if data is None else data)
    data['challenge']=self.route.challenge(self.token)['challenge']
    return self.route.accept(self.token,self.csrf,data)
  def test_route_is_display_only_and_full_geometry_is_retained(self):
    state=self.send();self.assertTrue(state['matched']);self.assertEqual(state['remaining_m'],1900)
    self.assertEqual(self.route.view(geometry=True)['geometry'],self.data['geometry'])
    self.assertFalse(state['control_enabled']);self.assertEqual(state['scope'],'route_display_only');self.assertEqual(self.store.writes,[])
  def test_replay_and_older_revision_rejected(self):
    self.send()
    with self.assertRaises(PhoneError):self.send()
    self.data.update(seq=2,revision=0)
    with self.assertRaises(PhoneError):self.send()
  def test_same_revision_cannot_replace_route(self):
    self.send();self.data.update(seq=2,destination='다른 곳')
    with self.assertRaises(PhoneError):self.send()
  def test_heartbeat_only_refreshes_progress(self):
    self.send();self.data.update(seq=2,remaining_m=1800)
    self.assertEqual(self.send()['remaining_m'],1800)
  def test_source_age_and_network_transit_withhold_route(self):
    self.data['challenge']=self.route.challenge(self.token)['challenge'];self.now+=2.995
    self.assertFalse(self.route.accept(self.token,self.csrf,self.data)['matched'])
    self.assertEqual(self.route.view(geometry=True)['geometry'],[])
    self.data.update(seq=2,location_age_ms=4000)
    self.assertFalse(self.send()['matched'])
  def test_receiver_expires_without_sender(self):
    self.send();self.now+=3
    self.assertFalse(self.route.view()['received']);self.assertEqual(self.route.view(geometry=True)['geometry'],[])
  def test_delayed_nonce_wrong_csrf_and_unpaired_rejected(self):
    nonce=self.route.challenge(self.token)['challenge'];self.data['challenge']=nonce
    with self.assertRaises(PhoneError):self.route.accept(self.token,'wrong',self.data)
    self.now+=3
    with self.assertRaises(PhoneError):self.route.accept(self.token,self.csrf,self.data)
    with self.assertRaises(PhoneError):self.route.challenge('wrong')
  def test_reroute_end_clear_and_old_route_cannot_return(self):
    self.send()
    for seq,state in [(2,'rerouting'),(3,'ended')]:
      self.data.update(seq=seq,revision=seq,state=state,geometry=[],geometry_status='unavailable',matched=False,
        total_m=None,total_s=None,remaining_m=None,remaining_s=None,location_age_ms=None)
      self.assertEqual(self.send()['state'],state);self.assertEqual(self.route.view(geometry=True)['geometry'],[])
    self.data.update(seq=4,revision=1)
    with self.assertRaises(PhoneError):self.send()
  def test_revocation_clears_route(self):
    self.send();self.service.device_revoke(self.service.session(self.token)['id']);self.assertFalse(self.route.view()['received'])
  def test_home_receive_allowed_but_mode_loss_invalidates_route(self):
    self.runtime.update(HomeSM(self.now),10,True);self.service.device_set_home(True);self.connect()
    self.assertEqual(self.send()['connection_mode'],'home_receive');self.assertEqual(self.store.writes,[])
    self.service.device_set_home(False);self.assertFalse(self.route.view()['received']);self.assertIsNone(self.route.latest)
  def test_invalid_payloads_rejected(self):
    changes=[('geometry',[[999,37],[127,37]]),('geometry',[[127,True],[127,37]]),('geometry',[[127,float('nan')],[127,37]]),('geometry',[[127,37]]*2049),('geometry_status','partial'),('destination','a\nb'),('destination','x'*121),('seq',True),('revision',True),('state',[]),('matched',1),('location_age_ms',-1),('remaining_m',float('inf')),('total_s',-1),('state','ended'),('matched',False)]
    for key,value in changes:
      with self.subTest(key=key,value=str(value)[:60]):
        payload=copy.deepcopy(self.data);payload[key]=value
        with self.assertRaises(PhoneError):self.send(payload)
  def test_oversized_shape_explicitly_missing(self):
    self.data.update(geometry=[],geometry_status='too_large')
    result=self.send();self.assertTrue(result['matched']);self.assertEqual(result['point_count'],0)
  def test_returned_shape_cannot_mutate_cache(self):
    self.send();self.route.view(geometry=True)['geometry'][0][0]=0
    self.assertEqual(self.route.view(geometry=True)['geometry'][0][0],127.)

if __name__=='__main__':unittest.main()
