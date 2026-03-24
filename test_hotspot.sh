#!/bin/bash
# Test script: starts the hotspot and Flask portal without the internet check.
# Run with: sudo bash test_hotspot.sh
# Stop with: Ctrl+C (cleans up automatically)

LOG="/home/pi/WifiPortal/portal.log"

cleanup() {
    echo ""
    echo "Cleaning up..."
    systemctl stop hostapd
    systemctl stop dnsmasq
    pkill -f "python3 portal.py" 2>/dev/null
    nmcli device set wlan0 managed yes 2>/dev/null
    systemctl start wpa_supplicant
    echo "Hotspot stopped. wpa_supplicant restored."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "Releasing wlan0 from NetworkManager..."
nmcli device disconnect wlan0 2>/dev/null
nmcli device set wlan0 managed no 2>/dev/null
echo "Stopping wpa_supplicant to free wlan0..."
systemctl stop wpa_supplicant
sleep 1

echo "Setting static IP 192.168.4.1 on wlan0..."
ip addr flush dev wlan0
ip addr add 192.168.4.1/24 dev wlan0
ip link set wlan0 up

echo "Starting hostapd..."
systemctl start hostapd
sleep 2

if ! systemctl is-active --quiet hostapd; then
    echo "ERROR: hostapd failed to start. Check: sudo journalctl -u hostapd -n 20"
    cleanup
fi

echo "Starting dnsmasq..."
systemctl start dnsmasq
sleep 1

echo ""
echo "================================================"
echo "  Hotspot: PiSetup (open, no password)"
echo "  Portal:  http://192.168.4.1"
echo "  Status:  $(sudo iw dev wlan0 info | grep 'ssid\|type' | xargs)"
echo "================================================"
echo ""
echo "Starting Flask portal (Ctrl+C to stop)..."
cd /home/pi/WifiPortal
python3 portal.py >> "$LOG" 2>&1 &
FLASK_PID=$!

echo "Flask PID: $FLASK_PID"
echo "Tailing log (Ctrl+C to stop everything)..."
tail -f "$LOG" &
TAIL_PID=$!

wait $FLASK_PID
kill $TAIL_PID 2>/dev/null
cleanup
