import gc
import time
from esp32 import RMT

from machine import Pin, disable_irq, enable_irq
from collections import namedtuple


Packet = namedtuple("Packet", ["value", "timing_us"])


class InfraredTx:
    def __init__(self, pin: Pin, rmt: RMT=None, rmt_number: int = 0) -> None:
        self.pin = pin
        if rmt is None:
            rmt = RMT(rmt_number, pin=self.pin, clock_div=80, carrier_freq=38000)
        self.rmt = rmt
        self.reset()

    def reset(self) -> None:
        self._buffer = []

    def _add(self, timing_us: float) -> None:
        self._buffer.append(int(timing_us))

    def trigger(self) -> None:
        rmt = self.rmt
        payload = tuple(self._buffer)
        rmt.write_pulses(payload, start=1)
        rmt.wait_done()

        self.reset()


class NEC(InfraredTx):
    def send(self, device_id: int, command: int):
        self._add_start_burst()
        self._add_code(device_id)
        self._add_code(command)
        self._add_end_burst()
        self.trigger()
    
    def _add_code(self, data: int) -> None:
        self._add_serialized(data)
        self._add_serialized(data ^ 0xFF)

    def _add_serialized(self, data: int) -> None:
        for index in range(7, -1, -1):
            self.add(bool(data & 2**index))

    def add(self, bit: bool) -> None:
        self._add(562.5)
        if bit:
            self._add(1687.5)
        else:
            self._add(562.5)

    def _add_start_burst(self) -> None:
        self._add(9000)
        self._add(4500)

    def _add_end_burst(self) -> None:
        self._add(562.5)
