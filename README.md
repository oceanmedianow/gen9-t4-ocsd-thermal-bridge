# Gen9 T4 OCSD Thermal Bridge

Experimental reference implementation by **Josh Murphy (Ocean Media Now)**,
[oceanmedianow.com](https://www.oceanmedianow.com).
[Original repository](https://github.com/oceanmedianow/gen9-t4-ocsd-thermal-bridge) | [MIT license](LICENSE)

This project feeds an NVIDIA Tesla T4 temperature into an HPE ProLiant DL380
Gen9's OCSD option-card record. Stock iLO 4 then sees a PCI temperature and
uses its own fan-control algorithm. The daemon does **not** set fan PWM or
modify iLO firmware.

```text
NVIDIA temperature -> host OCSD record 2 -> iLO PCI sensor -> HPE fan control
```

**This is not an HPE-supported integration or a universal Gen9 fan fix.** This
independent project is not affiliated with HPE or NVIDIA. OCSD
publication here is reverse-engineered and requires root access to `/dev/mem`.
An incorrect write could damage the running system's management state. Read
[SAFETY.md](SAFETY.md) before trying it. No install script or binary firmware
patch is supplied.

## What Was Observed

On one DL380 Gen9 with stock iLO 4 v2.82, BIOS `OptimalCooling`, the chassis
high-performance fans, and a Tesla T4, the host-published sensor appeared as
`21-PCI 1`. During a five-request sustained inference test, the T4 peaked at
65 C, about 71 W and 98% utilization; fans 4-6 rose to approximately
56/70/70%, with no NVIDIA thermal slowdown. Reboot, publisher crash recovery,
stale-data response, controlled idle shutdown, and a warm stop were also
exercised on that chassis. The iLO PCI reading was approximately **T4 + 15 C**
there; this offset is an observation, not a universal conversion rule.

Those results establish a working path on the tested machine only. They do
not certify other firmware revisions, chassis, GPUs, OCSD layouts, or cooling
hardware. The installed host version remains separate from this public copy.
This public adaptation uses generic names, configurable workload-service
targets, a manual registration helper, an explicit iLO-reset opt-in flag,
cool-GPU reset guard, and repeated hot-workload stop requests. Those changes
have offline tests but have **not** been requalified on the live chassis.
The example service is manual-start only; this release does not provide
unattended boot recovery.

## Scope And Requirements

- Linux and systemd; the tested host used Python 3.6.
- An exact `ProLiant DL380 Gen9` product match, a single 16 KiB OCSD SMBIOS
  type-229 allocation, two valid native records, and an empty third record.
- A Tesla T4 at the source's pinned PCI identity `00000000:05:00.0`, mapped
  to OCSD bus 5/device 0. Other placement needs code review and new tests.
- NVIDIA `nvidia-smi`, `ipmitool`, and root access to `/dev/mem` and IPMI.
- Explicit systemd workload units in `/etc/gen9-t4-ocsd.conf`; the daemon
  refuses to start if those units are missing or not loaded.
- `ilorest` only for an operator-approved iLO registration reset. The manual
  helper does not reset iLO unless invoked with `--allow-ilo-reset`, and it
  requires configured workloads to be inactive.

The code intentionally fails on unrecognized layouts or occupied records.
Do **not** bypass these checks to make another machine appear compatible.

## Repository Contents

- `gen9_t4_ocsd.py`: temperature publisher, ownership checks, watchdog,
  thermal-stop request, and bounded cool-down restoration.
- `gen9_t4_ocsd_register.py`: manual iLO registration check and guarded reset.
- `examples/systemd/`: **examples**, not installed or enabled by this repo.
- `examples/gen9-t4-ocsd.conf.example`: required workload-unit configuration.
- `tests/`: synthetic OCSD fixture and offline safety tests. No host memory
  snapshot, call data, credentials, or local backup is included.
- [PROTOCOL.md](PROTOCOL.md): the observed layout and its uncertainty.

Run the offline tests on Linux with `python3 -m unittest discover -s tests -v`.
No GPU or iLO is needed for those tests.

## Evaluation Path

1. Read [SAFETY.md](SAFETY.md), obtain console/iLO access, and preserve a
   private rollback snapshot. Never upload a raw OCSD memory dump to GitHub.
2. Confirm the exact chassis, iLO revision, GPU PCI identity, current cooling
   hardware, OCSD layout, and vacant record. Treat every mismatch as a stop.
3. Review the source and example units. Define **all** GPU workload systemd
   services in a root-owned, mode-0600 `/etc/gen9-t4-ocsd.conf`. Ensure they
   can be stopped without affecting unrelated production services. For an
   LLM machine these might be the local inference or model-server units;
   the example names are placeholders and must be replaced.
4. Stage the publisher under the path shown in the example unit only after
   adapting and reviewing every path and privilege. The unit has no `[Install]`
   section and must be started manually. It is not a boot-enabled thermal
   safeguard. Because this chassis may require an iLO reset to discover the
   published sensor, a manual start can remain `activating` until registration
   succeeds or the five-minute startup timeout expires. Use a separate console
   during this test; `systemctl start --no-block gen9-t4-ocsd.service` avoids
   waiting at the shell for the readiness notification.
5. Check registration manually with `gen9_t4_ocsd_register.py` while the
   publisher is running. If the sensor is absent, independently confirm all
   GPU work is idle and cool before deciding whether to invoke the helper
   with `--allow-ilo-reset` and the actual workload-unit environment. This
   resets iLO, not the host, but interrupts iLO management sessions. The
   helper cannot detect GPU processes outside configured systemd units.
6. Watch `nvidia-smi`, `ipmitool sdr get '21-PCI 1'`, all fan duties, and iLO
   logs together under bounded load. Verify cool-down and restoration.

**Do not enable these examples at boot.** There is no tested unattended
registration and recovery sequence. If iLO does not discover the sensor,
the publisher will not signal ready and systemd will eventually fail the
start. GPU work must remain stopped until an operator verifies sensor and fan
behavior. A boot-capable release needs separate hardware acceptance testing.

For example, after independent GPU-idle and console checks, an operator could
invoke the helper manually with the **actual** service names:

```sh
sudo env OCSD_WORKLOAD_UNITS="your-llm.service" \
  /usr/bin/python3 /opt/gen9-t4-ocsd/gen9_t4_ocsd_register.py --allow-ilo-reset
```

The command fails if the named unit is not loaded, is active, or the GPU is
still warm. It is never run automatically by the example service.

## Limits

This project is not a substitute for the correct fan kit, air baffles,
blanking panels, firmware, power budget, or independent thermal monitoring.
The model-specific sensor name, observed iLO offset, GPU PCI identity, and
85 C fail-high value must not be generalized without measurement. The daemon
stops only the configured systemd workloads; it does not stop arbitrary GPU
processes or guarantee that the GPU will cool after a stop request.

Contributions and chassis-specific test results are welcome. Please see
[CONTRIBUTING.md](CONTRIBUTING.md). The copyright and MIT notice must be kept
as required by the license; additional blog, video, or forum credit is
appreciated but not a license condition.
