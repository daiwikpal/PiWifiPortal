#!/bin/bash
# Checks for internet. If none, launches hotspot + config portal.

WIFI_CREDS="/home/pi/WifiPortal/wifi_creds.enc"
LOG="/home/pi/WifiPortal/portal.log"

check_internet() {
    for i in $(seq 1 10); do
        if ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
            return 0
        fi
        echo "$(date): Internet check attempt $i failed, retrying..." >> "$LOG"
        sleep 3
    done
    return 1
}

start_hotspot() {
    echo "$(date): No internet. Starting hotspot..." >> "$LOG"
    # Stop wpa_supplicant so we can take control of wlan0
    systemctl stop wpa_supplicant
    sleep 1

    # Configure a static IP for the Pi on the hotspot interface
    ip addr flush dev wlan0
    ip addr add 192.168.4.1/24 dev wlan0
    ip link set wlan0 up

    # Start hostapd (access point daemon)
    systemctl start hostapd
    sleep 2

    # Start dnsmasq (DHCP so phones/laptops get an IP)
    systemctl start dnsmasq

    # Launch the Flask config portal
    cd /home/pi/WifiPortal
    python3 portal.py >> "$LOG" 2>&1
}

connect_wifi() {
    echo "$(date): Credentials found. Connecting to WiFi..." >> "$LOG"
    python3 /home/pi/WifiPortal/apply_wifi.py >> "$LOG" 2>&1
}

# --- Main logic ---
if check_internet; then
    echo "$(date): Internet OK. Normal boot." >> "$LOG"
    exit 0
fi

if [ -f "$WIFI_CREDS" ]; then
    connect_wifi
    sleep 10
    if check_internet; then
        echo "$(date): Connected successfully." >> "$LOG"
        exit 0
    fi
fi

# No internet and no creds (or creds failed) → hotspot mode
start_hotspot
