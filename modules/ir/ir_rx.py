import math
import time
from machine import Pin, Timer
from collections import namedtuple
from array import array


class InfraredRX:
    def __init__(self, pin: Pin, number_edges: int, block_time_us: int):
        self.pin = pin
        self.number_edges = number_edges
        self.buffer = array('i', (0 for _ in range(number_edges)))
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
        self.buffer = array('i', (0 for _ in range(self.number_edges)))
        self.index = 0

    def close(self):
        self.pin.deinit()


class NECMessage(namedtuple("NECMessage", ["device_id", "command"])):
    def as_dict(self) -> dict:
        return {
            "type": "NEC",
            "device_id": self.device_id,
            "command": self.command
        }


def is_nec_start_high(first_timing: int, second_timing: int) -> bool:
    return (
        8000 < first_timing < 10000 and
        3500 < second_timing < 5500
    )


def convert_nec_to_bit(first_timing: int, second_timing: int) -> int:
    assert 250 < first_timing < 850
    return int(second_timing > 1100)


MAX_DEVICE_ID_INDEX = 9
MAX_DEVICE_ID_CHECK_INDEX = MAX_DEVICE_ID_INDEX + 8
MAX_COMMAND_ID_INDEX = MAX_DEVICE_ID_CHECK_INDEX + 8
MAX_COMMAND_ID_CHECK_INDEX = MAX_COMMAND_ID_INDEX + 8


class NEC(InfraredRX):
    def __init__(self, pin: Pin, callback=None):
        super().__init__(pin=pin, number_edges=(8*4+2+1)*2, block_time_us=80 * 1000)
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
        start_flag_received = False

        last_timing = None

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
            print("Could not decode NEC message DeviceID(%s, %s), CommandID(%s, %s)" % (device_id, device_id_check, command_id, command_id_check))
            return None
