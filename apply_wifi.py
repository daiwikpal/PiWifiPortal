#!/usr/bin/env python3
"""
Reads encrypted credentials and configures wpa_supplicant for client mode.
"""
import os, json, subprocess
from cryptography.fernet import Fernet

CREDS_FILE = "/home/pi/WifiPortal/wifi_creds.enc"
KEY_FILE   = "/home/pi/WifiPortal/.secret.key"
WPA_CONF   = "/etc/wpa_supplicant/wpa_supplicant.conf"

def load_credentials():
    with open(KEY_FILE, "rb") as f:
        key = f.read()
    fernet = Fernet(key)
    with open(CREDS_FILE, "rb") as f:
        encrypted = f.read()
    data = json.loads(fernet.decrypt(encrypted).decode())
    return data["ssid"], data["password"]

def write_wpa_config(ssid: str, password: str):
    config = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={{
    ssid="{ssid}"
    psk="{password}"
    key_mgmt=WPA-PSK
}}
"""
    with open(WPA_CONF, "w") as f:
        f.write(config)
    os.chmod(WPA_CONF, 0o600)
    print(f"Written wpa_supplicant config for SSID: {ssid}")

if __name__ == "__main__":
    ssid, password = load_credentials()
    write_wpa_config(ssid, password)
    # Restart networking
    subprocess.run(["systemctl", "restart", "wpa_supplicant"], check=True)
    subprocess.run(["systemctl", "restart", "dhcpcd"], check=True)
