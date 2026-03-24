# WiFi Captive Portal

A captive portal that lets users configure the Raspberry Pi's WiFi credentials via a hosted web page — no keyboard or monitor required.

## How it works

1. Pi boots → checks for internet → if none, starts **hotspot mode**
2. User connects to the `PiSetup` hotspot (password: `setupmode123`)
3. Any URL opened in a browser redirects to `192.168.4.1` → config page appears
4. User selects their network, enters password → hits **Save & Restart**
5. Pi encrypts & stores credentials → reboots → connects to home WiFi

## Files

| File | Purpose |
|---|---|
| `check_and_start.sh` | Boot script — checks internet, runs hotspot or applies creds |
| `portal.py` | Flask web server serving the config UI on port 80 |
| `apply_wifi.py` | Decrypts stored creds and writes `wpa_supplicant.conf` |
| `hostapd.conf` | Hotspot (access point) configuration |
| `dnsmasq_append.conf` | DHCP + captive DNS config (append to `/etc/dnsmasq.conf`) |
| `wifi-portal.service` | Systemd service that runs `check_and_start.sh` on every boot |

## One-time setup

### 1. Install dependencies

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq python3-pip
pip3 install flask cryptography
```

### 2. Copy system config files

```bash
# Hostapd config
sudo cp /home/pi/WifiPortal/hostapd.conf /etc/hostapd/hostapd.conf
sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# dnsmasq — append captive portal lines
sudo cat /home/pi/WifiPortal/dnsmasq_append.conf | sudo tee -a /etc/dnsmasq.conf

# Systemd service
sudo cp /home/pi/WifiPortal/wifi-portal.service /etc/systemd/system/wifi-portal.service
sudo systemctl daemon-reload
sudo systemctl enable wifi-portal.service
```

### 3. Make scripts executable

```bash
chmod +x /home/pi/WifiPortal/check_and_start.sh
```

### 4. Allow Python to bind port 80 without root (optional)

```bash
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3
```

> Alternatively the systemd service already runs as `root`, so this step is only needed for manual testing as a regular user.

## Security

- Credentials are encrypted with **Fernet (AES-128-CBC + HMAC-SHA256)** from the `cryptography` library
- Encryption key stored at `.secret.key` (chmod 600)
- Encrypted credentials stored at `wifi_creds.enc` (chmod 600)

## Configuration

| Setting | File | Default |
|---|---|---|
| Hotspot SSID | `hostapd.conf` | `PiSetup` |
| Hotspot password | `hostapd.conf` | `setupmode123` |
| Pi IP on hotspot | `check_and_start.sh` | `192.168.4.1` |
| Country code | `apply_wifi.py` | `GB` |

> **Change `country=GB`** in `apply_wifi.py` to your country code (`US`, `AU`, `IN`, etc.) for legal 5GHz operation.

## Logs

Runtime logs are written to `/home/pi/WifiPortal/portal.log`.
