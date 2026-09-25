import sys
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gen9_t4_ocsd as ocsd
import gen9_t4_ocsd_register as register


def synthetic_snapshot(address):
    memory = bytearray(0x4000)
    header = bytearray(64)
    header[0] = 2
    struct.pack_into("<H", header, 4, 0x4000)
    header[8] = 102
    header[12] = ocsd.RECORD_SIZE
    struct.pack_into("<I", header, 16, address + 64)
    header[32] = 5
    header[56] = 2
    struct.pack_into("<I", header, 60, ocsd.checksum_header(header))
    memory[:64] = header
    for index, bus in enumerate((2, 3)):
        native = bytearray(64)
        native[0] = 1
        native[4] = bus
        struct.pack_into("<I", native, 60,
                         (-sum(struct.unpack_from("<15I", native))) & 0xffffffff)
        offset = 64 + index * ocsd.RECORD_SIZE
        memory[offset:offset + 64] = native
    return bytes(memory)


class OcsdProtocolTests(unittest.TestCase):
    def setUp(self):
        self.address = 0x70000000
        self.snapshot = synthetic_snapshot(self.address)

    def test_synthetic_gen9_snapshot(self):
        self.assertEqual(len(self.snapshot), 0x4000)
        ocsd.validate_header(self.snapshot[:64], self.address)
        ocsd.validate_native_headers(self.snapshot)
        self.assertEqual(self.snapshot[56], 2)
        self.assertFalse(any(self.snapshot[ocsd.RECORD_OFFSET:
                                           ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE]))

    def test_example_service_is_manual_only(self):
        examples = Path(__file__).resolve().parent.parent / "examples" / "systemd"
        publisher = (examples / "gen9-t4-ocsd.service").read_text("ascii")
        self.assertNotIn("[Install]", publisher)
        self.assertFalse((examples / "gen9-t4-ocsd-register.service").exists())

    def test_header_rejects_corruption(self):
        header = self.snapshot[:64]
        enabled = ocsd.header_with_count(header, 3)
        ocsd.validate_header(enabled, self.address)
        self.assertEqual(ocsd.header_with_count(enabled, 2), header)
        corrupt = bytearray(enabled)
        corrupt[16] ^= 1
        with self.assertRaises(ValueError):
            ocsd.validate_header(corrupt, self.address)

    def test_claim_rejects_occupied_slot_without_writing(self):
        memory = bytearray(self.snapshot)
        memory[ocsd.RECORD_OFFSET] = 1
        before = bytes(memory)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"):
            with self.assertRaisesRegex(ValueError, "not empty"):
                ocsd.claim(memory, self.address)
        self.assertEqual(bytes(memory), before)

    def test_claim_rejects_corrupt_native_record_without_writing(self):
        memory = bytearray(self.snapshot)
        memory[64 + 4] = 9
        before = bytes(memory)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"):
            with self.assertRaisesRegex(ValueError, "native OCSD"):
                ocsd.claim(memory, self.address)
        self.assertEqual(bytes(memory), before)

    def test_ownership_and_sensor_checksum(self):
        record = ocsd.make_record(65, 65535)
        self.assertTrue(ocsd.owned_record(record))
        self.assertEqual(record[84], 65)
        self.assertEqual(struct.unpack_from("<H", record, 88)[0], 65535)
        corrupt = bytearray(record)
        corrupt[84] = 66
        self.assertFalse(ocsd.owned_record(corrupt))
        self.assertTrue(ocsd.owned_record(ocsd.make_record(38, 0)))

    def test_discover_unique_smbios_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "229-0"
            entry.mkdir()
            raw = bytes((229, 20, 0x83, 0)) + b"$OCS" + struct.pack(
                "<QI", self.address, 0x4000) + b"\0\0"
            (entry / "raw").write_bytes(raw)
            self.assertEqual(ocsd.discover_ocsd(Path(directory)), self.address)
            (entry / "raw").write_bytes(raw[:8] + struct.pack(
                "<QI", self.address, 0x2000) + b"\0\0")
            with self.assertRaises(ValueError):
                ocsd.discover_ocsd(Path(directory))

    def test_ilo_reading_parser(self):
        sample = "Sensor ID : 21-PCI 1\n Sensor Reading        : 53 (+/- 0) degrees C\n"
        self.assertEqual(ocsd.parse_ilo_temperature(sample), 53)
        self.assertIsNone(ocsd.parse_ilo_temperature(" Sensor Reading : Disabled\n"))

    def test_gpu_telemetry_rejects_wrong_pci_identity(self):
        with mock.patch.object(ocsd.subprocess, "check_output",
                               return_value=b"00000000:06:00.0, 58\n"):
            with self.assertRaisesRegex(ValueError, "PCI identity mismatch"):
                ocsd.gpu_temperature()

    def test_ilo_parser_rejects_unavailable_reading(self):
        self.assertIsNone(ocsd.parse_ilo_temperature(" Sensor Reading : Not Available\n"))

    def test_registration_never_resets_ilo_without_opt_in(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units") as configured, \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "requires --allow-ilo-reset"):
                register.main()
        configured.assert_not_called()
        run.assert_not_called()

    def test_registration_opt_in_still_requires_idle_workloads(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=True), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "GPU workload is active"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_requires_configured_workloads(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units",
                                  side_effect=ValueError("units not configured")), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "units not configured"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_refuses_hot_gpu(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=False), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=70), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "GPU is not cool"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_resets_once_only_when_cool_and_idle(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu",
                                  side_effect=[False, True]), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=False), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=45), \
                mock.patch.object(register.time, "sleep"), \
                mock.patch.object(register.subprocess, "run") as run:
            register.main(allow_ilo_reset=True)
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0], ["/usr/sbin/ilorest", "iloreset"])

    def test_workload_units_must_be_real_services(self):
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ()):
            with self.assertRaisesRegex(ValueError, "OCSD_WORKLOAD_UNITS"):
                ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("--unsafe.service",)):
            with self.assertRaisesRegex(ValueError, "invalid GPU workload"):
                ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("gpu-worker.service",)), \
                mock.patch.object(ocsd.subprocess, "check_output", return_value=b"loaded\n"):
            ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("missing.service",)), \
                mock.patch.object(ocsd.subprocess, "check_output", return_value=b"not-found\n"):
            with self.assertRaisesRegex(ValueError, "not loaded"):
                ocsd.validate_workload_units()

    def test_hot_gpu_retries_stop_while_workload_remains_active(self):
        with mock.patch.object(ocsd, "workloads_active", side_effect=[True, False]), \
                mock.patch.object(ocsd, "stop_workloads") as stop:
            self.assertTrue(ocsd.request_thermal_stop(82, False, False))
            self.assertTrue(ocsd.request_thermal_stop(83, False, True))
            self.assertTrue(ocsd.request_thermal_stop(84, False, True))
            self.assertFalse(ocsd.request_thermal_stop(60, False, True))
            self.assertEqual(stop.call_count, 2)
        with mock.patch.object(ocsd, "stop_workloads") as stop:
            self.assertTrue(ocsd.request_thermal_stop(85, True, False))
            stop.assert_called_once()

    def test_claim_publishes_fail_high_before_stop_request(self):
        memory = bytearray(self.snapshot)
        observed = []

        def inspect_stop():
            record = bytes(memory[ocsd.RECORD_OFFSET:
                                  ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
            observed.append((memory[56], record[84], ocsd.owned_record(record)))
            return False

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"), \
                mock.patch.object(ocsd, "boot_id", return_value="boot-one"), \
                mock.patch.object(ocsd, "gpu_temperature", side_effect=RuntimeError("NVML")), \
                mock.patch.object(ocsd, "stop_workloads", side_effect=inspect_stop):
            ocsd.claim(memory, self.address)
        self.assertEqual(observed, [(3, 85, True)])

    def test_claim_write_failure_still_requests_workload_stop(self):
        class FailingMemory(bytearray):
            def __setitem__(self, key, value):
                if (isinstance(key, slice) and key.start == ocsd.RECORD_OFFSET
                        and getattr(self, "fail_once", True)):
                    self.fail_once = False
                    raise RuntimeError("OCSD write failed")
                return super().__setitem__(key, value)

        memory = FailingMemory(self.snapshot)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"), \
                mock.patch.object(ocsd, "boot_id", return_value="boot-one"), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=45), \
                mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            with self.assertRaisesRegex(RuntimeError, "OCSD write failed"):
                ocsd.claim(memory, self.address)
            stop.assert_called_once()
            self.assertFalse(ocsd.STATE.exists())
        self.assertEqual(bytes(memory), self.snapshot)

    def test_update_publishes_fail_high_before_failed_status_check(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], 3)
        memory[:64] = active
        observed = []

        def inspect_status():
            record = bytes(memory[ocsd.RECORD_OFFSET:
                                  ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
            observed.append((record[84], ocsd.owned_record(record)))
            raise subprocess.TimeoutExpired("systemctl", 5)

        with mock.patch.object(ocsd, "workloads_active", side_effect=inspect_status), \
                mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            counter, warning = ocsd.publish_and_guard(
                memory, active, 1, 85, True, True)
        self.assertEqual((counter, warning), (2, True))
        self.assertEqual(observed, [(85, True)])
        stop.assert_called_once()

    def test_update_counter_wraps_in_synthetic_record(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], 3)
        memory[:64] = active
        counter, warning = ocsd.publish_and_guard(
            memory, active, 65535, 45, False, False)
        record = bytes(memory[ocsd.RECORD_OFFSET:
                              ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
        self.assertEqual((counter, warning), (0, False))
        self.assertEqual(struct.unpack_from("<H", record, 88)[0], 0)
        self.assertTrue(ocsd.owned_record(record))

    def test_update_header_mismatch_requests_workload_stop(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], 3)
        memory[:64] = active
        with mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            with self.assertRaisesRegex(RuntimeError, "header changed"):
                ocsd.publish_and_guard(memory, self.snapshot[:64], 1, 45, False, False)
            stop.assert_called_once()

    def test_stop_timeout_is_nonfatal(self):
        with mock.patch.object(ocsd.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("systemctl", 5)):
            self.assertFalse(ocsd.stop_workloads())

    def test_ownership_recovers_after_crash_and_new_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=38), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 1)
                self.assertEqual(memory[56], 3)
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 2)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=39), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-two"):
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 3)
                self.assertIn("boot-two", state.read_text())
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=39), mock.patch.object(
                    ocsd.time, "sleep", return_value=None):
                ocsd.restore(memory, original, active)
            self.assertEqual(bytes(memory), self.snapshot)
            self.assertFalse(state.exists())

    def test_restore_waits_for_cool_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, _ = ocsd.claim(memory, self.address)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", side_effect=[70, 64, 55, 54, 53]), mock.patch.object(
                    ocsd.time, "sleep", return_value=None) as sleep:
                ocsd.restore(memory, original, active)
            self.assertEqual(sleep.call_count, 4)
            self.assertEqual(bytes(memory), self.snapshot)
            self.assertFalse(state.exists())

    def test_restore_keeps_sensor_if_telemetry_stays_hot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, _ = ocsd.claim(memory, self.address)
            times = iter([0, 0, 0, 91])
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd.time, "monotonic", side_effect=lambda: next(times)), mock.patch.object(
                    ocsd.time, "sleep", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "retaining OCSD sensor"):
                    ocsd.restore(memory, original, active)
            self.assertEqual(memory[56], 3)
            self.assertTrue(ocsd.owned_record(memory[ocsd.RECORD_OFFSET:
                                                      ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE]))
            self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()
