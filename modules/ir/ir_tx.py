from collections import namedtuple

from esp32 import RMT
from machine import Pin
from micropython import const

Packet = namedtuple("Packet", ["value", "timing_us"])


class InfraredTx:
    def __init__(self, pin: Pin, rmt: RMT = None, rmt_number: int = 0, carrier_freq: int = 38000) -> None:
        self.pin = pin
        if rmt is None:
            rmt = RMT(rmt_number, pin=self.pin, clock_div=80, carrier_freq=carrier_freq)
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
            self.add(bool(data & 2 ** index))

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


RC6_TIME_FRAME_US = const(444)


class RC6(InfraredTx):
    trailing_flag = False

    def send(self, control: int, information: int, header: int = 0) -> None:
        self._current_state = None
        print("SENDING RC6 Message with Control=%s, Information=%s, Header=%s" % (control, information, header))
        self._add_start_burst()
        self._add_start_flag()
        self._add_header(header, trailing_flag=self.trailing_flag)
        self.trailing_flag = not self.trailing_flag
        self._add_control(control)
        self._add_information(information)
        self._finalize()
        self.trigger()

    def _add_start_burst(self) -> None:
        self._add(RC6_TIME_FRAME_US * 6)
        self._add(RC6_TIME_FRAME_US * 2)

    def _add_start_flag(self) -> None:
        self._add(RC6_TIME_FRAME_US)
        self._current_state = True

    def _add_header(self, header: int, trailing_flag: bool = True) -> None:
        self._add_bit_stream(header, 3)
        self._add_bit(trailing_flag, multiplicator=2)

    def _add_control(self, control: int) -> None:
        self._add_bit_stream(control, 8, previous_multiplicator=2)

    def _add_information(self, information: int) -> None:
        self._add_bit_stream(information, 8, previous_multiplicator=1)

    def _finalize(self) -> None:
        multiplier = 6
        if self._current_state:
            multiplier += 1
        else:
            self._add(RC6_TIME_FRAME_US)
        self._add(RC6_TIME_FRAME_US * multiplier)

    def _add_bit_stream(self, data: int, bit_length: int, previous_multiplicator: int = 1, multiplicator: int = 1):
        for index in range(bit_length - 1, -1, -1):
            self._add_bit(
                bool(data & 2 ** index), previous_multiplicator=previous_multiplicator, multiplicator=multiplicator
            )
            previous_multiplicator = multiplicator

    def _add_bit(self, bit: bool, previous_multiplicator: int = 1, multiplicator: int = 1) -> None:
        bit = bool(bit)
        if self._current_state == bit:
            self._add(RC6_TIME_FRAME_US * previous_multiplicator)
            self._add(RC6_TIME_FRAME_US * multiplicator)
        else:
            self._add(RC6_TIME_FRAME_US * previous_multiplicator + RC6_TIME_FRAME_US * multiplicator)
        self._current_state = bit
