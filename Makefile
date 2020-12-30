

erase:
	./venv/bin/esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash


flash:
	./venv/bin/esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash -z 0x1000 firmware.bin


copy-app: copy-main	
	./venv/bin/ampy -p /dev/ttyUSB0 put config.py /config.py
	./venv/bin/ampy -p /dev/ttyUSB0 put handler.py /handler.py
	./venv/bin/ampy -p /dev/ttyUSB0 put main.py /main.py

copy-config: copy-certs
	./venv/bin/ampy -p /dev/ttyUSB0 put config.json /config.json

copy-certs:
	./venv/bin/ampy -p /dev/ttyUSB0 put certs /certs

copy-main: copy-config
	./venv/bin/ampy -p /dev/ttyUSB0 put main.py /main.py

copy: copy-main

compile:
	docker build -t esp32-remote .
	docker run --rm -i -v "$$(pwd):/opt/copy" -t esp32-remote cp build-MQTT_IR_REMOTE/firmware.bin /opt/copy/firmware.bin

install: erase compile flash copy-certs copy-main


micropython-build-shell: compile
	docker run --rm -i -t esp32-remote bash


compile-and-flash: compile flash

compile-and-shell: compile-and-flash shell

shell:
	picocom /dev/ttyUSB0 -b115200
