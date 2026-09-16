#!/usr/bin/env python3
from openpilot.common.koranipilot import enabled as koranipilot_enabled
from openpilot.system.athena.manage_athenad import manage_athenad

if __name__ == '__main__' and not koranipilot_enabled():
  manage_athenad("SunnylinkDongleId", "SunnylinkdPid", 'sunnylinkd', 'sunnypilot.sunnylink.athena.sunnylinkd')
