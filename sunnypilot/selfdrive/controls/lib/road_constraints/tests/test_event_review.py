"""Runtime event binding and direction gates; all map/evidence truth is synthetic."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import date

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints import event_review as review
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.contract import RoadKind
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as fixtures
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.event_fixtures import bind_fixture


class ReviewTests(unittest.TestCase):
  setUp = fixtures.OfflineTests.setUp
  tearDown = fixtures.OfflineTests.tearDown
  event = fixtures.OfflineTests.event
  provider = fixtures.OfflineTests.provider
  observe = fixtures.OfflineTests.observe
  warm = fixtures.OfflineTests.warm

  def setup_review(self, **kwargs):
    self.event(**kwargs)
    self.p = self.provider()
    self.road = self.p.store.link(self.p.store.db.execute('SELECT * FROM links WHERE id="a"').fetchone())
    self.bound = dict(self.db.execute('SELECT * FROM events').fetchone()) if self.db.row_factory else dict(
      self.p.store.db.execute('SELECT * FROM events').fetchone())
    self.proof = review.attributes(self.bound)['event_review']

  def reason(self, event=None, road=None, neighbors=None, dataset_id='synthetic-test', today=fixtures.TODAY):
    return review.validate_review(event or self.bound, road or self.road, neighbors if neighbors is not None else [self.road], dataset_id, today)

  def mutated(self, **changes):
    event = deepcopy(self.bound)
    attrs = review.attributes(event)
    attrs['event_review'].update(changes)
    event['attributes'] = json.dumps(attrs)
    return event

  def test_complete_bound_camera_and_bump_reach_the_common_input(self):
    for kind in ('camera', 'bump'):
      self.db.execute('DELETE FROM events')
      self.db.execute('DELETE FROM bounds')
      self.db.execute('DELETE FROM links')
      self.setup_review(kind=kind)
      self.assertEqual(self.reason(), '')
      result = self.warm(self.p)
      self.assertTrue(any(event.kind == RoadKind(kind) for event in result.road_input.snapshot.constraints))

  def test_flag_and_legacy_booleans_do_not_authorize(self):
    self.setup_review()
    attrs = review.attributes(self.bound)
    attrs.pop('event_review')
    attrs.update(enforcement_direction_verified=True, target_road_position_verified=True)
    self.bound['attributes'] = json.dumps(attrs)
    self.assertEqual(self.reason(), 'reviewRequired')
    self.db.execute('UPDATE events SET attributes=?', (self.bound['attributes'],))
    self.db.commit()
    result = self.warm(self.p)
    self.assertEqual(result.event_review_reasons, ('reviewRequired',))
    self.assertFalse(any(event.kind == RoadKind.CAMERA for event in result.road_input.snapshot.constraints))

  def test_event_fields_and_road_geometry_cannot_reuse_review(self):
    self.setup_review()
    for key, value in [('target_kph', 90.), ('along_m', 160.), ('lon', fixtures.point(155)[0]),
                       ('updated', '2026-09-14'), ('id', 'copied-id'), ('link_id', 'other')]:
      with self.subTest(key=key):
        self.assertEqual(self.reason({**self.bound, key: value}), 'reviewBindingChanged')
    self.assertEqual(self.reason(road=replace(self.road, speed_kph=60.)), 'reviewBindingChanged')
    self.assertEqual(self.reason(dataset_id='replacement'), 'reviewBindingChanged')
    self.assertEqual(self.reason(neighbors=[self.road, fixtures.link('new-road', y=10.)]), 'reviewBindingChanged')

  def test_claims_and_evidence_expire_without_renewal_by_review(self):
    self.setup_review()
    self.assertEqual(self.reason(today=date(2026, 10, 2)), 'reviewExpiredOrFuture')
    self.assertEqual(self.reason(self.mutated(reviewed_at='2026-09-16')), 'reviewExpiredOrFuture')
    proofs = deepcopy(self.proof['evidence'])
    proofs[0]['observed_at'] = '2020-01-01'
    self.assertEqual(self.reason(self.mutated(evidence=proofs)), 'staleEvidence')
    for role in review.ROLES:
      claims = deepcopy(self.proof['claims'])
      claims[role]['evidence_ids'] = []
      self.assertEqual(self.reason(self.mutated(claims=claims)), 'missingEvidenceClaim')

  def test_review_cannot_predate_the_data_it_claims_to_check(self):
    self.setup_review(updated='2026-09-14')
    self.assertEqual(self.reason(), 'reviewPredatesData')

  def test_unknown_signal_and_unpaired_section_ignore_claimed_semantics(self):
    self.setup_review()
    for changes in ({'enforcement_code': '02'}, {'enforcement_code': '01+bad'},
                    {'section_position': '01', 'section_length': '3.3'}):
      attrs = review.attributes(self.bound)
      attrs.update(changes)
      attrs['semantic'] = {'status': 'pointCandidate'}
      event = {**self.bound, 'attributes': json.dumps(attrs)}
      self.assertIn(self.reason(event), ('noSpeedEnforcement', 'unknownEnforcement', 'sectionNeedsPair'))

  def test_bad_review_structures_never_raise_or_pass(self):
    self.setup_review()
    for value in (None, [], True, {}, 'yes'):
      attrs = review.attributes(self.bound)
      attrs['event_review'] = value
      self.assertTrue(self.reason({**self.bound, 'attributes': json.dumps(attrs)}))
    for key, value in [('evidence', [None]), ('claims', []), ('target', None), ('reviewer', True)]:
      self.assertTrue(self.reason(self.mutated(**{key: value})))

  def test_opposite_direction_offset_boundary_and_self_crossing_are_withheld(self):
    self.setup_review()
    target = deepcopy(self.proof['target'])
    for changes, expected in [({'bearing_deg': 270.}, 'directionMismatch'),
                              ({'latitude': fixtures.point(150, 10)[1]}, 'targetOffRoad'),
                              ({'along_m': 140.}, 'targetOffRoad')]:
      self.assertEqual(review.target_reason(self.bound, self.road, {**target, **changes}, [self.road]), expected)
    near_start = {**target, 'longitude': fixtures.point(2)[0], 'along_m': 2.}
    close_event = {**self.bound, 'lon': fixtures.point(2)[0]}
    self.assertEqual(review.target_reason(close_event, self.road, near_start, [self.road]), 'targetAtLinkBoundary')
    crossed = replace(self.road, points=(fixtures.point(0), fixtures.point(200), fixtures.point(0)))
    self.assertEqual(review.target_reason(self.bound, crossed, target, [crossed]), 'ambiguousTargetGeometry')

  def test_parallel_or_intersecting_target_is_not_resolved_by_name(self):
    self.setup_review()
    for other in (fixtures.link('adjacent', y=3.),
                  replace(fixtures.link('crossing'), points=(fixtures.point(150, -30), fixtures.point(150, 30)))):
      self.assertEqual(review.target_reason(self.bound, self.road, self.proof['target'], [self.road, other]), 'ambiguousTargetRoad')

  def test_event_on_reverse_or_adjacent_link_never_reaches_selected_path(self):
    self.event()
    opposite = fixtures.link('opposite', 300., 0., 0., 'r1', 'r0')
    other = fixtures.link('adjacent', y=30.)
    p = self.provider(fixtures.link(), opposite, other)
    for event_id, road in [('reverse-event', opposite), ('adjacent-event', other)]:
      raw = dict(p.store.db.execute('SELECT * FROM events WHERE id="test-camera"').fetchone())
      raw.update(id=event_id, link_id=road.id, lat=road.points[0][1])
      attrs = review.attributes(raw)
      attrs.pop('event_review')
      raw['attributes'] = json.dumps(attrs)
      bound = bind_fixture(raw, road, p.store)
      self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)', tuple(bound[k] for k in
                      ('id', 'kind', 'lon', 'lat', 'target_kph', 'updated', 'source', 'attributes', 'link_id', 'along_m', 'verified')))
    self.db.execute('DELETE FROM events WHERE id="test-camera"')
    self.db.commit()
    result = self.warm(p)
    self.assertFalse(any(e.kind in (RoadKind.CAMERA, RoadKind.BUMP) for e in result.road_input.snapshot.constraints))


if __name__ == '__main__':
  unittest.main()
