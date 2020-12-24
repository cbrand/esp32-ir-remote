from ir.ir_tx import NEC;from machine import Pin;pin = Pin(17, Pin.OUT);nec = NEC(pin);nec.send(32, 16)
from ir.ir_tx import RC6;from machine import Pin;pin = Pin(17, Pin.OUT);rc6 = RC6(pin);rc6.send(4, 12)

import time;from ir.ir_rx import NEC;from machine import Pin;res = NEC(Pin(26, Pin.IN));
while True:
    time.sleep_us(10)


import time;from ir.ir_rx import RC6;from machine import Pin;res = RC6(Pin(26, Pin.IN));
while True:
    time.sleep_us(10)
