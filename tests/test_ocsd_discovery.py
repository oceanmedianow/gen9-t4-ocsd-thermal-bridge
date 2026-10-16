import stat
import unittest
from unittest import mock
from ocsd_discovery import inspect, pci_displays, read_dmi_table, type229_summary


def dmi_structure(structure_type, handle, strings=()):
    formatted = bytes((structure_type, 4, handle & 0xff, handle >> 8))
    encoded = b"\x00".join(value.encode("ascii") for value in strings)
    return formatted + encoded + b"\x00\x00"


class DiscoveryTests(unittest.TestCase):
    def test_type229_marker(self):
        table = (dmi_structure(229, 1, ("$OCS",)) +
                 dmi_structure(229, 2, ("other",)) +
                 dmi_structure(127, 3))
        self.assertEqual(type229_summary(table),
                         {"type_229_structures": 2,
                          "type_229_with_ocs_marker": 1})

    def test_malformed_dmi_fails_closed(self):
        report = inspect(bytes((229, 3, 0, 0)), "", "unknown")
        self.assertEqual(report["smbios"], "unavailable")
        self.assertFalse(report["layout_validated"])

    def test_character_device_is_rejected_before_open(self):
        device = mock.Mock(st_mode=stat.S_IFCHR | 0o600)
        with mock.patch("ocsd_discovery.os.lstat", return_value=device), \
                mock.patch("ocsd_discovery.os.open") as open_file:
            self.assertIsNone(read_dmi_table("/dev/mem"))
        open_file.assert_not_called()

    def test_display_bdf_only(self):
        data = "0000:05:00.0 3D controller [0302]: NVIDIA T4 [10de:1eb8]\n0000:00:1f.0 ISA bridge [0601]: chipset"
        self.assertEqual(pci_displays(data), ["0000:05:00.0"])

    def test_fail_closed_unknown_layout(self):
        report = inspect(None, None, "unknown")
        self.assertFalse(report["layout_validated"])
        self.assertEqual(report["smbios"], "unavailable")
        self.assertEqual(report["display_pci_addresses"], "unavailable")

if __name__ == "__main__":
    unittest.main()
