# DL380 Gen10 / RTX 8000 discovery summary

This is a privacy-sanitized, human-written summary of previously validated
observations. It is **not verbatim output** from `ocsd_discovery.py` and is not
a fixture for its JSON schema. In particular, the tool reports display PCI
addresses, not vendor or GPU names; the display function names below are
separately identified.

| Observation | Result |
| --- | --- |
| Model | ProLiant DL380 Gen10 |
| SMBIOS type-229 structures | 1 |
| Type-229 structures with a visible `$OCS` marker | 0 |
| Display PCI functions | Matrox and RTX 8000 |
| `layout_validated` | `false` |

Server serial, PCI addresses, raw dumps, secrets, and internal infrastructure
details are deliberately omitted. The zero marker count does not establish
that OCSD is absent; it also does not validate an OCSD layout. No record
contents, ownership, checksums, or thermal response are established by this
summary. It does not establish compatibility with the Gen9 publisher or
authorize OCSD writes. See [OCSD discovery](../docs/OCSD_DISCOVERY.md).
