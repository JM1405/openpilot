"""Fresh authenticated SDK geometry -> independently matched road constraints.

No arbitrary camera speed, guessed heading, straight-line remaining distance or
manual-review bypass for static datasets. Uncertain SDK events are withheld.
"""
from dataclasses import replace
import json
import math
from .contract import RoadConstraint,RoadKind
from .offline import angle_delta,bearing,distance,project,project_segments

CODES={'KNSafetyCode_SpeedViolationCamera','KNSafetyCode_SignalAndSpeedViolationCamera','KNSafetyCode_BoxedSpeedViolationCamera'}
MAX_AGE=1.5


def point(value):
  return (isinstance(value,list) and len(value)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in value)
          and 124 <= value[0] <= 132 and 33 <= value[1] <= 39.5)


def geometry(value):
  if not isinstance(value,list) or len(value)!=3 or not all(point(p) for p in value):
    return False
  a,p,b=value
  return 8<=distance(a,p)<=25 and 8<=distance(p,b)<=25 and angle_delta(bearing(a,p),bearing(p,b))<=25


def parse(raw,now):
  if not raw:return None
  try:
    if len(raw)>8192:return None
    data=json.loads(raw)
    if set(data)!={'version','session','sequence','source_at','expires','events'} or data['version']!=1:return None
    if not isinstance(data['session'],str) or not 1<=len(data['session'])<=128 or type(data['sequence']) is not int or data['sequence']<1:return None
    if not all(type(data[k]) in (int,float) and math.isfinite(data[k]) for k in ('source_at','expires')):return None
    if not 0<=now-data['source_at']<MAX_AGE or not now<data['expires']<=data['source_at']+MAX_AGE+.000001:return None
    events=data['events']
    if not isinstance(events,list) or len(events)>8:return None
    ids=set()
    for e in events:
      if set(e)!={'id','code','limit_kph','geometry'} or not isinstance(e['id'],str) or not 1<=len(e['id'])<=80 or e['id'] in ids:return None
      if e['code'] not in CODES or type(e['limit_kph']) not in (int,float) or not math.isfinite(e['limit_kph']) or not 1<=e['limit_kph']<=130 or not geometry(e['geometry']):return None
      ids.add(e['id'])
    return data
  except (ValueError,TypeError,KeyError):return None


def merge(road,data,store,now):
  """Add eligible cameras only to the independently confirmed moving corridor."""
  if road is None or data is None:return road,0.,0
  # Revalidate even if the IPC packet was parsed on an earlier poll.
  data=parse(json.dumps(data),now)
  if data is None:return road,0.,0
  refs=road.context.path
  links=[];offset=0.
  for ref in refs:
    row=store.db.execute('SELECT * FROM links WHERE id=?',(ref.road_id,)).fetchone()
    if row is None:return road,0.,0
    link=store.link(row)
    if link.ref!=ref:return road,0.,0
    links.append((link,offset));offset+=link.length
  added=[]
  for event in data['events']:
    a,p,b=event['geometry'];course=bearing(a,b)
    options=[]
    for link,offset in links:
      gap,along,heading=project(p,link.points)
      if gap>8 or angle_delta(heading,course)>20 or along<20 or link.length-along<20:continue
      # Confirm both directed neighbors, rather than deriving direction from
      # the ego's heading or a camera type alone.
      ga,pa,ha=project(a,link.points);gb,pb,hb=project(b,link.points)
      if max(ga,gb)>8 or not pa<along<pb or angle_delta(ha,course)>25 or angle_delta(hb,course)>25:continue
      if any(abs(pos-along)>20 and other_gap<=gap+8 for other_gap,pos,_ in project_segments(p,link.points)):continue
      if any(other.id!=link.id and project(p,other.points)[0]<=gap+8 and angle_delta(project(p,other.points)[2],course)<145 for other in store.nearby(*p,radius_m=25)):continue
      target=offset+along-road.snapshot.reference_progress_m
      if not 0<=target<=1000:continue
      options.append(RoadConstraint('kakao:'+data['session']+':'+event['id'],RoadKind.CAMERA,link.ref,target,target,event['limit_kph']/3.6))
    if len(options)==1:added.extend(options)
  if not added:return road,0.,0
  # Keep the strongest target for duplicate physical camera locations, while
  # retaining all existing curve/section behavior and source provenance.
  events=list(road.snapshot.constraints)
  for event in added:
    duplicates=[e for e in events if e.kind==RoadKind.CAMERA and e.link==event.link and abs(e.start_m-event.start_m)<5]
    if duplicates and min(e.target_speed for e in duplicates)<=event.target_speed:continue
    events=[e for e in events if e not in duplicates];events.append(event)
  if len(events)>32:return road,0.,0
  snapshot=replace(road.snapshot,source=road.snapshot.source+'+kakao',source_at=min(road.snapshot.source_at,data['source_at']),constraints=tuple(events))
  return replace(road,snapshot=snapshot),data['expires'],len(added)
