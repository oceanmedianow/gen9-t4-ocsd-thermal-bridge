#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Josh Murphy (Ocean Media Now)
# Project: HPE iLO 4 OCSD GPU Fan Controller Daemon
# Author: Josh Murphy
# Company: Ocean Media Now (https://www.oceanmedianow.com)
# Architecture: NVIDIA telemetry -> OCSD -> stock iLO 4 -> HPE fan control.
"""Check T4 OCSD registration; iLO reset requires explicit opt-in."""

import argparse
import logging
import mmap
import os
import subprocess
import time

import gen9_t4_ocsd as ocsd


LOG = logging.getLogger("gen9-t4-ocsd-register")


def publisher_record_present():
    if not ocsd.STATE.is_file():
        return False
    process = subprocess.check_output(
        ["/usr/bin/systemctl", "show", "-P", "MainPID", "gen9-t4-ocsd.service"],
        timeout=5).decode("ascii").strip()
    if not process.isdigit() or int(process) <= 0:
        return False
    address = ocsd.discover_ocsd()
    descriptor = os.open("/dev/mem", os.O_RDONLY)
    try:
        memory = mmap.mmap(descriptor, 0x4000, access=mmap.ACCESS_READ, offset=address)
        try:
            header = bytes(memory[:64])
            record = bytes(memory[ocsd.RECORD_OFFSET:
                                  ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
            ocsd.validate_header(header, address)
            return header[56] == 3 and ocsd.owned_record(record)
        finally:
            memory.close()
    finally:
        os.close(descriptor)


def sensor_matches_gpu():
    try:
        reading = ocsd.ilo_temperature()
        gpu = ocsd.gpu_temperature()
        return reading is not None and abs(reading - (gpu + 15)) <= 6
    except Exception:
        return False


def main(allow_ilo_reset=False):
    deadline = time.monotonic() + 55
    while time.monotonic() < deadline:
        if publisher_record_present():
            break
        time.sleep(2)
    else:
        raise RuntimeError("T4 publisher did not claim OCSD slot")
    if sensor_matches_gpu():
        LOG.info("iLO already tracks T4; management reset unnecessary")
        return
    if not allow_ilo_reset:
        raise RuntimeError("T4 sensor absent; iLO reset requires --allow-ilo-reset")
    ocsd.validate_workload_units()
    if ocsd.workloads_active():
        raise RuntimeError("configured GPU workload is active; iLO reset deferred")
    for _ in range(3):
        if ocsd.gpu_temperature() > ocsd.RESTORE_COOL_C:
            raise RuntimeError("GPU is not cool; iLO reset deferred")
        time.sleep(1)
    LOG.warning("T4 sensor absent; resetting iLO management processor")
    subprocess.run(["/usr/sbin/ilorest", "iloreset"], timeout=20, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 105
    while time.monotonic() < deadline:
        if sensor_matches_gpu():
            LOG.info("iLO registered T4 OCSD sensor")
            return
        time.sleep(5)
    raise RuntimeError("iLO reset completed but T4 sensor did not register")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-ilo-reset", action="store_true",
                        help="reset iLO once if the sensor is absent and configured GPU workloads are idle")
    args = parser.parse_args()
    try:
        main(args.allow_ilo_reset)
    except Exception:
        LOG.exception("T4 sensor registration failed")
        raise SystemExit(1)
