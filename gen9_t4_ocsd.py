#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Josh Murphy (Ocean Media Now)
# Project: HPE iLO 4 OCSD GPU Fan Controller Daemon
# Author: Josh Murphy
# Company: Ocean Media Now (https://www.oceanmedianow.com)
# Architecture: NVIDIA telemetry -> OCSD -> stock iLO 4 -> HPE fan control.
"""Publish the Gen9 T4 temperature through the firmware OCSD option-card slot."""

import fcntl
import json
import logging
import mmap
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import time


LOG = logging.getLogger("gen9-t4-ocsd")
STATE = Path("/var/lib/gen9-t4-ocsd/ownership.json")
LOCK = "/run/gen9-t4-ocsd/publisher.lock"
DMI_ENTRIES = Path("/sys/firmware/dmi/entries")
EXPECTED_PRODUCT = "ProLiant DL380 Gen9"
GPU_PCI = "00000000:05:00.0"
BUS, DEVICE = 5, 0
RECORD_SIZE = 160
RECORD_OFFSET = 64 + 2 * RECORD_SIZE
CAUTION_C = 85
CONTINUOUS_C = 75
STOP_WORKLOAD_C = 82
RESTORE_COOL_C = 55
RESTORE_TIMEOUT_SECONDS = 90
WORKLOAD_UNITS = tuple(os.environ.get("OCSD_WORKLOAD_UNITS", "").split())
STOP = False


def checksum_header(header):
    return (-sum((header[0], struct.unpack_from("<H", header, 4)[0], header[8],
                  header[12], struct.unpack_from("<I", header, 16)[0],
                  header[32], header[56]))) & 0xffffffff


def header_with_count(original, count):
    value = bytearray(original)
    value[56] = count
    struct.pack_into("<I", value, 60, checksum_header(value))
    return bytes(value)


def validate_header(header, address):
    if len(header) != 64 or header[0] != 2 or header[8] != 102:
        raise ValueError("unexpected OCSD header version or card capacity")
    if struct.unpack_from("<H", header, 4)[0] != 0x4000:
        raise ValueError("unexpected OCSD allocation size")
    if header[12] != RECORD_SIZE or struct.unpack_from("<I", header, 16)[0] != address + 64:
        raise ValueError("unexpected OCSD record layout")
    if header[32] != 5 or header[56] not in (2, 3):
        raise ValueError("unexpected OCSD polling interval or device count")
    if struct.unpack_from("<I", header, 60)[0] != checksum_header(header):
        raise ValueError("invalid OCSD header checksum")


def validate_native_headers(memory):
    for index, bus in enumerate((2, 3)):
        head = bytes(memory[64 + index * RECORD_SIZE:128 + index * RECORD_SIZE])
        words = struct.unpack("<16I", head)
        if head[0] != 1 or head[4] != bus or head[8] != 0 or sum(words) & 0xffffffff:
            raise ValueError("unexpected native OCSD device header")


def discover_ocsd(entries=DMI_ENTRIES):
    matches = []
    for path in entries.glob("229-*/raw"):
        raw = path.read_bytes()
        length = raw[1]
        if raw[0] != 229 or length < 20 or length > len(raw) or (length - 4) % 16:
            raise ValueError("malformed HPE SMBIOS type 229 entry")
        for offset in range(4, length, 16):
            if raw[offset:offset + 4] == b"$OCS":
                address, size = struct.unpack_from("<QI", raw, offset + 4)
                matches.append((address, size))
    if len(matches) != 1 or matches[0][1] != 0x4000:
        raise ValueError("unique 16 KiB HPE OCSD allocation not found")
    address = matches[0][0]
    if address < 0x100000 or address >= 0x100000000 or address % mmap.PAGESIZE:
        raise ValueError("unexpected OCSD physical address")
    return address


def make_record(temperature, counter):
    if temperature < 0 or temperature > 100 or counter < 0 or counter > 65535:
        raise ValueError("temperature or update counter outside OCSD range")
    record = bytearray(RECORD_SIZE)
    record[0], record[4], record[8] = 1, BUS, DEVICE
    struct.pack_into("<I", record, 20, 0x10)
    struct.pack_into("<I", record, 60,
                     (-sum(struct.unpack_from("<15I", record, 0))) & 0xffffffff)
    sensor = 64
    record[sensor] = 1
    struct.pack_into("<I", record, sensor + 4, 1)
    record[sensor + 8], record[sensor + 12] = CAUTION_C, CONTINUOUS_C
    struct.pack_into("<I", record, sensor + 16, 0x000b0000)
    record[sensor + 20] = temperature
    struct.pack_into("<H", record, sensor + 24, counter)
    sensor_sum = (1 + 1 + CAUTION_C + CONTINUOUS_C + 0x000b0000
                  + temperature + counter + BUS)
    struct.pack_into("<I", record, sensor + 28, (-sensor_sum) & 0xffffffff)
    return bytes(record)


def owned_record(record):
    if len(record) != RECORD_SIZE or any(record[96:]):
        return False
    if record[0] != 1 or record[4] != BUS or record[8] != DEVICE:
        return False
    if struct.unpack_from("<I", record, 20)[0] != 0x10:
        return False
    if sum(struct.unpack_from("<16I", record, 0)) & 0xffffffff:
        return False
    if record[64] != 1 or struct.unpack_from("<I", record, 68)[0] != 1:
        return False
    if record[72] != CAUTION_C or record[76] != CONTINUOUS_C:
        return False
    if struct.unpack_from("<I", record, 80)[0] != 0x000b0000:
        return False
    temperature = record[84]
    counter = struct.unpack_from("<H", record, 88)[0]
    return record == make_record(temperature, counter)


def gpu_temperature():
    output = subprocess.check_output(
        ["/usr/bin/nvidia-smi", "--id=" + GPU_PCI,
         "--query-gpu=pci.bus_id,temperature.gpu", "--format=csv,noheader,nounits"],
        stderr=subprocess.DEVNULL, timeout=4).decode("ascii").strip().splitlines()
    if len(output) != 1:
        raise ValueError("unexpected NVIDIA GPU count")
    pci, raw = (part.strip() for part in output[0].split(","))
    if pci.lower() != GPU_PCI:
        raise ValueError("NVIDIA PCI identity mismatch")
    value = int(raw)
    if not 0 <= value <= 100:
        raise ValueError("NVIDIA temperature outside accepted range")
    return value


def ilo_temperature():
    output = subprocess.check_output(
        ["/usr/bin/ipmitool", "sdr", "get", "21-PCI 1"],
        stderr=subprocess.DEVNULL, timeout=5).decode("ascii", "replace")
    return parse_ilo_temperature(output)


def parse_ilo_temperature(output):
    match = re.search(r"^\s*Sensor Reading\s*:\s*(\d+)\s+", output, re.MULTILINE)
    return int(match.group(1)) if match else None


def notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        channel.connect(address)
        channel.sendall(message.encode("ascii"))
    finally:
        channel.close()


def stop_workloads():
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "stop", "--no-block"] + list(WORKLOAD_UNITS),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            check=False)
    except Exception as error:
        LOG.error("GPU workload stop request failed: %s", type(error).__name__)
        return False
    if result.returncode:
        LOG.error("GPU workload stop request returned status %d", result.returncode)
        return False
    return True


def workloads_active():
    return any(
        subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=False).returncode == 0
        for unit in WORKLOAD_UNITS
    )


def validate_workload_units():
    if not WORKLOAD_UNITS:
        raise ValueError("OCSD_WORKLOAD_UNITS must name the GPU workload services")
    for unit in WORKLOAD_UNITS:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*\.service", unit):
            raise ValueError("invalid GPU workload service name")
        output = subprocess.check_output(
            ["/usr/bin/systemctl", "show", "-P", "LoadState", unit],
            stderr=subprocess.DEVNULL, timeout=5).decode("ascii").strip()
        if output != "loaded":
            raise ValueError("configured GPU workload service is not loaded")


def request_thermal_stop(temperature, telemetry_failed, warning_active):
    if not telemetry_failed and temperature < STOP_WORKLOAD_C:
        return False
    try:
        retry = workloads_active() if warning_active else True
    except Exception as error:
        LOG.error("GPU workload status check failed: %s", type(error).__name__)
        retry = True
    if retry:
        stop_workloads()
    if not warning_active:
        LOG.warning("GPU workload stop requested at %d C", temperature)
    return True


def publish_and_guard(memory, active_header, counter, temperature,
                      telemetry_failed, warning_active):
    counter = (counter + 1) & 0xffff
    next_record = make_record(temperature, counter)
    memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE] = next_record
    if bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]) != next_record:
        raise RuntimeError("OCSD live update readback failed")
    if bytes(memory[:64]) != active_header:
        raise RuntimeError("OCSD header changed during publication")
    warning_active = request_thermal_stop(
        temperature, telemetry_failed, warning_active)
    return counter, warning_active


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def save_state(value):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE.with_name(".ownership.tmp")
    data = json.dumps(value, sort_keys=True).encode("ascii")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(str(temporary), str(STATE))


def claim(memory, address):
    current = bytes(memory[:64])
    record = bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE])
    validate_header(current, address)
    validate_native_headers(memory)
    if current[56] == 2 and not any(record):
        if STATE.exists():
            state = json.loads(STATE.read_text("ascii"))
            if (state.get("address") != address or state.get("gpu_pci") != GPU_PCI
                    or state.get("original_header") != current.hex()):
                raise ValueError("stale OCSD ownership state does not match empty slot")
            LOG.warning("recovering empty OCSD slot after interrupted boot")
            STATE.unlink()
        original = current
        save_state({"boot_id": boot_id(), "address": address,
                    "original_header": original.hex(), "gpu_pci": GPU_PCI})
        counter = 0
    elif current[56] == 3 and owned_record(record) and STATE.is_file():
        state = json.loads(STATE.read_text("ascii"))
        original = bytes.fromhex(state["original_header"])
        validate_header(original, address)
        if (state["address"] != address or state["gpu_pci"] != GPU_PCI
                or original[56] != 2
                or header_with_count(original, 3) != current):
            raise ValueError("OCSD ownership state does not match this boot")
        if state["boot_id"] != boot_id():
            LOG.warning("recovering owned OCSD record after a new host boot")
            state["boot_id"] = boot_id()
            save_state(state)
        counter = struct.unpack_from("<H", record, 88)[0]
        LOG.warning("recovering owned OCSD record after interrupted publisher")
    else:
        raise ValueError("OCSD slot 2 is not empty or safely recoverable")
    counter = (counter + 1) & 0xffff
    telemetry_failed = False
    try:
        temperature = gpu_temperature()
    except Exception as error:
        LOG.error("initial NVIDIA telemetry failed: %s", type(error).__name__)
        temperature = CAUTION_C
        telemetry_failed = True
    active_header = header_with_count(original, 3)
    try:
        new_record = make_record(temperature, counter)
        memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE] = new_record
        memory[:64] = active_header
        if (bytes(memory[:64]) != active_header
                or bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]) != new_record):
            raise RuntimeError("OCSD write readback failed")
    except Exception:
        if (bytes(memory[:64]) in (original, active_header)
                and (not any(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE])
                     or owned_record(bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE])))):
            memory[:64] = original
            memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE] = bytes(RECORD_SIZE)
            STATE.unlink()
        raise
    request_thermal_stop(temperature, telemetry_failed, False)
    return original, active_header, counter


def restore(memory, original, active_header):
    if bytes(memory[:64]) != active_header:
        raise RuntimeError("OCSD header changed externally; leaving fail-high state")
    record = bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE])
    if not owned_record(record):
        raise RuntimeError("OCSD record changed externally; leaving fail-high state")
    if workloads_active():
        stop_workloads()
        for _ in range(30):
            if not workloads_active():
                break
            time.sleep(1)
        if workloads_active():
            raise RuntimeError("GPU workload still active; retaining GPU sensor")
    counter = struct.unpack_from("<H", record, 88)[0]
    deadline = time.monotonic() + RESTORE_TIMEOUT_SECONDS
    cool_samples = 0
    while time.monotonic() < deadline:
        try:
            temperature = gpu_temperature()
            cool_samples = cool_samples + 1 if temperature <= RESTORE_COOL_C else 0
        except Exception as error:
            temperature = CAUTION_C
            cool_samples = 0
            LOG.warning("NVIDIA telemetry unavailable during cooldown: %s",
                        type(error).__name__)
        counter = (counter + 1) & 0xffff
        next_record = make_record(temperature, counter)
        memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE] = next_record
        if bytes(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]) != next_record:
            raise RuntimeError("OCSD cooldown update readback failed")
        if cool_samples >= 3:
            break
        time.sleep(1)
    else:
        raise RuntimeError("GPU did not cool; retaining OCSD sensor for fail-high cooling")
    memory[:64] = original
    memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE] = bytes(RECORD_SIZE)
    if bytes(memory[:64]) != original or any(memory[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]):
        raise RuntimeError("OCSD restoration readback failed")
    STATE.unlink()
    LOG.info("original OCSD header and empty slot 2 restored")


def run():
    global STOP
    if Path("/sys/class/dmi/id/product_name").read_text().strip() != EXPECTED_PRODUCT:
        raise ValueError("host is not the qualified DL380 Gen9")
    validate_workload_units()
    address = discover_ocsd()
    lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    memory = None
    original = None
    active_header = None
    try:
        memory = mmap.mmap(fd, 0x4000, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=address)
        original, active_header, counter = claim(memory, address)
        LOG.info("T4 sensor published at OCSD record 2, physical 0x%x", address)
        ready_count = 0
        misses = 0
        ready = False
        last_ilo_check = 0
        last_temp = None
        warning_active = False
        while not STOP:
            started = time.monotonic()
            try:
                temperature = gpu_temperature()
                telemetry_failed = False
            except Exception as error:
                temperature = CAUTION_C
                telemetry_failed = True
                LOG.error("NVIDIA telemetry failed; publishing 85 C: %s", type(error).__name__)
            counter, warning_active = publish_and_guard(
                memory, active_header, counter, temperature,
                telemetry_failed, warning_active)
            now = time.monotonic()
            if now - last_ilo_check >= 5:
                last_ilo_check = now
                try:
                    ilo = ilo_temperature()
                    match = ilo is not None and abs(ilo - (temperature + 15)) <= 6
                except Exception as error:
                    if not ready:
                        LOG.warning("iLO sensor verification unavailable: %s", type(error).__name__)
                    match = False
                ready_count = ready_count + 1 if match else 0
                misses = 0 if match else misses + 1
                if not ready and ready_count >= 2:
                    notify("READY=1\nSTATUS=T4 OCSD sensor confirmed in iLO")
                    LOG.info("iLO PCI sensor confirmed; service ready")
                    ready = True
                if ready and misses >= 2:
                    stop_workloads()
                    raise RuntimeError("iLO stopped tracking T4 OCSD temperature")
            notify("WATCHDOG=1")
            if last_temp != temperature and temperature >= 70:
                LOG.info("GPU temperature %d C", temperature)
            last_temp = temperature
            time.sleep(max(0, 1 - (time.monotonic() - started)))
    finally:
        if memory is not None:
            try:
                if original is not None:
                    restore(memory, original, active_header)
            finally:
                memory.close()
        os.close(fd)
        os.close(lock_fd)


def request_stop(_signum, _frame):
    global STOP
    STOP = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, request_stop)
    try:
        run()
    except Exception:
        LOG.exception("OCSD T4 publisher stopped")
        raise SystemExit(1)
