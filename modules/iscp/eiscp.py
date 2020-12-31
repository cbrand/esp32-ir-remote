import select
import socket
import time

import uasyncio

from .core import (
    ISCPMessage,
    command_to_iscp,
    command_to_packet,
    eISCPPacket,
    filter_for_message,
    iscp_to_command,
    parse_info,
)


class eISCP:
    """Implements the eISCP interface to Onkyo receivers.
    This uses a blocking interface. The remote end will regularily
    send unsolicited status updates. You need to manually call
    ``get_message`` to query those.
    You may want to look at the :meth:`Receiver` class instead, which
    uses a background thread.
    """

    ONKYO_PORT = 60128
    CONNECT_TIMEOUT = 5

    def __init__(self, host, port=60128):
        self.host = host
        self.port = port
        self._info = None

        self.command_socket = None

    @property
    def model_name(self) -> str:
        if self.info and self.info.get("model_name"):
            return self.info["model_name"]
        else:
            return "unknown-model"

    @property
    def identifier(self) -> str:
        if self.info and self.info.get("identifier"):
            return self.info["identifier"]
        else:
            return "no-id"

    def __repr__(self) -> str:
        if self.info and self.info.get("model_name"):
            model = self.info["model_name"]
        else:
            model = "unknown"
        string = "<{}({}) {}:{}>".format(self.__class__.__name__, model, self.host, self.port)
        return string

    @property
    def info(self) -> "Dict[str, str]":
        if not self._info:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setblocking(0)
            sock.bind(("0.0.0.0", self.ONKYO_PORT))
            sock.sendto(eISCPPacket("!xECNQSTN").get_raw(), (self.host, self.port))

            ready = select.select([sock], [], [], 0.1)
            if ready[0]:
                data = sock.recv(1024)
                self._info = parse_info(data)
            sock.close()
        return self._info

    @info.setter
    def info(self, value: "Dict[str, str]") -> None:
        self._info = value

    def _ensure_socket_connected(self) -> None:
        if self.command_socket is None:
            command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            command_socket.settimeout(self.CONNECT_TIMEOUT)
            command_socket.connect((self.host, self.port))
            command_socket.setblocking(0)
            self.command_socket = uasyncio.StreamWriter(command_socket)

    def disconnect(self) -> None:
        try:
            self.command_socket.close()
        except Exception:
            pass
        self.command_socket = None

    def __enter__(self):
        self._ensure_socket_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    async def send(self, iscp_message: str) -> None:
        """Send a low-level ISCP message, like ``MVL50``.
        This does not return anything, nor does it wait for a response
        from the receiver. You can query responses via :meth:`get`,
        or use :meth:`raw` to send a message and waiting for one.
        """
        self._ensure_socket_connected()
        self.command_socket.write(command_to_packet(iscp_message))
        await self.command_socket.drain()

    async def get(self, timeout: int = 0.2) -> bytes:
        """Return the next message sent by the receiver, or, after
        ``timeout`` has passed, return ``None``.
        """
        self._ensure_socket_connected()

        start = time.ticks_ms()
        header_bytes = b""
        while start + timeout * 1000 > time.ticks_ms() and len(header_bytes) < 16:
            header_bytes += await self.command_socket.read(16 - len(header_bytes))
            if len(header_bytes) < 16:
                await uasyncio.sleep_ms(1)

        if len(header_bytes) < 16:
            return None

        header = eISCPPacket.parse_header(header_bytes)
        print("Found ISCP header {}".format(header))
        body = b""
        start = time.ticks_ms()
        while len(body) < header.data_size:
            body += await self.command_socket.read(header.data_size - len(body))
            if start + timeout * 1000 < time.ticks_ms():
                return None
            elif len(body) < header.data_size:
                await uasyncio.sleep_ms(1)
        message = ISCPMessage.parse(body.decode())
        print("Identified ISCP response: {}".format(message))
        return message

    async def raw(self, iscp_message):
        """Send a low-level ISCP message, like ``MVL50``, and wait
        for a response.
        While the protocol is designed to acknowledge each message with
        a response, there is no fool-proof way to differentiate those
        from unsolicited status updates, though we'll do our best to
        try. Generally, this won't be an issue, though in theory the
        response this function returns to you sending ``SLI05`` may be
        an ``SLI06`` update from another controller.
        It'd be preferable to design your app in a way where you are
        processing all incoming messages the same way, regardless of
        their origin.
        """
        while await self.get(False):
            # Clear all incoming messages. If not yet queried,
            # they are lost. This is so that we can find the real
            # response to our sent command later.
            pass
        await self.send(iscp_message)
        return await filter_for_message(self.get, iscp_message)

    async def command(self, command: str, argument: str) -> "Optional[Tuple[str, str]]":
        """Send a high-level command to the receiver, return the
        receiver's response formatted has a command.
        This is basically a helper that combines :meth:`raw`,
        :func:`command_to_iscp` and :func:`iscp_to_command`.
        """
        iscp_message = command_to_iscp(command, argument)
        response = await self.raw(iscp_message)
        if response:
            return iscp_to_command(response)

        return None

    async def power_on(self) -> "Optional[Tuple[str, str]]":
        """Turn the receiver power on."""
        return await self.command("PWR", "01")

    async def power_off(self) -> "Optional[Tuple[str, str]]":
        """Turn the receiver power off."""
        return await self.command("PWR", "00")
