import re
import json
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder='.')
CORS(app)

IPS_BASE = "https://ipsexp.com/ips"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://ipsexp.com/ips/en/track",
    "Origin": "https://ipsexp.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), "mappings.json")
ADMIN_PASSWORD = "admin123"   # Change this to something secret

SCRUB = [
    (r'\bIPS\s+', ''),
    (r'\bIPS\b', ''),
]

def clean(text):
    if not text:
        return text
    for pattern, replacement in SCRUB:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip()

def load_mappings():
    if not os.path.exists(MAPPINGS_FILE):
        return {}
    with open(MAPPINGS_FILE, "r") as f:
        return json.load(f)

def save_mappings(m):
    with open(MAPPINGS_FILE, "w") as f:
        json.dump(m, f, indent=2)


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')


# ── Tracking API ──────────────────────────────────────────────────────────────

@app.route('/api/track')
def track():
    no = request.args.get('no', '').strip()
    if not no:
        return jsonify({"success": False, "message": "Please provide a tracking number."}), 400

    # Resolve alias → real IPS tracking number
    mappings = load_mappings()
    display_id = no                        # what the customer sees
    real_no    = mappings.get(no, no)      # real IPS number (falls back to what was entered)

    try:
        r1 = requests.get(
            f"{IPS_BASE}/cms/orderInfo/getTracks",
            params={"no": real_no, "languageId": 1},
            headers=HEADERS,
            timeout=12
        )
        data = r1.json()

        if data.get("code") != 0:
            return jsonify({"success": False, "message": data.get("enMsg") or "Failed to fetch tracking info."}), 502

        order = data.get("data", {})
        if not order.get("orderNo"):
            return jsonify({"success": False, "message": "No tracking information found for this ID."}), 404

        raw_traces = order.get("traces") or []

        location_map = {}
        for node in (order.get("traceNodes") or []):
            node_traces = node.get("traces") or []
            loc = clean(node.get("serverSiteEnName") or node.get("serverSiteName") or "")
            for t in node_traces:
                location_map[t.get("id")] = loc

        traces = []
        for t in raw_traces:
            desc = clean(t.get("nodeEnDescription") or t.get("nodeDescription") or "")
            loc  = location_map.get(t.get("id"), "")
            traces.append({"time": t.get("createDateTime"), "description": desc, "location": loc})

        return jsonify({
            "success": True,
            "orderNo": display_id,          # show alias, not real IPS number
            "origin": order.get("startSecondEnName") or order.get("startSecondName", ""),
            "destination": order.get("endSecondEnName") or order.get("endSecondName", ""),
            "traces": traces,
        })

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "Request timed out. Please try again."}), 504
    except Exception as e:
        app.logger.exception("Track error")
        return jsonify({"success": False, "message": f"Server error: {e}"}), 500


# ── Admin API (password-protected) ───────────────────────────────────────────

def check_auth():
    pwd = request.headers.get("X-Admin-Password") or request.args.get("pwd", "")
    return pwd == ADMIN_PASSWORD

@app.route('/api/admin/mappings', methods=['GET'])
def get_mappings():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_mappings())

@app.route('/api/admin/mappings', methods=['POST'])
def add_mapping():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    body = request.json or {}
    alias   = (body.get("alias") or "").strip()
    real_id = (body.get("realId") or "").strip()
    if not alias or not real_id:
        return jsonify({"error": "Both alias and realId are required."}), 400
    m = load_mappings()
    m[alias] = real_id
    save_mappings(m)
    return jsonify({"success": True, "alias": alias, "realId": real_id})

@app.route('/api/admin/mappings/<alias>', methods=['DELETE'])
def delete_mapping(alias):
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    m = load_mappings()
    if alias not in m:
        return jsonify({"error": "Alias not found."}), 404
    del m[alias]
    save_mappings(m)
    return jsonify({"success": True})


if __name__ == '__main__':
    print("Starting shipment tracking server on http://localhost:8080")
    print("Admin panel: http://localhost:8080/admin")
    app.run(debug=False, port=8080)
