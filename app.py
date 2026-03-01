"""
AEGIS — AI-Powered Disaster Management System
Flask Backend Server
"""
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
import sqlite3, hashlib, datetime, json, os
from ai_model import DisasterRiskModel

app = Flask(__name__, static_folder='.', template_folder='.')
CORS(app)

DB_PATH = 'aegis.db'
model = DisasterRiskModel()

# ─── DATABASE INIT ───────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disaster_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            location TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            description TEXT,
            image_path TEXT,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            region TEXT,
            risk_level TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS weather_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temperature REAL,
            humidity REAL,
            wind_speed REAL,
            rainfall REAL,
            pressure REAL,
            aqi REAL,
            flood_risk REAL,
            risk_level TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            contact TEXT,
            region TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Seed admin user
    ph = hashlib.sha256(b'admin123').hexdigest()
    cur.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                ('Admin AEGIS', 'admin@aegis.gov.in', ph, 'admin'))
    # Seed sample alerts
    sample_alerts = [
        ('Flash Flood Warning', 'Yamuna River rising — 24 zones affected', 'critical', 'Delhi NCR', 'HIGH'),
        ('Heatwave Advisory', 'Temperature 47°C forecast — stay indoors', 'warning', 'Rajasthan', 'MEDIUM'),
        ('Cyclone Watch', 'Bay of Bengal depression intensifying', 'warning', 'Odisha', 'HIGH'),
    ]
    for a in sample_alerts:
        cur.execute("INSERT OR IGNORE INTO alerts(title,message,alert_type,region,risk_level) VALUES(?,?,?,?,?)", a)
    con.commit()
    con.close()

# ─── HELPERS ─────────────────────────────────────────────────────
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

# ─── ROUTES ──────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Auth
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    con = get_db()
    user = con.execute(
        "SELECT * FROM users WHERE email=? AND password_hash=?",
        (data['email'], hash_password(data['password']))
    ).fetchone()
    con.close()
    if user:
        return jsonify({'success': True, 'user': {'id': user['id'], 'name': user['name'], 'role': user['role']}})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    con = get_db()
    try:
        con.execute("INSERT INTO users(name,email,phone,password_hash) VALUES(?,?,?,?)",
                    (data['name'], data['email'], data.get('phone'), hash_password(data['password'])))
        con.commit()
        return jsonify({'success': True, 'message': 'Account created successfully'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Email already registered'}), 409
    finally:
        con.close()

# Weather + AI Risk
@app.route('/api/weather/current')
def weather():
    import requests
    lat = request.args.get('lat', 28.6139)
    lon = request.args.get('lon', 77.2090)
    api_key = os.environ.get('OWM_API_KEY', '')
    weather_data = {}
    if api_key:
        try:
            res = requests.get(f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric', timeout=5)
            if res.ok:
                d = res.json()
                weather_data = {
                    'temperature': d['main']['temp'],
                    'humidity': d['main']['humidity'],
                    'wind_speed': d['wind']['speed'] * 3.6,
                    'rainfall': d.get('rain', {}).get('1h', 0),
                    'pressure': d['main']['pressure'],
                    'condition': d['weather'][0]['description'],
                    'cloud_cover': d['clouds']['all'],
                    'visibility': d.get('visibility', 10000) / 1000,
                }
        except:
            pass
    if not weather_data:  # Simulated fallback
        import random, math
        h = datetime.datetime.now().hour
        weather_data = {
            'temperature': round(28 + math.sin(h / 8) * 6 + random.uniform(-2, 2), 1),
            'humidity': round(65 + random.uniform(0, 20), 1),
            'wind_speed': round(12 + random.uniform(0, 18), 1),
            'rainfall': round(random.uniform(0, 30) if random.random() < 0.4 else 0, 1),
            'pressure': round(1005 + random.uniform(-10, 10), 1),
            'condition': 'Partly Cloudy',
            'cloud_cover': round(40 + random.uniform(0, 50), 1),
            'visibility': round(6 + random.uniform(0, 8), 1),
        }
    weather_data['aqi'] = 120
    # AI risk prediction
    risk = model.predict(weather_data)
    weather_data['risk'] = risk
    # Log to DB
    con = get_db()
    con.execute("INSERT INTO weather_log(temperature,humidity,wind_speed,rainfall,pressure,aqi,flood_risk,risk_level) VALUES(?,?,?,?,?,?,?,?)",
                (weather_data['temperature'], weather_data['humidity'], weather_data['wind_speed'],
                 weather_data['rainfall'], weather_data['pressure'], weather_data['aqi'],
                 risk['flood'], risk['overall_level']))
    con.commit(); con.close()
    return jsonify(weather_data)

# Reports
@app.route('/api/reports', methods=['GET'])
def get_reports():
    con = get_db()
    rows = con.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT 50").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/reports', methods=['POST'])
def create_report():
    data = request.json
    con = get_db()
    cur = con.execute("INSERT INTO reports(disaster_type,severity,location,latitude,longitude,description,user_id) VALUES(?,?,?,?,?,?,?)",
                      (data['type'], data['severity'], data['location'],
                       data.get('lat'), data.get('lng'), data.get('description'), data.get('user_id')))
    con.commit(); report_id = cur.lastrowid; con.close()
    return jsonify({'success': True, 'report_id': report_id})

# Alerts
@app.route('/api/alerts')
def get_alerts():
    region = request.args.get('region', '')
    con = get_db()
    q = "SELECT * FROM alerts WHERE is_active=1"
    params = []
    if region:
        q += " AND (region LIKE ? OR region='All India')"
        params.append(f'%{region}%')
    q += " ORDER BY created_at DESC LIMIT 20"
    rows = con.execute(q, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/alerts', methods=['POST'])
def create_alert():
    data = request.json
    con = get_db()
    con.execute("INSERT INTO alerts(title,message,alert_type,region,risk_level) VALUES(?,?,?,?,?)",
                (data['title'], data['message'], data['type'], data.get('region', 'All India'), data.get('risk', 'MEDIUM')))
    con.commit(); con.close()
    return jsonify({'success': True})

# Subscribe
@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    data = request.json
    con = get_db()
    con.execute("INSERT INTO subscriptions(type,contact,region) VALUES(?,?,?)",
                (data['type'], data['contact'], data.get('region', 'All India')))
    con.commit(); con.close()
    return jsonify({'success': True, 'message': f"Subscribed {data['contact']} for {data['type']} alerts"})

# Dashboard stats
@app.route('/api/dashboard/stats')
def dashboard_stats():
    con = get_db()
    total_reports = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    active_alerts = con.execute("SELECT COUNT(*) FROM alerts WHERE is_active=1").fetchone()[0]
    total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    recent_logs = con.execute("SELECT * FROM weather_log ORDER BY logged_at DESC LIMIT 24").fetchall()
    con.close()
    return jsonify({
        'total_reports': total_reports,
        'active_alerts': active_alerts,
        'total_users': total_users,
        'weather_trend': [dict(r) for r in recent_logs]
    })

if __name__ == '__main__':
    init_db()
    print("\n🛡️  AEGIS Backend Starting...")
    print("📡  Server: http://localhost:5000")
    print("💾  Database: aegis.db")
    app.run(debug=True, port=5000)
