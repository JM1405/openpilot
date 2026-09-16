"""Compact local pairing QR. Carries no private key and grants no approval."""
import ipaddress
import re
from urllib.parse import urlsplit


def pairing_payload(url, fingerprint, code):
  parsed = urlsplit(url)
  address = ipaddress.IPv4Address(parsed.hostname or '')
  local = any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
  if not local or parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
    raise ValueError('Invalid local pairing address')
  port = parsed.port or 443
  if not 1 <= port <= 65535 or not re.fullmatch(r'[a-fA-F0-9]{64}', fingerprint) or not re.fullmatch(r'[0-9]{6}', code):
    raise ValueError('Invalid pairing values')
  # All characters fit QR alphanumeric mode, keeping the physical code large.
  return f'KORANI1:{address}:{port}:{fingerprint.upper()}:{code}'


def qr_tiles(payload, x=304, y=12, size=216):
  import qrcode
  qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
  qr.add_data(payload)
  qr.make(fit=True)
  matrix = qr.get_matrix()
  scale = size // len(matrix)
  if scale < 3:
    raise ValueError('QR too dense for C4')
  left = x + (size - len(matrix) * scale) // 2
  top = y + (size - len(matrix) * scale) // 2
  tiles = []
  for row, values in enumerate(matrix):
    start = None
    for col, filled in enumerate(values + [False]):
      if filled and start is None:
        start = col
      elif not filled and start is not None:
        tiles.append((left + start * scale, top + row * scale, (col-start)*scale, scale))
        start = None
  return tiles
