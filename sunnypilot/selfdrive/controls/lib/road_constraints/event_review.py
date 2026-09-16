"""Evidence-bound point-event reviews. Hashes detect drift, not source truth.

No legacy boolean or road-name match authorizes an event. Offline review records
bind explicit evidence claims to one dataset, event and directed road geometry.
"""
import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import date

from .event_semantics import camera_semantics

POLICY = 'point-event-review-v1'
ROLES = ('source_identity', 'road_direction', 'target_position', 'target_speed')


def digest(value):
  return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def attributes(event):
  value = json.loads(event['attributes'])
  if not isinstance(value, dict):
    raise ValueError('invalidEventAttributes')
  return value


def event_digest(event):
  attrs = attributes(event)
  attrs.pop('event_review', None)
  return digest({key: attrs if key == 'attributes' else event[key] for key in
                 ('id', 'kind', 'lon', 'lat', 'target_kph', 'updated', 'source', 'attributes', 'link_id', 'along_m')})


def link_digest(road):
  return digest(asdict(road))


def neighbors_digest(roads):
  return digest([asdict(road) for road in sorted(roads, key=lambda road: road.id)])


def finite(value, low, high):
  return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def source_reason(event):
  """Recompute semantics from source fields, ignoring claimed semantic flags."""
  try:
    attrs = attributes(event)
    if event['kind'] == 'camera' and event['source'] == 'data.go.kr/15028200':
      semantic = camera_semantics({'REGLT_SE': attrs.get('enforcement_code'), 'LMTT_VE': event['target_kph'],
                                   'ROAD_ROUTE_DRC': attrs.get('direction_code'),
                                   'REGLT_SCTN_LC_SE': attrs.get('section_position') or '',
                                   'OVRSPD_REGLT_SCTN_LT': attrs.get('section_length') or ''})
      return '' if semantic['status'] == 'pointCandidate' else semantic['status']
    if event['kind'] == 'bump' and event['source'] == 'data.go.kr/15160269':
      return '' if attrs.get('shape') == '원호형' else 'unsupportedBumpShape'
    return 'unsupportedEventSource'
  except (TypeError, ValueError, KeyError):
    return 'invalidEventAttributes'


def target_reason(event, road, target, neighbors):
  from .offline import angle_delta, distance, project, project_segments
  if not isinstance(target, dict) or not all(finite(target.get(k), *limits) for k, limits in
      (('longitude', (124, 132.5)), ('latitude', (32, 39.8)), ('bearing_deg', (0, 359.999999)), ('along_m', (0, road.length)))):
    return 'invalidTargetPosition'
  point = (target['longitude'], target['latitude'])
  gap, along, course = project(point, road.points)
  if gap > 3 or abs(along-target['along_m']) > 1:
    return 'targetOffRoad'
  if angle_delta(course, target['bearing_deg']) > 15:
    return 'directionMismatch'
  if distance((event['lon'], event['lat']), point) > 100:
    return 'installationTargetTooFar'
  if min(along, road.length-along) < 8:
    return 'targetAtLinkBoundary'
  if any(abs(other-along) > 5 and dist <= gap+2 for dist, other, _ in project_segments(point, road.points)):
    return 'ambiguousTargetGeometry'
  for other in neighbors:
    if other.id == road.id:
      continue
    dist, _, heading = project(point, other.points)
    if dist <= 5 and angle_delta(heading, course) < 150:
      return 'ambiguousTargetRoad'
  return ''


def evidence_reason(review, today):
  try:
    if review['decision'] != 'confirmed' or not isinstance(review['reviewer'], str) or not 1 <= len(review['reviewer'].strip()) <= 120:
      return 'reviewNotConfirmed'
    reviewed, expires = date.fromisoformat(review['reviewed_at']), date.fromisoformat(review['expires_at'])
    if not reviewed <= today <= expires or not 0 <= (expires-reviewed).days <= 365:
      return 'reviewExpiredOrFuture'
    proofs = review['evidence']
    if not isinstance(proofs, list) or not 1 <= len(proofs) <= 12:
      return 'missingEvidence'
    ids = set()
    for item in proofs:
      if (not isinstance(item['id'], str) or not 1 <= len(item['id']) <= 64 or item['id'] in ids
          or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
          or not isinstance(item['locator'], str) or not 1 <= len(item['locator'].strip()) <= 500
          or not isinstance(item['uri'], str) or not item['uri'].startswith(('https://', 'field-record:'))
          or len(item['uri']) > 1000 or not reviewed >= date.fromisoformat(item['observed_at'])):
        return 'invalidEvidence'
      if not 0 <= (today-date.fromisoformat(item['observed_at'])).days <= 365:
        return 'staleEvidence'
      ids.add(item['id'])
    for role in ROLES:
      claim = review['claims'][role]
      if (not isinstance(claim['statement'], str) or not 1 <= len(claim['statement'].strip()) <= 1000
          or not isinstance(claim['evidence_ids'], list) or not claim['evidence_ids']
          or not set(claim['evidence_ids']) <= ids):
        return 'missingEvidenceClaim'
  except (KeyError, ValueError, TypeError, AttributeError):
    return 'invalidReview'
  return ''


def validate_review(event, road, neighbors, dataset_id, today):
  """Returns one withholding reason, or empty string for a current bound review."""
  from .offline import recent
  try:
    if event['verified'] != 1:
      return 'reviewRequired'
    reason = source_reason(event)
    if reason:
      return reason
    review = attributes(event).get('event_review')
    if not isinstance(review, dict) or review.get('policy') != POLICY:
      return 'reviewRequired'
    if (review['dataset_id'] != dataset_id or review['bound_event_sha256'] != event_digest(event)
        or review['link_sha256'] != link_digest(road) or review['neighbors_sha256'] != neighbors_digest(neighbors)
        or review['link_id'] != road.id or review['direction'] != road.ref.direction or event['link_id'] != road.id):
      return 'reviewBindingChanged'
    reason = evidence_reason(review, today)
    if reason:
      return reason
    if not recent(event['updated'], today, 365) or not road.usable(today, 730):
      return 'staleEventOrRoad'
    if max(date.fromisoformat(event['updated']), date.fromisoformat(road.updated)) > date.fromisoformat(review['reviewed_at']):
      return 'reviewPredatesData'
    if not finite(event['target_kph'], 1, 130) or event['along_m'] != review['target']['along_m']:
      return 'invalidTargetSpeedOrPosition'
    return target_reason(event, road, review['target'], neighbors)
  except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
    return 'invalidReview'
