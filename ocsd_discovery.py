#!/usr/bin/env python3
"""Conservative, read-only OCSD discovery report. No /dev/mem access."""
import argparse
import json
import os
import re
import subprocess
import sys

DISPLAY_CLASS = re.compile(r"^([0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\\.[0-7])\\s+(.+)$")
DISPLAY_WORDS = ("vga compatible controller", "3d controller", "display controller")
DMI_HEADER = re.compile(r"^Handle 0x[0-9a-fA-F]+, DMI type (\\d+),")


def type229_summary(output):
    """Count type-229 structures; never publish their addresses or bytes."""
    blocks = []
    current = None
    for line in output.splitlines():
        match = DMI_HEADER.match(line)
        if match:
            if current is not None:
                blocks.append(current)
            current = {"type": int(match.group(1)), "ocs_marker": False}
        elif current is not None and "$OCS" in line:
            current["ocs_marker"] = True
    if current is not None:
        blocks.append(current)
    found = [block for block in blocks if block["type"] == 229]
    return {"type_229_structures": len(found),
            "type_229_with_ocs_marker": sum(1 for block in found if block["ocs_marker"])}


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
    if re.fullmatch(r"ProLiant (?:DL|ML|BL|SL)\\d{2,4}(?:p)? Gen(?:8|9|10)(?: Plus)?", name):
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


def inspect(dmidecode_text, lspci_text, product):
    dmi = type229_summary(dmidecode_text) if dmidecode_text is not None else None
    pci = pci_displays(lspci_text) if lspci_text is not None else None
    return {
        "tool": "ocsd-discovery",
        "mode": "metadata-only; no physical memory read or writes",
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
    args = parser.parse_args(argv)
    report = inspect(run_capture(["dmidecode", "-t", "229"]),
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
