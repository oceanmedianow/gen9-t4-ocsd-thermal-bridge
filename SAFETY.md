# Safety And Recovery

This code writes a reverse-engineered OCSD record in physical memory as root.
It has been demonstrated on one specific DL380 Gen9, not certified by HPE.
Use it only if you can recover the machine locally and accept the risk of
management-controller misbehavior or inadequate cooling.

## Before Any Write

- Keep stock iLO firmware and the complete, correct physical air path.
- Verify the exact product, GPU identity, sensor mapping, firmware, and fan
  hardware; do not infer compatibility from the Gen9 label alone.
- Confirm that a unique SMBIOS type-229 OCSD allocation exists, its header and
  native records validate, record 2 is empty, and no other publisher owns it.
- Preserve the original OCSD state in a **private** rollback location. Raw
  physical-memory snapshots do not belong in a public issue or repository.
- Arrange an operator-controlled maintenance window, console access, and a
  known way to stop GPU work. A remote-only recovery plan is insufficient.
- Configure real systemd GPU workload services; a missing or wrong unit means
  the thermal-stop action may not stop the workload.

## Runtime Invariants

The publisher writes only its claimed record and the device-count header.
It verifies writes, validates ownership on restart, and refuses to reclaim an
unknown record. If GPU telemetry fails it publishes 85 C and requests the
configured workloads stop. At 82 C it requests a stop. If iLO stops tracking
the sensor, it requests a stop and fails. Its systemd watchdog is intended to
restart a stalled publisher before iLO treats updates as stale.

These are risk reductions, **not guarantees**. In the tested chassis, stale
OCSD data caused iLO to drive fans to 100%, but other firmware may behave
differently. Monitor the actual GPU and fan telemetry; do not rely only on the
service's `active` state.

## Stop And Rollback

Stopping the publisher asks configured GPU workloads to stop, continues to
publish during cool-down, then restores the original header and empty slot
only after three cool samples at or below 55 C. If the GPU stays hot, sensor
data is lost, ownership changes, or restoration cannot be verified, it leaves
the OCSD record in place rather than blindly writing over an unknown state.
That failure requires operator attention and a documented maintenance
recovery; do not issue ad hoc `/dev/mem` writes.

The registration helper is manual. Without `--allow-ilo-reset` it only checks
registration. An operator may invoke it with that flag after independently
verifying all GPU activity is idle.
It then checks the configured workload units are loaded and inactive, takes
three cool GPU samples, and checks that the publisher record exists and the
sensor is absent before resetting
**iLO only**. It cannot detect unconfigured GPU processes. iLO reset
interrupts management access; never perform it without an independent
recovery path.

The example publisher unit has no boot-enable section. It is not an unattended
thermal safeguard: iLO may require an operator-approved reset to discover the
sensor, and systemd startup times out without registration. Keep GPU workloads
stopped until sensor and fan response are verified. Complete manual start,
load, telemetry-loss, restart, stop, and restoration checks on your own
hardware before considering any boot automation. Do not attempt a manual iLO
registration reset without a maintenance window and independent recovery path.
