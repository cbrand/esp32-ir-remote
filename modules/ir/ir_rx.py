import math
import time
from array import array
from collections import namedtuple

from machine import Pin, Timer
from micropython import const


class InfraredRX:
    def __init__(self, pin: Pin, number_edges: int, block_time_us: int):
        self.pin = pin
        self.number_edges = number_edges
        self.buffer = array("i", (0 for _ in range(number_edges)))
        self.block_time_us = block_time_us
        self.wait_time_ms = int(math.floor(self.block_time_us / 1000))
        self.index = 0
        pin.irq(handler=self._on_data, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)
        self.timer = Timer(1)

    def _on_data(self, pin):
        tick_time = time.ticks_us()
        if self.index < self.number_edges:
            if not self.index:
                self.timer.init(period=self.wait_time_ms, mode=Timer.ONE_SHOT, callback=lambda *args: self._callback())

            self.buffer[self.index] = tick_time
            self.index += 1

    @property
    def time_relative_buffer(self):
        start = None
        d = []
        for item in self.buffer:
            if start is None:
                start = item
            if item <= 0:
                break

            d.append(item - start)
            start = item
        return d

    def _callback(self):
        self.buffer = array("i", (0 for _ in range(self.number_edges)))
        self.index = 0

    def close(self):
        self.pin.deinit()


class NECMessage(namedtuple("NECMessage", ["device_id", "command"])):
    def as_dict(self) -> dict:
        return {"type": "NEC", "device_id": self.device_id, "command": self.command}


def is_nec_start_high(first_timing: int, second_timing: int) -> bool:
    return 8000 < first_timing < 10000 and 3500 < second_timing < 5500


def convert_nec_to_bit(first_timing: int, second_timing: int) -> int:
    assert 250 < first_timing < 850
    return int(second_timing > 1100)


MAX_DEVICE_ID_INDEX = 9
MAX_DEVICE_ID_CHECK_INDEX = MAX_DEVICE_ID_INDEX + 8
MAX_COMMAND_ID_INDEX = MAX_DEVICE_ID_CHECK_INDEX + 8
MAX_COMMAND_ID_CHECK_INDEX = MAX_COMMAND_ID_INDEX + 8


class NEC(InfraredRX):
    def __init__(self, pin: Pin, callback=None):
        super().__init__(pin=pin, number_edges=(8 * 4 + 2 + 1) * 2, block_time_us=80 * 1000)
        self.on_data = callback

    def _callback(self):
        decoded = self._decode()
        if decoded is not None:
            if self.on_data is None:
                print(decoded)
            else:
                self.on_data(decoded)

        super()._callback()

    def _decode(self) -> "Optional[NECMessage]":
        start_high_received = False

        device_id = 0
        device_id_check = 0
        command_id = 0
        command_id_check = 0

        for index in range(self.number_edges / 2):
            real_index = index * 2
            if real_index + 2 >= self.number_edges:
                break
            first_timing = self.buffer[real_index + 1] - self.buffer[real_index]
            second_timing = self.buffer[real_index + 2] - self.buffer[real_index + 1]

            if not start_high_received:
                if not is_nec_start_high(first_timing, second_timing):
                    print("Start Flag not there Timing(%s, %s)" % (first_timing, second_timing))
                    return None
                else:
                    start_high_received = True
                    continue

            try:
                nec_bit = convert_nec_to_bit(first_timing, second_timing)
            except AssertionError:
                print("Cannot decode NEC Burst(%s, %s)" % (first_timing, second_timing))
                return None

            if index < MAX_DEVICE_ID_INDEX:
                device_id = (device_id << 1) | nec_bit
            elif index < MAX_DEVICE_ID_CHECK_INDEX:
                device_id_check = (device_id_check << 1) | nec_bit
            elif index < MAX_COMMAND_ID_INDEX:
                command_id = (command_id << 1) | nec_bit
            elif index < MAX_COMMAND_ID_CHECK_INDEX:
                command_id_check = (command_id_check << 1) | nec_bit

        if device_id == device_id_check ^ 0xFF and command_id == command_id_check ^ 0xFF:
            return NECMessage(device_id, command_id)
        else:
            print(
                "Could not decode NEC message DeviceID(%s, %s), CommandID(%s, %s)"
                % (device_id, device_id_check, command_id, command_id_check)
            )
            return None


RC6_TIME_FRAME_US = const(444)
RC6_LS_TIME = const(RC6_TIME_FRAME_US * 6 + RC6_TIME_FRAME_US * 2)
RC6_NORMAL_BIT_TIME = const(RC6_TIME_FRAME_US * 2)
RC6_TRAILER_BIT_TIME = const(RC6_NORMAL_BIT_TIME * 2)
RC6_SIGNAL_FREE_TIME = const(RC6_TIME_FRAME_US * 6)
RC6_BLOCK_TIME = const(
    sum(
        (
            RC6_LS_TIME,
            RC6_NORMAL_BIT_TIME,
            RC6_NORMAL_BIT_TIME * 3,
            RC6_TRAILER_BIT_TIME,
            RC6_NORMAL_BIT_TIME * 16,
            RC6_SIGNAL_FREE_TIME,
        )
    )
)


def convert_to_int(byte_list: List[int]) -> int:
    item = 0
    for byte_item in byte_list:
        item = (item << 1) | byte_item
    return item


class RC6Message(namedtuple("RC6Message", ["header", "control", "information"])):
    def as_dict(self) -> dict:
        return {"type": "RC6", "header": self.header, "control": self.control, "information": self.information}


def is_rc6_start(first_timing: int, second_timing: int) -> bool:
    first_timing_fits = RC6_TIME_FRAME_US * 5 < first_timing < RC6_TIME_FRAME_US * 7
    second_timing_fits = RC6_TIME_FRAME_US * 1 < second_timing < RC6_TIME_FRAME_US * 3
    return first_timing_fits and second_timing_fits


def timing_in_rc_units(timing: int) -> int:
    return int(round(float(timing) / RC6_TIME_FRAME_US))


def buffer_to_rc6(buffer: List[int]) -> Optional[RC6Message]:
    if len(buffer) != 20:
        print("Tried to convert a message which doesn't have 20 bits for RC6. Aborting. Message: %s" % buffer)
        return None

    mode = convert_to_int(buffer[0:3])
    if mode != 0:
        print("Unknown RC6 mode received. Only mode 0 is supported. Got an RC6 message with mode %s" % mode)
        return None

    control_buffer_start = 4
    control_buffer_end = control_buffer_start + 8
    control = buffer[control_buffer_start:control_buffer_end]
    information_buffer_start = control_buffer_end
    information_buffer_end = information_buffer_start + 8
    information = buffer[information_buffer_start:information_buffer_end]
    return RC6Message(header=mode, control=convert_to_int(control), information=convert_to_int(information))


class RC6(InfraredRX):
    def __init__(self, pin: Pin, callback=None):
        super().__init__(pin=pin, number_edges=(1 + 1 + 3 + 1 + 8 * 2 + 1) * 2, block_time_us=RC6_BLOCK_TIME)
        self.on_data = callback

    def _callback(self):
        decoded = self._decode()
        if decoded is not None:
            if self.on_data is None:
                print(decoded)
            else:
                self.on_data(decoded)

        super()._callback()

    def _decode(self) -> "Optional[RC6Message]":
        buffer = self.time_relative_buffer
        if len(buffer) < 4:
            return None

        timing_buffer = [timing_in_rc_units(item) for item in buffer]
        first_timing = buffer[1]
        second_timing = buffer[2]
        if not is_rc6_start(first_timing, second_timing):
            print("Could not decode RC6 message. Timing(%s, %s)" % (first_timing, second_timing))
            return None

        current_state = 1
        if timing_in_rc_units(buffer[3]) != 1:
            print(
                "Could not decode RC6 message. Timing of Start bit after LS bit is not 1 Unit. "
                "Timing was (%s, %s ticks)" % (buffer[3], timing_in_rc_units(buffer[3]))
            )
            return None

        decoded_binary = []
        last_recorded_index = 3

        def record_value(state: int) -> None:
            decoded_binary.append(state % 2)

        for i in range(4, len(buffer)):
            rc_unit_timing = timing_in_rc_units(buffer[i])
            if len(decoded_binary) == 4 + 2 * 8:
                if i - last_recorded_index == 1:
                    continue

                if rc_unit_timing == 0 or rc_unit_timing in (6, 7):
                    return buffer_to_rc6(decoded_binary)
                else:
                    print(
                        "Did not find RC6 signal free time at index %s on buffer %s with timings %s with payload %s"
                        % (i, buffer, timing_buffer, decoded_binary)
                    )
                    return None
            if len(decoded_binary) == 3:
                # Header time
                if rc_unit_timing == 2:
                    if i - last_recorded_index > 1:
                        record_value(current_state)
                        last_recorded_index = i
                elif rc_unit_timing == 3:
                    current_state = current_state + 1
                    record_value(current_state)
                    last_recorded_index = i
                else:
                    print(
                        "Invalid state sending in RC6 message on header. "
                        "Stopped at index %s on buffer %s with timings %s" % (i, buffer, timing_buffer)
                    )
                    return None

            elif rc_unit_timing == 1:
                # No Change in current state
                if i - last_recorded_index > 1:
                    record_value(current_state)
                    last_recorded_index = i
            elif rc_unit_timing == 2 or rc_unit_timing == 3 and len(decoded_binary) == 4:
                current_state = current_state + 1
                record_value(current_state)
                last_recorded_index = i
            else:
                print(
                    "Invalid state sending in RC6 message. Stopped at index %s on buffer %s with timings %s"
                    % (i, buffer, timing_buffer)
                )
                return None

        if len(buffer) % 2 == 1:
            decoded_binary.append(current_state)

        return buffer_to_rc6(decoded_binary)
