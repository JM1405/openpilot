"""Approved phone API -> two serialized IPC hops -> isolated selection proposal."""
import hashlib
import os
import sqlite3
import struct
import unittest
from dataclasses import replace

from . import test_b1_integration as base
from . import test_route_integration as routes
from . import test_offline as fixtures
from .test_curves import curved_link
from .test_offline import link, point
from ..selection import RoadCandidateSelector


class SelectionIntegrationTests(base.Fixture, unittest.TestCase):
  setUp = base.B1IntegrationTests.setUp
  report = base.B1IntegrationTests.report
  tick = routes.RouteIntegrationTests.tick
  send_route = routes.RouteIntegrationTests.send_route

  def prepare(self, mode, kind):
    fixture = fixtures.OfflineTests()
    fixture.setUp()
    self.addCleanup(fixture.tearDown)
    road = curved_link() if kind == 'curve' else replace(link(), points=tuple(point(x) for x in range(0,301,5)))
    if kind == 'camera':
      fixture.event(at=100.)
    fixture.provider(road)
    fixture.db.close()
    # Keep its cleanup valid after closing the writer before atomic replacement.
    fixture.db = sqlite3.connect(':memory:')
    os.replace(fixture.path, self.fixture.path)
    if mode == 'route':
      digest = hashlib.sha256(b''.join(struct.pack('>dd', *p) for p in road.points)).hexdigest()
      self.route_frame = dict(protocol=2, challenge='', seq=1, revision=1, state='active',
        destination='합성 시험', shape_id=digest, point_count=len(road.points), geometry_status='full',
        total_m=road.length, total_s=100, remaining_m=road.length-20, remaining_s=90,
        location_age_ms=0, matched=True)
      self.send_route()
      api = self.service.route
      api.chunk(self.token, self.csrf, dict(challenge=api.challenge(self.token)['challenge'], seq=2,
        revision=1, shape_id=digest, offset=0, points=[list(p) for p in road.points]))
    return RoadCandidateSelector()

  def choose(self, selector, previous=0., active=True, base_accel=0.):
    return selector.update(self.reader.road, now=self.now, valid_until=self.reader.valid_until,
      v_ego=20., a_ego=0., previous_accel=previous, base_accel=base_accel, base_source='e2e',
      should_stop=False, accel_bounds=(-3.5, 2.), action_t=.3, dt=.1, active=active, enabled=True)

  def exercise(self, mode, kind):
    selector = self.prepare(mode, kind)
    previous = 0.
    for x in (20., 22., 24., 26., 28., 30.):
      self.tick(x)
      result = self.choose(selector, previous)
      selector.observe_applied(result.selected)
      previous = result.acceleration
    self.assertEqual(result.plan.kind, kind)
    self.assertTrue(result.selected)
    self.assertLess(result.acceleration, 0.)
    # The independently computed proposal does not change the actual observer.
    self.assertFalse(self.report().selected)
    self.assertTrue(self.report().observationOnly)
    self.assertEqual(self.report().selectedAcceleration, 0.)
    self.tick(32.)
    self.assertFalse(self.choose(selector, previous, active=False).selected)
    self.service.disconnect(self.token)
    self.now += .05
    self.publisher.publish(self.api.sample())
    self.deriver.tick()
    self.observer.update(self.sm, self.cp, .05, 0., 'e2e', True)
    self.assertIsNone(self.reader.road)
    self.assertFalse(self.choose(selector, previous, active=False).selected)
    self.assertEqual(self.store.writes, [])

  def test_free_camera(self):
    self.exercise('free', 'camera')

  def test_free_curve(self):
    self.exercise('free', 'curve')

  def test_route_camera(self):
    self.exercise('route', 'camera')

  def test_route_curve(self):
    self.exercise('route', 'curve')
