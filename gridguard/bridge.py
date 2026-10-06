"""Optional read-only bridges reuse pinned SCADA_Generator adapters."""

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from gridguard.scada.config.loader import DeviceConfig, parse_config
from gridguard.scada.drivers import QUALITY_GOOD, Driver, create_driver
from gridguard.schema import Sample
from gridguard.store import Store
from gridguard.worker import exporter

Source = Literal["synthetic", "external-unvalidated"]
CHANNELS = ("temperature_c", "load_pu", "vibration_g")


class Bridge:
    def __init__(self, device: DeviceConfig, source: Source) -> None:
        if device.protocol not in {"modbus_tcp", "iec104", "opcua", "mqtt"}:
            raise ValueError("unsupported bridge protocol")
        if {tag.name for tag in device.tags} != set(CHANNELS):
            raise ValueError("bridge tags must explicitly map temperature_c, load_pu, vibration_g")
        if any(tag.writable for tag in device.tags):
            raise ValueError("GridGuard bridges are read-only")
        self.device = device
        self.source = source
        self.driver: Driver = create_driver(device)

    async def read(self) -> Sample | None:
        if not self.driver.is_connected:
            return None
        readings = await self.driver.read()
        values = [readings[name][0] for name in CHANNELS]
        if any(value is None for value in values):
            return None  # Missing measurement must not become a fabricated zero.
        stamp = time.time_ns() // 1_000_000
        test_bit = 2048 if self.source == "synthetic" else 0
        quality = tuple(
            test_bit | (0 if readings[name][1] == QUALITY_GOOD else 1) for name in CHANNELS
        )
        return Sample(
            asset=self.device.id,
            source=self.source,
            protocol=self.device.protocol,
            timestamp_basis="gateway-received",
            quality_basis="gateway-normalized",
            temperature_c=float(values[0]),
            load_pu=float(values[1]),
            vibration_g=float(values[2]),
            sample_ms=stamp,
            channel_ms=(stamp, stamp, stamp),
            quality=quality,
        )

    async def run(self, store: Store) -> None:
        delay = 0.25
        try:
            while True:
                if not self.driver.is_connected and not await self.driver.connect():
                    print(
                        json.dumps(
                            {
                                "event": "bridge_reconnect",
                                "asset": self.device.id,
                                "protocol": self.device.protocol,
                                "delay_s": delay,
                            }
                        ),
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 10)
                    continue
                sample = await self.read()
                if sample is not None:
                    store.insert(sample)
                    delay = 0.25
                await asyncio.sleep(self.device.poll_interval_ms / 1000)
        finally:
            await self.driver.disconnect()


async def run(config: dict[str, object], source: Source, store: Store) -> None:
    devices = parse_config(config).devices
    bridges = [Bridge(device, source) for device in devices]
    if not bridges:
        raise ValueError("bridge configuration requires at least one device")
    await asyncio.gather(*(bridge.run(store) for bridge in bridges))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly mapped read-only laboratory protocol bridges"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", choices=["synthetic", "external-unvalidated"], required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    store = Store(Path(os.environ.get("GRIDGUARD_DB", "work/gridguard.sqlite")))
    stop = threading.Event()
    dsn = os.environ.get("GRIDGUARD_PG_DSN")
    thread = (
        threading.Thread(target=exporter, args=(store, dsn, stop), daemon=True) if dsn else None
    )
    if thread:
        thread.start()
    try:
        asyncio.run(run(config, args.source, store))
    finally:
        stop.set()
        if thread:
            thread.join(timeout=4)


if __name__ == "__main__":
    main()
