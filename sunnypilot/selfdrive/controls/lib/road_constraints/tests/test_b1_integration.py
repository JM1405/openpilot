"""B1 approved GPS -> actual Cap'n Proto hops -> SQLite -> shadow candidate.

Synthetic location, road, clock and car state. No vehicle process or Params writes.
"""
import ast
import hashlib
import os
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from cereal import custom
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_runtime import PhoneRuntime
from openpilot.selfdrive.ui.sunnypilot.mici.korean.phone_settings import PhoneError
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_management import Store, SM
from openpilot.selfdrive.ui.sunnypilot.mici.korean.tests.test_phone_home import HomeSM
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints import ipc
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.observer import RoadObserver
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.roadinputd import RoadInputService
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests import test_offline as fixtures
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.tests.test_live import Fixture


class Mailbox:
  def __init__(self):
    self.packet = None

  def send(self, data):
    self.packet = data

  def receive(self, **kwargs):
    data, self.packet = self.packet, None
    return data


class Vehicle(dict):
  def __init__(self):
    super().__init__(carState=NS(vEgo=20., aEgo=0., gasPressed=False, brakePressed=False),
      carControl=NS(longActive=True, cruiseControl=NS(override=False)))
    self.valid = True

  def all_checks(self, **kwargs):
    return self.valid


class B1IntegrationTests(Fixture, unittest.TestCase):
  def setUp(self):
    self.enterContext(patch.dict(os.environ, KOREAN_ROAD_INPUT='1'))
    self.now = 100.
    self.store = Store()
    self.runtime = PhoneRuntime(self.store, clock=lambda: self.now, allow_settings_change=False)
    self.runtime.update(SM(self.now), 10, True)
    self.addCleanup(self.runtime.close)
    self.service = self.runtime.service
    self.api = self.service.road_input
    self.token, self.csrf = self.pair()
    self.sync_seq = self.seq = 0
    self.sync = None
    self.fixture = fixtures.OfflineTests()
    self.fixture.setUp()
    self.addCleanup(self.fixture.tearDown)
    self.fixture.event(at=70.)
    self.fixture.provider(fixtures.link())  # binds synthetic event review/provenance
    self.location_socket, self.road_socket = Mailbox(), Mailbox()
    clock = lambda: self.now
    self.publisher = ipc.LocationPublisher(clock=clock, socket=self.location_socket)
    self.deriver = RoadInputService(str(self.fixture.path), clock=clock, today=lambda: fixtures.TODAY,
      reader=ipc.LocationReader(clock=clock, socket=self.location_socket),
      publisher=ipc.RoadPublisher(clock=clock, socket=self.road_socket))
    self.addCleanup(self.deriver.close)
    self.reader = ipc.RoadReader(clock=clock, socket=self.road_socket)
    self.observer = RoadObserver(self.reader, clock=clock)
    self.addCleanup(self.observer.close)
    self.sm = Vehicle()
    self.cp = NS(openpilotLongitudinalControl=True, longitudinalActuatorDelay=.2)
    self.synchronize()

  def tick(self, x):
    self.receive(x)
    self.runtime.update(SM(self.now), 10, True)
    self.publisher.publish(self.api.sample())
    self.deriver.tick()
    self.observer.update(self.sm, self.cp, .05, 0., 'e2e', True)

  def warm(self):
    for x in (20., 22., 24., 26.):
      self.tick(x)

  def install_curve_dataset(self):
    from .test_curves import curved_link
    from ..offline import create_schema, insert_link
    path = self.fixture.path.with_name('curve.sqlite')
    with sqlite3.connect(path) as db:
      create_schema(db)
      db.execute("INSERT INTO metadata VALUES('dataset_id','synthetic-curve-test')")
      insert_link(db, curved_link())
    os.replace(path, self.fixture.path)

  def test_curve_crosses_ipc_into_observer_and_expires(self):
    self.install_curve_dataset()
    self.warm()
    self.assertEqual(self.observer.plan.kind, 'curve')
    self.assertLess(self.observer.plan.acceleration, 0.)
    report = self.report()
    self.assertTrue(report.observationOnly)
    self.assertTrue(report.hasCandidate)
    self.assertFalse(report.selected)
    self.assertEqual(report.selectedAcceleration, 0.)
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.deceleration import explain
    self.assertEqual(explain(report, self.now).detail, '커브 후보 · 제어 미적용')
    self.now += .21
    self.assertFalse(self.report().hasCandidate)
    self.assertEqual(self.report().rejection, 'inputExpired')

  def report(self):
    report = custom.LongitudinalPlanSP.new_message().roadConstraint
    self.observer.publish(report)
    return report

  def tearDown(self):
    self.assertEqual(self.store.writes, [])

  def test_full_pipeline_produces_shadow_candidate_and_never_selects_it(self):
    self.warm()
    self.assertEqual(self.observer.plan.status, 'constraint')
    self.assertEqual(self.observer.plan.event_id, 'test-camera')
    self.assertLess(self.observer.plan.acceleration, 0.)
    report = self.report()
    self.assertTrue(report.observationOnly)
    self.assertTrue(report.hasCandidate)
    self.assertFalse(report.selected)
    self.assertEqual(report.selectedSource, 'e2e')
    self.assertEqual(report.selectedAcceleration, 0.)
    from openpilot.selfdrive.ui.sunnypilot.mici.korean.deceleration import explain
    display = explain(report, self.now)
    self.assertEqual(display.title, '도로 후보 관찰')
    self.assertIn('제어 미적용', display.detail)
    self.assertFalse(display.selected)

  def test_source_ttl_survives_fresh_publication_and_removes_candidate(self):
    self.warm()
    previous = self.api.sample()
    self.now += .21
    self.publisher.publish(previous)
    self.deriver.tick()
    self.observer.update(self.sm, self.cp, .05, 0., 'e2e', True)
    self.assertIsNone(self.observer.plan.acceleration)
    self.assertFalse(self.report().hasCandidate)

  def test_report_cannot_republish_an_expired_candidate(self):
    self.warm()
    self.now += .21
    self.assertFalse(self.report().hasCandidate)
    self.assertEqual(self.report().rejection, 'inputExpired')

  def test_revoke_and_stop_remove_the_input(self):
    self.warm()
    self.service.disconnect(self.token)
    self.publisher.publish(self.api.sample())
    self.deriver.tick()
    self.observer.update(self.sm, self.cp, .05, 0., 'e2e', True)
    self.assertIsNone(self.observer.plan.acceleration)
    self.assertFalse(self.report().selected)

  def test_brake_gas_cancel_invalid_vehicle_never_produce_candidate(self):
    for mode in ('brake', 'gas', 'cancel', 'invalid', 'stock'):
      with self.subTest(mode=mode):
        self.sm = Vehicle()
        self.cp.openpilotLongitudinalControl = mode != 'stock'
        self.sm['carState'].brakePressed = mode == 'brake'
        self.sm['carState'].gasPressed = mode == 'gas'
        self.sm['carControl'].longActive = mode != 'cancel'
        self.sm.valid = mode != 'invalid'
        self.warm()
        self.assertIsNone(self.observer.plan.acceleration)

  def test_home_mode_rejects_gps_even_with_module_available(self):
    self.service.disconnect(self.token)
    self.runtime.update(HomeSM(self.now), 10, True)
    self.service.device_set_home(True)
    self.token, self.csrf = self.pair()
    with self.assertRaises(PhoneError) as error:
      self.synchronize()
    self.assertEqual(error.exception.code, 'receive_only')

  def test_default_runtime_is_not_silently_enabled_by_imported_code(self):
    with patch.dict(os.environ, KOREAN_ROAD_INPUT='0'):
      runtime = PhoneRuntime(Store())
      try:
        self.assertFalse(runtime.road_input_available)
        self.assertEqual(runtime.service.road_input.view()['scope'], 'not_connected')
        with self.assertRaises(RuntimeError):
          runtime.attach_road_publisher()
      finally:
        runtime.close()

  def test_bad_source_cannot_interrupt_stock_loop(self):
    self.addCleanup(setattr, self.observer, 'source', self.reader)
    self.observer.source = lambda now: (_ for _ in ()).throw(ValueError('broken IPC'))
    self.observer.update(self.sm, self.cp, .05, -.7, 'lead0', True)
    self.assertEqual(self.observer.plan.rejection, 'observerError')
    self.assertAlmostEqual(self.report().selectedAcceleration, -.7)
    self.assertFalse(self.report().hasCandidate)
    self.observer.source = self.reader

  def test_stock_planner_actuation_statements_unchanged(self):
    # Compare against the exact pre-edit B1 source, not a different Sunny version.
    repo = Path(__file__).resolve().parents[6]
    after = repo/'selfdrive/controls/lib/longitudinal_planner.py'
    def update(path):
      tree = ast.parse(path.read_text())
      cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LongitudinalPlanner')
      return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'update')
    new = update(after)
    last = new.body.pop()
    self.assertIsInstance(last, ast.If)
    self.assertIn('self.road_observer', ast.unparse(last.test))
    # SHA-256 of the unmodified B1 update() AST captured before this integration.
    # Keeping the digest makes this check runnable without the desktop backup tree.
    self.assertEqual(hashlib.sha256(ast.dump(new).encode()).hexdigest(),
                     'c12838fa345ced7fa5ed0d4d0e3101bf316f728b4cd758c94d3f76df3fef50a7')
