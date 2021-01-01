import gc
import json
import time

import uasyncio
from mqtt_as import MQTTClient
from ntptime import settime

from .ir_handler import IRHandler
from .iscp_handler import ISCPHandler

loop = uasyncio.get_event_loop()


def current_isotime():
    current_time = time.localtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*current_time[0:6])


async def wifi_han(state):
    print("Wifi is", "up" if state else "down")
    if state:
        settime()
    await uasyncio.sleep_ms(1000)


class Handler:
    def __init__(self, config: dict):
        config["subs_cb"] = self.sub_cb
        config["connect_coro"] = self.subscribe_topics
        config["wifi_coro"] = wifi_han
        self.config = config
        self.client = MQTTClient(config)
        self.stopped = False
        self.ir_handler = IRHandler(config)
        self.last_lifesign = None
        self.iscp_handler = ISCPHandler()

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
        if data_type == "RC6":
            await self.send_rc6_command(data)
        elif data_type == "ISCP":
            await self.send_iscp_command(data)
        elif data_type == "SCENE":
            await self.play_scene(data)
        elif data_type == "WAIT":
            await uasyncio.sleep_ms(data.get("ms", data.get("s", 1) * 1000))
        elif data_type == "REPEAT":
            await self.play_repeat(data)
        else:
            await self.send_error("Unknown command type", data)

    async def iscp_discover(self) -> None:
        try:
            print("Searching for ISCP devices on network")
            result = await self.iscp_handler.discover()
            print("ISCP devices found: {}".format(result))
            await self.client.publish(self.topic_name("iscp/discover/result"), json.dumps(result), False, 0)
        except Exception as error:
            print("Failed Discovering ISCP devices with error {}".format(error))
            await self.send_error("Failed discovering iscp devices with error {}".format(error))

    async def send_iscp_command(self, data: dict) -> None:
        if "identifier" not in data or "command" not in data or "argument" not in data:
            await self.send_error("No identifier, command or argument provided in iscp payload", data)
        identifier: str = data["identifier"]
        command: str = data["command"]
        argument: str = data["argument"]

        retries = 0

        check = False
        result = None
        while not check:
            try:
                result = await self.iscp_handler.send(identifier, command, argument)
                check = True
            except Exception as error:
                await self.send_error(
                    "Could not send ISCP command ({}, {}={}). Error: {}. Retry: {}".format(
                        identifier, command, argument, error, retries
                    ),
                    data,
                )
                retries += 1
                if retries > 3:
                    raise error

        if result is None:
            await self.send_error("Could not send ISCP command ({}, {}={})".format(identifier, command, argument), data)

        data["result"] = result
        data["type"] = "ISCP"
        await self._record_send_command(data)

    async def send_nec_command(self, data: dict) -> None:
        if "command" not in data and "device_id" not in data:
            await self.send_error("No command or device_id added in nec command", data)
            return
        await self.ir_handler.send_nec(data["device_id"], data["command"])
        await self._record_send_command(data)

    async def send_rc6_command(self, data: dict) -> None:
        if "control" not in data or "information" not in data:
            await self.send_error("No control or information added in rc9 command", data)
        await self.ir_handler.send_rc6(
            mode=data.get("mode", 0), control=data["control"], information=data["information"]
        )
        await self._record_send_command(data)

    async def _record_send_command(self, data: dict) -> None:
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
        await self.client.publish(
            self.topic_name("error"), json.dumps({"message": error_message, "context": context}), False, 0
        )
        gc.collect()

    def sub_cb(self, topic: bytes, message: bytes, retained: bool) -> None:
        try:
            topic = topic.decode()
            message = message.decode()
            print("Topic = {} Payload = {} Retained = {}".format(topic, message, retained))
            if topic.endswith("ir/command"):
                loop.create_task(self.send_command(json.loads(message)))
            elif topic.endswith("ir/listening-mode"):
                loop.create_task(self.start_listening_mode(message))
            elif topic.endswith("iscp/command"):
                loop.create_task(self.send_iscp_command(json.loads(message)))
            elif topic.endswith("iscp/discover"):
                loop.create_task(self.iscp_discover())
            else:
                print("Unknown MQTT topic for subscription {}".format(topic))
        except Exception as e:
            print(e)
            raise

    async def subscribe_topics(self, client: MQTTClient):
        await client.subscribe(self.topic_name("ir/listening-mode"), 1)
        await client.subscribe(self.topic_name("ir/command"), 1)
        await client.subscribe(self.topic_name("iscp/discover"), 1)
        await client.subscribe(self.topic_name("iscp/command"), 1)
        await self.send_lifesign()
        print("Subscribed to topics and published livesign to {}".format(self.topic_name("livesign")))

    async def send_lifesign_if_necessary(self) -> None:
        if self.last_lifesign is None or self.last_lifesign + 5 * 1000 < time.ticks_ms():
            await self.send_lifesign()

    async def send_lifesign(self) -> None:
        await self.client.publish(
            self.topic_name("livesign"), json.dumps({"ticks": time.ticks_ms(), "datetime": current_isotime()}), True, 0
        )
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
        loop.create_task(
            self.client.publish(self.topic_name("ir/last-captured-command"), json.dumps(message_dict), False, 1)
        )

    def run_forever(self) -> None:
        loop.run_until_complete(self.start())


def topic_name(config, name: str) -> str:
    return "{}/{}".format(config["topic_prefix"], name)
