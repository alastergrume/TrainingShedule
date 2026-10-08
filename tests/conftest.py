"""Guards for the whole suite: unit tests must never touch the network or a DB.

If code under test reaches for either, the test fails immediately with a clear
message instead of hanging on a CI agent that has no Postgres/Redis/VK access.
"""
import ipaddress
import socket

import pytest

_real_connect = socket.socket.connect


def _is_loopback(host) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Loopback stays allowed: asyncio's event loop uses a socketpair on Windows.
    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(f"network access attempted in a unit test: {address!r}")
        return _real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    import src.models.base as base

    def forbidden(*args, **kwargs):
        raise AssertionError("unit test tried to open a real database session")

    monkeypatch.setattr(base, "SessionLocal", forbidden)
