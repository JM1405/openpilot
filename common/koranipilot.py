"""Fork identity and explicit local usage acknowledgement; no UI imports."""
import os

NOTICE_VERSION = "koranipilot-home-1"


def enabled():
  return os.getenv("KOREAN_PHONE_LOCAL", "0") == "1"


def product_name():
  return "Koranipilot" if enabled() else "sunnypilot"


def brand_text(value):
  if not enabled():
    return value
  return value.replace("sunnypilot", "Koranipilot").replace("Sunnypilot", "Koranipilot").replace("써니파일럿", "고라니파일럿")


def notice_versions(upstream, sunny):
  # Reuse existing registered storage keys, with a distinct fork value.
  # This never records acceptance of an upstream service's terms/version.
  return (NOTICE_VERSION, NOTICE_VERSION) if enabled() else (upstream, sunny)


def accepted_notices(params, upstream, sunny):
  versions = notice_versions(upstream, sunny)
  return (params.get("HasAcceptedTerms") == versions[0],
          params.get("HasAcceptedTermsSP") == versions[1])


def local_data_root():
  from openpilot.system.hardware import PC
  from openpilot.system.hardware.hw import Paths
  return os.path.join(Paths.comma_home() if PC else "/data", "koranipilot")
