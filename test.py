import time
data = [1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1]
from machine import PWM, Pin, Timer
data = []

pin = Pin(25, Pin.OUT)

previous_timing = None
def copy(d):
print(d.value())
to_set_value = 1 if not d.value() else 0
global previous_timing
now = time.ticks_us()
if previous_timing is None:
previous_timing = now

data.append((to_set_value, now - previous_timing))
previous_timing = now
pin.value(to_set_value)

pin_in = Pin(27, Pin.IN, handler = copy, trigger = (Pin.IRQ_FALLING | Pin.IRQ_RISING))


# pwm = PWM(pin, freq=38000)

def send():
to_send = [(1, 0), (0, 10656), (0, 10975), (1, 11017), (0, 10983), (0, 11012), (0, 10988), (0, 10996), (0, 10988), (0, 11011), (0, 10988), (0, 11012), (0, 10987), (0, 11012), (1, 61004), (0, 11014), (0, 10988), (0, 11009), (0, 10991), (1, 11019), (0, 10981), (0, 10996), (0, 10988), (0, 11011), (0, 10988), (0, 11012), (0, 10988), (0, 11011)]
for item, wait in to_send:
time.sleep_us(wait)
pin.value(item)
#print("setting to %s" % item)

time.sleep_ms(4)
pin.value(0)


from machine import Pin;inp = Pin(26, Pin.IN, handler=(lambda a: print(a.irqvalue())), trigger = (Pin.IRQ_FALLING | Pin.IRQ_RISING))

from machine import Pin;out = Pin(17, Pin.OUT);out.value(1)

value = 0
while True:
import time
out.value(value)
value = 0 if value else 1
time.sleep(1)


import time;from ir_rx import NEC;from machine import Pin;res = NEC(Pin(27, Pin.IN));
while True:
    time.sleep_us(10)