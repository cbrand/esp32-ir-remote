from collections import namedtuple
import gc
import time
import uasyncio
import json
from mqtt_as import MQTTClient
from .config import get_config
from ir.ir_tx import NEC as NECTx
from ir.ir_rx import NEC as NECRx, NECMessage
from machine import Pin
from ntptime import settime

loop = uasyncio.get_event_loop()


def current_isotime():
    current_time = time.localtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*current_time[0:6])


class IRHandler:
    def __init__(self, config):
        self.tx_pin = Pin(config["tx_pin"], Pin.OUT)
        self.rx_pin = Pin(config["rx_pin"], Pin.IN)
        self.nec_tx = NECTx(self.tx_pin)
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
        elif mode is not None:
            print("Unknown mode requested for listening to IR signals \"{}\"".format(mode))
        

    async def send_nec(self, device_id: int, command: int) -> None:
        print("Adding NECMessage({}, {}) to send buffer".format(device_id, command))
        self.buffer.append(NECMessage(device_id, command))
        while command in self.buffer:
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
                    self.buffer.remove(item)
                except Exception as e:
                    print(e)
                    raise
    
    


async def wifi_han(state):
    print('Wifi is', 'up' if state else 'down')
    if state:
        settime()
    await uasyncio.sleep_ms(1000)


class Handler:
    def __init__(self, config: dict):
        config['subs_cb'] = self.sub_cb
        config['connect_coro'] = self.subscribe_topics
        config['wifi_coro'] = wifi_han
        self.config = config
        self.client = MQTTClient(config)
        self.stopped = False
        self.ir_handler = IRHandler(config)
        self.last_lifesign = None

    def stop(self):
        self.ir_handler.stop()
        self.stopped = True

    async def start(self):
        await self.client.connect()
        loop.create_task(self.ir_handler.start())
        while not self.stopped:
            if self.ir_handler.is_listening:
                sleep_ms = 1
            else:
                sleep_ms = 1000
            await uasyncio.sleep_ms(sleep_ms)
            await self.send_lifesign_if_necessary()

    async def send_command(self, data: dict) -> None:
        try:
            await self._send_command(data)
        except Exception as e:
            print(e)
            await self.send_error(str(e), data)

    async def _send_command(self, data: dict) -> None:
        data_type = data.get("type", "").upper()
        if data_type == "NEC":
            await self.send_nec_command(data)
        elif data_type == "SCENE":
            await self.play_scene(data)
        elif data_type == "WAIT":
            await uasyncio.sleep_ms(data.get("ms", data.get("s", 1) * 1000))
        elif data_type == "REPEAT":
            await self.play_repeat(data)
        else:
            await self.send_error("Unknown command type", data)

    async def send_nec_command(self, data: dict) -> None:
        if not "command" in data and not "device_id" in data:
            await self.send_error("No command or device_id added in nec command", data)
            return
        await self.ir_handler.send_nec(data["device_id"], data["command"])
        await self.client.publish(self.topic_name("ir/last-sent-command"), json.dumps(data), False, 0)

    async def play_scene(self, data: dict) -> None:
        if "scene" not in data or not isinstance(data["scene"], list):
            await self.send_error("No scene in payload")
            return

        for item in data["scene"]:
            await self._send_command(item)

    async def play_repeat(self, data: dict) -> None:
        repeats = data.get("count", 1)
        if "item" not in data:
            await self.send_error("No item in repeat configuration {}".format(data))
        for _ in range(repeats):
            await self._send_command(data["item"])

    async def send_error(self, error_message: str, context: dict = None) -> None:
        context = context or {}
        await self.client.publish(self.topic_name("error"), json.dumps({"message": error_message, "context": context}), False, 0)
        gc.collect()

    def sub_cb(self, topic: bytes, message: bytes, retained: bool) -> None:
        try:
            topic = topic.decode()
            message = message.decode()
            print('Topic = {} Payload = {} Retained = {}'.format(topic, message, retained))
            if topic.endswith("ir/command"):
                loop.create_task(self.send_command(json.loads(message)))
            elif topic.endswith("ir/listening-mode"):
                loop.create_task(self.start_listening_mode(message))
        except Exception as e:
            print(e)
            raise

    async def subscribe_topics(self, client: MQTTClient):
        await client.subscribe(self.topic_name("ir/listening-mode"), 1)
        await client.subscribe(self.topic_name("ir/command"), 1)
        await self.send_lifesign()
        print("Subscribed to topics and published livesign to {}".format(self.topic_name("livesign")))

    async def send_lifesign_if_necessary(self) -> None:
        if self.last_lifesign is None or self.last_lifesign < time.ticks_ms() - 60 * 1000:
            await self.send_lifesign()

    async def send_lifesign(self) -> None:
        await self.client.publish(self.topic_name("livesign"), json.dumps({"ticks": time.ticks_ms(), "datetime": current_isotime()}), False, 0)
        self.last_lifesign = time.ticks_ms()

    def topic_name(self, name: str) -> str:
        return topic_name(self.config, name)

    async def start_listening_mode(self, mode: str) -> None:
        self.record_mode(mode)

    def record_mode(self, mode: str) -> None:
        self.ir_handler.record_mode(mode, self._on_message_callback)

    def _on_message_callback(self, message):
        print("Captured IR Command", message)
        message_dict = message.as_dict()
        message_dict["ticks"] = time.ticks_ms()
        loop.create_task(self.client.publish(self.topic_name("ir/last-captured-command"), json.dumps(message_dict), False, 1))

    def run_forever(self) -> None:
        loop.run_until_complete(self.start())


def topic_name(config, name: str) -> str:
    return "{}/{}".format(config["topic_prefix"], name)
