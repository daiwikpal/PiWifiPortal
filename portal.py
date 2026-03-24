#!/usr/bin/env python3
"""
Captive portal - serves WiFi config page and saves encrypted credentials.
"""
import os
import json
import subprocess
from flask import Flask, request, jsonify, render_template_string
from cryptography.fernet import Fernet

app = Flask(__name__)

CREDS_FILE = "/home/pi/WifiPortal/wifi_creds.enc"
KEY_FILE   = "/home/pi/WifiPortal/.secret.key"

def get_or_create_key():
    """Load or generate the encryption key."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(KEY_FILE, 0o600)  # owner read-only
    return key

def save_credentials(ssid: str, password: str):
    key = get_or_create_key()
    fernet = Fernet(key)
    data = json.dumps({"ssid": ssid, "password": password}).encode()
    encrypted = fernet.encrypt(data)
    with open(CREDS_FILE, "wb") as f:
        f.write(encrypted)
    os.chmod(CREDS_FILE, 0o600)

def scan_networks():
    """Returns list of nearby SSIDs."""
    try:
        result = subprocess.run(
            ["iwlist", "wlan0", "scan"],
            capture_output=True, text=True, timeout=10
        )
        ssids = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("ESSID:"):
                ssid = line.split('"')[1]
                if ssid and ssid not in ssids:
                    ssids.append(ssid)
        return ssids
    except Exception:
        return []

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
    background: #0f0f0f;
    color: #e8e8e8;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  .card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 16px;
    padding: 2rem;
    width: 100%;
    max-width: 420px;
  }
  .logo {
    width: 48px; height: 48px;
    background: #cc0000;
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px;
    margin-bottom: 1.5rem;
  }
  h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; }
  .subtitle { color: #888; font-size: 0.9rem; margin-bottom: 2rem; }
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
  .btn {
    width: 100%; padding: 0.875rem;
    background: #cc0000; border: none;
    border-radius: 8px; color: white;
    font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  .btn:hover { background: #aa0000; }
  .btn:disabled { background: #444; cursor: not-allowed; }
  .status {
    margin-top: 1rem; padding: 0.75rem 1rem;
    border-radius: 8px; font-size: 0.9rem;
    display: none;
  }
  .status.success { background: #0d2b1a; border: 1px solid #1a5c35; color: #4ade80; }
  .status.error   { background: #2b0d0d; border: 1px solid #5c1a1a; color: #f87171; }
  .spinner { display: inline-block; width: 16px; height: 16px;
    border: 2px solid #fff3; border-top-color: #fff;
    border-radius: 50%; animation: spin 0.7s linear infinite;
    vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .networks-hint { font-size: 0.8rem; color: #666; margin-top: -1rem; margin-bottom: 1.25rem; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">&#127968;</div>
  <h1>WiFi Setup</h1>
  <p class="subtitle">Connect your Raspberry Pi to your network</p>

  <label for="ssid-select">Nearby networks</label>
  <select id="ssid-select" onchange="fillSSID(this.value)">
    <option value="">— select or type below —</option>
    {% for net in networks %}
    <option value="{{ net }}">{{ net }}</option>
    {% endfor %}
  </select>

  <label for="ssid">Network name (SSID)</label>
  <input type="text" id="ssid" placeholder="My Home WiFi" autocomplete="off" />

  <label for="password">Password</label>
  <input type="password" id="password" placeholder="••••••••" autocomplete="new-password" />
  <p class="networks-hint">Password is encrypted before saving to disk.</p>

  <button class="btn" id="save-btn" onclick="saveCredentials()">Save &amp; Restart</button>
  <div class="status" id="status"></div>
</div>

<script>
function fillSSID(val) {
  if (val) document.getElementById('ssid').value = val;
}

async function saveCredentials() {
  const ssid = document.getElementById('ssid').value.trim();
  const password = document.getElementById('password').value;
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('status');

  if (!ssid) { showStatus('Please enter a network name.', 'error'); return; }
  if (!password) { showStatus('Please enter a password.', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Saving...';

  try {
    const res = await fetch('/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ssid, password })
    });
    const data = await res.json();
    if (data.ok) {
      showStatus('Saved! Pi is rebooting — reconnect to your main WiFi in ~30 seconds.', 'success');
      btn.innerHTML = 'Restarting...';
    } else {
      showStatus(data.error || 'Something went wrong.', 'error');
      btn.disabled = false;
      btn.innerHTML = 'Save & Restart';
    }
  } catch (e) {
    showStatus('Network error. Make sure you are on the PiSetup hotspot.', 'error');
    btn.disabled = false;
    btn.innerHTML = 'Save & Restart';
  }
}

function showStatus(msg, type) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + type;
  el.style.display = 'block';
}
</script>
</body>
</html>
"""

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
        # Schedule a reboot in 3 seconds (gives Flask time to respond)
        subprocess.Popen(["bash", "-c", "sleep 3 && reboot"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    # Serve on all interfaces so phones on the hotspot can reach it
    app.run(host="0.0.0.0", port=80, debug=False)
