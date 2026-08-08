"""
agent/state_store.py -- StateMixin: everything that reads/writes on-disk
state (status.json, workspace/notes/agent_journal.md, ideas_history.json)
and the locks that make concurrent access to them safe.
"""
import json
import os
import threading
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent import config
from agent.models import TradeIdea


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON to ``path`` atomically (write-temp, then os.replace).

    Without this, a crash or a concurrent reader mid-write can leave the
    file half-written and unparseable. os.replace is atomic on Windows
    and POSIX so the existing file is always either the old contents or
    the new contents, never a mix.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class StateMixin:
    # Single process-wide lock for every read-modify-write of the on-disk
    # state files. Without this, two threads (chat + dashboard poll) can
    # interleave and produce unparseable JSON.
    _state_lock = threading.Lock()
    # Guards the read-then-clear of pending_trade in _confirm_pending/
    # _cancel_pending. Without this, two near-simultaneous confirm calls
    # (double-click, a retried request, two browser tabs) can both read the
    # same pending idea before either clears it, and both call place_order.
    _trade_lock = threading.Lock()

    def _maybe_reset_daily_counters(self) -> None:
        """Zero the daily counter when the calendar date has changed.

        Without this, a long-running agent (or a process that survives a
        restart) keeps the previous day's trade count and the daily limit
        becomes a one-time-only limit for the lifetime of the process.
        """
        today = date.today().isoformat()
        if today != self._last_reset_date:
            previous = self.daily_trades
            self.daily_trades = 0
            self._last_reset_date = today
            if previous:
                self.log_event(
                    f"Daily trade counter reset (was {previous}, new day {today}).",
                    "SYSTEM",
                )

    # ------------------------------------------------------------------
    # Logging (single source of truth per write -- no duplicate rewrites)
    # ------------------------------------------------------------------
    def _append_status_log(self, message: str, event_type: str) -> None:
        root_status = config.STATUS_FILE
        with self._state_lock:
            if root_status.exists():
                try:
                    with open(root_status, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                except Exception:
                    data = {"logs": []}
            else:
                data = {"logs": []}
            data.setdefault("logs", []).append({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": event_type,
                "message": message,
            })
            data["logs"] = data["logs"][-50:]
            _atomic_write_json(root_status, data)

    def _append_journal(self, message: str, category: str = "general") -> str:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## {timestamp}\n- Category: {category}\n- Thought: {message}\n"
        journal_path = config.WORKSPACE_DIR / "notes" / "agent_journal.md"
        if journal_path.exists():
            existing = journal_path.read_text(encoding="utf-8")
            updated = existing.rstrip() + "\n\n" + entry
        else:
            updated = f"# Agent Journal\n\n{entry}"
        journal_path.write_text(updated, encoding="utf-8")
        return str(journal_path)

    def _append_audit(self, event_type: str, detail: Dict[str, Any]) -> None:
        """Full-fidelity, append-only audit trail.

        status.json is trimmed to the last 20 entries for dashboard
        readability, and agent_journal.md is meant for human review. Neither
        is the right place for "log absolutely everything." This file is:
        every log_event call (mirrored here automatically), every raw
        Delta API request/response, every chat turn regardless of surface
        (CLI or dashboard). Never trimmed automatically -- rotates by size
        instead, so nothing is silently dropped.
        """
        path = config.WORKSPACE_DIR / "logs" / "audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event_type, **detail}
        with self._state_lock:
            if path.exists() and path.stat().st_size > 5_000_000:
                rotated = path.with_suffix(".log.1")
                path.replace(rotated)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")

    def record_thought(self, thought: str, category: str = "general") -> str:
        # Journal-only. Does NOT touch status.json -- log_event is the
        # place that updates both, so a single event is never written twice.
        return self._append_journal(thought, category=category)

    def log_event(self, message: str, event_type: str = "INFO") -> None:
        self._append_status_log(message, event_type)
        self._append_journal(message, category=event_type.lower())
        self._append_audit("log_event", {"type": event_type, "message": message})

    # ------------------------------------------------------------------
    # Ideas history (for the dashboard's "recent ideas" panel)
    # ------------------------------------------------------------------
    def _ideas_history_path(self) -> Path:
        return config.WORKSPACE_DIR / "ideas_history.json"

    def _append_idea_history(self, idea: TradeIdea, outcome: str = "proposed") -> None:
        path = self._ideas_history_path()
        with self._state_lock:
            try:
                items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            except Exception:
                items = []
            items.append({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "outcome": outcome,
                **asdict(idea),
            })
            items = items[-30:]
            _atomic_write_json(path, items)

    def load_ideas_history(self) -> List[Dict[str, Any]]:
        path = self._ideas_history_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _pending_dict(self) -> Optional[Dict[str, Any]]:
        return asdict(self.pending_trade) if self.pending_trade else None

    def _trade_history_summary(self) -> Dict[str, Any]:
        """Reconstruct trade history from ideas_history.json: total
        executed trades ever, and how many were executed today.

        This exists because daily_trades used to be hardcoded to 0 in
        __init__ -- meaning restarting the process silently reset the
        daily trade limit (a real risk-control gap), and a fresh session
        had zero historical context, so a plain "have you ever taken a
        trade" question got answered from today's (post-restart) counter
        alone -- correctly reporting 0, but incorrectly implying "never."
        """
        items = self.load_ideas_history()
        today = date.today().isoformat()
        executed = [i for i in items if i.get("outcome") == "executed"]
        executed_today = [i for i in executed if str(i.get("timestamp", "")).startswith(today)]
        return {
            "total_executed": len(executed),
            "executed_today": len(executed_today),
            "most_recent": executed[-1] if executed else None,
        }

    # ------------------------------------------------------------------
    # Full dashboard/state snapshot -- the single writer of status.json
    # and workspace/agent_state.json
    # ------------------------------------------------------------------
    def write_agent_state(self, status: str, message: str, ideas: Optional[List[TradeIdea]] = None, snapshot: Optional[Dict[str, Any]] = None) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        existing_logs: List[Dict[str, Any]] = []
        root_status = config.STATUS_FILE
        if root_status.exists():
            try:
                with open(root_status, "r", encoding="utf-8") as handle:
                    previous = json.load(handle)
                if isinstance(previous.get("logs"), list):
                    existing_logs = previous["logs"]
            except Exception:
                existing_logs = []

        existing_logs = existing_logs[-20:]

        snapshot = snapshot or self._delta_account_snapshot()
        balance_value = (
            config.BALANCE_OVERRIDE
            or config.ACCOUNT_BALANCE
            or snapshot["balance"]
            or ("Unavailable" if snapshot["connected"] else "Not connected")
        )
        payload = {
            "status": status,
            "message": message,
            "mode": "testnet" if config.TESTNET_ONLY else "live",
            "daily_trades": self.daily_trades,
            "last_scan": now,
            "balance": balance_value,
            "delta_connected": snapshot["connected"],
            "delta_detail": snapshot["detail"],
            "account": {
                "balance": balance_value,
            },
            "summary": {
                "balance": balance_value,
                "equity": "0.00",
                "pnl": "0.00",
                "status": status,
                "message": message,
                "last_scan": now,
                "daily_trades": self.daily_trades,
            },
            "logs": existing_logs,
            "capabilities": [
                "Scans multiple Delta markets",
                "Builds structured trade ideas",
                "Creates research notes and strategy files",
                "Runs autonomous scan cycles",
                "Chats using the full AGENTS.md ruleset",
                "Operates in testnet-first mode",
            ],
            "pending_trade": self._pending_dict(),
            "ideas": [
                {
                    "symbol": idea.symbol,
                    "side": idea.side,
                    "confidence": idea.confidence,
                    "rationale": idea.rationale,
                }
                for idea in (ideas or [])
            ],
        }
        state_path = config.WORKSPACE_DIR / "agent_state.json"
        with self._state_lock:
            _atomic_write_json(state_path, payload)
            _atomic_write_json(root_status, payload)