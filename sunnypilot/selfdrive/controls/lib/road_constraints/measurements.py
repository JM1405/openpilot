"""Shared GPS measurement parsing. Missing low-speed heading never becomes zero."""

MOVING_SPEED = 2.0


def parse_measurements(values):
  lon, lat, course, speed, accuracy, heading_accuracy = values

  def number(value):
    # The range comparison also rejects NaN/inf and avoids overflow on huge ints.
    return type(value) in (int, float) and -1e9 <= value <= 1e9

  if not all(number(v) for v in (lon, lat, speed, accuracy)):
    raise ValueError('missingOrInvalidMeasurement')
  for value in (course, heading_accuracy):
    if value is None and speed < MOVING_SPEED:
      continue
    if not number(value):
      raise ValueError('missingOrInvalidMeasurement')
  if not (
    124 <= lon <= 132.5
    and 32 <= lat <= 39.8
    and 0 <= speed <= 70
    and 0 < accuracy <= 15
    and (course is None or 0 <= course < 360)
    and (heading_accuracy is None or 0 <= heading_accuracy <= (180 if speed < MOVING_SPEED else 20))
  ):
    raise ValueError('uncertainFix')
  if course is None or heading_accuracy is None:
    course = heading_accuracy = None
  return lon, lat, course, speed, accuracy, heading_accuracy
