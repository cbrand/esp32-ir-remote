import uasyncio
from ir.ir_rx import NEC as NECRx
from ir.ir_rx import RC6 as RC6Rx
from ir.ir_rx import NECMessage, RC6Message
from ir.ir_tx import NEC as NECTx
from ir.ir_tx import RC6 as RC6Tx
from machine import Pin


class IRHandler:
    def __init__(self, config):
        self.tx_pin = Pin(config["tx_pin"], Pin.OUT)
        self.rx_pin = Pin(config["rx_pin"], Pin.IN)
        self.nec_tx = NECTx(self.tx_pin)
        self.rc6_tx = RC6Tx(self.tx_pin, rmt=self.nec_tx.rmt)
        self.receiver = None
        self.buffer = []
        self.stopped = False
        self.callback = None

    @property
    def is_listening(self) -> bool:
        return self.receiver is not None

    def record_mode(self, mode: str, callback) -> None:
        if self.receiver is not None:
            self.receiver.close()
            self.receiver = None
        self.callback = callback

        if isinstance(mode, str) and mode.upper() == "NEC":
            self.receiver = NECRx(self.rx_pin, callback)
            return
        elif isinstance(mode, str) and mode.upper() == "RC6":
            self.receiver = RC6Rx(self.rx_pin, callback)
            return
        elif mode is not None:
            print('Unknown mode requested for listening to IR signals "{}"'.format(mode))

    async def send_nec(self, device_id: int, command: int) -> None:
        print("Adding NECMessage({}, {}) to send buffer".format(device_id, command))
        nec_message = NECMessage(device_id, command)
        self.buffer.append(nec_message)
        while nec_message in self.buffer:
            await uasyncio.sleep_ms(1)

    async def send_rc6(self, control: int, information: int, mode: int = 0) -> None:
        print("Adding RC6Message({}, {}, {}) to send buffer".format(mode, control, information))
        rc6_message = RC6Message(mode, control, information)
        self.buffer.append(rc6_message)
        while rc6_message in self.buffer:
            await uasyncio.sleep_ms(1)

    def stop(self) -> None:
        self.stopped = True

    async def start(self) -> None:
        while not self.stopped:
            await uasyncio.sleep_ms(100)
            if len(self.buffer) > 0:
                try:
                    item = self.buffer[0]
                    if isinstance(item, NECMessage):
                        print("SENDING ", item)
                        self.nec_tx.send(item.device_id, item.command)
                        await uasyncio.sleep_ms(100)
                    if isinstance(item, RC6Message):
                        print("SENDING", item)
                        self.rc6_tx.send(header=item.header, control=item.control, information=item.information)
                        await uasyncio.sleep_ms(100)
                    self.buffer.remove(item)
                except Exception as e:
                    print(e)
                    raise
