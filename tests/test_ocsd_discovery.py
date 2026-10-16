import unittest
from ocsd_discovery import inspect, pci_displays, type229_summary

class DiscoveryTests(unittest.TestCase):
    def test_type229_marker(self):
        dump = "Handle 0x0001, DMI type 229, 16 bytes\n  String: $OCS\nHandle 0x0002, DMI type 1, 8 bytes"
        self.assertEqual(type229_summary(dump), {"type_229_structures": 1, "type_229_with_ocs_marker": 1})

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
