"""Shared test fixtures and a hardware-free fake DALI driver.

The fake driver records every command sent and drives command *sequences*
(generators passed to ``run_sequence``) just like the real python-dali async
driver, feeding back programmable responses. No USB hardware is required.
"""
import asyncio
import os
import re
import sys
from types import SimpleNamespace

import pytest

# Make the `app` package importable (tests live in dali2mqtt/tests).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dali.frame import BackwardFrame  # noqa: E402
from dali.command import NumericResponse, YesNoResponse  # noqa: E402


# --------------------------------------------------------------------------- #
# Response helpers
# --------------------------------------------------------------------------- #
def yes():
    return YesNoResponse(BackwardFrame(0xFF))


def no():
    return YesNoResponse(None)


def numeric(value):
    return NumericResponse(BackwardFrame(value))


class RawResp:
    """A minimal response exposing .value / .raw_value.as_integer."""

    def __init__(self, value=None, raw_int=None, error=False):
        self._value = value
        self.raw_value = (
            None if raw_int is None else SimpleNamespace(as_integer=raw_int, error=error)
        )

    @property
    def value(self):
        return self._value


def groups_value(mask):
    """A response whose .value has .as_integer (like the group queries)."""
    return RawResp(value=SimpleNamespace(as_integer=mask))


# --------------------------------------------------------------------------- #
# Command inspection helpers
# --------------------------------------------------------------------------- #
def cname(cmd):
    return type(cmd).__name__


def dest_addr(cmd):
    dest = getattr(cmd, "destination", None)
    return getattr(dest, "address", None)


def dtr_value(cmd):
    """Extract the integer argument from a DTR0/DTR1 command via its repr."""
    m = re.search(r"\((\d+)\)", str(cmd))
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Fake driver
# --------------------------------------------------------------------------- #
class FakeDriver:
    def __init__(self, responder=None):
        self.connected = asyncio.Event()
        self.connected.set()
        self.transaction_lock = asyncio.Lock()
        self.sent = []                 # every command sent (send + run_sequence)
        self._responder = responder or (lambda cmd: None)
        self.bus_traffic = SimpleNamespace(
            _cbs=[], register=self._register
        )

    def _register(self, cb):
        self.bus_traffic._cbs.append(cb)
        return SimpleNamespace(unregister=lambda: None)

    async def send(self, command, **kw):
        self.sent.append(command)
        return self._responder(command)

    async def run_sequence(self, seq, progress=None):
        response = None
        try:
            while True:
                cmd = seq.send(response)
                self.sent.append(cmd)
                response = self._responder(cmd)
        except StopIteration as stop:
            return stop.value
        finally:
            seq.close()

    # test helpers
    def sent_types(self):
        return [cname(c) for c in self.sent]

    def reset(self):
        self.sent.clear()


@pytest.fixture
def driver():
    return FakeDriver()


@pytest.fixture
def busy():
    return asyncio.Event()
