r"""
=============================================================================
  TECHNO COMMUNICATIONS - COMPLIANCE DATA WEBSITE
  -----------------------------------------------------------------
  A tiny local website that lets anyone:
     • pick a single market (or ALL markets)
     • choose a date range
     • click "Get Compliance Data"
     • download the generated CSV

  Run:   python web_app.py
  Open:  http://127.0.0.1:5000

  Needs credentials.json in this same folder (same one your importer uses).
=============================================================================
"""

import os
import threading
import traceback
from datetime import date, datetime, timedelta

from flask import (Flask, render_template, jsonify, request,
                   send_file, abort, Response)

import compliance_core as core

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---- optional password gate -------------------------------------------------
# When APP_PASSWORD is set (e.g. on Render), the whole site requires a password
# via the browser's built-in login prompt. Any username works; the password
# must match. Locally, leave it unset and there's no prompt.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()


@app.before_request
def _require_password():
    if not APP_PASSWORD:
        return
    auth = request.authorization
    if auth and auth.password == APP_PASSWORD:
        return
    return Response(
        "Login required.", 401,
        {"WWW-Authenticate": 'Basic realm="Techno Communications Compliance Data"'},
    )

# ---- single global job (this is a local, single-user tool) ------------------
JOB = {
    "state":    "idle",     # idle | running | done | error
    "pct":      0,
    "message":  "",
    "started":  None,
    "result":   None,       # dict from core.generate_compliance_csv
    "error":    None,
}
JOB_LOCK = threading.Lock()


def _set(**kw):
    with JOB_LOCK:
        JOB.update(kw)


def _progress(pct, message):
    _set(pct=pct, message=message)


def _run_job(markets, range_start, range_end):
    try:
        result = core.generate_compliance_csv(
            selected_markets=markets,
            range_start=range_start,
            range_end=range_end,
            on_progress=_progress,
        )
        _set(state="done", pct=100, message="Done", result=result, error=None)
    except Exception as e:
        traceback.print_exc()
        _set(state="error", message=str(e), error=str(e))


# ---- routes -----------------------------------------------------------------

@app.route("/")
def index():
    today = date.today()
    default_from = (today - timedelta(days=13)).isoformat()
    default_to   = today.isoformat()
    return render_template(
        "index.html",
        markets=core.ALL_MARKET_NAMES,
        default_from=default_from,
        default_to=default_to,
    )


@app.route("/api/markets")
def api_markets():
    return jsonify({"markets": core.ALL_MARKET_NAMES})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    with JOB_LOCK:
        if JOB["state"] == "running":
            return jsonify({"error": "A pull is already running. Please wait."}), 409

    data   = request.get_json(silent=True) or {}
    market = (data.get("market") or "").strip()
    d_from = (data.get("from") or "").strip()
    d_to   = (data.get("to") or "").strip()

    if not market:
        return jsonify({"error": "Please select a market."}), 400

    try:
        range_start = datetime.strptime(d_from, "%Y-%m-%d").date()
        range_end   = datetime.strptime(d_to, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "Please choose valid From and To dates."}), 400

    if range_end < range_start:
        return jsonify({"error": "'To' date must be on or after 'From' date."}), 400

    if market.upper() == "ALL":
        markets = ["ALL"]
    elif market in core.ALL_MARKET_NAMES:
        markets = [market]
    else:
        return jsonify({"error": f"Unknown market: {market}"}), 400

    _set(state="running", pct=0, message="Starting…",
         started=datetime.now().isoformat(), result=None, error=None)

    t = threading.Thread(
        target=_run_job, args=(markets, range_start, range_end), daemon=True
    )
    t.start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with JOB_LOCK:
        payload = {
            "state":   JOB["state"],
            "pct":     JOB["pct"],
            "message": JOB["message"],
        }
        if JOB["state"] == "done" and JOB["result"]:
            r = JOB["result"]
            payload["result"] = {
                "filename": r["filename"],
                "sheets":   r["sheets"],
                "rows":     r["rows"],
                "markets":  r["markets"],
            }
        if JOB["state"] == "error":
            payload["error"] = JOB["error"]
    return jsonify(payload)


@app.route("/api/download")
def api_download():
    with JOB_LOCK:
        result = JOB["result"]
    if not result:
        abort(404, "Nothing to download yet.")
    path = result["csv_path"]
    if not os.path.exists(path):
        abort(404, "The generated file is missing on disk.")
    return send_file(path, as_attachment=True,
                     download_name=result["filename"],
                     mimetype="text/csv")


if __name__ == "__main__":
    # Local dev server. On Render, gunicorn runs the app instead (see Procfile),
    # so this block is only used when you run `python web_app.py` on your PC.
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  Techno Communications — Compliance Data website")
    print(f"  Open  ->  http://127.0.0.1:{port}")
    print("  Stop  ->  Ctrl + C")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
