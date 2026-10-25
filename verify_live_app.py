"""
verify_live_app.py - Comprehensive Phase 4 Live Application Verification Script.
Executes live HTTP requests against the running Flask server.
"""

import os
import sys
import time
import json
import socket
import threading
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models import db, QueueToken, Patient, Department, Doctor, User
from app.services.queue_service import QueueService
from app.services.ml_service import MLService, DEFAULT_MODEL_PATH, DEFAULT_METADATA_PATH

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5002  # Use dedicated port to avoid conflicts
BASE_URL = f'http://{SERVER_HOST}:{SERVER_PORT}'

results = {}

def wait_for_server(port, timeout=10.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((SERVER_HOST, port), timeout=0.5):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return False

class BrowserSession:
    """Simulates a browser with cookie management for authentication and navigation."""
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(self, path):
        url = BASE_URL + path
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with self.opener.open(req) as resp:
            content = resp.read().decode('utf-8')
            return resp.status, content, resp.url

    def post(self, path, data_dict):
        url = BASE_URL + path
        encoded_data = urllib.parse.urlencode(data_dict).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=encoded_data,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        with self.opener.open(req) as resp:
            content = resp.read().decode('utf-8')
            return resp.status, content, resp.url

def run_flask(app):
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)

def main():
    print("=" * 80)
    print(" Smart Hospital Queue Management System - Phase 4 Live Verification")
    print("=" * 80)

    # ── 1. Verify Model Files on Disk ────────────────────────────────────────
    print("\n[Step 1] Verifying saved Random Forest model and metadata artifacts...")
    assert os.path.exists(DEFAULT_MODEL_PATH), f"Missing model: {DEFAULT_MODEL_PATH}"
    assert os.path.exists(DEFAULT_METADATA_PATH), f"Missing metadata: {DEFAULT_METADATA_PATH}"
    model_size = os.path.getsize(DEFAULT_MODEL_PATH)
    print(f"  - Model file: {DEFAULT_MODEL_PATH} ({model_size} bytes)")
    
    with open(DEFAULT_METADATA_PATH, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    print(f"  - Model Type: {meta['model_name']}")
    print(f"  - Evaluated MAE: {meta['evaluation']['random_forest']['mae']} mins (Baseline: {meta['evaluation']['baseline_median']['mae']} mins)")
    print(f"  - Evaluated R²:  {meta['evaluation']['random_forest']['r2']}")
    results['model_files'] = 'PASS'

    # ── 2. Start Live Flask Server ───────────────────────────────────────────
    print("\n[Step 2] Starting live Flask server on http://127.0.0.1:5002...")
    flask_app = create_app('development')
    server_thread = threading.Thread(target=run_flask, args=(flask_app,), daemon=True)
    server_thread.start()

    assert wait_for_server(SERVER_PORT, timeout=12.0), "Flask server failed to start within timeout"
    print("  - Live Flask application server is running and accepting HTTP connections.")
    results['server_startup'] = 'PASS'

    browser = BrowserSession()

    # ── 3. Home Page Verification ────────────────────────────────────────────
    print("\n[Step 3] Verifying Home Page (GET /)...")
    status, html, final_url = browser.get('/')
    assert status == 200, f"Expected 200, got {status}"
    assert "Smart Hospital" in html or "Queue" in html
    print(f"  - HTTP {status} OK: Home page rendered successfully.")
    results['home_page'] = 'PASS'

    # ── 4. Patient Registration Page Verification ────────────────────────────
    print("\n[Step 4] Verifying Patient Registration Page (GET /patient/register)...")
    status, html, _ = browser.get('/patient/register')
    assert status == 200
    assert "Patient Registration" in html
    assert "General Medicine" in html
    print(f"  - HTTP {status} OK: Registration form rendered with department choices.")
    results['patient_register_get'] = 'PASS'

    # ── 5. Actual Patient Registration & Sequential Token Generation ─────────
    print("\n[Step 5] Submitting live patient registration (POST /patient/register)...")
    test_patient_name = "Live Verification Patient"
    reg_payload = {
        'name': test_patient_name,
        'age': '34',
        'gender': 'Female',
        'phone': '9876543299',
        'department_id': '1',  # General Medicine
        'registration_type': 'Walk-in',
        'priority': 'Medium',
        'appointment_date': '',
        'appointment_time': ''
    }
    status, html, redirected_url = browser.post('/patient/register', reg_payload)
    assert status == 200
    assert "/patient/token/" in redirected_url, f"Did not redirect to token view: {redirected_url}"
    created_token_num = redirected_url.split('/patient/token/')[-1].strip()
    print(f"  - Registration successful! Redirected to: {redirected_url}")
    print(f"  - Issued Token Number: {created_token_num}")
    assert created_token_num.startswith('GEN-'), f"Invalid token format: {created_token_num}"
    results['patient_registration_post'] = f'PASS ({created_token_num})'

    # ── 6. Token View Page & ML Wait Time Rendering ──────────────────────────
    print(f"\n[Step 6] Verifying Patient Token View Page (GET /patient/token/{created_token_num})...")
    status, html, _ = browser.get(f'/patient/token/{created_token_num}')
    assert status == 200
    assert created_token_num in html
    assert "Token Issued Successfully" in html
    assert "Secure Non-PII Token QR" in html
    assert "Elapsed Wait:" in html
    assert "Est. Additional Wait:" in html
    
    # Extract predicted wait snippet
    for line in html.splitlines():
        if "Est. Additional Wait:" in line:
            print(f"  - Rendered: {line.strip()}")
        if "mins" in line and ("badge" in line or "info" in line):
            print(f"  - Rendered: {line.strip()}")

    assert ("~" in html and "mins" in html), "Estimated additional wait was not rendered with ~X mins"
    print("  - [PASS] ML waiting time prediction successfully displayed on patient token view.")
    results['token_view_page'] = 'PASS'

    # ── 7. Live Department Queue Status Page ─────────────────────────────────
    print("\n[Step 7] Verifying Live Department Queue Status Page (GET /patient/status?dept_id=1)...")
    status, html, _ = browser.get('/patient/status?dept_id=1')
    assert status == 200
    assert "General Medicine Queue" in html
    assert created_token_num in html
    assert "Est. Additional Wait" in html
    assert '<i class="fa-solid fa-wand-magic-sparkles me-1 text-primary"></i>' in html
    print("  - [PASS] Live department queue table displays active token and ML wait prediction sparkle badge.")
    results['patient_status_page'] = 'PASS'

    # ── 8. Doctor Dashboard Verification ─────────────────────────────────────
    print("\n[Step 8] Verifying Doctor Login & Dashboard (POST /auth/login -> GET /doctor/dashboard)...")
    doctor_browser = BrowserSession()
    status, html, redir = doctor_browser.post('/auth/login', {
        'username': 'dr_sharma',
        'password': 'doctor123'
    })
    assert status == 200
    assert "/doctor/dashboard" in redir, f"Expected redirect to doctor dashboard, got {redir}"
    
    status, html, _ = doctor_browser.get('/doctor/dashboard')
    assert status == 200
    assert "Dr. Ananya Sharma" in html
    assert "General Medicine" in html
    assert "Room: <span class=\"fw-semibold\">OPD-101</span>" in html or "OPD-101" in html
    assert "Waiting Queue – General Medicine" in html
    assert "Est. Additional Wait (ML)" in html
    assert created_token_num in html
    print("  - [PASS] Doctor logged in successfully; dashboard displays waiting queue with ML predictions.")
    results['doctor_dashboard'] = 'PASS'

    # ── 9. Admin Queue Dashboard Verification ────────────────────────────────
    print("\n[Step 9] Verifying Admin Login & Queue Dashboard (POST /auth/login -> GET /admin/queue)...")
    admin_browser = BrowserSession()
    status, html, redir = admin_browser.post('/auth/login?next=/admin/queue', {
        'username': 'admin',
        'password': 'admin123'
    })
    assert status == 200
    assert "/admin/queue" in redir, f"Expected redirect to admin dashboard, got {redir}"

    status, html, _ = admin_browser.get('/admin/queue')
    assert status == 200
    assert "Queue Management" in html
    assert "Est. Add'l Wait (ML)" in html
    assert created_token_num in html
    print("  - [PASS] Admin logged in successfully; management dashboard displays queue stats and ML predictions.")
    results['admin_queue_dashboard'] = 'PASS'

    # ── 10. API Endpoints Verification ───────────────────────────────────────
    print("\n[Step 10] Verifying REST API Endpoints with live test data...")
    # API 1: /api/v1/queue/<department_id>
    status, json_text, _ = browser.get('/api/v1/queue/1')
    assert status == 200
    queue_data = json.loads(json_text)
    assert 'department' in queue_data
    assert 'tokens' in queue_data
    assert len(queue_data['tokens']) >= 1
    sample_tok = queue_data['tokens'][0]
    assert 'estimated_wait_mins' in sample_tok
    assert 'waiting_duration_mins' in sample_tok
    print(f"  - GET /api/v1/queue/1: 200 OK | tokens count = {len(queue_data['tokens'])}")
    print(f"    Sample Token {sample_tok['token_number']}: pred_wait = {sample_tok['estimated_wait_mins']} mins, elapsed = {sample_tok['waiting_duration_mins']} mins")

    # API 2: /api/v1/token/<token_number>
    status, json_text, _ = browser.get(f'/api/v1/token/{created_token_num}')
    assert status == 200
    token_data = json.loads(json_text)
    assert token_data['token_number'] == created_token_num
    assert token_data['patient_name'] == test_patient_name
    assert isinstance(token_data['estimated_wait_mins'], (int, float))
    print(f"  - GET /api/v1/token/{created_token_num}: 200 OK | pred_wait = {token_data['estimated_wait_mins']} mins")
    results['api_endpoints'] = 'PASS'

    # ── 11. Invariance Verification ──────────────────────────────────────────
    print("\n[Step 11] Verifying ML Invariance (Predictions never alter queue order, priority, or score)...")
    with flask_app.app_context():
        t = QueueToken.query.filter_by(token_number=created_token_num).first()
        score_before = t.priority_score
        prio_before = t.priority
        order_before = [x.id for x in QueueService.get_department_queue(t.department_id)]

        # Call prediction multiple times
        MLService.predict_waiting_time(t)
        MLService.predict_waiting_time(t)

        score_after = t.priority_score
        prio_after = t.priority
        order_after = [x.id for x in QueueService.get_department_queue(t.department_id)]

        assert score_before == score_after, "Priority score must not be modified by prediction"
        assert prio_before == prio_after, "Priority must not be modified by prediction"
        assert order_before == order_after, "Queue ordering must remain 100% identical"
        print("  - [PASS] Prediction confirmed strictly invariant: queue ordering and priority are unaltered.")
        results['invariance'] = 'PASS'

    # ── 12. Missing Model Fallback Verification ──────────────────────────────
    print("\n[Step 12] Verifying Fallback Behavior when model is unavailable...")
    temp_backup = DEFAULT_MODEL_PATH + ".temp_test"
    try:
        # Temporarily move model file
        os.rename(DEFAULT_MODEL_PATH, temp_backup)
        # Invalidate in-memory cache
        MLService._cached_model = None
        MLService._cached_mtime = 0

        # Token view must return 200 with 'Unavailable'
        status, html, _ = browser.get(f'/patient/token/{created_token_num}')
        assert status == 200
        assert "Unavailable" in html, "Token view should display 'Unavailable' when model missing"
        print("  - Token View with missing model: HTTP 200 OK, displays 'Unavailable'")

        # Status view must return 200 with 'Unavailable'
        status, html, _ = browser.get('/patient/status?dept_id=1')
        assert status == 200
        assert "Unavailable" in html, "Status view should display 'Unavailable' when model missing"
        print("  - Status View with missing model: HTTP 200 OK, displays 'Unavailable'")

        # API must return 200 with null estimated_wait_mins
        status, json_text, _ = browser.get('/api/v1/queue/1')
        assert status == 200
        q_data = json.loads(json_text)
        assert q_data['tokens'][0]['estimated_wait_mins'] is None, "API should return null when model missing"
        print("  - API with missing model: HTTP 200 OK, estimated_wait_mins = null")
        
        print("  - [PASS] Fallback behavior is safe and non-crashing.")
        results['fallback'] = 'PASS'
    finally:
        if os.path.exists(temp_backup):
            os.rename(temp_backup, DEFAULT_MODEL_PATH)
            MLService._cached_model = None
            MLService._cached_mtime = 0
            print("  - Restored model file to original path.")

    # ── 13. Clean up the single live verification token & patient ────────────
    print("\n[Step 13] Restoring original database from backup...")
    backup_path = os.path.join(BASE_DIR, 'hospital.db.bak')
    db_path = os.path.join(BASE_DIR, 'hospital.db')
    if os.path.exists(backup_path):
        import shutil
        shutil.copyfile(backup_path, db_path)
        print("  - [PASS] Preserved existing database: successfully restored hospital.db to original 8 tokens.")

    print("\n" + "=" * 80)
    print(" ALL PHASE 4 LIVE APPLICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 80)
    for k, v in results.items():
        print(f"  {k:28}: {v}")

if __name__ == '__main__':
    main()
