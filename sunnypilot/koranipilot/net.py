"""Local LAN / hotspot IPv4 discovery for C4 QR and UDP beacon."""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess

_EXCLUDED_IFACE_PREFIXES = ("lo", "rmnet", "ccmni", "wwan", "pdp_ip", "docker", "br-", "veth", "tun", "tap", "utun")
_PREFERRED_IFACE_ORDER = ("wlan", "ap", "usb", "rndis", "eth", "en")


def is_usable_lan_ip(addr: str | None) -> bool:
  if not addr:
    return False
  try:
    ip = ipaddress.IPv4Address(addr.strip())
  except ValueError:
    return False
  return ip.is_private and not ip.is_loopback and not ip.is_link_local


def _iface_rank(name: str) -> int:
  lower = name.lower()
  if lower.startswith(_EXCLUDED_IFACE_PREFIXES):
    return 999
  for idx, prefix in enumerate(_PREFERRED_IFACE_ORDER):
    if lower.startswith(prefix):
      return idx
  return 100


def _collect_from_ip_cmd() -> list[tuple[str, str]]:
  out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True, timeout=1.5)
  found: list[tuple[str, str]] = []
  for line in out.splitlines():
    match = re.match(r"^\d+:\s+(\S+)\s+inet\s+([0-9.]+)/\d+", line.strip())
    if match:
      found.append((match.group(1), match.group(2)))
  return found


def _collect_from_ifconfig() -> list[tuple[str, str]]:
  out = subprocess.check_output(["ifconfig"], text=True, timeout=1.5)
  found: list[tuple[str, str]] = []
  iface = ""
  for line in out.splitlines():
    hdr = re.match(r"^([A-Za-z0-9_.:-]+):\s+", line)
    if hdr:
      iface = hdr.group(1)
      continue
    m = re.search(r"\binet\s+([0-9.]+)\b", line)
    if m and iface:
      found.append((iface, m.group(1)))
  return found


def get_lan_ip() -> str | None:
  candidates: list[tuple[int, str]] = []
  for collector in (_collect_from_ip_cmd, _collect_from_ifconfig):
    try:
      pairs = collector()
    except Exception:
      continue
    for iface, addr in pairs:
      rank = _iface_rank(iface)
      if rank < 999 and is_usable_lan_ip(addr):
        candidates.append((rank, addr))
    if candidates:
      candidates.sort(key=lambda item: item[0])
      return candidates[0][1]

  for probe_target in ("192.168.43.1", "172.20.10.1", "10.0.0.1"):
    try:
      with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((probe_target, 7000))
        addr = sock.getsockname()[0]
      if is_usable_lan_ip(addr):
        return addr
    except OSError:
      continue

  return None


def get_broadcast_addresses(lan_ip: str | None) -> list[str]:
  targets: list[str] = []
  if is_usable_lan_ip(lan_ip):
    parts = lan_ip.split(".")
    if len(parts) == 4:
      targets.append(f"{parts[0]}.{parts[1]}.{parts[2]}.255")
  targets.append("255.255.255.255")
  return list(dict.fromkeys(targets))
