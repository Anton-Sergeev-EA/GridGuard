"""Wire-level read-only bridge checks against laboratory protocol servers."""

import asyncio
import socket

import pytest

from gridguard.bridge import CHANNELS, Bridge
from gridguard.scada.config.loader import DeviceConfig, TagConfig
from gridguard.scada.sim.datastore import DataStore
from gridguard.scada.sim.iec104_station import StationProcess
from gridguard.scada.sim.modbus_server import ModbusTCPServer
from gridguard.scada.sim.mqtt_broker import MiniMqttBroker

pytestmark = pytest.mark.bridges
VALUES = (45.0, 0.7, 0.03)


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def check(bridge: Bridge) -> None:
    assert await bridge.driver.connect()
    for _ in range(50):
        sample = await bridge.read()
        if sample is not None:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("protocol produced no complete sample")
    assert (sample.temperature_c, sample.load_pu, sample.vibration_g) == pytest.approx(VALUES)
    assert sample.timestamp_basis == "gateway-received"
    assert sample.quality_basis == "gateway-normalized"
    assert sample.quality == (2048, 2048, 2048)
    await bridge.driver.disconnect()
    assert await bridge.read() is None


def test_modbus_wire() -> None:
    async def scenario() -> None:
        data = DataStore()
        data.holding[:3] = [450, 700, 30]
        server = ModbusTCPServer(data, "127.0.0.1", port())
        device = DeviceConfig(
            id="lab",
            host="127.0.0.1",
            port=server.port,
            tags=[
                TagConfig(name=name, address=i, scale=scale)
                for i, (name, scale) in enumerate(zip(CHANNELS, (0.1, 0.001, 0.001), strict=True))
            ],
        )
        await server.start()
        try:
            await check(Bridge(device, "synthetic"))
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_mqtt_wire() -> None:
    async def scenario() -> None:
        server = MiniMqttBroker(port=port())
        for name, value in zip(CHANNELS, VALUES, strict=True):
            server.publish(name, str(value), retain=True)
        device = DeviceConfig(
            id="lab",
            host="127.0.0.1",
            port=server.port,
            protocol="mqtt",
            tags=[TagConfig(name=name, topic=name) for name in CHANNELS],
        )
        await server.start()
        try:
            await check(Bridge(device, "synthetic"))
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_opcua_wire() -> None:
    from asyncua import Server

    async def scenario() -> None:
        server = Server()
        await server.init()
        endpoint = f"opc.tcp://127.0.0.1:{port()}/gridguard"
        server.set_endpoint(endpoint)
        namespace = await server.register_namespace("urn:gridguard:synthetic")
        tags = []
        for name, value in zip(CHANNELS, VALUES, strict=True):
            node = await server.nodes.objects.add_variable(namespace, name, value)
            tags.append(TagConfig(name=name, node=node.nodeid.to_string()))
        device = DeviceConfig(id="lab", protocol="opcua", options={"endpoint": endpoint}, tags=tags)
        async with server:
            await check(Bridge(device, "synthetic"))

    asyncio.run(scenario())


def test_iec104_wire() -> None:
    async def scenario() -> None:
        station_port = port()
        server = StationProcess(
            station_port, 5, [f"{1001 + i}:float:{value}" for i, value in enumerate(VALUES)], []
        )
        device = DeviceConfig(
            id="lab",
            host="127.0.0.1",
            port=station_port,
            protocol="iec104",
            options={"common_address": 5},
            tags=[
                TagConfig(name=name, ioa=1001 + i, type="float") for i, name in enumerate(CHANNELS)
            ],
        )
        await server.start()
        try:
            await check(Bridge(device, "synthetic"))
        finally:
            await server.stop()

    asyncio.run(scenario())
