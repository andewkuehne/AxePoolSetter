import sqlite3
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, render_template, g
from flask_cors import CORS

app = Flask(__name__, static_folder='static', template_folder='static')
CORS(app)  # Allow Cross-Origin Resource Sharing

# --- Database Setup ---
DATABASE_DIR = '/app/data'
DATABASE_PATH = os.path.join(DATABASE_DIR, 'devices.db')

def init_db():
    """Initializes the SQLite database and creates the devices table."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def get_db():
    """Opens a new database connection if one is not already open."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        
        # Create table if it doesn't exist
        g.db.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            ip TEXT PRIMARY KEY,
            hostname TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_data TEXT
        )
        ''')
        g.db.commit()
    return g.db

@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'db'):
        g.db.close()

# --- Utility Functions ---

def is_valid_ip(ip):
    """Basic validation for an IP address."""
    return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)

def fetch_device_info(ip):
    """Fetches info from a single device."""
    try:
        response = requests.get(f"http://{ip}/api/system/info", timeout=2)
        if response.status_code == 200:
            data = response.json()
            hostname = data.get('hostname', ip)
            
            db = get_db()
            db.execute(
                "INSERT OR REPLACE INTO devices (ip, hostname, last_data, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (ip, hostname, json.dumps(data))
            )
            db.commit()
            return {"ip": ip, "hostname": hostname, "status": "online", "data": data}
    except Exception as e:
        # If device was known, mark it as offline
        db = get_db()
        res = db.execute("SELECT 1 FROM devices WHERE ip = ?", (ip,)).fetchone()
        if res:
             db.execute(
                "UPDATE devices SET last_data = ? WHERE ip = ?",
                (json.dumps({"status": "offline"}), ip)
            )
             db.commit()
        return {"ip": ip, "status": "offline", "error": str(e)}
    return None

# --- API Endpoints ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Returns a list of all known devices and their last known data."""
    db = get_db()
    devices = []
    
    # We use a ThreadPool to refresh all known devices quickly
    ips_to_check = [row['ip'] for row in db.execute("SELECT ip FROM devices").fetchall()]
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(fetch_device_info, ip) for ip in ips_to_check]
        for future in futures:
            future.result() # We just wait for them to finish updating the DB

    # After refresh, read all data from DB
    for row in db.execute("SELECT ip, hostname, last_data FROM devices ORDER BY ip").fetchall():
        try:
            data = json.loads(row['last_data'])
        except:
            data = {"status": "error", "error": "Invalid data in DB"}
        
        devices.append({
            "ip": row['ip'],
            "hostname": row['hostname'],
            "data": data
        })
        
    return jsonify(devices)

@app.route('/api/devices', methods=['POST'])
def add_device():
    """Manually adds a new device IP."""
    data = request.json
    ip = data.get('ip')
    
    if not ip or not is_valid_ip(ip):
        return jsonify({"error": "Invalid IP address"}), 400
        
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO devices (ip, hostname) VALUES (?, ?)",
        (ip, ip) # Default hostname to IP until first fetch
    )
    db.commit()
    
    # Try to fetch info immediately
    device_info = fetch_device_info(ip)
    
    if device_info and device_info.get('status') == 'online':
        return jsonify({"success": True, "device": device_info}), 201
    else:
        return jsonify({"error": "Device added, but it appears to be offline."}), 404

@app.route('/api/scan', methods=['POST'])
def scan_network():
    """Scans a /24 subnet for devices."""
    data = request.json
    subnet_prefix = data.get('subnet') # e.g., "192.168.1"
    
    if not subnet_prefix or not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.$", subnet_prefix):
        return jsonify({"error": "Invalid subnet prefix. Expected format: '192.168.1.'"}), 400

    ips_to_scan = [f"{subnet_prefix}{i}" for i in range(1, 255)]
    found_devices = 0
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(fetch_device_info, ip) for ip in ips_to_scan]
        
        for future in futures:
            result = future.result()
            if result and result.get('status') == 'online':
                found_devices += 1
                
    return jsonify({"success": True, "message": f"Scan complete. Found {found_devices} new devices."})

@app.route('/api/update-all', methods=['POST'])
def update_all_devices():
    """Updates the configuration on all known devices."""
    
    settings = request.json
    
    # Convert checkbox 'on'/'off' or true/false to 0/1 for the API
    for key in ['stratumEnonceSubscribe', 'fallbackStratumEnonceSubscribe']:
        if key in settings:
            settings[key] = 1 if settings[key] in [True, 'on', 1] else 0

    # Convert port numbers from string to integer
    for key in ['stratumPort', 'fallbackStratumPort', 'stratumSuggestedDifficulty', 'fallbackStratumSuggestedDifficulty']:
        if key in settings:
            try:
                settings[key] = int(settings[key])
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid value for {key}. Must be a number."}), 400

    db = get_db()
    ips = [row['ip'] for row in db.execute("SELECT ip FROM devices").fetchall()]
    
    results = {"success": [], "failed": []}
    
    def update_device(ip):
        try:
            # --- UPDATED ENDPOINT as per user request ---
            response = requests.patch(f"http://{ip}/api/system", json=settings, timeout=5)
            
            if 200 <= response.status_code < 300:
                results["success"].append(ip)
            else:
                results["failed"].append({"ip": ip, "error": response.text})
        except Exception as e:
            results["failed"].append({"ip": ip, "error": str(e)})

    with ThreadPoolExecutor(max_workers=50) as executor:
        [executor.submit(update_device, ip) for ip in ips]

    return jsonify(results)

if __name__ == '__main__':
    init_db() # Initialize the database before first request
    app.run(host='0.0.0.0', port=5000)

