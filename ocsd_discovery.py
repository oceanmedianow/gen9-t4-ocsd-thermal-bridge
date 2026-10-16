#!/usr/bin/env python3
"""Conservative, read-only OCSD discovery report. No /dev/mem access."""
import argparse
import json
import os
import re
import stat
import subprocess
import sys

DISPLAY_CLASS = re.compile(r"^([0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s+(.+)$")
DISPLAY_WORDS = ("vga compatible controller", "3d controller", "display controller")
DMI_TABLE = "/sys/firmware/dmi/tables/DMI"
MAX_DMI_TABLE_SIZE = 16 * 1024 * 1024


def type229_summary(table):
    """Count type-229 structures in a raw sysfs DMI table.

    Only aggregate counts leave this function. Physical addresses, formatted
    bytes, strings and handles are deliberately discarded.
    """
    count = 0
    marker_count = 0
    offset = 0
    while offset + 4 <= len(table):
        structure_type = table[offset]
        formatted_length = table[offset + 1]
        if formatted_length < 4 or offset + formatted_length > len(table):
            raise ValueError("malformed DMI structure header")
        terminator = table.find(b"\x00\x00", offset + formatted_length)
        if terminator < 0:
            raise ValueError("unterminated DMI string table")
        end = terminator + 2
        if structure_type == 229:
            count += 1
            if b"$OCS" in table[offset:end]:
                marker_count += 1
        offset = end
        if structure_type == 127:
            break
    return {"type_229_structures": count,
            "type_229_with_ocs_marker": marker_count}


def read_dmi_table(path=DMI_TABLE):
    """Read the kernel-exported SMBIOS table only; never fall back to memory."""
    descriptor = None
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        with stream:
            table = stream.read(MAX_DMI_TABLE_SIZE + 1)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(table) > MAX_DMI_TABLE_SIZE:
        return None
    return table


def pci_displays(output):
    results = []
    for line in output.splitlines():
        match = DISPLAY_CLASS.match(line.strip())
        if not match:
            continue
        identity, description = match.groups()
        if any(word in description.lower() for word in DISPLAY_WORDS):
            # Only PCI identity; no raw vendor strings, device serials, or paths.
            results.append(identity.lower())
    return sorted(set(results))


def read_product_name(path="/sys/class/dmi/id/product_name"):
    try:
        with open(path, "r") as stream:
            name = stream.read(256).strip()
    except (OSError, UnicodeError):
        return "unknown"
    # Strict allowlist so untrusted DMI strings do not leak arbitrary data.
    if re.fullmatch(r"ProLiant (?:DL|ML|BL|SL)\d{2,4}(?:p)? Gen(?:8|9|10)(?: Plus)?", name):
        return name
    return "unrecognized (redacted)"


def run_capture(command):
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, universal_newlines=True,
                                 timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.stdout if process.returncode == 0 else None


def inspect(dmi_table, lspci_text, product):
    try:
        dmi = type229_summary(dmi_table) if dmi_table is not None else None
    except (TypeError, ValueError):
        dmi = None
    pci = pci_displays(lspci_text) if lspci_text is not None else None
    return {
        "tool": "ocsd-discovery",
        "mode": "metadata-only; SMBIOS sysfs read; no physical memory access or writes",
        "model": product,
        "smbios": dmi if dmi is not None else "unavailable",
        "display_pci_addresses": pci if pci is not None else "unavailable",
        "layout_validated": False,
        "gen8_compatibility": "unverified",
        "notes": [
            "Type-229 and $OCS presence do not prove allocation size or record layout.",
            "No record contents, occupancy, checksums or iLO fan response were inspected.",
            "Do not run the Gen9 publisher or attempt OCSD writes based on this report."
        ]
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print sanitized JSON")
    parser.add_argument("--dmi-table", default=DMI_TABLE,
                        help="raw kernel-exported DMI table (default: %(default)s)")
    args = parser.parse_args(argv)
    report = inspect(read_dmi_table(args.dmi_table),
                     run_capture(["lspci", "-Dnn"]), read_product_name())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("OCSD metadata-only discovery (NO memory access)")
        print("Model:", report["model"])
        print("SMBIOS type 229:", report["smbios"])
        print("Display PCI addresses:", report["display_pci_addresses"])
        print("Layout validated: NO; Gen8 compatibility: UNVERIFIED")
        print("Read docs/OCSD_DISCOVERY.md before sharing results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
