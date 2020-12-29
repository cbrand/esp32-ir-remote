from collections import namedtuple
import struct
import re
import time



class ISCPMessage(object):
    """Deals with formatting and parsing data wrapped in an ISCP
    containers. The docs say:
        ISCP (Integra Serial Control Protocol) consists of three
        command characters and parameter character(s) of variable
        length.
    It seems this was the original protocol used for communicating
    via a serial cable.
    """

    def __init__(self, data: str):
        self.data = data

    def __str__(self) -> str:
        # ! = start character
        # 1 = destination unit type, 1 means receiver
        # End character may be CR, LF or CR+LF, according to doc
        return '!1{}\r'.format(self.data)

    @classmethod
    def parse(self, data: bytes) -> bytes:
        EOF = '\x1a'
        TERMINATORS = ['\n', '\r']
        assert data[:2] == '!1'
        eof_offset = -1
        # EOF can be followed by CR/LF/CR+LF
        if data[eof_offset] in TERMINATORS:
          eof_offset -= 1
          if data[eof_offset] in TERMINATORS:
            eof_offset -= 1
        assert data[eof_offset] == EOF
        return data[2:eof_offset]


class eISCPPacket(object):
    """For communicating over Ethernet, traditional ISCP messages are
    wrapped inside an eISCP package.
    """

    header = namedtuple('header', ('magic', 'header_size', 'data_size', 'version', 'reserved'))

    def __init__(self, iscp_message: "Union[bytes, str]"):
        iscp_message = str(iscp_message)
        # We attach data separately, because Python's struct module does
        # not support variable length strings,
        header = struct.pack(
            '!4sIIb3s',
            b'ISCP',            # magic
            16,                 # header size (16 bytes)
            len(iscp_message),  # data size
            0x01,               # version
            b'\x00\x00\x00'     #reserved
        )

        if isinstance(iscp_message, str):
            iscp_message = iscp_message.encode("utf-8")

        self._bytes = header + iscp_message
        # __new__, string subclass?

    def __str__(self):
        return self._bytes.decode('utf-8')

    def get_raw(self):
        return self._bytes

    @classmethod
    def parse(cls, bytes):
        """Parse the eISCP package given by ``bytes``.
        """
        h = cls.parse_header(bytes[:16])
        data = bytes[h.header_size:h.header_size + h.data_size].decode()
        assert len(data) == h.data_size
        return data

    @classmethod
    def parse_header(self, bytes):
        """Parse the header of an eISCP package.
        This is useful when reading data in a streaming fashion,
        because you can subsequently know the number of bytes to
        expect in the packet.
        """
        # A header is always 16 bytes in length
        assert len(bytes) == 16

        # Parse the header
        magic, header_size, data_size, version, reserved = \
            struct.unpack('!4sIIb3s', bytes)

        magic = magic.decode()
        reserved = reserved.decode()

        # Strangly, the header contains a header_size field.
        assert magic == 'ISCP'
        assert header_size == 16

        return eISCPPacket.header(
            magic, header_size, data_size, version, reserved)



def parse_info(data: bytes) -> "Dict[str, str]":
    response = eISCPPacket.parse(data)
    # Return string looks something like this:
    # !1ECNTX-NR609/60128/DX
    matched = re.match(r'''!(\d)ECN([^/]*)/(\d\d\d\d\d)/(\w\w)/(.*)''', response.strip())
    if matched is None:
        return None
    
    identifier = matched.group(5)
    if len(identifier) > 12:
        identifier = identifier[0:12]

    info = {
        "device_category": matched.group(1),
        "model_name": matched.group(2),
        "iscp_port": matched.group(3),
        "area_code": matched.group(4),
        "identifier": identifier
    }
    return info


def command_to_packet(command: str) -> bytes:
    """
    Convert an ascii command like (PVR00) to the binary data we
    need to send to the receiver.
    """
    return eISCPPacket(ISCPMessage(command)).get_raw()


def filter_for_message(getter_func: "Callable[[], Optional[str]]", msg: str) -> str:
    """Helper that calls ``getter_func`` until a matching message
    is found, or the timeout occurs. Matching means the same commands
    group, i.e. for sent message MVLUP we would accept MVL13
    in response."""
    start = time.time()
    while True:
        candidate = getter_func(0.05)
        # It seems ISCP commands are always three characters.
        if candidate and candidate[:3] == msg[:3]:
            return candidate

        # exception for HDMI-CEC commands (CTV) since they don't provide any response/confirmation
        if "CTV" in msg[:3]:
            return msg
        
        # The protocol docs claim that a response  should arrive
        # within *50ms or the communication has failed*. In my tests,
        # however, the interval needed to be at least 200ms before
        # I managed to see any response, and only after 300ms
        # reproducably, so use a generous timeout.
        if time.time() - start > 5.0:
            raise ValueError('Timeout waiting for response.')



def command_to_iscp(command: str, argument: str) -> str:
    return "{}{}".format(command, argument)


def iscp_to_command(iscp_message: str) -> "Tuple[str, str]":
    command, args = iscp_message[:3], iscp_message[3:]
    return command, args
