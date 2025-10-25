import sqlite3
import requests
import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, g
from flask_cors import CORS
import os
import logging

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# --- Database Configuration ---
DATABASE = os.environ.get('DATABASE_PATH', '/app/data/devices.db')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with db as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    ip TEXT PRIMARY KEY,
                    hostname TEXT,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

# --- API Helper Functions ---
def parse_device_info(ip, data):
    """Parses the JSON data from a device, handling different formats."""
    try:
        # Common fields
        hostname = data.get('hostname', f"miner-{ip}")
        
        # Get relevant stratum settings
        settings = {
            "stratumURL": data.get("stratumURL", ""),
            "stratumPort": data.get("stratumPort", 0),
            "stratumUser": data.get("stratumUser", ""),
            "stratumPass": data.get("stratumPass", ""),
            "stratumSuggestedDifficulty": data.get("stratumSuggestedDifficulty", 0),
            "stratumExtranonceSubscribe": data.get("stratumExtranonceSubscribe", 0),
            
            "fallbackStratumURL": data.get("fallbackStratumURL", ""),
            "fallbackStratumPort": data.get("fallbackStratumPort", 0),
            "fallbackStratumUser": data.get("fallbackStratumUser", ""),
            "fallbackStratumPass": data.get("fallbackStratumPass", ""),
            "fallbackStratumSuggestedDifficulty": data.get("fallbackStratumSuggestedDifficulty", 0),
            "fallbackStratumExtranonceSubscribe": data.get("fallbackStratumExtranonceSubscribe", 0)
        }

        # Return only the info relevant for pool management
        return {
            "ip": ip,
            "hostname": hostname,
            "online": True,
            "settings": settings
        }
    except Exception as e:
        app.logger.error(f"Error parsing data for {ip}: {e}")
        return None

def fetch_device_info(ip):
    """Fetches info from a single device and updates the database."""
    # THIS IS THE FIX: Wrap the logic in an app context for thread-safe DB access
    with app.app_context():
        db = get_db()
        try:
            url = f"http://{ip}/api/system/info"
            response = requests.get(url, timeout=2)
            response.raise_for_status()
            
            data = response.json()
            parsed_data = parse_device_info(ip, data)
            
            if parsed_data:
                # Add or update the device in the database
                with db as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO devices (ip, hostname, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)",
                        (ip, parsed_data['hostname'])
                    )
                return parsed_data
            
            return {"ip": ip, "online": False, "error": "Failed to parse data"}

        except requests.exceptions.RequestException as e:
            # Device is offline or not a miner
            return {"ip": ip, "online": False, "error": str(e)}
        except Exception as e:
            app.logger.error(f"Unhandled exception in fetch_device_info for {ip}: {e}")
            return {"ip": ip, "online": False, "error": "Unhandled exception"}


# --- Routes ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    return app.send_static_file('index.html')

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Gets all known devices from the DB and fetches their current status."""
    db = get_db()
    with db as conn:
        cursor = conn.execute("SELECT ip, hostname FROM devices")
        devices = cursor.fetchall()

    device_ips = [device['ip'] for device in devices]
    results = []
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(fetch_device_info, ip): ip for ip in device_ips}
        for future in as_completed(futures):
            results.append(future.result())
            
    return jsonify(results)

@app.route('/api/devices', methods=['POST'])
def add_device():
    """Manually adds a new device by IP."""
    data = request.get_json()
    ip = data.get('ip')
    
    if not ip:
        return jsonify({"error": "IP address is required"}), 400

    # Try to fetch info to get hostname
    info = fetch_device_info(ip)
    
    hostname = info.get('hostname') if info.get('online') else f"miner-{ip}"

    try:
        db = get_db()
        with db as conn:
            conn.execute(
                "INSERT OR REPLACE INTO devices (ip, hostname, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (ip, hostname)
            )
        return jsonify({"success": True, "ip": ip, "hostname": hostname}), 201
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/devices/<ip>', methods=['DELETE'])
def delete_device(ip):
    """Deletes a device from the database."""
    try:
        db = get_db()
        with db as conn:
            conn.execute("DELETE FROM devices WHERE ip = ?", (ip,))
        return jsonify({"success": True, "ip": ip}), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scan', methods=['POST'])
def scan_network():
    """Scans a network subnet for devices."""
    data = request.get_json()
    subnet = data.get('subnet') # e.g., "192.168.1.0/24"
    
    if not subnet:
        return jsonify({"error": "Subnet is required"}), 400

    try:
        # Use strict=False to allow host addresses (e.g., 192.168.1.1/24)
        # instead of just network addresses (e.g., 192.168.1.0/24)
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        return jsonify({"error": f"Invalid subnet: {e}"}), 400

    ips_to_scan = [str(ip) for ip in network.hosts()]
    scan_results = []

    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(fetch_device_info, ip): ip for ip in ips_to_scan}
        
        for future in as_completed(futures):
            result = future.result()
            if result and result.get('online'):
                scan_results.append(result)
                
    return jsonify(scan_results)

@app.route('/api/devices/update', methods=['POST'])
def update_all_devices():
    """Updates the config for all known devices."""
    config_data = request.get_json()
    
    db = get_db()
    with db as conn:
        cursor = conn.execute("SELECT ip FROM devices")
        devices = cursor.fetchall()

    device_ips = [device['ip'] for device in devices]
    update_results = []
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(update_device, ip, config_data): ip for ip in device_ips}
        for future in as_completed(futures):
            update_results.append(future.result())

    return jsonify(update_results)

def update_device(ip, config):
    """Helper function to send a PATCH request to a single device."""
    try:
        url = f"http://{ip}/api/system"
        # We only send the fields we want to change
        response = requests.patch(url, json=config, timeout=5) 
        
        response.raise_for_status() # Will raise an error for 4xx/5xx responses
        
        return {"ip": ip, "success": True, "data": response.json()}
    
    except requests.exceptions.HTTPError as e:
        # Handle cases where the device rejects the config
        error_message = f"HTTP Error: {e.response.status_code}"
        try:
            error_message = e.response.json().get("error", error_message)
        except:
            pass
        return {"ip": ip, "success": False, "error": error_message}
    
    except requests.exceptions.RequestException as e:
        # Handle network errors (timeout, connection refused)
        return {"ip": ip, "success": False, "error": f"Offline or unreachable: {str(e)}"}
    
    except Exception as e:
        app.logger.error(f"Unhandled exception in update_device for {ip}: {e}")
        return {"ip": ip, "success": False, "error": "An unexpected error occurred"}


if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    app.logger.info("Initializing database...")
    init_db()
    app.logger.info("Starting Flask server...")
    # We use 0.0.0.0 to be accessible within the Docker network
    app.run(host='0.0.0.0', port=5005, debug=True)