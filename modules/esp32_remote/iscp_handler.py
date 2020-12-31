from collections import namedtuple
from uasyncio import Lock

from iscp import discover, eISCP

ISCPCommand = namedtuple("ISCPCommand", ("identifier", "command", "argument"))


class ISCPHandler:
    def __init__(self):
        self.known_iscps: "Dict[str, eISCP]" = {}
        self.known_iscps_lock: "Dict[str, Lock]" = {}

    async def _update_known_iscps(self) -> None:
        self.known_iscps.update(dict((item.identifier, item) for item in await discover()))

    async def discover(self) -> "List[Dict[str, str]]":
        await self._update_known_iscps()
        return list(iscp.info for iscp in self.known_iscps.values())

    async def send(self, identifier: str, command: str, argument: str) -> "Optional[Tuple[str, str]]":
        print("Sending ISCP command({}, {}={}) to send buffer".format(identifier, command, argument))
        iscp_command = ISCPCommand(identifier, command, argument)

        lock = self.known_iscps_lock.setdefault(identifier, Lock())
        with await lock:
            iscp = await self._get_or_query(identifier)
            if iscp is None:
                print("Didn't find ISCP target with identifier {}".format(iscp))
                return None
            print("Found ISCP device for sending to {} ({})".format(identifier, iscp.info))

            return await iscp.command(iscp_command.command, iscp_command.argument)

    async def _get_or_query(self, identifier: str) -> "Optional[eISCP]":
        if identifier in self.known_iscps:
            return self.known_iscps[identifier]

        await self._update_known_iscps()
        return self.known_iscps.get(identifier, None)
