import uasyncio
import socket
import network
import time
from .core import eISCPPacket, parse_info
from .eiscp import eISCP


def get_current_ip_address() -> str:
    wlan_network = network.WLAN(network.STA_IF)
    if not wlan_network.isconnected():
        raise OSError("Must connect to network first")
    connection_details = wlan_network.ifconfig()
    return connection_details[0]


def get_current_broadcast_address() -> str:
    wlan_network = network.WLAN(network.STA_IF)
    if not wlan_network.isconnected():
        raise OSError("Must connect to network first")
    connection_details = wlan_network.ifconfig()
    ip_address = connection_details[0]
    netmask = connection_details[1]
    ip_address_segments = (int(item) for item in ip_address.split("."))
    netmask_segments = (int(item) for item in netmask.split("."))
    broadcast_segments = []
    for (ip_address_segment, netmask_segment) in zip(ip_address_segments, netmask_segments):
        if int(netmask_segment) == 255:
            broadcast_segments.append(ip_address_segment)
        else:
            network_segment = ip_address_segment & netmask_segment
            broadcast_segments.append(network_segment + (255 - netmask_segment))
    return ".".join(str(item) for item in broadcast_segments)


async def discover(timeout: int = 5, clazz=None):
    onkyo_magic = eISCPPacket('!xECNQSTN').get_raw()
    pioneer_magic = eISCPPacket('!pECNQSTN').get_raw()
    found_receivers = {}
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    broadcast_socket.setblocking(0)
    broadcast_address = get_current_broadcast_address()
    own_address = get_current_ip_address()
    
    try:
        broadcast_socket.bind((own_address, eISCP.ONKYO_PORT))  # The port doesn't matter. It is "0" in the original implementation. MicroPython doesn't support this.
        broadcast_socket.sendto(onkyo_magic, (broadcast_address, eISCP.ONKYO_PORT))
        broadcast_socket.sendto(pioneer_magic, (broadcast_address, eISCP.ONKYO_PORT))
        start = time.ticks_ms()
        while True:
            ready = uasyncio.select.select([broadcast_socket], [], [], 0.01)
            if not ready[0]:
                await uasyncio.sleep_ms(100)
            else:
                data, addr = broadcast_socket.recvfrom(1024)
                info = parse_info(data)
                receiver = (clazz or eISCP)(addr[0], int(info['iscp_port']))
                receiver.info = info
                found_receivers[info["identifier"]] = receiver

            if start + timeout * 1000 < time.ticks_ms():
                break

    finally:
        broadcast_socket.close()
    return list(found_receivers.values())
