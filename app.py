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

@app.route('/')
def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stolen Phone Tracker - Kenya</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            body { font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
            #map { height: 500px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; }
            h1 { color: #d32f2f; }
            .stat { display: inline-block; margin-right: 30px; }
            .stat-value { font-size: 2em; font-weight: bold; color: #1976d2; }
            button { background: #1976d2; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
            input { padding: 8px; margin: 5px; border: 1px solid #ddd; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📱 Kenya Stolen Phone Tracker</h1>
                <p>Mesh network device recovery system</p>
                <div class="stat">
                    <div class="stat-value" id="sightings-24h">-</div>
                    <div class="stat-label">Recent Sightings</div>
                </div>
            </div>
            <div class="card">
                <h3>🔍 Track Device</h3>
                <input type="text" id="device-hash" placeholder="Device hash..." style="width: 300px;">
                <button onclick="trackDevice()">Locate</button>
                <div id="track-result" style="margin-top: 15px;"></div>
            </div>
            <div class="card">
                <h3>🗺️ Live Heatmap</h3>
                <div id="map"></div>
            </div>
        </div>
        <script>
            var map = L.map('map').setView([-1.2921, 36.8219], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
            var markers = [];
            function updateStats() {
                fetch('/api/heatmap/all-active')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('sightings-24h').textContent = data.active_sightings;
                        markers.forEach(m => map.removeLayer(m));
                        markers = [];
                        data.points.forEach(p => {
                            var color = p.signal > -60 ? '#d32f2f' : p.signal > -75 ? '#f57c00' : '#388e3c';
                            var circle = L.circleMarker([p.lat, p.lon], {
                                radius: 8, fillColor: color, color: '#fff', weight: 1, fillOpacity: 0.7
                            }).addTo(map);
                            circle.bindPopup('Device: ' + p.device + '<br>Signal: ' + p.signal + 'dBm');
                            markers.push(circle);
                        });
                    });
            }
            function trackDevice() {
                var hash = document.getElementById('device-hash').value;
                fetch('/api/locate/' + hash)
                    .then(r => r.json())
                    .then(data => {
                        var html = '<strong>Status:</strong> ' + data.status + '<br>';
                        if (data.lat) {
                            html += '<strong>Location:</strong> ' + data.lat + ', ' + data.lon + '<br>';
                            map.setView([data.lat, data.lon], 15);
                            L.marker([data.lat, data.lon]).addTo(map);
                        }
                        document.getElementById('track-result').innerHTML = html;
                    });
            }
            updateStats();
            setInterval(updateStats, 10000);
        </script>
    </body>
    </html>
    """

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

# ADD THE MISSING ROUTE HERE - before if __name__ == "__main__":
@app.route('/api/heatmap/all-active', methods=['GET'])
def all_active_heatmap():
    conn = get_db()
    c = conn.cursor()
    since = datetime.now() - timedelta(hours=6)
    
    c.execute("""
        SELECT r.relay_lat, r.relay_lon, r.signal_strength, r.timestamp, s.device_hash
        FROM relay_reports r
        JOIN stolen_devices s ON r.device_hash = s.device_hash
        WHERE r.timestamp > ? AND s.status = 'active'
        ORDER BY r.timestamp DESC
    """, (since,))
    
    points = []
    for row in c.fetchall():
        points.append({
            'lat': row['relay_lat'],
            'lon': row['relay_lon'],
            'device': row['device_hash'][:8] + '...',
            'signal': row['signal_strength'],
            'time': row['timestamp']
        })
    conn.close()
    return jsonify({'active_sightings': len(points), 'points': points})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
