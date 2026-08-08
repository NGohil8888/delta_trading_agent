import json
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from datetime import datetime

import engine
import diagnostics

# index.html lives next to this file rather than in a templates/ folder,
# so point Flask's template loader at the current directory.
app = Flask(__name__, template_folder='.')
STATUS_FILE = Path(__file__).resolve().parent / 'status.json'
AGENT_CAPABILITIES = [
    "Scans multiple Delta markets",
    "Builds structured trade ideas",
    "Creates research notes and strategy files",
    "Runs autonomous scan cycles",
    "Chats using the full AGENTS.md ruleset",
    "Operates in testnet-first mode",
]

# Lazily-constructed process-wide agent.
#
# Why lazy and not a module-level global:
#   - Constructing TradingAgent() reads .env, makes the Ollama client, and
#     touches disk (workspace dirs, status.json). Doing that at import time
#     means `import dashboard` (e.g. from tests, REPLs, or one-off scripts)
#     has a side effect you can't undo -- and tests have to either patch the
#     whole TradingAgent or work around the live network calls.
#   - The old per-request pattern (TradingAgent() per Flask request) wiped
#     in-memory state (daily_trades, pending_trade, failure_count) on every
#     request, so a chat message could clear a pending trade mid-confirm.
#   - The test suite already expects `_get_agent` to be patchable; that's
#     the contract we expose here. Callers go through `_get_agent()` so they
#     can be unit-tested with a MagicMock, but the real process still gets
#     one shared instance.
_AGENT_SINGLETON: "engine.TradingAgent | None" = None


def _get_agent() -> "engine.TradingAgent":
    """Return the process-wide TradingAgent, constructing it on first use."""
    global _AGENT_SINGLETON
    if _AGENT_SINGLETON is None:
        _AGENT_SINGLETON = engine.TradingAgent()
    return _AGENT_SINGLETON


def _reset_agent_for_tests() -> None:
    """Drop the cached singleton. Intended for test isolation only."""
    global _AGENT_SINGLETON
    _AGENT_SINGLETON = None


def _default_state_payload():
    return {
        "status": "Monitoring",
        "message": "Agent is connected and monitoring the market.",
        "mode": "testnet",
        "daily_trades": 0,
        "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "balance": "Connected",
            "equity": "0.00",
            "pnl": "0.00",
            "status": "Monitoring",
            "message": "Agent is connected and monitoring the market.",
            "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "daily_trades": 0,
        },
        "logs": [
            {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": "SYSTEM",
                "message": "Dashboard state initialized successfully.",
            }
        ],
        "capabilities": AGENT_CAPABILITIES,
        "delta_connected": None,
        "delta_detail": "Not checked yet.",
        "ideas": [],
        "pending_trade": None,
    }


def load_dashboard_state():
    if not STATUS_FILE.exists():
        payload = _default_state_payload()
        STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return payload

    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:
        payload = _default_state_payload()
        STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return payload

    summary = data.get('summary', {}) if isinstance(data.get('summary', {}), dict) else {}
    logs = data.get('logs', []) if isinstance(data.get('logs', []), list) else []
    account = data.get('account', {}) if isinstance(data.get('account', {}), dict) else {}
    balance_value = (
        data.get('balance')
        or account.get('balance')
        or summary.get('balance')
        or account.get('available_balance')
        or 'Connected'
    )
    status_value = data.get('status') or summary.get('status') or 'Monitoring'
    message_value = data.get('message') or summary.get('message') or 'Agent is connected and monitoring the market.'
    last_scan_value = data.get('last_scan') or summary.get('last_scan') or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    daily_trades = data.get('daily_trades', summary.get('daily_trades', 0))
    delta_connected = data.get('delta_connected')
    delta_detail = data.get('delta_detail') or ''

    payload = {
        "summary": {
            "balance": balance_value,
            "equity": summary.get('equity') or data.get('equity') or '0.00',
            "pnl": summary.get('pnl') or data.get('pnl') or '0.00',
            "status": status_value,
            "message": message_value,
            "last_scan": last_scan_value,
            "daily_trades": daily_trades,
        },
        "logs": logs[-20:],
        "capabilities": data.get('capabilities', AGENT_CAPABILITIES),
        "status": status_value,
        "message": message_value,
        "last_scan": last_scan_value,
        "mode": data.get('mode', 'testnet'),
        "delta_connected": delta_connected,
        "delta_detail": delta_detail,
        "ideas": data.get('ideas', []),
        "pending_trade": _get_agent()._pending_dict(),
    }

    return payload


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def get_status():
    return jsonify(load_dashboard_state())


@app.route('/api/log', methods=['POST'])
def add_log():
    payload = request.get_json(silent=True) or {}
    _get_agent().log_event(payload.get("message", "No message"), payload.get("type", "INFO"))
    return jsonify({"status": "ok"})


@app.route('/api/pending')
def pending():
    return jsonify({"pending_trade": _get_agent()._pending_dict()})


@app.route('/api/confirm', methods=['POST'])
def confirm_route():
    # place_order() inside _confirm_pending() makes a real HTTP call to
    # Delta. If that raises (timeout, connection error, malformed JSON
    # response) this used to propagate straight out of the route as an
    # unhandled 500 with nothing logged -- the pending trade would just
    # silently stop responding to confirm clicks. /api/chat already guards
    # against this; this route needs the same guard.
    try:
        reply = _get_agent()._confirm_pending()
    except Exception as exc:
        _get_agent().handle_failure("confirm route", exc)
        reply = f"Something went wrong confirming that trade ({exc}). It's been logged for review."
    _get_agent().log_event(reply, "AGENT")
    return jsonify({"reply": reply, "pending_trade": _get_agent()._pending_dict()})


@app.route('/api/cancel', methods=['POST'])
def cancel_route():
    try:
        reply = _get_agent()._cancel_pending()
    except Exception as exc:
        _get_agent().handle_failure("cancel route", exc)
        reply = f"Something went wrong cancelling that trade ({exc}). It's been logged for review."
    _get_agent().log_event(reply, "AGENT")
    return jsonify({"reply": reply, "pending_trade": _get_agent()._pending_dict()})


@app.route('/api/ideas')
def ideas_route():
    return jsonify({"ideas": _get_agent().load_ideas_history()})


@app.route('/api/journal')
def journal_route():
    path = engine.WORKSPACE_DIR / "notes" / "agent_journal.md"
    if not path.exists():
        return jsonify({"journal": ""})
    text = path.read_text(encoding="utf-8")
    entries = text.split("\n\n")
    return jsonify({"journal": "\n\n".join(entries[-15:])})


@app.route('/api/diagnostics')
def diagnostics_route():
    """Read-only connectivity + integrity check. Never writes/deletes/trades."""
    findings = diagnostics.run_diagnostics(verbose=False)
    bugs = [f for f in findings if not f["ok"] and f["severity"] in ("error", "critical")]
    warnings = [f for f in findings if not f["ok"] and f["severity"] == "warning"]
    return jsonify({
        "findings": findings,
        "bug_count": len(bugs),
        "warning_count": len(warnings),
        "healthy": len(bugs) == 0,
    })


@app.route('/api/workspace')
def workspace_route():
    """List files the autonomous agent has created, scoped to workspace/."""
    subdir = request.args.get('subdir', '')
    try:
        files = _get_agent().list_workspace_files(subdir)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"files": files})


_AUTONOMOUS_THREAD_STARTED = False


def _maybe_start_autonomous_loop() -> None:
    """Start the heartbeat/autonomous background thread once, if
    AUTONOMOUS_MODE=true in .env. This only ever scans/proposes/journals
    (via TradingAgent.run_forever -> autonomous_cycle) -- it never calls
    _confirm_pending, so it cannot place a trade without a human explicitly
    confirming one, regardless of how long it runs unattended.
    """
    global _AUTONOMOUS_THREAD_STARTED
    if _AUTONOMOUS_THREAD_STARTED or not engine.AUTONOMOUS_MODE:
        return
    _AUTONOMOUS_THREAD_STARTED = True
    agent = _get_agent()
    agent.log_event(
        f"Autonomous mode enabled (interval={engine.AUTONOMOUS_INTERVAL_SECONDS}s). "
        "Starting background heartbeat/scan loop.",
        "SYSTEM",
    )
    thread = threading.Thread(target=agent.run_forever, daemon=True, name="autonomous-loop")
    thread.start()


_maybe_start_autonomous_loop()


@app.route('/api/chat', methods=['POST'])
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', '').strip()
    if not message:
        return jsonify({"reply": "Please enter a message.", "pending_trade": _get_agent()._pending_dict()})

    _get_agent().log_event(message, "USER")

    try:
        result = _get_agent().agent_respond(message)
    except Exception as exc:
        _get_agent().handle_failure("chat handling", exc)
        result = {"reply": f"Something went wrong: {exc}", "pending_trade": _get_agent()._pending_dict()}

    _get_agent().log_event(result.get("reply", ""), "AGENT")
    return jsonify(result)


if __name__ == '__main__':
    app.run(port=5000, debug=True, use_reloader=False)