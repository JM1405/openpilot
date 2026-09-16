# Koranipilot B1 home reception candidate

This branch is a **comma four home test**, not a driving release.
The user reports installation and native UI entry. Actual QR pairing and
wireless phone reception have not yet been validated.

## Installation

Enter `installer.comma.ai/JM1405/koranipilot-b1-home` on the comma setup screen
after this branch has been published. This is a separate branch; B0 is unchanged.
After boot, open settings → **폰 연결** → **집 모드** → **집 수신 켜기**.
Home reception is never enabled automatically and must be selected again after
restart or loss of the required device/panda state. Approve pairing on the C4.
Use Android manager v0.12-qr-pairing on the same network. On the C4, choose
**QR로 폰 연결**. In the phone app choose **C4 연결하기**, allow camera access
when prompted and scan the C4 QR. Confirm **연결 요청** on the phone, then
**승인** on the C4. No address, 64-character fingerprint or code typing is needed.
The QR carries the complete TLS certificate pin and one-use pairing code. It
expires with the pairing window/device state; scanning never grants approval.
If Wi-Fi was unavailable at UI startup, **다시 확인** retries local address/TLS setup.
The main pairing/approval/home controls use 24–30 px text and 48–66 px tall targets.
Physical C4 display readability and real phone camera scanning remain unverified.

## Phone startup repair and product identity

The previous release tried to store local TLS identities under `/persist`,
which AGNOS mounts read-only. Identities now use `/data/koranipilot/phone_tls`
with private-key permissions 0600 and survive normal software updates.
Setup failures identify address, certificate or listener stages on screen.
The phone app remains v0.12; no new Android installation is needed if already updated.

Home, settings, updates and the local usage guide identify Koranipilot.
The home profile omits the Sunnylink card/consent step and gates off its
registration, uploader, status, backup and daemon paths. Saved upstream
consent is not changed. Optional comma services remain distinct.
Original license files are unchanged and readable from usage guide → open source.

On first boot after this update, explicitly confirm the Koranipilot usage guide.
The existing storage keys use the separate `koranipilot-home-1` marker, not an
upstream terms version. Hardware startup checks this same explicit marker;
existing training, driver checks and other start conditions remain required.
This changes the notice gate only, not driving planners, vehicle control or CAN.
81 Python tests pass, including local TLS and source/widget-double flow tests.
Actual C4 storage, screen rendering and wireless recovery remain unverified.

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

Settings → device → uninstall Koranipilot → confirm. On the setup screen,
select custom software and enter `install.sunnypilot.ai/release-mici`.
This reinstalls the currently offered sunnypilot release; previous settings need
not be preserved. No SSH registration or exact settings backup is required.
These menu labels are verified against source, not an observed device session.

Base: sunnypilot release-mici 6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2.
The upstream AGNOS requirement and prebuilt binaries are retained.
Upstream LICENSE and font OFL/provenance remain included.
