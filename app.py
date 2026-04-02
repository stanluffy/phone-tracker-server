from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
from datetime import datetime, timedelta
import os

app = Flask(__name__)
CORS(app)

def init_db():
    conn = sqlite3.connect('tracker.db')
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS stolen_devices (
            id INTEGER PRIMARY KEY,
            device_hash TEXT UNIQUE,
            phone_number TEXT,
            imei_hash TEXT,
            reported_at TIMESTAMP,
            last_seen TIMESTAMP,
            status TEXT DEFAULT 'active',
            beacon_signature TEXT
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS relay_reports (
            id INTEGER PRIMARY KEY,
            device_hash TEXT,
            relay_id TEXT,
            relay_lat REAL,
            relay_lon REAL,
            signal_strength INTEGER,
            timestamp TIMESTAMP,
            detection_method TEXT
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS relay_nodes (
            id INTEGER PRIMARY KEY,
            relay_id TEXT UNIQUE,
            node_type TEXT,
            lat REAL,
            lon REAL,
            last_active TIMESTAMP,
            trust_score REAL DEFAULT 1.0
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('tracker.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/")
def home():
    return "Server is running!"

@app.route('/api/report-stolen', methods=['POST'])
def report_stolen():
    data = request.json
    device_hash = hashlib.sha256(data.get('device_id', '').encode()).hexdigest()[:16]
    beacon_sig = hashlib.sha256((data.get('device_id', '') + "beacon_salt").encode()).hexdigest()[:12]
    
    conn = get_db()
    c = conn.cursor()
    
    try:
        c.execute("""
            INSERT INTO stolen_devices 
            (device_hash, phone_number, imei_hash, reported_at, beacon_signature)
            VALUES (?, ?, ?, ?, ?)
        """, (
            device_hash,
            data.get('phone_number'),
            hashlib.sha256(data.get('imei', '').encode()).hexdigest()[:16],
            datetime.now(),
            beacon_sig
        ))
        conn.commit()
        return jsonify({'success': True, 'device_hash': device_hash, 'beacon_signature': beacon_sig})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Device already registered'}), 400
    finally:
        conn.close()

@app.route('/api/relay-report', methods=['POST'])
def relay_report():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM relay_nodes WHERE relay_id = ?', (data.get('relay_id'),))
    if not c.fetchone():
        c.execute("""
            INSERT INTO relay_nodes (relay_id, node_type, lat, lon, last_active)
            VALUES (?, ?, ?, ?, ?)
        """, (
            data.get('relay_id'),
            data.get('node_type', 'mobile_app'),
            data.get('lat'),
            data.get('lon'),
            datetime.now()
        ))
    
    c.execute("""
        INSERT INTO relay_reports 
        (device_hash, relay_id, relay_lat, relay_lon, signal_strength, timestamp, detection_method)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get('device_hash'),
        data.get('relay_id'),
        data.get('lat'),
        data.get('lon'),
        data.get('signal_strength'),
        datetime.now(),
        data.get('method', 'bluetooth_le')
    ))
    
    c.execute("UPDATE stolen_devices SET last_seen = ? WHERE device_hash = ?",
              (datetime.now(), data.get('device_hash')))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/locate/<device_hash>', methods=['GET'])
def locate_device(device_hash):
    conn = get_db()
    c = conn.cursor()
    since = datetime.now() - timedelta(hours=24)
    
    c.execute("""
        SELECT relay_lat, relay_lon, signal_strength, timestamp, detection_method
        FROM relay_reports
        WHERE device_hash = ? AND timestamp > ?
        ORDER BY timestamp DESC
    """, (device_hash, since))
    
    reports = c.fetchall()
    if not reports:
        return jsonify({'status': 'no_data'})
    
    total_weight = 0
    weighted_lat = 0
    weighted_lon = 0
    
    for report in reports:
        rssi = report['signal_strength'] or -70
        weight = max((100 + rssi) / 100, 0.1)
        weighted_lat += report['relay_lat'] * weight
        weighted_lon += report['relay_lon'] * weight
        total_weight += weight
    
    probable_lat = weighted_lat / total_weight
    probable_lon = weighted_lon / total_weight
    
    conn.close()
    return jsonify({
        'status': 'located',
        'lat': probable_lat,
        'lon': probable_lon
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
