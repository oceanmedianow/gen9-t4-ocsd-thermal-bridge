# Observed OCSD Layout

This is a record of observations from one HPE DL380 Gen9 with stock iLO 4
v2.82, not an HPE specification. The code is deliberately strict about this
layout and should reject a different one instead of guessing.

- SMBIOS type 229 contains one `$OCS` descriptor identifying a page-aligned
  16 KiB physical-memory allocation. The publisher discovers its address at
  runtime; no physical address is embedded in the release.
- A 64-byte header precedes 160-byte option-card records. The implementation
  requires header version marker 2, allocation size `0x4000`, record size
  160, marker 102, and interval marker 5, plus its observed checksum rule.
- The tested allocation had two valid native records and an empty third
  record. The publisher uses only record index 2 and changes the header count
  from 2 to 3 while it owns that slot. It refuses to overwrite a nonempty
  or unrecognized record.
- The published record identifies the tested T4 at PCI bus 5/device 0. Its
  temperature byte is at record offset 84 and its 16-bit update counter at
  offset 88. Header, device, and sensor checksums are checked or recomputed
  as required by the observed layout.
- iLO exposed the record as `21-PCI 1`. On this chassis that reading tracked
  the source GPU temperature with an approximately +15 C display offset.
  Neither the sensor label nor offset is guaranteed elsewhere.

The publisher's counter advances while running, including during shutdown
cool-down. A stopped publisher or stale count can change iLO's fan response;
on the tested chassis stale data drove the fans to 100%. That behavior is a
single-platform observation, not a recovery guarantee for other firmware.

The synthetic unit-test fixture constructs only the fields needed to test
these checks. It is not a dump of host memory and cannot prove another
machine has the same layout. Before any live write, inspect and privately
back up the target machine's allocation, then stop on every mismatch.
