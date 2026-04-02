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
    
