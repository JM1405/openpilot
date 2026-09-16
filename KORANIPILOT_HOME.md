# Koranipilot B1 home reception candidate

This branch is a **comma four home test**, not a driving release.
C4 boot, native UI and wireless phone reception have not yet been validated.

## Installation

Enter `installer.comma.ai/JM1405/koranipilot-b1-home` on the comma setup screen
after this branch has been published. This is a separate branch; B0 is unchanged.
After boot, open settings → **폰 연결** → **모드** → **집 수신 켜기**.
Home reception is never enabled automatically and must be selected again after
restart or loss of the required device/panda state. Approve pairing on the C4.
Use the Android manager v0.11 route-aware build on the same network.

## Scope

The launcher enables the phone menu and local pinned HTTPS service only.
Phone setting writes, model changes, road IPC and Korean driving overlays are OFF.
Home reception requires fresh offroad/no-ignition/noOutput device and panda data.
No synthetic device state is used. Missing state blocks reception.
The D219 phone/route implementation is included, but its schema, planner and
manager integration changes are excluded to retain the prebuilt release runtime.
The original sunnypilot driving functionality still exists: this profile does
not turn the entire device into a no-output firmware. Test at home, off vehicle.

## Return to sunnypilot

Settings → device → uninstall sunnypilot → confirm. On the setup screen,
select custom software and enter `install.sunnypilot.ai/release-mici`.
This reinstalls the currently offered sunnypilot release; previous settings need
not be preserved. No SSH registration or exact settings backup is required.
These menu labels are verified against source, not an observed device session.

Base: sunnypilot release-mici 6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2.
The upstream AGNOS requirement and prebuilt binaries are retained.
Upstream LICENSE and font OFL/provenance remain included.
