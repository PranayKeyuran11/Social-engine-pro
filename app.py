from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from functools import wraps
import os
import hashlib
import secrets
import smtplib
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from graph.orchestrator import build_graph
from scheduler import start_scheduler, schedule_automation, unschedule_automation

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DATABASE_URL = os.environ.get("DATABASE_URL")

# SMTP config (use Gmail App Password or any SMTP)
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ.get("SMTP_USER", "")        # your Gmail address
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")    # Gmail App Password

DAILY_GENERATION_LIMIT = int(os.environ.get("DAILY_GENERATION_LIMIT", 10))
OTP_EXPIRY_MINUTES = 15

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    gemini_api_key TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS automations (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    topics TEXT NOT NULL,
                    context TEXT,
                    email TEXT NOT NULL,
                    send_time TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    last_sent TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS otp_tokens (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL,
                    otp TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    date DATE NOT NULL DEFAULT CURRENT_DATE,
                    generation_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, date)
                )
            ''')
            # Add columns to existing tables if upgrading
            try:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gemini_api_key TEXT")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


init_db()
start_scheduler()

# ─────────────────────────────────────────────
# EMAIL HELPER
# ─────────────────────────────────────────────

def send_email(to_email, subject, html_body):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[Email] SMTP not configured. OTP for {to_email}: {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Social Engine Pro <{SMTP_USER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[Email] Failed to send to {to_email}: {e}")
        return False


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


def create_otp(email, purpose):
    otp = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Invalidate old OTPs for this email+purpose
            cur.execute("UPDATE otp_tokens SET used=TRUE WHERE email=%s AND purpose=%s AND used=FALSE",
                        (email, purpose))
            cur.execute(
                "INSERT INTO otp_tokens (email, otp, purpose, expires_at) VALUES (%s,%s,%s,%s)",
                (email, otp, purpose, expires_at)
            )
        conn.commit()
    finally:
        conn.close()
    return otp


def verify_otp(email, otp, purpose):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM otp_tokens
                   WHERE email=%s AND otp=%s AND purpose=%s AND used=FALSE
                     AND expires_at > NOW()
                   ORDER BY created_at DESC LIMIT 1""",
                (email, otp, purpose)
            )
            token = cur.fetchone()
        if not token:
            return False
        with conn.cursor() as cur:
            cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token['id'],))
        conn.commit()
        return True
    finally:
        conn.close()


def send_verification_email(email, otp):
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:500px;margin:0 auto;padding:2rem;">
        <div style="background:linear-gradient(135deg,#4f46e5,#6366f1);border-radius:16px;padding:2rem;text-align:center;color:white;">
            <h1 style="margin:0 0 0.5rem;">🚀 Social Engine Pro</h1>
            <p style="margin:0;opacity:0.85;">Email Verification</p>
        </div>
        <div style="background:white;border:1px solid #e2e8f0;border-radius:16px;padding:2rem;margin-top:1rem;">
            <p style="color:#1e293b;font-size:1rem;">Your verification code is:</p>
            <div style="background:#f0f5ff;border:2px solid #4f46e5;border-radius:12px;padding:1.5rem;text-align:center;margin:1rem 0;">
                <span style="font-size:2.5rem;font-weight:700;letter-spacing:0.5rem;color:#4f46e5;">{otp}</span>
            </div>
            <p style="color:#64748b;font-size:0.875rem;">This code expires in {OTP_EXPIRY_MINUTES} minutes.</p>
        </div>
    </div>"""
    send_email(email, "Verify your Social Engine Pro account", html)


def send_reset_email(email, otp):
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:500px;margin:0 auto;padding:2rem;">
        <div style="background:linear-gradient(135deg,#4f46e5,#6366f1);border-radius:16px;padding:2rem;text-align:center;color:white;">
            <h1 style="margin:0 0 0.5rem;">🚀 Social Engine Pro</h1>
            <p style="margin:0;opacity:0.85;">Password Reset</p>
        </div>
        <div style="background:white;border:1px solid #e2e8f0;border-radius:16px;padding:2rem;margin-top:1rem;">
            <p style="color:#1e293b;font-size:1rem;">Your password reset code is:</p>
            <div style="background:#fff7ed;border:2px solid #f97316;border-radius:12px;padding:1.5rem;text-align:center;margin:1rem 0;">
                <span style="font-size:2.5rem;font-weight:700;letter-spacing:0.5rem;color:#f97316;">{otp}</span>
            </div>
            <p style="color:#64748b;font-size:0.875rem;">This code expires in {OTP_EXPIRY_MINUTES} minutes. If you didn't request this, ignore this email.</p>
        </div>
    </div>"""
    send_email(email, "Reset your Social Engine Pro password", html)

# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_user_by_email(email):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
            return cur.fetchone()
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM users WHERE username = %s', (username,))
            return cur.fetchone()
    finally:
        conn.close()


def create_user(username, email, password):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO users (username, email, password_hash, is_verified) VALUES (%s, %s, %s, FALSE)',
                (username, email, hash_password(password))
            )
        conn.commit()
    finally:
        conn.close()


def mark_user_verified(email):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE users SET is_verified=TRUE WHERE email=%s', (email,))
        conn.commit()
    finally:
        conn.close()


def update_password(email, new_password):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE users SET password_hash=%s WHERE email=%s',
                        (hash_password(new_password), email))
        conn.commit()
    finally:
        conn.close()


def update_gemini_key(user_id, api_key):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE users SET gemini_api_key=%s WHERE id=%s', (api_key, user_id))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────

def get_daily_usage(user_id):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT generation_count FROM usage_logs WHERE user_id=%s AND date=CURRENT_DATE',
                (user_id,)
            )
            row = cur.fetchone()
            return row['generation_count'] if row else 0
    finally:
        conn.close()


def increment_daily_usage(user_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO usage_logs (user_id, date, generation_count)
                VALUES (%s, CURRENT_DATE, 1)
                ON CONFLICT (user_id, date)
                DO UPDATE SET generation_count = usage_logs.generation_count + 1
            ''', (user_id,))
        conn.commit()
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
# SHARED STYLES
# ─────────────────────────────────────────────

AUTH_STYLES = '''
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root { --primary: #4f46e5; --border: #e2e8f0; --text-dark: #1e293b; --text-muted: #64748b; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Inter',sans-serif; background:linear-gradient(135deg,#4f46e5 0%,#6366f1 50%,#818cf8 100%); min-height:100vh; display:flex; align-items:center; justify-content:center; }
.auth-card { background:white; border-radius:20px; padding:2.5rem; width:100%; max-width:420px; box-shadow:0 25px 60px rgba(0,0,0,0.15); }
.auth-logo { text-align:center; margin-bottom:2rem; }
.logo-icon { width:60px; height:60px; background:linear-gradient(135deg,#4f46e5,#6366f1); border-radius:16px; display:inline-flex; align-items:center; justify-content:center; font-size:1.75rem; margin-bottom:0.75rem; }
.auth-logo h1 { font-size:1.5rem; font-weight:700; color:var(--text-dark); }
.auth-logo p { color:var(--text-muted); font-size:0.875rem; margin-top:0.25rem; }
.form-group { margin-bottom:1.25rem; }
label { display:block; font-weight:500; font-size:0.875rem; color:var(--text-dark); margin-bottom:0.5rem; }
input,select { width:100%; padding:0.75rem 1rem; border:1.5px solid var(--border); border-radius:10px; font-size:0.9rem; font-family:'Inter',sans-serif; transition:border-color 0.2s; outline:none; }
input:focus,select:focus { border-color:var(--primary); box-shadow:0 0 0 3px rgba(79,70,229,0.1); }
.btn-auth { width:100%; padding:0.875rem; background:linear-gradient(135deg,#4f46e5,#6366f1); color:white; border:none; border-radius:10px; font-size:1rem; font-weight:600; cursor:pointer; transition:all 0.3s; margin-top:0.5rem; font-family:'Inter',sans-serif; }
.btn-auth:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,0.35); }
.btn-secondary { background:white; color:var(--primary); border:1.5px solid var(--primary); }
.btn-secondary:hover { background:#f0f5ff; box-shadow:none; }
.auth-footer { text-align:center; margin-top:1.5rem; font-size:0.875rem; color:var(--text-muted); }
.auth-footer a { color:var(--primary); text-decoration:none; font-weight:500; }
.alert { padding:0.75rem 1rem; border-radius:10px; font-size:0.875rem; margin-bottom:1.25rem; }
.alert-error { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
.alert-success { background:#f0fdf4; color:#16a34a; border:1px solid #86efac; }
.alert-info { background:#f0f5ff; color:#4f46e5; border:1px solid #c7d2fe; }
.otp-inputs { display:flex; gap:0.5rem; justify-content:center; margin:1rem 0; }
.otp-inputs input { width:50px; text-align:center; font-size:1.5rem; font-weight:700; padding:0.5rem; letter-spacing:0; }
</style>'''

NAVBAR_CSS = '''
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
:root { --primary:#4f46e5; --bg-light:#f8fafc; --card-bg:#ffffff; --text-dark:#1e293b; --text-muted:#64748b; --border:#e2e8f0; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Inter',sans-serif; background:var(--bg-light); color:var(--text-dark); min-height:100vh; }
.navbar { background:linear-gradient(135deg,#4f46e5 0%,#6366f1 100%); padding:1rem 0; box-shadow:0 4px 20px rgba(79,70,229,0.15); }
.navbar-brand { font-weight:700; font-size:1.5rem; color:white!important; text-decoration:none; }
.nav-link-item { color:rgba(255,255,255,0.8)!important; font-size:0.875rem; font-weight:500; padding:0.4rem 0.9rem; border-radius:8px; text-decoration:none; transition:all 0.2s; }
.nav-link-item:hover,.nav-link-item.active { background:rgba(255,255,255,0.15); color:white!important; }
.nav-user { color:rgba(255,255,255,0.85); font-size:0.875rem; display:flex; align-items:center; gap:1rem; }
.btn-logout { background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); color:white; border-radius:8px; padding:0.4rem 1rem; font-size:0.8rem; font-weight:500; text-decoration:none; transition:all 0.2s; }
.btn-logout:hover { background:rgba(255,255,255,0.25); color:white; }
.main-container { padding:2rem 0; min-height:calc(100vh - 72px); }
.footer { background:var(--card-bg); border-top:1px solid var(--border); padding:1.5rem 0; text-align:center; color:var(--text-muted); font-size:0.875rem; }
.usage-badge { background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); color:white; border-radius:8px; padding:0.3rem 0.75rem; font-size:0.78rem; }
</style>'''

def navbar_html(active, username, daily_usage=0):
    limit = DAILY_GENERATION_LIMIT
    return f'''
<nav class="navbar">
    <div class="container d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-4">
            <a href="/" class="navbar-brand"><i class="bi bi-rocket-takeoff"></i> Social Engine Pro</a>
            <div class="d-flex gap-1">
                <a href="/" class="nav-link-item {"active" if active=="home" else ""}"><i class="bi bi-house"></i> Home</a>
                <a href="/automation" class="nav-link-item {"active" if active=="automation" else ""}"><i class="bi bi-clock-history"></i> Automation</a>
                <a href="/settings" class="nav-link-item {"active" if active=="settings" else ""}"><i class="bi bi-gear"></i> Settings</a>
            </div>
        </div>
        <div class="nav-user">
            <span class="usage-badge"><i class="bi bi-lightning"></i> {daily_usage}/{limit} today</span>
            <span><i class="bi bi-person-circle"></i> {username}</span>
            <a href="/logout" class="btn-logout"><i class="bi bi-box-arrow-right"></i> Logout</a>
        </div>
    </div>
</nav>'''

# ─────────────────────────────────────────────
# AUTH TEMPLATES
# ─────────────────────────────────────────────

LOGIN_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Login</title>''' + AUTH_STYLES + '''</head><body>
<div class="auth-card">
    <div class="auth-logo"><div class="logo-icon">🚀</div><h1>Social Engine Pro</h1><p>Sign in to your account</p></div>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
    {% if info %}<div class="alert alert-info">{{ info }}</div>{% endif %}
    <form method="POST" action="/login">
        <div class="form-group"><label>Email</label><input type="email" name="email" placeholder="you@example.com" required></div>
        <div class="form-group"><label>Password</label><input type="password" name="password" placeholder="••••••••" required></div>
        <button type="submit" class="btn-auth">Sign In</button>
    </form>
    <div class="auth-footer" style="margin-top:1rem;">
        <a href="/forgot-password">Forgot password?</a>
    </div>
    <div class="auth-footer">Don't have an account? <a href="/signup">Create one</a></div>
</div></body></html>'''

SIGNUP_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Sign Up</title>''' + AUTH_STYLES + '''</head><body>
<div class="auth-card">
    <div class="auth-logo"><div class="logo-icon">🚀</div><h1>Create Account</h1><p>Join Social Engine Pro</p></div>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    <form method="POST" action="/signup">
        <div class="form-group"><label>Username</label><input type="text" name="username" placeholder="yourname" required></div>
        <div class="form-group"><label>Email</label><input type="email" name="email" placeholder="you@example.com" required></div>
        <div class="form-group"><label>Password</label><input type="password" name="password" placeholder="Min. 6 characters" required></div>
        <div class="form-group"><label>Confirm Password</label><input type="password" name="confirm_password" placeholder="••••••••" required></div>
        <button type="submit" class="btn-auth">Create Account</button>
    </form>
    <div class="auth-footer">Already have an account? <a href="/login">Sign in</a></div>
</div></body></html>'''

VERIFY_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Verify Email</title>''' + AUTH_STYLES + '''</head><body>
<div class="auth-card">
    <div class="auth-logo"><div class="logo-icon">✉️</div><h1>Verify Your Email</h1><p>We sent a 6-digit code to <strong>{{ email }}</strong></p></div>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
    <form method="POST" action="/verify-email">
        <input type="hidden" name="email" value="{{ email }}">
        <div class="form-group"><label>Enter 6-digit code</label><input type="text" name="otp" maxlength="6" placeholder="123456" required style="text-align:center;font-size:1.5rem;letter-spacing:0.5rem;font-weight:700;"></div>
        <button type="submit" class="btn-auth">Verify Email</button>
    </form>
    <div class="auth-footer"><a href="/resend-otp?email={{ email }}&purpose=verify">Resend code</a></div>
</div></body></html>'''

FORGOT_PASSWORD_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Forgot Password</title>''' + AUTH_STYLES + '''</head><body>
<div class="auth-card">
    <div class="auth-logo"><div class="logo-icon">🔑</div><h1>Reset Password</h1><p>Enter your email to receive a reset code</p></div>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
    <form method="POST" action="/forgot-password">
        <div class="form-group"><label>Email</label><input type="email" name="email" placeholder="you@example.com" required></div>
        <button type="submit" class="btn-auth">Send Reset Code</button>
    </form>
    <div class="auth-footer"><a href="/login">Back to Sign In</a></div>
</div></body></html>'''

RESET_PASSWORD_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Reset Password</title>''' + AUTH_STYLES + '''</head><body>
<div class="auth-card">
    <div class="auth-logo"><div class="logo-icon">🔑</div><h1>Set New Password</h1><p>Enter the code sent to <strong>{{ email }}</strong></p></div>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    <form method="POST" action="/reset-password">
        <input type="hidden" name="email" value="{{ email }}">
        <div class="form-group"><label>6-digit Code</label><input type="text" name="otp" maxlength="6" placeholder="123456" required style="text-align:center;font-size:1.5rem;letter-spacing:0.5rem;font-weight:700;"></div>
        <div class="form-group"><label>New Password</label><input type="password" name="password" placeholder="Min. 6 characters" required></div>
        <div class="form-group"><label>Confirm New Password</label><input type="password" name="confirm_password" placeholder="••••••••" required></div>
        <button type="submit" class="btn-auth">Reset Password</button>
    </form>
    <div class="auth-footer"><a href="/resend-otp?email={{ email }}&purpose=reset">Resend code</a></div>
</div></body></html>'''

# ─────────────────────────────────────────────
# SETTINGS TEMPLATE
# ─────────────────────────────────────────────

SETTINGS_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Settings – Social Engine Pro</title>
''' + NAVBAR_CSS + '''
<style>
.page-header { margin-bottom:2rem; }
.page-header h2 { font-size:1.5rem; font-weight:700; }
.page-header p { color:var(--text-muted); font-size:0.9rem; margin-top:0.25rem; }
.card { background:white; border-radius:16px; border:1px solid var(--border); box-shadow:0 4px 20px rgba(0,0,0,0.05); padding:1.75rem; margin-bottom:1.5rem; }
.card-title { font-size:1rem; font-weight:600; margin-bottom:1.5rem; display:flex; align-items:center; gap:0.5rem; }
.form-label { font-weight:500; font-size:0.875rem; margin-bottom:0.5rem; display:block; }
.form-control { width:100%; padding:0.75rem 1rem; border:1.5px solid var(--border); border-radius:10px; font-size:0.9rem; font-family:'Inter',sans-serif; outline:none; transition:border-color 0.2s; }
.form-control:focus { border-color:#4f46e5; box-shadow:0 0 0 3px rgba(79,70,229,0.1); }
.mb-3 { margin-bottom:1rem; }
.btn-save { background:linear-gradient(135deg,#4f46e5,#6366f1); color:white; border:none; border-radius:10px; padding:0.75rem 2rem; font-size:0.9rem; font-weight:600; cursor:pointer; transition:all 0.3s; font-family:'Inter',sans-serif; }
.btn-save:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,0.3); }
.alert { padding:0.875rem 1rem; border-radius:10px; font-size:0.875rem; margin-bottom:1.5rem; }
.alert-success { background:#f0fdf4; color:#16a34a; border:1px solid #86efac; }
.alert-error { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
.key-hint { font-size:0.78rem; color:var(--text-muted); margin-top:0.4rem; }
.key-hint a { color:#4f46e5; }
.usage-bar-wrap { background:#f0f5ff; border-radius:10px; padding:1.25rem; }
.usage-bar-bg { background:#e2e8f0; border-radius:999px; height:10px; margin:0.75rem 0; overflow:hidden; }
.usage-bar-fill { background:linear-gradient(90deg,#4f46e5,#6366f1); height:100%; border-radius:999px; transition:width 0.5s; }
.stat-row { display:flex; justify-content:space-between; font-size:0.85rem; color:var(--text-muted); }
.stat-val { font-weight:700; color:var(--text-dark); }
</style></head><body>
{{ navbar | safe }}
<div class="main-container"><div class="container" style="max-width:700px;">
    <div class="page-header">
        <h2><i class="bi bi-gear"></i> Account Settings</h2>
        <p>Manage your API key, password, and usage limits.</p>
    </div>
    {% if message %}<div class="alert alert-{{ message_type }}">{{ message }}</div>{% endif %}

    <!-- Usage Stats -->
    <div class="card">
        <div class="card-title"><i class="bi bi-bar-chart" style="color:#4f46e5;"></i> Today's Usage</div>
        <div class="usage-bar-wrap">
            <div class="stat-row"><span>Generations used today</span><span class="stat-val">{{ daily_usage }} / {{ limit }}</span></div>
            <div class="usage-bar-bg"><div class="usage-bar-fill" style="width:{{ [daily_usage / limit * 100, 100]|min }}%;"></div></div>
            <div class="stat-row"><span>Resets at midnight</span><span class="stat-val">{{ limit - daily_usage }} remaining</span></div>
        </div>
        {% if not has_own_key %}
        <p style="margin-top:1rem;font-size:0.85rem;color:#f97316;"><i class="bi bi-exclamation-triangle"></i> You're using the shared API key. Add your own Gemini key below for unlimited generations.</p>
        {% else %}
        <p style="margin-top:1rem;font-size:0.85rem;color:#16a34a;"><i class="bi bi-check-circle"></i> You're using your own Gemini API key — no daily limit applies.</p>
        {% endif %}
    </div>

    <!-- Gemini API Key -->
    <div class="card">
        <div class="card-title"><i class="bi bi-key" style="color:#4f46e5;"></i> Your Gemini API Key</div>
        <form method="POST" action="/settings/update-key">
            <div class="mb-3">
                <label class="form-label">Gemini API Key</label>
                <input type="text" name="gemini_api_key" class="form-control" placeholder="AIzaSy..." value="{{ masked_key }}">
                <p class="key-hint">Get a free key at <a href="https://aistudio.google.com/app/apikey" target="_blank">aistudio.google.com</a>. Your key is stored securely and used only for your generations.</p>
            </div>
            <button type="submit" class="btn-save"><i class="bi bi-save"></i> Save API Key</button>
        </form>
    </div>

    <!-- Change Password -->
    <div class="card">
        <div class="card-title"><i class="bi bi-shield-lock" style="color:#4f46e5;"></i> Change Password</div>
        <form method="POST" action="/settings/change-password">
            <div class="mb-3"><label class="form-label">Current Password</label><input type="password" name="current_password" class="form-control" placeholder="••••••••" required></div>
            <div class="mb-3"><label class="form-label">New Password</label><input type="password" name="new_password" class="form-control" placeholder="Min. 6 characters" required></div>
            <div class="mb-3"><label class="form-label">Confirm New Password</label><input type="password" name="confirm_password" class="form-control" placeholder="••••••••" required></div>
            <button type="submit" class="btn-save"><i class="bi bi-lock"></i> Update Password</button>
        </form>
    </div>
</div></div>
<footer class="footer"><div class="container"><p>Social Engine Pro | Powered by LangGraph &amp; Gemini API</p></div></footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>'''

# ─────────────────────────────────────────────
# MAIN PAGE TEMPLATE
# ─────────────────────────────────────────────

MAIN_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Social Engine Pro</title>
''' + NAVBAR_CSS + '''
<style>
.sidebar-card { background:var(--card-bg); border-radius:16px; border:1px solid var(--border); box-shadow:0 4px 20px rgba(0,0,0,0.05); padding:1.5rem; position:sticky; top:2rem; }
.sidebar-title { font-size:1.1rem; font-weight:600; margin-bottom:1.5rem; display:flex; align-items:center; gap:0.5rem; }
.form-label { font-weight:500; font-size:0.875rem; margin-bottom:0.5rem; }
.form-control,.form-select { border:1px solid var(--border); border-radius:10px; padding:0.75rem 1rem; font-size:0.9rem; }
.form-control:focus,.form-select:focus { border-color:var(--primary); box-shadow:0 0 0 3px rgba(79,70,229,0.1); }
.btn-generate { background:linear-gradient(135deg,#4f46e5,#6366f1); border:none; border-radius:10px; padding:0.875rem 1.5rem; font-weight:600; color:white; width:100%; transition:all 0.3s; }
.btn-generate:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,0.3); color:white; }
.btn-generate:disabled { opacity:0.7; cursor:not-allowed; transform:none; }
.content-card { background:var(--card-bg); border-radius:16px; border:1px solid var(--border); box-shadow:0 4px 20px rgba(0,0,0,0.05); padding:1.5rem; margin-bottom:1.5rem; transition:all 0.3s; }
.content-card:hover { box-shadow:0 8px 30px rgba(0,0,0,0.08); }
.content-header { display:flex; align-items:center; gap:0.75rem; margin-bottom:1rem; padding-bottom:1rem; border-bottom:1px solid var(--border); }
.content-icon { width:40px; height:40px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:1.25rem; }
.instagram-icon { background:linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888); color:white; }
.linkedin-icon { background:#0077b5; color:white; }
.article-icon { background:#2ecc71; color:white; }
.announcement-icon { background:#9b59b6; color:white; }
.content-title { font-weight:600; font-size:1rem; }
.content-body { font-size:0.9rem; line-height:1.7; white-space:pre-wrap; }
.hashtags-box { background:#f0f5ff; border:1px solid #dbeafe; border-radius:10px; padding:1rem; margin-top:1rem; font-family:monospace; font-size:0.85rem; color:#1e40af; }
.copy-btn { background:transparent; border:1px solid var(--border); border-radius:8px; padding:0.5rem 1rem; font-size:0.8rem; color:var(--text-muted); transition:all 0.3s; }
.copy-btn:hover { background:var(--primary); border-color:var(--primary); color:white; }
.stats-row { display:flex; gap:1rem; margin-top:1rem; flex-wrap:wrap; }
.stat-item { background:#f8fafc; border-radius:10px; padding:0.75rem 1rem; text-align:center; flex:1; min-width:100px; }
.stat-value { font-weight:700; font-size:1.25rem; color:var(--primary); }
.stat-label { font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; }
.loading-spinner { display:none; text-align:center; padding:3rem; }
.spinner-border { color:var(--primary); }
.loading-text { margin-top:1rem; color:var(--text-muted); }
.empty-state { text-align:center; padding:4rem 2rem; color:var(--text-muted); }
.empty-state i { font-size:4rem; margin-bottom:1rem; opacity:0.3; }
.limit-banner { background:#fff7ed; border:1px solid #fed7aa; border-radius:12px; padding:1rem 1.25rem; margin-bottom:1.5rem; display:flex; align-items:center; gap:0.75rem; font-size:0.875rem; color:#9a3412; }
@media(max-width:768px){.sidebar-card{position:static;margin-bottom:2rem;}}
</style></head><body>
{{ navbar | safe }}
<div class="main-container"><div class="container"><div class="row">
    <div class="col-lg-4 mb-4">
        <div class="sidebar-card">
            <h5 class="sidebar-title"><i class="bi bi-sliders"></i> Content Inputs</h5>
            {% if not has_own_key and daily_usage >= limit %}
            <div class="limit-banner"><i class="bi bi-exclamation-triangle-fill" style="font-size:1.25rem;flex-shrink:0;"></i>
                <span>Daily limit reached. <a href="/settings" style="color:#9a3412;font-weight:600;">Add your own Gemini key</a> in Settings for unlimited use.</span>
            </div>
            {% endif %}
            <div class="mb-3"><label class="form-label">Topic</label><input type="text" class="form-control" id="topic" placeholder="Enter your topic..." value="The rise of AI agents in 2025"></div>
            <div class="mb-3"><label class="form-label">Context</label><textarea class="form-control" id="context" rows="4">Focus on how LangGraph enables multi-agent workflows for businesses</textarea></div>
            <div class="mb-3"><label class="form-label">Tone</label>
                <select class="form-select" id="tone">
                    <option value="Professional" selected>Professional</option>
                    <option value="Casual">Casual</option>
                    <option value="Enthusiastic">Enthusiastic</option>
                    <option value="Thoughtful">Thoughtful</option>
                </select>
            </div>
            <div class="mb-3"><label class="form-label">Target Audience</label>
                <select class="form-select" id="audience">
                    <option value="General">General</option>
                    <option value="Tech Professionals" selected>Tech Professionals</option>
                    <option value="Business Leaders">Business Leaders</option>
                    <option value="Students">Students</option>
                </select>
            </div>
            <button class="btn btn-generate" id="generateBtn" onclick="generateContent()"><i class="bi bi-magic"></i> Generate Content</button>
        </div>
    </div>
    <div class="col-lg-8">
        <div id="loadingSpinner" class="loading-spinner">
            <div class="spinner-border" role="status" style="width:3rem;height:3rem;"></div>
            <p class="loading-text" id="loadingText">Initializing workflow...</p>
        </div>
        <div id="resultsContainer">
            <div class="empty-state"><i class="bi bi-chat-square-text"></i><h4>No Content Generated Yet</h4><p>Enter a topic and click Generate Content.</p></div>
        </div>
    </div>
</div></div></div>
<footer class="footer"><div class="container"><p>Social Engine Pro | Powered by LangGraph &amp; Gemini API</p></div></footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
let isGenerating = false;
async function generateContent() {
    if (isGenerating) return;
    const topic = document.getElementById('topic').value.trim();
    const context = document.getElementById('context').value.trim();
    if (!topic) { alert('Please enter a topic.'); return; }
    isGenerating = true;
    const btn = document.getElementById('generateBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Generating...';
    document.getElementById('resultsContainer').style.display = 'none';
    document.getElementById('loadingSpinner').style.display = 'block';
    document.getElementById('loadingText').textContent = 'Preparing AI agents...';
    try {
        const response = await fetch('/generate', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({topic,context}) });
        document.getElementById('loadingText').textContent = 'Generating content...';
        const result = await response.json();
        if (!response.ok) {
            if (response.status === 429) {
                document.getElementById('loadingSpinner').style.display = 'none';
                const c = document.getElementById('resultsContainer');
                c.style.display = 'block';
                c.innerHTML = `<div class="limit-banner" style="border-radius:16px;padding:1.5rem;"><i class="bi bi-exclamation-triangle-fill" style="font-size:1.5rem;flex-shrink:0;"></i>
                    <div><strong>Daily limit reached!</strong><br>Add your own Gemini API key in <a href="/settings">Settings</a> for unlimited generations.</div></div>`;
                return;
            }
            throw new Error(result.error || `Server error: ${response.status}`);
        }
        document.getElementById('loadingText').textContent = 'Complete!';
        displayResults(result);
    } catch (error) {
        document.getElementById('loadingSpinner').style.display = 'none';
        const c = document.getElementById('resultsContainer');
        c.style.display = 'block';
        c.innerHTML = `<div class="content-card" style="border-color:#fca5a5;background:#fef2f2;">
            <div class="content-header"><div class="content-icon" style="background:#dc2626;color:white;"><i class="bi bi-exclamation-triangle"></i></div>
            <span class="content-title" style="color:#dc2626;">Generation Failed</span></div>
            <div class="content-body" style="color:#7f1d1d;">${error.message}</div></div>`;
    } finally {
        isGenerating = false; btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-magic"></i> Generate Content';
    }
}
function displayResults(result) {
    document.getElementById('loadingSpinner').style.display = 'none';
    const c = document.getElementById('resultsContainer');
    c.style.display = 'block';
    const tags = result.instagram_hashtags ? result.instagram_hashtags.join(' ') : '';
    c.innerHTML = `
        <div class="content-card">
            <div class="content-header"><div class="content-icon instagram-icon"><i class="bi bi-instagram"></i></div>
            <span class="content-title">Instagram Caption</span>
            <button class="btn copy-btn ms-auto" onclick="cp('igCap')"><i class="bi bi-clipboard"></i> Copy</button></div>
            <div class="content-body" id="igCap">${result.instagram_caption||'N/A'}</div>
            ${tags?`<div class="hashtags-box">${tags}</div>`:''}
        </div>
        <div class="content-card">
            <div class="content-header"><div class="content-icon linkedin-icon"><i class="bi bi-linkedin"></i></div>
            <span class="content-title">LinkedIn Post</span>
            <button class="btn copy-btn ms-auto" onclick="cp('liPost')"><i class="bi bi-clipboard"></i> Copy</button></div>
            <div class="content-body" id="liPost">${result.linkedin_post||'N/A'}</div>
        </div>
        <div class="content-card">
            <div class="content-header"><div class="content-icon article-icon"><i class="bi bi-file-text"></i></div>
            <span class="content-title">LinkedIn Article</span>
            <button class="btn copy-btn ms-auto" onclick="cp('liArt')"><i class="bi bi-clipboard"></i> Copy</button></div>
            <div class="content-body" id="liArt">${result.linkedin_article||'N/A'}</div>
        </div>
        <div class="content-card">
            <div class="content-header"><div class="content-icon announcement-icon"><i class="bi bi-megaphone"></i></div>
            <span class="content-title">Announcement</span>
            <button class="btn copy-btn ms-auto" onclick="cp('ann')"><i class="bi bi-clipboard"></i> Copy</button></div>
            <div class="content-body" id="ann">${result.announcement||'N/A'}</div>
        </div>
        <div class="stats-row">
            <div class="stat-item"><div class="stat-value">${result.instagram_caption?result.instagram_caption.split(' ').length:0}</div><div class="stat-label">Instagram Words</div></div>
            <div class="stat-item"><div class="stat-value">${result.linkedin_post?result.linkedin_post.split(' ').length:0}</div><div class="stat-label">LinkedIn Words</div></div>
            <div class="stat-item"><div class="stat-value">${result.linkedin_article?result.linkedin_article.split(' ').length:0}</div><div class="stat-label">Article Words</div></div>
            <div class="stat-item"><div class="stat-value">${result.announcement?result.announcement.split(' ').length:0}</div><div class="stat-label">Announcement Words</div></div>
        </div>`;
}
function cp(id) { navigator.clipboard.writeText(document.getElementById(id).innerText).then(()=>alert('Copied!')); }
</script></body></html>'''

# ─────────────────────────────────────────────
# AUTOMATION PAGE TEMPLATE  (unchanged from before)
# ─────────────────────────────────────────────

AUTOMATION_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Automation – Social Engine Pro</title>
''' + NAVBAR_CSS + '''
<style>
.page-header { margin-bottom:2rem; }
.page-header h2 { font-size:1.5rem; font-weight:700; }
.page-header p { color:var(--text-muted); font-size:0.9rem; margin-top:0.25rem; }
.card { background:white; border-radius:16px; border:1px solid var(--border); box-shadow:0 4px 20px rgba(0,0,0,0.05); padding:1.75rem; margin-bottom:1.5rem; }
.card-title { font-size:1rem; font-weight:600; margin-bottom:1.5rem; display:flex; align-items:center; gap:0.5rem; }
.form-label { font-weight:500; font-size:0.875rem; margin-bottom:0.5rem; display:block; }
.form-control,.form-select { width:100%; padding:0.75rem 1rem; border:1.5px solid var(--border); border-radius:10px; font-size:0.9rem; font-family:'Inter',sans-serif; outline:none; transition:border-color 0.2s; }
.form-control:focus,.form-select:focus { border-color:#4f46e5; box-shadow:0 0 0 3px rgba(79,70,229,0.1); }
.mb-3 { margin-bottom:1rem; }
.two-col { display:flex; gap:1rem; }
.two-col > div { flex:1; }
.btn-save { background:linear-gradient(135deg,#4f46e5,#6366f1); color:white; border:none; border-radius:10px; padding:0.875rem 2rem; font-size:0.95rem; font-weight:600; cursor:pointer; transition:all 0.3s; font-family:'Inter',sans-serif; }
.btn-save:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,0.3); }
.topic-list { display:flex; flex-direction:column; gap:0.5rem; margin-bottom:0.75rem; }
.topic-row { display:flex; align-items:center; gap:0.5rem; }
.topic-row input { flex:1; padding:0.6rem 0.875rem; border:1.5px solid var(--border); border-radius:8px; font-size:0.875rem; font-family:'Inter',sans-serif; outline:none; }
.topic-row input:focus { border-color:#4f46e5; }
.btn-remove-topic { background:#fef2f2; border:1px solid #fca5a5; color:#dc2626; border-radius:8px; padding:0.5rem 0.75rem; cursor:pointer; font-size:0.8rem; transition:all 0.2s; flex-shrink:0; }
.btn-remove-topic:hover { background:#dc2626; color:white; }
.btn-add-topic { background:#f0f9ff; border:1px solid #bae6fd; color:#0369a1; border-radius:8px; padding:0.5rem 1rem; cursor:pointer; font-size:0.85rem; font-weight:500; transition:all 0.2s; font-family:'Inter',sans-serif; }
.btn-add-topic:hover { background:#0369a1; color:white; }
.topic-hint { font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem; }
.auto-item { background:#f8fafc; border:1px solid var(--border); border-radius:12px; padding:1.25rem; display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; margin-bottom:0.75rem; }
.auto-info h4 { font-size:0.95rem; font-weight:600; margin-bottom:0.4rem; }
.auto-info p { font-size:0.8rem; color:var(--text-muted); margin:0 0 0.2rem; }
.topics-preview { display:flex; flex-wrap:wrap; gap:0.35rem; margin-top:0.5rem; }
.topic-chip { background:white; border:1px solid var(--border); border-radius:20px; padding:0.2rem 0.65rem; font-size:0.75rem; color:var(--text-dark); }
.topic-chip.active-chip { background:#ede9fe; border-color:#c4b5fd; color:#5b21b6; font-weight:600; }
.badge { display:inline-block; padding:0.25rem 0.75rem; border-radius:20px; font-size:0.75rem; font-weight:600; }
.badge-active { background:#dcfce7; color:#16a34a; }
.badge-paused { background:#fef9c3; color:#ca8a04; }
.auto-actions { display:flex; gap:0.5rem; flex-shrink:0; flex-direction:column; align-items:flex-end; }
.btn-sm { padding:0.4rem 0.875rem; border-radius:8px; font-size:0.8rem; font-weight:500; cursor:pointer; border:none; font-family:'Inter',sans-serif; transition:all 0.2s; }
.btn-danger { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
.btn-danger:hover { background:#dc2626; color:white; }
.btn-toggle { background:#f0f9ff; color:#0369a1; border:1px solid #bae6fd; }
.btn-toggle:hover { background:#0369a1; color:white; }
.empty-auto { text-align:center; padding:3rem; color:var(--text-muted); }
.empty-auto i { font-size:3rem; opacity:0.3; display:block; margin-bottom:1rem; }
.alert { padding:0.875rem 1rem; border-radius:10px; font-size:0.875rem; margin-bottom:1.5rem; }
.alert-success { background:#f0fdf4; color:#16a34a; border:1px solid #86efac; }
.alert-error { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
</style></head><body>
{{ navbar | safe }}
<div class="main-container"><div class="container" style="max-width:800px;">
    <div class="page-header">
        <h2><i class="bi bi-clock-history"></i> Automation Settings</h2>
        <p>Schedule daily content generation with rotating topics — a different topic every day.</p>
    </div>
    {% if message %}<div class="alert alert-{{ message_type }}">{{ message }}</div>{% endif %}
    <div class="card">
        <div class="card-title"><i class="bi bi-plus-circle" style="color:#4f46e5;"></i> Create New Automation</div>
        <form method="POST" action="/automation/create">
            <div class="mb-3">
                <label class="form-label">Topic List <span style="color:#94a3b8;font-weight:400;">(rotates daily, one per day)</span></label>
                <div class="topic-list" id="topicList">
                    <div class="topic-row">
                        <input type="text" name="topics[]" placeholder="e.g. The rise of AI agents in 2025" required>
                        <button type="button" class="btn-remove-topic" onclick="removeTopic(this)" title="Remove">✕</button>
                    </div>
                </div>
                <button type="button" class="btn-add-topic" onclick="addTopic()"><i class="bi bi-plus"></i> Add Another Topic</button>
                <p class="topic-hint">Topics rotate in order. After the last topic, it loops back to the first.</p>
            </div>
            <div class="mb-3"><label class="form-label">Context <span style="color:#94a3b8;font-weight:400;">(optional — applies to all topics)</span></label>
                <textarea name="context" class="form-control" rows="2" placeholder="e.g. Focus on practical business impact"></textarea>
            </div>
            <div class="mb-3"><label class="form-label">Send to Email</label>
                <input type="email" name="email" class="form-control" placeholder="you@example.com" required>
            </div>
            <div class="two-col">
                <div class="mb-3"><label class="form-label">Send Time (24h)</label>
                    <input type="time" name="send_time" class="form-control" value="08:00" required>
                </div>
                <div class="mb-3"><label class="form-label">Timezone</label>
                    <select name="timezone" class="form-select">
                        <option value="Asia/Kolkata" selected>India (IST)</option>
                        <option value="America/New_York">US Eastern (EST)</option>
                        <option value="America/Los_Angeles">US Pacific (PST)</option>
                        <option value="Europe/London">London (GMT)</option>
                        <option value="Asia/Dubai">Dubai (GST)</option>
                        <option value="Asia/Singapore">Singapore (SGT)</option>
                        <option value="UTC">UTC</option>
                    </select>
                </div>
            </div>
            <button type="submit" class="btn-save"><i class="bi bi-calendar-check"></i> Save Automation</button>
        </form>
    </div>
    <div class="card">
        <div class="card-title"><i class="bi bi-list-check" style="color:#4f46e5;"></i> Your Automations</div>
        {% if automations %}
            {% for a in automations %}
            {% if a.get('topics') %}
                {% set topics = a['topics'].split('||') %}
                {% set idx = a['current_index'] %}
                <div class="auto-item">
                    <div class="auto-info" style="flex:1;">
                        <h4>{{ topics|length }} topic{{ 's' if topics|length != 1 else '' }} · rotates daily</h4>
                        <p><i class="bi bi-envelope"></i> {{ a['email'] }} &nbsp;·&nbsp; <i class="bi bi-clock"></i> {{ a['send_time'] }} ({{ a['timezone'] }})</p>
                        <p><i class="bi bi-arrow-repeat"></i> Next: <strong>Topic {{ (idx % topics|length) + 1 }}</strong> of {{ topics|length }}</p>
                        {% if a['last_sent'] %}<p style="color:#16a34a;"><i class="bi bi-check-circle"></i> Last sent: {{ a['last_sent'] }}</p>{% endif %}
                        <div class="topics-preview">
                            {% for t in topics %}
                            <span class="topic-chip {% if loop.index0 == idx % topics|length %}active-chip{% endif %}">
                                {% if loop.index0 == idx % topics|length %}▶ {% endif %}{{ t.strip() }}
                            </span>
                            {% endfor %}
                        </div>
                    </div>
                    <div class="auto-actions">
                        <span class="badge {% if a['is_active'] %}badge-active{% else %}badge-paused{% endif %}">
                            {% if a['is_active'] %}Active{% else %}Paused{% endif %}
                        </span>
                        <form method="POST" action="/automation/toggle/{{ a['id'] }}" style="margin:0;">
                            <button type="submit" class="btn-sm btn-toggle">
                                {% if a['is_active'] %}<i class="bi bi-pause"></i> Pause{% else %}<i class="bi bi-play"></i> Resume{% endif %}
                            </button>
                        </form>
                        <form method="POST" action="/automation/delete/{{ a['id'] }}" style="margin:0;" onsubmit="return confirm('Delete this automation?')">
                            <button type="submit" class="btn-sm btn-danger"><i class="bi bi-trash"></i> Delete</button>
                        </form>
                    </div>
                </div>
            {% else %}
                <div class="auto-item"><div class="auto-info">No topics set for this automation.</div></div>
            {% endif %}
            {% endfor %}
        {% else %}
        <div class="empty-auto"><i class="bi bi-calendar-x"></i><p>No automations yet. Create one above.</p></div>
        {% endif %}
    </div>
</div></div>
<footer class="footer"><div class="container"><p>Social Engine Pro | Powered by LangGraph &amp; Gemini API</p></div></footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
function addTopic() {
    const list = document.getElementById('topicList');
    const row = document.createElement('div');
    row.className = 'topic-row';
    row.innerHTML = `<input type="text" name="topics[]" placeholder="Enter a topic...">
                     <button type="button" class="btn-remove-topic" onclick="removeTopic(this)" title="Remove">✕</button>`;
    list.appendChild(row);
    row.querySelector('input').focus();
}
function removeTopic(btn) {
    const list = document.getElementById('topicList');
    if (list.children.length <= 1) { alert('You need at least one topic.'); return; }
    btn.closest('.topic-row').remove();
}
</script>
</body></html>'''

# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = get_user_by_email(email)
        if not user or user['password_hash'] != hash_password(password):
            return render_template_string(LOGIN_TEMPLATE, error='Invalid email or password.', success=None, info=None)
        if not user['is_verified']:
            otp = create_otp(email, 'verify')
            send_verification_email(email, otp)
            return redirect(url_for('verify_email') + f'?email={email}&resent=1')
        session['user_id'] = user['id']
        session['username'] = user['username']
        return redirect(url_for('index'))
    success_msg = request.args.get('registered')
    reset_msg = request.args.get('reset')
    return render_template_string(LOGIN_TEMPLATE, error=None,
                                  success='Account created! Please sign in.' if success_msg else ('Password reset successfully!' if reset_msg else None),
                                  info=None)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not username or not email or not password:
            return render_template_string(SIGNUP_TEMPLATE, error='All fields are required.')
        if len(password) < 6:
            return render_template_string(SIGNUP_TEMPLATE, error='Password must be at least 6 characters.')
        if password != confirm:
            return render_template_string(SIGNUP_TEMPLATE, error='Passwords do not match.')
        if get_user_by_email(email):
            return render_template_string(SIGNUP_TEMPLATE, error='Email already registered.')
        if get_user_by_username(username):
            return render_template_string(SIGNUP_TEMPLATE, error='Username already taken.')
        create_user(username, email, password)
        otp = create_otp(email, 'verify')
        send_verification_email(email, otp)
        return redirect(url_for('verify_email') + f'?email={email}')
    return render_template_string(SIGNUP_TEMPLATE, error=None)


@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    email = request.args.get('email', '') or request.form.get('email', '')
    if not email:
        return redirect(url_for('login'))
    if request.method == 'POST':
        otp = request.form.get('otp', '').strip()
        if verify_otp(email, otp, 'verify'):
            mark_user_verified(email)
            return redirect(url_for('login') + '?registered=1')
        return render_template_string(VERIFY_TEMPLATE, email=email, error='Invalid or expired code. Please try again.', success=None)
    resent = request.args.get('resent')
    return render_template_string(VERIFY_TEMPLATE, email=email, error=None,
                                  success='Verification code sent!' if resent else None)


@app.route('/resend-otp')
def resend_otp():
    email = request.args.get('email', '')
    purpose = request.args.get('purpose', 'verify')
    if not email:
        return redirect(url_for('login'))
    user = get_user_by_email(email)
    if not user:
        return redirect(url_for('login'))
    otp = create_otp(email, purpose)
    if purpose == 'verify':
        send_verification_email(email, otp)
        return redirect(url_for('verify_email') + f'?email={email}&resent=1')
    else:
        send_reset_email(email, otp)
        return redirect(url_for('reset_password') + f'?email={email}&resent=1')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = get_user_by_email(email)
        # Always show success to avoid email enumeration
        if user:
            otp = create_otp(email, 'reset')
            send_reset_email(email, otp)
        return render_template_string(FORGOT_PASSWORD_TEMPLATE, error=None,
                                      success=f'If {email} is registered, a reset code has been sent.')
    return render_template_string(FORGOT_PASSWORD_TEMPLATE, error=None, success=None)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = request.args.get('email', '') or request.form.get('email', '')
    if not email:
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        otp = request.form.get('otp', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            return render_template_string(RESET_PASSWORD_TEMPLATE, email=email, error='Password must be at least 6 characters.')
        if password != confirm:
            return render_template_string(RESET_PASSWORD_TEMPLATE, email=email, error='Passwords do not match.')
        if verify_otp(email, otp, 'reset'):
            update_password(email, password)
            return redirect(url_for('login') + '?reset=1')
        return render_template_string(RESET_PASSWORD_TEMPLATE, email=email, error='Invalid or expired code.')
    resent = request.args.get('resent')
    return render_template_string(RESET_PASSWORD_TEMPLATE, email=email,
                                  error=None if not resent else None)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────────
# SETTINGS ROUTES
# ─────────────────────────────────────────────

@app.route('/settings')
@login_required
def settings():
    user = get_user_by_id(session['user_id'])
    daily_usage = get_daily_usage(session['user_id'])
    has_own_key = bool(user.get('gemini_api_key'))
    masked = ''
    if has_own_key:
        k = user['gemini_api_key']
        masked = k[:6] + '•' * (len(k) - 10) + k[-4:] if len(k) > 10 else '•' * len(k)
    return render_template_string(SETTINGS_TEMPLATE,
        navbar=navbar_html('settings', session['username'], daily_usage),
        daily_usage=daily_usage,
        limit=DAILY_GENERATION_LIMIT,
        has_own_key=has_own_key,
        masked_key=masked,
        message=None, message_type='success')


@app.route('/settings/update-key', methods=['POST'])
@login_required
def settings_update_key():
    api_key = request.form.get('gemini_api_key', '').strip()
    update_gemini_key(session['user_id'], api_key if api_key else None)
    user = get_user_by_id(session['user_id'])
    daily_usage = get_daily_usage(session['user_id'])
    has_own_key = bool(user.get('gemini_api_key'))
    masked = ''
    if has_own_key:
        k = user['gemini_api_key']
        masked = k[:6] + '•' * (len(k) - 10) + k[-4:] if len(k) > 10 else '•' * len(k)
    return render_template_string(SETTINGS_TEMPLATE,
        navbar=navbar_html('settings', session['username'], daily_usage),
        daily_usage=daily_usage, limit=DAILY_GENERATION_LIMIT,
        has_own_key=has_own_key, masked_key=masked,
        message='API key saved successfully!' if api_key else 'API key removed.',
        message_type='success')


@app.route('/settings/change-password', methods=['POST'])
@login_required
def settings_change_password():
    user = get_user_by_id(session['user_id'])
    daily_usage = get_daily_usage(session['user_id'])
    has_own_key = bool(user.get('gemini_api_key'))
    masked = ''
    if has_own_key:
        k = user['gemini_api_key']
        masked = k[:6] + '•' * (len(k) - 10) + k[-4:] if len(k) > 10 else '•' * len(k)

    def render(msg, t='error'):
        return render_template_string(SETTINGS_TEMPLATE,
            navbar=navbar_html('settings', session['username'], daily_usage),
            daily_usage=daily_usage, limit=DAILY_GENERATION_LIMIT,
            has_own_key=has_own_key, masked_key=masked,
            message=msg, message_type=t)

    current = request.form.get('current_password', '')
    new_pw  = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if user['password_hash'] != hash_password(current):
        return render('Current password is incorrect.')
    if len(new_pw) < 6:
        return render('New password must be at least 6 characters.')
    if new_pw != confirm:
        return render('New passwords do not match.')
    update_password(user['email'], new_pw)
    return render('Password updated successfully!', 'success')

# ─────────────────────────────────────────────
# MAIN ROUTE
# ─────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    user = get_user_by_id(session['user_id'])
    daily_usage = get_daily_usage(session['user_id'])
    has_own_key = bool(user.get('gemini_api_key'))
    return render_template_string(MAIN_TEMPLATE,
        navbar=navbar_html('home', session['username'], daily_usage),
        daily_usage=daily_usage,
        limit=DAILY_GENERATION_LIMIT,
        has_own_key=has_own_key)

# ─────────────────────────────────────────────
# AUTOMATION ROUTES
# ─────────────────────────────────────────────

def _get_automations():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM automations WHERE user_id = %s ORDER BY created_at DESC', (session['user_id'],))
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def _render_automation(success=None, error=None):
    daily_usage = get_daily_usage(session['user_id'])
    return render_template_string(AUTOMATION_TEMPLATE,
        navbar=navbar_html('automation', session['username'], daily_usage),
        automations=_get_automations(),
        message=success or error,
        message_type='success' if success else 'error')

@app.route('/automation')
@login_required
def automation():
    return _render_automation()

@app.route('/automation/create', methods=['POST'])
@login_required
def automation_create():
    raw_topics = request.form.getlist('topics[]')
    topics = [t.strip() for t in raw_topics if t.strip()]
    if not topics:
        return _render_automation(error='Please add at least one topic.')
    context = request.form.get('context', '').strip()
    email = request.form.get('email', '').strip()
    send_time = request.form.get('send_time', '08:00')[:5]
    timezone = request.form.get('timezone', 'Asia/Kolkata')
    if not email or not send_time:
        return _render_automation(error='Email and send time are required.')
    topics_str = '||'.join(topics)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO automations (user_id, topics, context, email, send_time, timezone, is_active, current_index)
                   VALUES (%s,%s,%s,%s,%s,%s,TRUE,0) RETURNING id''',
                (session['user_id'], topics_str, context, email, send_time, timezone)
            )
            auto_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    h, m = map(int, send_time.split(':'))
    schedule_automation(auto_id, h, m, timezone)
    return _render_automation(success=f'Automation saved! {len(topics)} topic{"s" if len(topics)>1 else ""} will rotate daily at {send_time} ({timezone}).')

@app.route('/automation/toggle/<int:auto_id>', methods=['POST'])
@login_required
def automation_toggle(auto_id):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM automations WHERE id=%s AND user_id=%s', (auto_id, session['user_id']))
            auto = cur.fetchone()
        if not auto:
            return redirect(url_for('automation'))
        new_status = not auto['is_active']
        with conn.cursor() as cur:
            cur.execute('UPDATE automations SET is_active=%s WHERE id=%s', (new_status, auto_id))
        conn.commit()
    finally:
        conn.close()
    if new_status:
        h, m = map(int, auto['send_time'][:5].split(':'))
        schedule_automation(auto_id, h, m, auto['timezone'])
    else:
        unschedule_automation(auto_id)
    return redirect(url_for('automation'))

@app.route('/automation/delete/<int:auto_id>', methods=['POST'])
@login_required
def automation_delete(auto_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM automations WHERE id=%s AND user_id=%s', (auto_id, session['user_id']))
        conn.commit()
    finally:
        conn.close()
    unschedule_automation(auto_id)
    return redirect(url_for('automation'))

# ─────────────────────────────────────────────
# GENERATE ROUTE  (with rate limiting + per-user key)
# ─────────────────────────────────────────────

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    user = get_user_by_id(session['user_id'])
    has_own_key = bool(user.get('gemini_api_key'))

    # Rate limit only if user doesn't have their own key
    if not has_own_key:
        daily_usage = get_daily_usage(session['user_id'])
        if daily_usage >= DAILY_GENERATION_LIMIT:
            return jsonify({'error': 'Daily limit reached. Add your own Gemini API key in Settings for unlimited use.'}), 429
    
    # Validate that we actually have an API key
    api_key_to_use = user.get('gemini_api_key') or os.environ.get("GOOGLE_API_KEY")
    if not api_key_to_use:
        return jsonify({'error': 'No API key configured. Add your Gemini API key in Settings.'}), 400

    data = request.get_json()
    topic = data.get('topic', '')
    context = data.get('context', '')

    # Use user's own key if available, else fall back to env key
    api_key = user.get('gemini_api_key') or os.environ.get("GOOGLE_API_KEY")
    os.environ["GOOGLE_API_KEY"] = api_key

    graph = build_graph()
    initial_state = {
        'topic': topic, 'context': context,
        'instagram_caption': None, 'instagram_hashtags': None,
        'linkedin_post': None, 'linkedin_article': None, 'announcement': None,
    }
    try:
        result = graph.invoke(initial_state)
        # Only count against shared key usage
        if not has_own_key:
            increment_daily_usage(session['user_id'])
        return jsonify({
            'instagram_caption': result.get('instagram_caption', ''),
            'instagram_hashtags': result.get('instagram_hashtags', []),
            'linkedin_post': result.get('linkedin_post', ''),
            'linkedin_article': result.get('linkedin_article', ''),
            'announcement': result.get('announcement', ''),
        })
    except Exception as e:
        msg = str(e)
        if '429' in msg or 'RESOURCE_EXHAUSTED' in msg or 'quota' in msg.lower():
            return jsonify({'error': 'API quota exceeded. Please wait and try again.'}), 429
        elif 'API key' in msg or 'authentication' in msg.lower():
            return jsonify({'error': 'Invalid API key. Check your Gemini key in Settings.'}), 401
        else:
            return jsonify({'error': f'Failed to generate content: {msg}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5002))
    app.run(debug=False, host='0.0.0.0', port=port)