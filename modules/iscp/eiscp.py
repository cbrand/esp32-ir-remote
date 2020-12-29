import select
import socket
from .core import ISCPMessage, eISCPPacket, parse_info, command_to_packet, filter_for_message, command_to_iscp, iscp_to_command


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
        if self.info and self.info.get('model_name'):
            return self.info['model_name']
        else:
            return 'unknown-model'

    @property
    def identifier(self) -> str:
        if self.info and self.info.get('identifier'):
            return self.info['identifier']
        else:
            return 'no-id'

    def __repr__(self) -> str:
        if self.info and self.info.get('model_name'):
            model = self.info['model_name']
        else:
            model = 'unknown'
        string = "<{}({}) {}:{}>".format(
            self.__class__.__name__, model, self.host, self.port)
        return string

    @property
    def info(self) -> "Dict[str, str]":
        if not self._info:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setblocking(0)
            sock.bind(('0.0.0.0', self.ONKYO_PORT))
            sock.sendto(eISCPPacket('!xECNQSTN').get_raw(), (self.host, self.port))

            ready = select.select([sock], [], [], 0.1)
            if ready[0]:
                data = sock.recv(1024)
                self._info = parse_info(data)
            sock.close()
        return self._info

    @info.setter
    def info(self, value: "Dict[str, str]"):
        self._info = value

    def _ensure_socket_connected(self) -> None:
        if self.command_socket is None:
            self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.command_socket.settimeout(self.CONNECT_TIMEOUT)
            self.command_socket.connect((self.host, self.port))
            self.command_socket.setblocking(0)

    def disconnect(self) -> None:
        try:
            self.command_socket.close()
        except:
            pass
        self.command_socket = None

    def __enter__(self):
        self._ensure_socket_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def send(self, iscp_message: str) -> None:
        """Send a low-level ISCP message, like ``MVL50``.
        This does not return anything, nor does it wait for a response
        from the receiver. You can query responses via :meth:`get`,
        or use :meth:`raw` to send a message and waiting for one.
        """
        self._ensure_socket_connected()
        self.command_socket.send(command_to_packet(iscp_message))

    def get(self, timeout: int=0.1) -> bytes:
        """Return the next message sent by the receiver, or, after
        ``timeout`` has passed, return ``None``.
        """
        self._ensure_socket_connected()

        ready = select.select([self.command_socket], [], [], timeout or 0)
        if ready[0]:
            header_bytes = self.command_socket.recv(16)
            header = eISCPPacket.parse_header(header_bytes)
            body = b''
            while len(body) < header.data_size:
                ready = select.select([self.command_socket], [], [], timeout or 0)
                if not ready[0]:
                    return None
                body += self.command_socket.recv(header.data_size - len(body))
            return ISCPMessage.parse(body.decode())

    def raw(self, iscp_message):
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
        while self.get(False):
            # Clear all incoming messages. If not yet queried,
            # they are lost. This is so that we can find the real
            # response to our sent command later.
            pass
        self.send(iscp_message)
        return filter_for_message(self.get, iscp_message)

    def command(self, command: str, argument: str) -> "Optional[str]":
        """Send a high-level command to the receiver, return the
        receiver's response formatted has a command.
        This is basically a helper that combines :meth:`raw`,
        :func:`command_to_iscp` and :func:`iscp_to_command`.
        """
        iscp_message = command_to_iscp(command, argument)
        response = self.raw(iscp_message)
        if response:
            return iscp_to_command(response)

    def power_on(self) -> Optional[str]:
        """Turn the receiver power on."""
        return self.command('PWR', '01')

    def power_off(self) -> Optional[str]:
        """Turn the receiver power off."""
        return self.command('PWR', '00')