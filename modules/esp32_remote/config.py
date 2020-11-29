import gc
import json

from mqtt_as import config


def get_config(with_ssl: bool = True, config_path: str = "/config.json"):
    with open(config_path, 'r') as handle:
        data = json.load(handle)

    for key in ('topic_prefix', 'client_id', 'server', 'port', 'ssid', 'wifi_pw', 'no_run'):
        config[key] = data.get(key, None)
    
    config["tx_pin"] = config.get("tx_pin", 17)
    config["rx_pin"] = config.get("rx_pin", 26)

    del data
    gc.collect()

    if with_ssl:
        config['ssl'] = True
        gc.collect()

        config['ssl_params'] = {
            # "key": key,
            # "cert": cert,
            "server_side": False,
            # "ca_cert": ca,
            # "cert_reqs": 2,
        }
    else:
        config['ssl'] = False
    
    return config
