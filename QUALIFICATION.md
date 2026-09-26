# Public-Copy Qualification

This log distinguishes the public reference code from the separately installed
publisher. It contains only sanitized observations; no raw OCSD memory, host
address, serial number, workload data, or credentials are included.

## 2026-09-25: Manual Idle Lifecycle

- Tested public commit `7f38276` on a ProLiant DL380 Gen9 with iLO 4 v2.82,
  System ROM P89, Tesla T4 at PCI `00000000:05:00.0`, and Python 3.6.15.
- All 26 synthetic tests passed on the host. The example service passed
  `systemd-analyze verify` and remained a static, manual-start unit.
- Before the swap, the T4 was idle at 39 C and iLO `21-PCI 1` read 54 C.
  The live OCSD layout and two native records validated against the public
  parser. A private prewrite snapshot was kept off-repository.
- The separately installed publisher stopped and restored header count 2
  with an empty record 2. The public publisher then claimed record 2 and
  reached systemd ready after iLO sensor confirmation, without an iLO reset.
- During the public run, the valid record counter advanced 50, 56, 61;
  T4 remained at 39 C and iLO at 54 C. Fans 4-6 were approximately 12-13%.
- Stopping the public publisher restored header count 2 and an empty record
  2. The separately installed publisher resumed and confirmed the iLO sensor.

This was an **idle lifecycle test**, not a sustained GPU-load or fault-injection
test. The public service was stopped afterward. Natural 16-bit rollover, boot
registration, fail-high fan response, and long-run stability of this exact
public build remain unqualified. The separately installed publisher's natural
rollover was subsequently observed on 2026-09-26, as recorded below.

## 2026-09-26: Installed Publisher Natural Rollover

- This was a read-only observation of the separately installed publisher on
  the same DL380 Gen9, not a live rollover run of the public reference code.
- The publisher stayed active with the same PID and zero systemd restarts.
  OCSD record 2 and its header/native records validated throughout the test.
- A pre-wrap sample had counter 65300, T4 41 C, iLO `21-PCI 1` at 56 C,
  and all six fans at approximately 12-16% duty.
- The monitor directly observed counter 65535 followed by 0. At 0, the
  record remained valid, the T4 was 41 C, iLO still read 56 C, and all six
  fans were approximately 9-12%. A later read reached counter 18 and remained
  valid.
- Observation used `os.O_RDONLY` and `mmap.ACCESS_READ` for `/dev/mem`.
  No GPU load, iLO reset, service action, or Asterisk action was performed.

**Result: pass for one natural 16-bit rollover of the installed publisher and
stock iLO 4 v2.82 on this chassis.** It supports the OCSD/iLO control path,
but does not establish sustained-load rollover behavior, public-copy long-run
stability, unattended boot recovery, or compatibility with other systems.
