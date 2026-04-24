from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from functools import wraps
import os
import sqlite3
import hashlib
import secrets
from dotenv import load_dotenv
from graph.orchestrator import build_graph
from scheduler import start_scheduler, schedule_automation, unschedule_automation

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
load_dotenv()

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # topics: "||"-separated list of topics
        # current_index: which topic fires next
        conn.execute('''CREATE TABLE IF NOT EXISTS automations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topics TEXT NOT NULL,
            context TEXT,
            email TEXT NOT NULL,
            send_time TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            is_active INTEGER NOT NULL DEFAULT 1,
            current_index INTEGER NOT NULL DEFAULT 0,
            last_sent TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')
        conn.commit()

init_db()
start_scheduler()

# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_by_email(email):
    with get_db() as conn:
        return conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

def get_user_by_username(username):
    with get_db() as conn:
        return conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

def create_user(username, email, password):
    with get_db() as conn:
        conn.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                     (username, email, hash_password(password)))
        conn.commit()

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
.auth-footer { text-align:center; margin-top:1.5rem; font-size:0.875rem; color:var(--text-muted); }
.auth-footer a { color:var(--primary); text-decoration:none; font-weight:500; }
.alert { padding:0.75rem 1rem; border-radius:10px; font-size:0.875rem; margin-bottom:1.25rem; }
.alert-error { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
.alert-success { background:#f0fdf4; color:#16a34a; border:1px solid #86efac; }
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
</style>'''

def navbar_html(active, username):
    return f'''
<nav class="navbar">
    <div class="container d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-4">
            <a href="/" class="navbar-brand"><i class="bi bi-rocket-takeoff"></i> Social Engine Pro</a>
            <div class="d-flex gap-1">
                <a href="/" class="nav-link-item {"active" if active=="home" else ""}"><i class="bi bi-house"></i> Home</a>
                <a href="/automation" class="nav-link-item {"active" if active=="automation" else ""}"><i class="bi bi-clock-history"></i> Automation</a>
            </div>
        </div>
        <div class="nav-user">
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
    <form method="POST" action="/login">
        <div class="form-group"><label>Email</label><input type="email" name="email" placeholder="you@example.com" required></div>
        <div class="form-group"><label>Password</label><input type="password" name="password" placeholder="••••••••" required></div>
        <button type="submit" class="btn-auth">Sign In</button>
    </form>
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
@media(max-width:768px){.sidebar-card{position:static;margin-bottom:2rem;}}
</style></head><body>
{{ navbar | safe }}
<div class="main-container"><div class="container"><div class="row">
    <div class="col-lg-4 mb-4">
        <div class="sidebar-card">
            <h5 class="sidebar-title"><i class="bi bi-sliders"></i> Content Inputs</h5>
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
        if (!response.ok) throw new Error(result.error || `Server error: ${response.status}`);
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
# AUTOMATION PAGE TEMPLATE
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

/* Topic list builder */
.topic-list { display:flex; flex-direction:column; gap:0.5rem; margin-bottom:0.75rem; }
.topic-row { display:flex; align-items:center; gap:0.5rem; }
.topic-row input { flex:1; padding:0.6rem 0.875rem; border:1.5px solid var(--border); border-radius:8px; font-size:0.875rem; font-family:'Inter',sans-serif; outline:none; }
.topic-row input:focus { border-color:#4f46e5; }
.btn-remove-topic { background:#fef2f2; border:1px solid #fca5a5; color:#dc2626; border-radius:8px; padding:0.5rem 0.75rem; cursor:pointer; font-size:0.8rem; transition:all 0.2s; flex-shrink:0; }
.btn-remove-topic:hover { background:#dc2626; color:white; }
.btn-add-topic { background:#f0f9ff; border:1px solid #bae6fd; color:#0369a1; border-radius:8px; padding:0.5rem 1rem; cursor:pointer; font-size:0.85rem; font-weight:500; transition:all 0.2s; font-family:'Inter',sans-serif; }
.btn-add-topic:hover { background:#0369a1; color:white; }
.topic-hint { font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem; }

/* Automation list */
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

    <!-- Create Automation -->
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

    <!-- Existing Automations -->
    <div class="card">
        <div class="card-title"><i class="bi bi-list-check" style="color:#4f46e5;"></i> Your Automations</div>
        {% if automations %}
            {% for a in automations %}
            {% if 'topics' in a and a['topics'] %}
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
                </div>
            {% else %}
                <div class="auto-item">
                    <div class="auto-info">No topics set for this automation.</div>
                </div>
            {% endif %}
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
        if user and user['password_hash'] == hash_password(password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        return render_template_string(LOGIN_TEMPLATE, error='Invalid email or password.', success=None)
    success_msg = request.args.get('registered')
    return render_template_string(LOGIN_TEMPLATE, error=None,
                                  success='Account created! Please sign in.' if success_msg else None)

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
        return redirect(url_for('login') + '?registered=1')
    return render_template_string(SIGNUP_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────────
# MAIN ROUTE
# ─────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    username = session.get('username')
    return render_template_string(MAIN_TEMPLATE, navbar=navbar_html('home', username))

# ─────────────────────────────────────────────
# AUTOMATION ROUTES
# ─────────────────────────────────────────────

def _get_automations():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM automations WHERE user_id = ? ORDER BY created_at DESC',
            (session['user_id'],)
        ).fetchall()
        return [dict(row) for row in rows]

def _render_automation(success=None, error=None):
    username = session.get('username')
    return render_template_string(AUTOMATION_TEMPLATE,
                                  navbar=navbar_html('automation', username),
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
    # Collect topic list and join with || separator
    raw_topics = request.form.getlist('topics[]')
    topics = [t.strip() for t in raw_topics if t.strip()]

    if not topics:
        return _render_automation(error='Please add at least one topic.')

    context = request.form.get('context', '').strip()
    email = request.form.get('email', '').strip()
    send_time = request.form.get('send_time', '08:00')
    timezone = request.form.get('timezone', 'Asia/Kolkata')

    if not email or not send_time:
        return _render_automation(error='Email and send time are required.')

    topics_str = '||'.join(topics)

    with get_db() as conn:
        cursor = conn.execute(
            'INSERT INTO automations (user_id, topics, context, email, send_time, timezone, is_active, current_index) VALUES (?,?,?,?,?,?,1,0)',
            (session['user_id'], topics_str, context, email, send_time, timezone)
        )
        conn.commit()
        auto_id = cursor.lastrowid

    h, m = map(int, send_time.split(':'))
    schedule_automation(auto_id, h, m, timezone)

    return _render_automation(
        success=f'Automation saved! {len(topics)} topic{"s" if len(topics)>1 else ""} will rotate daily at {send_time} ({timezone}).'
    )

@app.route('/automation/toggle/<int:auto_id>', methods=['POST'])
@login_required
def automation_toggle(auto_id):
    with get_db() as conn:
        auto = conn.execute('SELECT * FROM automations WHERE id=? AND user_id=?',
                            (auto_id, session['user_id'])).fetchone()
        if not auto:
            return redirect(url_for('automation'))
        new_status = 0 if auto['is_active'] else 1
        conn.execute('UPDATE automations SET is_active=? WHERE id=?', (new_status, auto_id))
        conn.commit()

    if new_status == 1:
        h, m = map(int, auto['send_time'].split(':'))
        schedule_automation(auto_id, h, m, auto['timezone'])
    else:
        unschedule_automation(auto_id)
    return redirect(url_for('automation'))

@app.route('/automation/delete/<int:auto_id>', methods=['POST'])
@login_required
def automation_delete(auto_id):
    with get_db() as conn:
        conn.execute('DELETE FROM automations WHERE id=? AND user_id=?',
                     (auto_id, session['user_id']))
        conn.commit()
    unschedule_automation(auto_id)
    return redirect(url_for('automation'))

# ─────────────────────────────────────────────
# GENERATE ROUTE
# ─────────────────────────────────────────────

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    data = request.get_json()
    topic = data.get('topic', '')
    context = data.get('context', '')
    graph = build_graph()
    initial_state = {
        'topic': topic, 'context': context,
        'instagram_caption': None, 'instagram_hashtags': None,
        'linkedin_post': None, 'linkedin_article': None, 'announcement': None,
    }
    try:
        result = graph.invoke(initial_state)
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
            return jsonify({'error': 'Invalid API key. Check your GOOGLE_API_KEY in .env.'}), 401
        else:
            return jsonify({'error': f'Failed to generate content: {msg}'}), 500

if __name__ == '__main__':
        port = int(os.environ.get("PORT", 5002))
        app.run(debug=False, host='0.0.0.0', port=port)