"""Synthetic evidence only. No public record is independently approved by tests."""
import json
from copy import deepcopy

from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.event_review import (
  POLICY, ROLES, attributes, digest, event_digest, link_digest, neighbors_digest,
)
from openpilot.sunnypilot.selfdrive.controls.lib.road_constraints.offline import project


def review_fixture(event, road, target=None):
  _, along, bearing = project((event['lon'], event['lat']), road.points)
  return {'event_id': event['id'], 'event_sha256': event_digest(event), 'decision': 'confirmed',
          'reviewer': 'synthetic test fixture', 'reviewed_at': '2026-09-01', 'expires_at': '2026-10-01',
          'link_id': road.id, 'direction': road.ref.direction, 'link_sha256': link_digest(road),
          'target_kph': event['target_kph'],
          'target': target or {'longitude': event['lon'], 'latitude': event['lat'], 'bearing_deg': bearing,
                               'along_m': event['along_m'] if event['along_m'] is not None else along},
          'evidence': [{'id': 'fixture', 'sha256': digest('synthetic evidence'), 'uri': 'field-record:synthetic-only',
                        'locator': 'synthetic scene truth', 'observed_at': '2026-09-01'}],
          'claims': {role: {'statement': 'synthetic fixture only: '+role, 'evidence_ids': ['fixture']} for role in ROLES}}


def bind_fixture(event, road, store, target=None):
  event = deepcopy(dict(event))
  record = review_fixture(event, road, target)
  event['along_m'] = record['target']['along_m']
  record.update(policy=POLICY, dataset_id=store.metadata['dataset_id'],
                bound_event_sha256=event_digest(event), neighbors_sha256=neighbors_digest(store.nearby(
                  record['target']['longitude'], record['target']['latitude'], 15.)))
  attrs = attributes(event)
  attrs['event_review'] = record
  event['attributes'] = json.dumps(attrs)
  return event
