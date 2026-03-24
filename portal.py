#!/usr/bin/env python3
"""
Captive portal - WiFi provisioning with personal and school/hotel flows.
"""
import os
import json
import time
import subprocess
import urllib.request
from flask import Flask, request, jsonify, render_template_string
from cryptography.fernet import Fernet

app = Flask(__name__)

CREDS_FILE   = "/home/pi/WifiPortal/wifi_creds.enc"
KEY_FILE     = "/home/pi/WifiPortal/.secret.key"
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"

# ── Encryption ───────────────────────────────────────────────────────────────

def get_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(KEY_FILE, 0o600)
    return key

def save_credentials(ssid: str, password: str):
    key = get_or_create_key()
    fernet = Fernet(key)
    data = json.dumps({"ssid": ssid, "password": password}).encode()
    encrypted = fernet.encrypt(data)
    with open(CREDS_FILE, "wb") as f:
        f.write(encrypted)
    os.chmod(CREDS_FILE, 0o600)

# ── Network helpers ──────────────────────────────────────────────────────────

def scan_networks():
    """Returns list of dicts: {ssid, open}."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=15
        )
        seen = set()
        nets = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 2:
                ssid = parts[0].strip()
                security = parts[1].strip()
                if ssid and ssid not in seen:
                    seen.add(ssid)
                    nets.append({"ssid": ssid, "open": security == "--"})
        return nets
    except Exception:
        return []

def detect_captive_portal():
    """Returns None = real internet, URL string = captive portal, 'offline' = no connectivity."""
    try:
        req = urllib.request.Request(
            "http://clients3.google.com/generate_204",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        return None if resp.status == 204 else resp.url
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        return loc if loc else None
    except Exception:
        return "offline"

def setup_ap_sta(ssid: str, password: str = None):
    """
    Move the hotspot to a virtual uap0 interface, connect wlan0 to the
    target network, then set up NAT so hotspot clients can reach internet.
    """
    # Create virtual AP interface (ignore error if already exists)
    subprocess.run(
        ["iw", "phy", "phy0", "interface", "add", "uap0", "type", "__ap"],
        capture_output=True
    )
    time.sleep(0.5)

    # Assign the static hotspot IP to uap0
    subprocess.run(["ip", "addr", "flush", "dev", "uap0"], capture_output=True)
    subprocess.run(["ip", "addr", "add", "192.168.4.1/24", "dev", "uap0"])
    subprocess.run(["ip", "link", "set", "uap0", "up"])

    # Update hostapd to use uap0 instead of wlan0
    with open(HOSTAPD_CONF) as f:
        conf = f.read()
    conf = conf.replace("interface=wlan0", "interface=uap0")
    with open(HOSTAPD_CONF, "w") as f:
        f.write(conf)

    # Release wlan0 back to NetworkManager and restart hostapd on uap0
    subprocess.run(["nmcli", "device", "set", "wlan0", "managed", "yes"], capture_output=True)
    subprocess.run(["systemctl", "restart", "hostapd"])
    time.sleep(2)

    # Connect wlan0 to the target network
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not connect to that network.")

    # Enable NAT: hotspot clients route through wlan0 to the internet
    subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    subprocess.run(["iptables", "-t", "nat", "-F"])
    subprocess.run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", "wlan0", "-j", "MASQUERADE"])
    subprocess.run(["iptables", "-A", "FORWARD", "-i", "uap0", "-o", "wlan0", "-j", "ACCEPT"])
    subprocess.run(["iptables", "-A", "FORWARD", "-i", "wlan0", "-o", "uap0",
                    "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

# ── HTML ─────────────────────────────────────────────────────────────────────

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pi WiFi Setup</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f0f0f; color: #e8e8e8;
    min-height: 100vh; display: flex;
    align-items: center; justify-content: center; padding: 1rem;
  }
  .card {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    border-radius: 16px; padding: 2rem;
    width: 100%; max-width: 440px;
  }
  .logo {
    width: 48px; height: 48px; background: #cc0000;
    border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 24px; margin-bottom: 1.5rem;
  }
  h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; }
  .subtitle { color: #888; font-size: 0.9rem; margin-bottom: 2rem; }
  .back-btn {
    background: none; border: none; color: #888; font-size: 0.85rem;
    cursor: pointer; padding: 0; margin-bottom: 1.5rem; display: flex;
    align-items: center; gap: 6px;
  }
  .back-btn:hover { color: #e8e8e8; }
  /* Choice cards */
  .choice-grid { display: flex; flex-direction: column; gap: 0.75rem; }
  .choice {
    background: #111; border: 1px solid #333; border-radius: 12px;
    padding: 1.25rem 1.5rem; cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    display: flex; align-items: center; gap: 1rem;
  }
  .choice:hover { border-color: #cc0000; background: #1f1010; }
  .choice-icon { font-size: 2rem; flex-shrink: 0; }
  .choice-title { font-weight: 600; font-size: 1rem; margin-bottom: 0.2rem; }
  .choice-desc { font-size: 0.8rem; color: #888; }
  /* Toggle */
  .toggle-row { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
  .toggle-btn {
    flex: 1; padding: 0.6rem; background: #111; border: 1px solid #333;
    border-radius: 8px; color: #888; font-size: 0.85rem;
    cursor: pointer; transition: all 0.2s;
  }
  .toggle-btn.active { background: #2a0a0a; border-color: #cc0000; color: #e8e8e8; }
  /* Form elements */
  label { display: block; font-size: 0.85rem; color: #aaa; margin-bottom: 0.4rem; }
  input, select {
    width: 100%; padding: 0.75rem 1rem;
    background: #111; border: 1px solid #333;
    border-radius: 8px; color: #e8e8e8;
    font-size: 1rem; margin-bottom: 1.25rem;
    outline: none; transition: border-color 0.2s;
  }
  input:focus, select:focus { border-color: #cc0000; }
  select option { background: #1a1a1a; }
  .hint { font-size: 0.8rem; color: #666; margin-top: -1rem; margin-bottom: 1.25rem; }
  .btn {
    width: 100%; padding: 0.875rem; background: #cc0000;
    border: none; border-radius: 8px; color: white;
    font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s;
  }
  .btn:hover { background: #aa0000; }
  .btn:disabled { background: #444; cursor: not-allowed; }
  .btn.secondary {
    background: #222; border: 1px solid #444; color: #e8e8e8; margin-top: 0.75rem;
  }
  .btn.secondary:hover { background: #2a2a2a; }
  /* Status */
  .status {
    margin-top: 1rem; padding: 0.75rem 1rem;
    border-radius: 8px; font-size: 0.9rem; display: none;
  }
  .status.success { background: #0d2b1a; border: 1px solid #1a5c35; color: #4ade80; }
  .status.error   { background: #2b0d0d; border: 1px solid #5c1a1a; color: #f87171; }
  .status.info    { background: #0d1a2b; border: 1px solid #1a3a5c; color: #60a5fa; }
  /* Waiting state */
  .waiting-box {
    background: #111; border: 1px solid #2a2a2a;
    border-radius: 12px; padding: 1.5rem; text-align: center;
    margin-bottom: 1rem; display: none;
  }
  .waiting-box .big-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
  .waiting-box h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.5rem; }
  .waiting-box p { font-size: 0.85rem; color: #888; line-height: 1.5; }
  .pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .spinner { display: inline-block; width: 16px; height: 16px;
    border: 2px solid #fff3; border-top-color: #fff;
    border-radius: 50%; animation: spin 0.7s linear infinite;
    vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .screen { display: none; }
  .screen.active { display: block; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">&#128246;</div>

  <!-- Screen: Landing -->
  <div class="screen active" id="screen-landing">
    <h1>WiFi Setup</h1>
    <p class="subtitle">What type of network are you connecting to?</p>
    <div class="choice-grid">
      <div class="choice" onclick="showScreen('screen-hotel')">
        <div class="choice-icon">&#127979;</div>
        <div>
          <div class="choice-title">School or Hotel WiFi</div>
          <div class="choice-desc">Requires a login page or browser sign-in</div>
        </div>
      </div>
      <div class="choice" onclick="showScreen('screen-personal')">
        <div class="choice-icon">&#127968;</div>
        <div>
          <div class="choice-title">Home / Personal WiFi</div>
          <div class="choice-desc">Standard network with a password</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Screen: Personal WiFi -->
  <div class="screen" id="screen-personal">
    <button class="back-btn" onclick="showScreen('screen-landing')">&#8592; Back</button>
    <h1>Personal WiFi</h1>
    <p class="subtitle">Enter your network credentials</p>

    <div class="toggle-row">
      <button class="toggle-btn active" id="toggle-visible" onclick="setNetworkMode('visible')">Visible network</button>
      <button class="toggle-btn" id="toggle-hidden" onclick="setNetworkMode('hidden')">Hidden network</button>
    </div>

    <div id="visible-section">
      <label for="ssid-select">Nearby networks</label>
      <select id="ssid-select" onchange="fillSSID(this.value)">
        <option value="">— select or type below —</option>
        {% for net in networks %}
        <option value="{{ net.ssid }}">{{ net.ssid }}</option>
        {% endfor %}
      </select>
    </div>

    <label for="ssid">Network name (SSID)</label>
    <input type="text" id="ssid" placeholder="My Home WiFi" autocomplete="off" />

    <label for="password">Password</label>
    <input type="password" id="password" placeholder="••••••••" autocomplete="new-password" />
    <p class="hint">Password is encrypted before saving to disk.</p>

    <button class="btn" id="save-btn" onclick="saveCredentials()">Save &amp; Restart</button>
    <div class="status" id="personal-status"></div>
  </div>

  <!-- Screen: School/Hotel WiFi -->
  <div class="screen" id="screen-hotel">
    <button class="back-btn" onclick="showScreen('screen-landing')">&#8592; Back</button>
    <h1>School / Hotel WiFi</h1>
    <p class="subtitle">Select the network to connect to</p>

    <label for="hotel-select">Available networks</label>
    <select id="hotel-select" onchange="onHotelNetworkChange()">
      <option value="">— choose a network —</option>
      {% for net in networks %}
      <option value="{{ net.ssid }}" data-open="{{ 'true' if net.open else 'false' }}">
        {{ net.ssid }}{% if not net.open %} &#128274;{% endif %}
      </option>
      {% endfor %}
    </select>

    <div id="hotel-password-section" style="display:none">
      <label for="hotel-password">Network password</label>
      <input type="password" id="hotel-password" placeholder="••••••••" autocomplete="new-password" />
    </div>

    <button class="btn" id="hotel-connect-btn" onclick="connectHotel()" disabled>Connect</button>
    <div class="status" id="hotel-status"></div>

    <!-- After connecting: waiting for captive portal login -->
    <div class="waiting-box" id="waiting-box">
      <div class="big-icon pulse" id="waiting-icon">&#127760;</div>
      <h3 id="waiting-title">Waiting for login...</h3>
      <p id="waiting-desc">Open any website in a new browser tab to complete the network login, then return here.</p>
    </div>
  </div>

</div>

<script>
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function setNetworkMode(mode) {
  const visBtn = document.getElementById('toggle-visible');
  const hidBtn = document.getElementById('toggle-hidden');
  const visSection = document.getElementById('visible-section');
  if (mode === 'visible') {
    visBtn.classList.add('active'); hidBtn.classList.remove('active');
    visSection.style.display = 'block';
  } else {
    hidBtn.classList.add('active'); visBtn.classList.remove('active');
    visSection.style.display = 'none';
    document.getElementById('ssid').value = '';
  }
}

function fillSSID(val) {
  if (val) document.getElementById('ssid').value = val;
}

function onHotelNetworkChange() {
  const sel = document.getElementById('hotel-select');
  const opt = sel.options[sel.selectedIndex];
  const isOpen = opt && opt.getAttribute('data-open') === 'true';
  const pwSection = document.getElementById('hotel-password-section');
  const connectBtn = document.getElementById('hotel-connect-btn');
  pwSection.style.display = (sel.value && !isOpen) ? 'block' : 'none';
  connectBtn.disabled = !sel.value;
}

async function saveCredentials() {
  const ssid = document.getElementById('ssid').value.trim();
  const password = document.getElementById('password').value;
  const btn = document.getElementById('save-btn');

  if (!ssid) { showStatus('personal-status', 'Please enter a network name.', 'error'); return; }
  if (!password) { showStatus('personal-status', 'Please enter a password.', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Saving...';
  try {
    const res = await fetch('/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ ssid, password })
    });
    const data = await res.json();
    if (data.ok) {
      showStatus('personal-status', 'Saved! Pi is rebooting — reconnect to your main WiFi in ~30 seconds.', 'success');
      btn.innerHTML = 'Restarting...';
    } else {
      showStatus('personal-status', data.error || 'Something went wrong.', 'error');
      btn.disabled = false; btn.innerHTML = 'Save & Restart';
    }
  } catch (e) {
    showStatus('personal-status', 'Network error.', 'error');
    btn.disabled = false; btn.innerHTML = 'Save & Restart';
  }
}

async function connectHotel() {
  const ssid = document.getElementById('hotel-select').value;
  const password = document.getElementById('hotel-password').value;
  const btn = document.getElementById('hotel-connect-btn');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Connecting...';
  showStatus('hotel-status', 'Connecting to ' + ssid + '... this may take 15-20 seconds.', 'info');

  try {
    const res = await fetch('/connect-captive', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ ssid, password })
    });
    const data = await res.json();
    if (data.ok) {
      showStatus('hotel-status', '', 'info');
      document.getElementById('hotel-status').style.display = 'none';
      btn.style.display = 'none';
      document.getElementById('hotel-select').disabled = true;
      showWaiting(ssid, data.captive_url);
      pollInternet();
    } else {
      showStatus('hotel-status', data.error || 'Could not connect.', 'error');
      btn.disabled = false; btn.innerHTML = 'Connect';
    }
  } catch (e) {
    showStatus('hotel-status', 'Network error. Try again.', 'error');
    btn.disabled = false; btn.innerHTML = 'Connect';
  }
}

function showWaiting(ssid, captiveUrl) {
  const box = document.getElementById('waiting-box');
  box.style.display = 'block';
  if (captiveUrl && captiveUrl !== 'offline') {
    document.getElementById('waiting-title').textContent = 'Login required';
    document.getElementById('waiting-desc').innerHTML =
      'Open <a href="' + captiveUrl + '" target="_blank" style="color:#60a5fa">' + captiveUrl + '</a> to complete the login, then return here.';
  } else {
    document.getElementById('waiting-title').textContent = 'Connected to ' + ssid;
    document.getElementById('waiting-desc').textContent =
      'Open any website in a new browser tab to complete the network login, then return here.';
  }
}

let pollTimer = null;
function pollInternet() {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch('/internet-check');
      const data = await res.json();
      if (data.connected) {
        clearInterval(pollTimer);
        document.getElementById('waiting-icon').textContent = '✅';
        document.getElementById('waiting-icon').classList.remove('pulse');
        document.getElementById('waiting-title').textContent = 'Connected!';
        document.getElementById('waiting-desc').textContent =
          'Your Pi now has internet access. You can close this page.';
      }
    } catch (_) {}
  }, 3000);
}

function showStatus(id, msg, type) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'status ' + type;
  el.style.display = msg ? 'block' : 'none';
}
</script>
</body>
</html>
"""

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    networks = scan_networks()
    return render_template_string(HTML_PAGE, networks=networks)

@app.route("/save", methods=["POST"])
def save():
    data = request.get_json(force=True)
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "")
    if not ssid or not password:
        return jsonify({"ok": False, "error": "SSID and password are required."})
    try:
        save_credentials(ssid, password)
        subprocess.Popen(["bash", "-c", "sleep 3 && reboot"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/connect-captive", methods=["POST"])
def connect_captive():
    data = request.get_json(force=True)
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "") or None
    if not ssid:
        return jsonify({"ok": False, "error": "Network name required."})
    try:
        setup_ap_sta(ssid, password)
        time.sleep(4)
        captive_url = detect_captive_portal()
        return jsonify({"ok": True, "captive_url": captive_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/internet-check")
def internet_check():
    result = detect_captive_portal()
    return jsonify({"connected": result is None})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)
