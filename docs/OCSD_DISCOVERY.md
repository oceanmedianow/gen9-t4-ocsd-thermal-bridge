# Metadata-only OCSD discovery (experimental)

This utility is for community discovery, **not Gen8 support**. It performs no
`/dev/mem` access, does not decode OCSD records and cannot enable a GPU fan
integration. It reads the kernel-exported `/sys/firmware/dmi/tables/DMI` table,
invokes only `lspci -Dnn`, and reads `/sys/class/dmi/id/product_name`. It does
not invoke `dmidecode`, because that utility can fall back to physical memory
on systems where the sysfs DMI table is unavailable.

## Usage

From the repository root:

```sh
python3 ocsd_discovery.py --json
python3 -m unittest discover -s tests -v
```

The sysfs DMI table is commonly root-readable only. If the first command marks
SMBIOS unavailable, limit privilege to copying that one kernel-exported file
into the temporary working directory, then run Python unprivileged:

```sh
sudo -n cat /sys/firmware/dmi/tables/DMI > ./DMI.read-only-copy
chmod 600 ./DMI.read-only-copy
python3 ocsd_discovery.py --dmi-table ./DMI.read-only-copy --json
```

The output intentionally includes only an allowlisted server model name,
counts of SMBIOS type-229 entries and visible `$OCS` markers, and PCI
bus/device/function addresses for display-class controllers. It excludes the
physical OCSD address, raw SMBIOS data, vendor descriptions, memory contents,
serial numbers, sensor values and iLO details.

Review the output yourself before posting. DMI and PCI data still describe
hardware. If the sysfs DMI table or `lspci` is unavailable, the relevant field
is marked unavailable; no compatibility conclusion is drawn.

**Important:** The type-229 output can vary between firmware implementations.
A marker count of zero is not proof that OCSD is absent. A positive marker count
is not proof that the Gen9 record layout exists. We have not established Gen8
record size, checksum rules, ownership, thermal behavior, or safe slots.

Never run the Gen9 publisher unchanged on another chassis. Do not post raw
physical-memory dumps. For Gen8 investigations, open an issue with the
sanitized output plus separately confirmed chassis, firmware, cooling
configuration and test conditions. No read-only report authorizes a write.
