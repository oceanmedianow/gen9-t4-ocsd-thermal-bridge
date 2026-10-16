# Metadata-only OCSD discovery (experimental)

This utility is for community discovery, **not Gen8 support**. It performs no
`/dev/mem` access, does not decode OCSD records and cannot enable a GPU fan
integration. It invokes only `dmidecode -t 229`, `lspci -Dnn`, and reads
`/sys/class/dmi/id/product_name`. These calls may require elevated privileges.

## Usage

From the repository root:

```sh
sudo python3 ocsd_discovery.py --json
python3 -m unittest discover -s tests -v
```

The output intentionally includes only an allowlisted server model name,
counts of SMBIOS type-229 entries and visible `$OCS` markers, and PCI
bus/device/function addresses for display-class controllers. It excludes the
physical OCSD address, raw SMBIOS data, vendor descriptions, memory contents,
serial numbers, sensor values and iLO details.

Review the output yourself before posting. DMI and PCI data still describe
hardware. If `dmidecode` or `lspci` is unavailable, the relevant field is
marked unavailable; no compatibility conclusion is drawn.

**Important:** The type-229 output can vary between firmware implementations.
A marker count of zero is not proof that OCSD is absent. A positive marker count
is not proof that the Gen9 record layout exists. We have not established Gen8
record size, checksum rules, ownership, thermal behavior, or safe slots.

Never run the Gen9 publisher unchanged on another chassis. Do not post raw
physical-memory dumps. For Gen8 investigations, open an issue with the
sanitized output plus separately confirmed chassis, firmware, cooling
configuration and test conditions. No read-only report authorizes a write.
