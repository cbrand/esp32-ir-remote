from esp32_remote import Handler, get_config

config = get_config()
handler = Handler(config)
print("STARTING IR MQTT Handler")

if not config.get("no_run", False):
    handler.run_forever()
