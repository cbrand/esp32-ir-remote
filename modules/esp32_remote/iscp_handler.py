from collections import namedtuple
from uasyncio import Lock

from eiscp import discover, eISCP


class ISCPCommand(namedtuple("ISCPCommand", ("identifier", "command", "argument"))):
    @property
    def expect_response(self) -> bool:
        return True


class ISCPHandler:
    def __init__(self):
        self.known_iscps: "Dict[str, eISCP]" = {}
        self.known_iscps_lock: "Dict[str, Lock]" = {}

    def reset(self) -> None:
        self.known_iscps = {}
        self.known_iscps_lock = {}

    async def _update_known_iscps(self) -> None:
        self.known_iscps.update(dict((item.identifier, item) for item in await discover()))

    async def discover(self) -> "List[Dict[str, str]]":
        await self._update_known_iscps()
        return list(iscp.info for iscp in self.known_iscps.values())

    async def send(self, identifier: str, command: str, argument: str) -> "Optional[Tuple[str, str]]":
        print("Sending ISCP command({}, {}={}) to send buffer".format(identifier, command, argument))
        iscp_command = ISCPCommand(identifier, command, argument)

        lock = self.known_iscps_lock.setdefault(identifier, Lock())

        async with lock:
            iscp = await self._get_or_query(identifier)
            if iscp is None:
                print("Didn't find ISCP target with identifier {}".format(identifier))
                return None
            print("Found ISCP device for sending to {} ({})".format(identifier, iscp.info))

            try:
                result = await iscp.command(iscp_command.command, iscp_command.argument, iscp_command.expect_response)
            except ValueError:
                print("ISCP timeout for ISCP command {}".format(iscp_command))
                result = None

        return result

    async def _get_or_query(self, identifier: str) -> "Optional[eISCP]":
        if identifier in self.known_iscps:
            return self.known_iscps[identifier]

        await self._update_known_iscps()
        return self.known_iscps.get(identifier, None)
