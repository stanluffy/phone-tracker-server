import os
import logging
import sqlite3
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import BadRequest

# ==================== LOGGING CONFIGURATION ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ENVIRONMENT CONFIGURATION ====================
class Config:
    """Application configuration from environment variables"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'tracker.db')
    API_KEY = os.getenv('API_KEY', None)
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV == 'development'

config = Config()

# ==================== FLASK APP INITIALIZATION ====================
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False
CORS(app)

# ==================== DATABASE UTILITIES ====================
def get_db_connection():
    """Create and return a database connection with Row factory"""
    try:
        conn = sqlite3.connect(config.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise

def init_db():
    """Initialize database tables"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stolen_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_hash TEXT UNIQUE NOT NULL,
                phone_number TEXT,
                imei_hash TEXT,
                reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'recovered', 'inactive')),
                beacon_signature TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relay_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_hash TEXT NOT NULL,
                relay_id TEXT NOT NULL,
                relay_lat REAL NOT NULL,
                relay_lon REAL NOT NULL,
                signal_strength INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                detection_method TEXT DEFAULT 'bluetooth_le',
                FOREIGN KEY (device_hash) REFERENCES stolen_devices(device_hash)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relay_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relay_id TEXT UNIQUE NOT NULL,
                node_type TEXT DEFAULT 'mobile_app',
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trust_score REAL DEFAULT 1.0 CHECK(trust_score >= 0 AND trust_score <= 1.0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stolen_devices_hash ON stolen_devices(device_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relay_reports_device ON relay_reports(device_hash, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relay_reports_timestamp ON relay_reports(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relay_nodes_id ON relay_nodes(relay_id)")
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise

# Initialize database on startup
try:
    init_db()
except Exception as e:
    logger.warning(f"Could not initialize database: {e}")

# ==================== SECURITY DECORATORS ====================
def require_api_key(f):
    """Decorator to require API key for protected endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if config.API_KEY:
            api_key = request.headers.get('X-API-KEY')
            if not api_key or api_key != config.API_KEY:
                logger.warning(f"Unauthorized API access attempt from {request.remote_addr}")
                return jsonify({'error': 'Unauthorized'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==================== VALIDATION HELPERS ====================
def validate_coordinates(lat: float, lon: float) -> bool:
    """Validate latitude and longitude"""
    return -90 <= lat <= 90 and -180 <= lon <= 180

def validate_signal_strength(signal: int) -> bool:
    """Validate RSSI signal strength"""
    return -120 <= signal <= 0

def validate_json_data(data, required_fields):
    """Validate that required fields exist in JSON data"""
    if not data:
        raise BadRequest("Request body cannot be empty")
    for field in required_fields:
        if field not in data:
            raise BadRequest(f"Missing required field: {field}")

# ==================== ERROR HANDLERS ====================
@app.errorhandler(400)
def bad_request(e):
    logger.warning(f"Bad Request: {e.description}")
    return jsonify({'error': 'Bad Request', 'message': str(e.description)}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not Found', 'message': 'The requested resource was not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal Server Error: {e}")
    return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500

# ==================== ROUTES ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/', methods=['GET'])
def dashboard():
    """Render the main dashboard"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Stolen Phone Tracker - Kenya</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                min-height: 100vh;
                padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { 
                background: white; 
                padding: 25px; 
                border-radius: 12px; 
                margin-bottom: 20px; 
                box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                transition: transform 0.3s ease;
            }
            .card:hover { transform: translateY(-2px); }
            h1 { color: #d32f2f; margin-bottom: 10px; font-size: 2.5em; }
            h3 { color: #333; margin-bottom: 15px; }
            .stat-container { display: flex; gap: 30px; margin: 20px 0; flex-wrap: wrap; }
            .stat { flex: 1; min-width: 200px; }
            .stat-value { font-size: 2.5em; font-weight: bold; color: #1976d2; }
            .stat-label { color: #666; font-size: 0.95em; margin-top: 5px; }
            #map { height: 500px; border-radius: 8px; border: 1px solid #ddd; }
            .form-group { margin-bottom: 15px; }
            input[type="text"] { 
                padding: 10px 15px; 
                border: 1px solid #ddd; 
                border-radius: 6px; 
                width: 100%; 
                max-width: 400px;
                font-size: 1em;
            }
            button { 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; 
                border: none; 
                padding: 12px 25px; 
                border-radius: 6px; 
                cursor: pointer;
                font-weight: 600;
                transition: opacity 0.3s;
            }
            button:hover { opacity: 0.9; }
            button:active { transform: scale(0.98); }
            #track-result { 
                margin-top: 15px; 
                padding: 15px; 
                background: #f5f5f5; 
                border-radius: 6px;
                display: none;
            }
            #track-result.show { display: block; }
            .error { color: #d32f2f; }
            .success { color: #388e3c; }
            @media (max-width: 768px) {
                h1 { font-size: 1.8em; }
                .stat-value { font-size: 1.8em; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📱 Kenya Stolen Phone Tracker</h1>
                <p>Mesh network device recovery system</p>
                <div class="stat-container">
                    <div class="stat">
                        <div class="stat-value" id="sightings-24h">-</div>
                        <div class="stat-label">Active Sightings (24h)</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="total-devices">-</div>
                        <div class="stat-label">Tracked Devices</div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h3>🔍 Track Device</h3>
                <div class="form-group">
                    <input type="text" id="device-hash" placeholder="Enter device hash..." />
                    <button onclick="trackDevice()" style="margin-left: 10px; margin-top: 10px;">🔎 Locate</button>
                </div>
                <div id="track-result"></div>
            </div>
            
            <div class="card">
                <h3>🗺️ Live Heatmap (Last 6 hours)</h3>
                <div id="map"></div>
            </div>
        </div>
        
        <script>
            const map = L.map('map').setView([-1.2921, 36.8219], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors',
                maxZoom: 19
            }).addTo(map);
            
            let markers = [];
            
            function updateStats() {
                fetch('/api/heatmap/all-active')
                    .then(response => {
                        if (!response.ok) throw new Error('Failed to fetch heatmap data');
                        return response.json();
                    })
                    .then(data => {
                        document.getElementById('sightings-24h').textContent = data.active_sightings || 0;
                        document.getElementById('total-devices').textContent = data.total_devices || 0;
                        
                        markers.forEach(m => map.removeLayer(m));
                        markers = [];
                        
                        (data.points || []).forEach(p => {
                            const signal = p.signal || -70;
                            const color = signal > -60 ? '#d32f2f' : signal > -75 ? '#f57c00' : '#388e3c';
                            const circle = L.circleMarker([p.lat, p.lon], {
                                radius: 8,
                                fillColor: color,
                                color: '#fff',
                                weight: 2,
                                opacity: 1,
                                fillOpacity: 0.8
                            }).addTo(map);
                            
                            const timeStr = new Date(p.time).toLocaleString();
                            circle.bindPopup(`<b>Device:</b> ${p.device}<br><b>Signal:</b> ${signal} dBm<br><b>Time:</b> ${timeStr}`);
                            markers.push(circle);
                        });
                    })
                    .catch(error => console.error('Error updating stats:', error));
            }
            
            function trackDevice() {
                const hash = document.getElementById('device-hash').value.trim();
                const resultDiv = document.getElementById('track-result');
                
                if (!hash) {
                    resultDiv.innerHTML = '<p class="error">Please enter a device hash</p>';
                    resultDiv.classList.add('show');
                    return;
                }
                
                resultDiv.innerHTML = '<p>Locating device...</p>';
                resultDiv.classList.add('show');
                
                fetch(`/api/locate/${encodeURIComponent(hash)}`)
                    .then(response => {
                        if (!response.ok) throw new Error('Device not found');
                        return response.json();
                    })
                    .then(data => {
                        let html = `<p><strong>Status:</strong> <span class="success">${data.status}</span></p>`;
                        if (data.lat && data.lon) {
                            html += `<p><strong>Location:</strong> ${data.lat.toFixed(4)}°, ${data.lon.toFixed(4)}°</p>`;
                            html += `<p><strong>Accuracy:</strong> ${data.accuracy || 'N/A'}</p>`;
                            map.setView([data.lat, data.lon], 15);
                            L.marker([data.lat, data.lon]).bindPopup('Device Location').addTo(map);
                        }
                        resultDiv.innerHTML = html;
                    })
                    .catch(error => {
                        resultDiv.innerHTML = `<p class="error">Error: ${error.message}</p>`;
                    });
            }
            
            updateStats();
            setInterval(updateStats, 10000);
            
            document.getElementById('device-hash').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') trackDevice();
            });
        </script>
    </body>
    </html>
    """

@app.route('/api/report-stolen', methods=['POST'])
@require_api_key
def report_stolen():
    """Report a stolen device"""
    try:
        data = request.get_json()
        validate_json_data(data, ['device_id', 'phone_number', 'imei'])
        
        device_id = data.get('device_id', '').strip()
        phone_number = data.get('phone_number', '').strip()
        imei = data.get('imei', '').strip()
        
        if not all([device_id, phone_number, imei]):
            raise BadRequest("All fields must be non-empty")
        
        import hashlib
        device_hash = hashlib.sha256(device_id.encode()).hexdigest()[:16]
        imei_hash = hashlib.sha256(imei.encode()).hexdigest()[:16]
        beacon_sig = hashlib.sha256((device_id + "beacon_salt").encode()).hexdigest()[:12]
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO stolen_devices 
                (device_hash, phone_number, imei_hash, beacon_signature)
                VALUES (?, ?, ?, ?)
            """, (device_hash, phone_number, imei_hash, beacon_sig))
            conn.commit()
            logger.info(f"Device reported stolen: {device_hash}")
            return jsonify({
                'success': True,
                'device_hash': device_hash,
                'beacon_signature': beacon_sig
            }), 201
        except sqlite3.IntegrityError:
            logger.warning(f"Device already registered: {device_hash}")
            return jsonify({'error': 'Device already registered'}), 400
        finally:
            conn.close()
    except BadRequest as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error reporting stolen device: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/relay-report', methods=['POST'])
@require_api_key
def relay_report():
    """Report device sighting from a relay node"""
    try:
        data = request.get_json()
        validate_json_data(data, ['device_hash', 'relay_id', 'lat', 'lon', 'signal_strength'])
        
        lat = float(data.get('lat'))
        lon = float(data.get('lon'))
        signal = int(data.get('signal_strength'))
        
        if not validate_coordinates(lat, lon):
            raise BadRequest("Invalid coordinates")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        relay_id = data.get('relay_id')
        cursor.execute("""
            INSERT OR REPLACE INTO relay_nodes 
            (relay_id, node_type, lat, lon, last_active)
            VALUES (?, ?, ?, ?, ?)
        """, (relay_id, data.get('node_type', 'mobile_app'), lat, lon, datetime.now()))
        
        cursor.execute("""
            INSERT INTO relay_reports 
            (device_hash, relay_id, relay_lat, relay_lon, signal_strength, detection_method)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.get('device_hash'), relay_id, lat, lon, signal, data.get('method', 'bluetooth_le')))
        
        cursor.execute("""
            UPDATE stolen_devices SET last_seen = ? WHERE device_hash = ?
        """, (datetime.now(), data.get('device_hash')))
        
        conn.commit()
        conn.close()
        logger.info(f"Relay report received for device: {data.get('device_hash')}")
        return jsonify({'success': True}), 201
    except BadRequest as e:
        return jsonify({'error': str(e)}), 400
    except ValueError as e:
        return jsonify({'error': 'Invalid data format'}), 400
    except Exception as e:
        logger.error(f"Error processing relay report: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/locate/<device_hash>', methods=['GET'])
def locate_device(device_hash):
    """Get device location based on relay reports"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        since = datetime.now() - timedelta(hours=24)
        
        cursor.execute("""
            SELECT relay_lat, relay_lon, signal_strength, timestamp
            FROM relay_reports
            WHERE device_hash = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT 100
        """, (device_hash, since))
        
        reports = cursor.fetchall()
        conn.close()
        
        if not reports:
            return jsonify({'status': 'no_data', 'message': 'No recent sightings'}), 404
        
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
        
        logger.info(f"Device located: {device_hash} at ({probable_lat}, {probable_lon})")
        return jsonify({
            'status': 'located',
  
