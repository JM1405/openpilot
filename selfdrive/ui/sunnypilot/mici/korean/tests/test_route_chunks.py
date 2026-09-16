import copy
import hashlib
import struct
import unittest
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests import test_phone_route as baseline
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.test_offline import fix, point

class RouteChunkTest(unittest.TestCase):
  setUp=baseline.PhoneRouteTest.setUp
  connect=baseline.PhoneRouteTest.connect

  def prepare(self, count=5000):
    self.points=[list(point(i*.5)) for i in range(count)]
    digest=hashlib.sha256(b''.join(struct.pack('>dd',*p) for p in self.points)).hexdigest()
    self.data.pop('geometry',None)
    self.data.update(protocol=2,shape_id=digest,point_count=count,location_age_ms=0)
    return self.status()
  def status(self,**changes):
    self.data.update(changes)
    self.data['seq']=self.service.session(self.token).get('route_seq',0)+1
    self.data['challenge']=self.route.challenge(self.token)['challenge']
    return self.route.accept(self.token,self.csrf,self.data)
  def chunk(self,offset=0,points=None,**changes):
    data={'challenge':self.route.challenge(self.token)['challenge'],
      'seq':self.service.session(self.token).get('route_seq',0)+1,'revision':self.data['revision'],
      'shape_id':self.data['shape_id'],'offset':offset,'points':self.points[offset:offset+2048] if points is None else points}
    data.update(changes)
    return self.route.chunk(self.token,self.csrf,data)
  def complete(self):
    for i in range(0,len(self.points),2048):self.chunk(i)
  def test_complete_long_shape_is_atomic(self):
    self.assertEqual(self.prepare()['geometry_status'],'pending')
    self.chunk();self.assertEqual(self.route.view(geometry=True)['geometry'],[])
    self.assertEqual(self.route.challenge(self.token)['upload']['next_offset'],2048)
    self.chunk(2048);self.chunk(4096)
    self.assertEqual(self.route.view(geometry=True)['geometry'],self.points)
    self.assertTrue(self.status()['upload']['complete']);self.assertEqual(self.store.writes,[])
  def test_out_of_order_duplicate_and_old_revision_rejected(self):
    self.prepare()
    for kwargs in ({'offset':2048},{'revision':0},{'shape_id':'f'*64},{'seq':1}):
      with self.subTest(kwargs=kwargs),self.assertRaises(PhoneError):self.chunk(**kwargs)
    self.chunk()
    with self.assertRaises(PhoneError):self.chunk()
  def test_changed_route_cannot_mix_previous_chunks(self):
    self.prepare();self.chunk();old=self.data['shape_id']
    self.status(revision=2,shape_id='a'*64)
    with self.assertRaises(PhoneError):self.chunk(2048,shape_id=old)
    self.assertEqual(self.route.challenge(self.token)['upload']['next_offset'],0)
  def test_hash_mismatch_never_commits_and_restarts_clean(self):
    self.prepare(3);bad=copy.deepcopy(self.points);bad[1][0]+=.001
    with self.assertRaises(PhoneError):self.chunk(points=bad)
    self.assertEqual(self.route.view(geometry=True)['geometry'],[])
    self.status();self.complete();self.assertEqual(self.route.view(geometry=True)['geometry'],self.points)
  def test_chunk_upload_does_not_renew_live_expiry(self):
    self.prepare();self.now+=2.;self.chunk();self.now+=1.1;self.chunk(2048);self.chunk(4096)
    self.assertFalse(self.route.view()['received'])
    owner=self.service.session(self.token)['id']
    self.assertEqual(self.route.hint(owner,fix(20)).state,'pending')
    self.assertTrue(self.status(location_age_ms=0)['matched'])
  def test_shape_remains_but_old_source_age_cannot_refresh_hint(self):
    self.prepare();self.complete();self.status(location_age_ms=3500)
    self.assertEqual(self.route.hint(self.service.session(self.token)['id'],fix(20)).state,'pending')
  def test_stop_clears_upload_and_no_route_is_reused(self):
    self.prepare();self.chunk()
    self.status(revision=2,state='ended',shape_id='',point_count=0,geometry_status='unavailable',matched=False,
      total_m=None,total_s=None,remaining_m=None,remaining_s=None,location_age_ms=None)
    self.assertEqual(self.route.challenge(self.token)['upload']['next_offset'],0)
    with self.assertRaises(PhoneError):self.chunk()
    self.assertEqual(self.route.hint(self.service.session(self.token)['id'],fix(20)).state,'none')
  def test_only_same_phone_fresh_route_gets_bounded_original_window(self):
    self.prepare();self.complete();owner=self.service.session(self.token)['id']
    self.assertEqual(self.route.hint('other-phone',fix(20)).state,'pending')
    hint=self.route.hint(owner,fix(20))
    self.assertEqual(hint.state,'active');self.assertLessEqual(len(hint.points),1024)
    self.assertTrue(all(list(p) in self.points for p in hint.points))
  def test_revocation_blocks_chunk_and_hint(self):
    self.prepare();owner=self.service.session(self.token)['id'];self.service.device_revoke(owner)
    with self.assertRaises(PhoneError):self.chunk()
    self.assertEqual(self.route.hint(owner,fix(20)).state,'pending')
  def test_request_bounds_and_bad_geometry(self):
    self.prepare()
    for changes in ({'points':[]},{'points':self.points[:2049]},{'points':[[True,37.]]},{'points':[[float('nan'),37.]]},{'offset':True}):
      with self.subTest(changes=str(changes)[:40]),self.assertRaises(PhoneError):self.chunk(**changes)
    with self.assertRaises(PhoneError):self.status(point_count=65537)
  def test_heartbeat_does_not_reupload_or_replace_complete_shape(self):
    self.prepare(30);self.complete();shape=self.service.session(self.token)['route_shape']
    self.status(remaining_m=1800);self.assertIs(self.service.session(self.token)['route_shape'],shape)
    self.assertEqual(self.route.challenge(self.token)['upload']['next_offset'],30)

  def test_turn_is_hidden_when_original_location_expires(self):
    self.prepare(30)
    turn={'code':'exit','label':'오른쪽 진출','distance_m':450}
    self.status(turn=turn,location_age_ms=2500)
    self.assertEqual(self.route.view()['turn'],turn)
    self.now+=.6
    self.assertIsNone(self.route.view()['turn'])

  def test_malformed_or_unmatched_turn_is_rejected(self):
    self.prepare(30)
    for turn in ({'code':'exit','label':'진출','distance_m':-1},
                 {'code':'exit','label':'진출','distance_m':True},
                 {'code':'exit','label':'진출\n','distance_m':10}):
      with self.subTest(turn=turn),self.assertRaises(PhoneError):self.status(turn=turn)
    with self.assertRaises(PhoneError):
      self.status(turn={'code':'exit','label':'진출','distance_m':10},matched=False,remaining_m=None,remaining_s=None)

if __name__=='__main__':unittest.main()
