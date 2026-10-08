"""The suite-wide guards in conftest.py must actually trip."""
import socket

import pytest


def test_outbound_network_is_blocked():
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="network access attempted"):
            sock.connect(("192.0.2.1", 443))   # TEST-NET-1, never routable
    finally:
        sock.close()


def test_real_database_session_is_blocked():
    from src.models.base import SessionLocal

    with pytest.raises(AssertionError, match="real database session"):
        SessionLocal()
