"""Single-file road snapshots. Validate before use; never modify the source database."""
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .offline import RoadStore


@dataclass(frozen=True)
class DatasetInfo:
  state: str = 'missing'
  dataset_id: str = ''
  revision: int = 0
  latest_road_date: str = ''
  links: int = 0
  verified_events: int = 0

  def wire(self):
    return dict(zip(('state', 'datasetId', 'revision', 'latestRoadDate', 'links', 'verifiedEvents'), asdict(self).values(), strict=True))


def signature(path):
  path = Path(path)
  if not path.is_absolute() or not path.is_file():
    raise FileNotFoundError('absolute snapshot file required')
  s = path.stat()
  # Mutable/WAL snapshots can span files and are not an atomic handoff.
  if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
    raise ValueError('snapshotSidecar')
  return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def inspect_snapshot(path, revision=0):
  before = signature(path)
  store = RoadStore(path)
  try:
    store.db.execute('PRAGMA busy_timeout=50')
    store.db.execute('PRAGMA query_only=ON')
    if store.db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
      raise ValueError('snapshotJournalMode')
    if store.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
      raise ValueError('snapshotCorrupt')
    for table, columns in {
      'links': 'pk,id,start,end,name,points,speed_kph,updated,road_use,rest_veh,connector',
      'events': 'id,kind,lon,lat,target_kph,updated,source,attributes,link_id,along_m,verified',
      'bounds': 'pk,minlon,maxlon,minlat,maxlat',
    }.items():
      store.db.execute(f'SELECT {columns} FROM {table} LIMIT 0')
    identity = store.metadata.get('dataset_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', identity):
      raise ValueError('snapshotIdentity')
    count, latest = store.db.execute('SELECT count(*),max(updated) FROM links').fetchone()
    if not 0 < count <= 10_000_000 or count != store.db.execute('SELECT count(*) FROM bounds').fetchone()[0]:
      raise ValueError('snapshotIndex')
    if store.db.execute('SELECT 1 FROM links l LEFT JOIN bounds b ON l.pk=b.pk WHERE b.pk IS NULL LIMIT 1').fetchone():
      raise ValueError('snapshotIndex')
    verified = store.db.execute('SELECT count(*) FROM events WHERE verified=1').fetchone()[0]
    if verified > 10_000_000:
      raise ValueError('snapshotTooLarge')
    try:
      latest = date.fromisoformat(latest).isoformat()
    except (ValueError, TypeError):
      latest = ''
    if signature(path) != before:
      raise ValueError('snapshotChangedDuringCheck')
    return store, before, DatasetInfo('ready', identity, revision, latest, count, verified)
  except Exception:
    store.close()
    raise
