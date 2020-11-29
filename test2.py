from ir_tx import NEC;from machine import Pin;pin = Pin(17, Pin.OUT);nec = NEC(pin);nec.send(32, 16)

import time;from ir_rx import NEC;from machine import Pin;res = NEC(Pin(26, Pin.IN));
while True:
    time.sleep_us(10)
