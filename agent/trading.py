"""
agent/trading.py -- TradingMixin: trade-idea generation, risk-based
position sizing, and the confirm/cancel gates.

This is the only place in the codebase that can turn a proposal into a
real order (via place_order in agent/delta_client.py), and only after
_confirm_pending -- i.e. only after an explicit human confirmation.
"""
import json
from dataclasses import asdict
from typing import Any, Dict, Optional

from agent import config
from agent.models import TradeIdea


class TradingMixin:
    def fallback_trade_idea(self, symbol: str) -> Optional[TradeIdea]:
        symbol_upper = symbol.upper()
        if any(token in symbol_upper for token in ["BTC", "ETH", "SOL", "XRP", "DOGE"]):
            side = "buy"
            confidence = 0.62
        else:
            side = "none"
            confidence = 0.0

        if side == "none":
            return None

        return TradeIdea(
            symbol=symbol,
            side=side,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            size=0.01,
            confidence=confidence,
            rationale="Conservative heuristic candidate from broad market scan.",
        )

    def propose_trade(self, symbol: str) -> Optional[TradeIdea]:
        self.record_thought(f"Preparing a trade idea for {symbol}.", category="trade")
        prompt = f"""
Analyze {symbol} and return only JSON:
{{
  "symbol": "{symbol}",
  "side": "buy|sell|none",
  "entry": 0,
  "stop_loss": 0,
  "take_profit": 0,
  "size": 0,
  "confidence": 0.0,
  "rationale": "short reason"
}}
Use conservative sizing and skip if no edge.
"""
        raw = self.llm_chat(prompt)
        try:
            data = json.loads(raw)
            if data.get("side") == "none":
                return None
            return TradeIdea(
                symbol=data["symbol"],
                side=data["side"],
                entry=float(data["entry"]),
                stop_loss=float(data["stop_loss"]),
                take_profit=float(data["take_profit"]),
                size=float(data["size"]),
                confidence=float(data["confidence"]),
                rationale=str(data["rationale"]),
            )
        except Exception:
            return None

    def confirm(self, idea: TradeIdea) -> bool:
        """CLI-only helper (python engine.py direct use), not the dashboard path."""
        print("\nTrade idea:")
        print(idea)
        ans = input("Approve this trade? (yes/no): ").strip().lower()
        if ans != "yes":
            self.log_event(f"User rejected the trade idea for {idea.symbol}.", "INFO")
            return False
        self.log_event(f"User approved the trade idea for {idea.symbol}.", "INFO")
        return True

    def _idea_text(self, idea: TradeIdea) -> str:
        return (
            f"Trade proposal for {idea.symbol}:\n"
            f"- Side: {idea.side.upper()}\n"
            f"- Entry: {idea.entry or 'TBD'}\n"
            f"- Stop loss: {idea.stop_loss or 'TBD'}\n"
            f"- Take profit: {idea.take_profit or 'TBD'}\n"
            f"- Size: {idea.size}\n"
            f"- Confidence: {idea.confidence}\n"
            f"- Rationale: {idea.rationale}\n"
            f"Reply 'confirm' to submit this on testnet, or 'cancel' to drop it."
        )

    def _build_trade_idea(self, data: Dict[str, Any]) -> TradeIdea:
        symbol = str(data.get("symbol") or "BTCUSD").upper()
        side = str(data.get("side") or "buy").lower()
        if side not in ("buy", "sell"):
            side = "buy"

        entry = data.get("entry")
        try:
            entry = float(entry) if entry else 0.0
        except (TypeError, ValueError):
            entry = 0.0
        if not entry:
            ticker = self.fetch_ticker(symbol) or {}
            try:
                entry = float(ticker.get("mark_price") or ticker.get("close") or 0.0)
            except (TypeError, ValueError):
                entry = 0.0

        def _num(value, default):
            try:
                return float(value) if value not in (None, "") else default
            except (TypeError, ValueError):
                return default

        if entry:
            default_sl = entry * (1 - config.MAX_RISK_PCT) if side == "buy" else entry * (1 + config.MAX_RISK_PCT)
            default_tp = entry * (1 + config.MAX_RISK_PCT * 2) if side == "buy" else entry * (1 - config.MAX_RISK_PCT * 2)
        else:
            default_sl = 0.0
            default_tp = 0.0

        stop_loss = _num(data.get("stop_loss"), default_sl)
        take_profit = _num(data.get("take_profit"), default_tp)
        size = _num(data.get("size"), self._compute_position_size(entry, stop_loss))
        confidence = _num(data.get("confidence"), 0.6)
        rationale = data.get("rationale") or data.get("reply") or "Trade idea generated from chat request."

        return TradeIdea(symbol, side, entry, stop_loss, take_profit, size, confidence, str(rationale))

    def _compute_position_size(self, entry: float, stop_loss: float) -> float:
        """Derive size from account balance and MAX_RISK_PCT instead of a
        fixed 0.01 default.

        size = (balance * MAX_RISK_PCT) / abs(entry - stop_loss)

        Falls back to 0.01 if balance or stop distance are unavailable.
        """
        try:
            balance_raw = config.BALANCE_OVERRIDE or config.ACCOUNT_BALANCE or self.fetch_account_balance()
            balance = float(balance_raw) if balance_raw not in (None, "", "Connected") else None
        except (TypeError, ValueError):
            balance = None

        if not balance or not entry or not stop_loss:
            return 0.01

        distance = abs(entry - stop_loss)
        if distance <= 0:
            return 0.01

        risk_amount = balance * config.MAX_RISK_PCT
        size = risk_amount / distance
        return max(round(size, 4), 0.001)

    def _confirm_pending(self) -> str:
        with self._trade_lock:
            idea = self.pending_trade
            if idea is None:
                return "There's no pending trade to confirm."
            # Claim it immediately, inside the lock, so a concurrent confirm
            # call sees no pending trade instead of racing this same idea
            # through place_order a second time.
            self.pending_trade = None

        self._maybe_reset_daily_counters()
        if self.daily_trades >= config.MAX_DAILY_TRADES:
            self.log_event(f"Blocked trade for {idea.symbol}: daily trade limit reached.", "RISK")
            self._append_idea_history(idea, outcome="blocked_daily_limit")
            return f"Daily trade limit ({config.MAX_DAILY_TRADES}) reached. The {idea.symbol} trade was not placed."

        if idea.confidence < config.MIN_CONFIDENCE:
            self.log_event(
                f"Blocked trade for {idea.symbol}: confidence {idea.confidence} below minimum {config.MIN_CONFIDENCE}.",
                "RISK",
            )
            self._append_idea_history(idea, outcome="blocked_low_confidence")
            return (
                f"The {idea.symbol} trade was not placed: confidence {idea.confidence} is below the "
                f"minimum bar of {config.MIN_CONFIDENCE} (MIN_CONFIDENCE in .env). Propose a higher-conviction "
                "setup or lower the threshold explicitly if you want to override this."
            )

        self.log_event(f"User approved the trade idea for {idea.symbol}.", "TRADE")
        code, res = self.place_order(idea)

        if code in (200, 201):
            self.daily_trades += 1
            self.log_event(f"Order submitted for {idea.symbol}: {res}", "TRADE")
            self._append_idea_history(idea, outcome="executed")
            self.write_agent_state("monitoring", f"Order submitted for {idea.symbol}.")
            return f"Order submitted for {idea.symbol} ({idea.side}, size {idea.size}). Response: {res}"

        reason = res.get("error") if isinstance(res, dict) else res
        self.log_event(f"Order not placed for {idea.symbol}: {reason}", "WARN")
        self._append_idea_history(idea, outcome="rejected")
        return f"Order was NOT placed for {idea.symbol}. Reason: {reason}"

    def _cancel_pending(self) -> str:
        idea = self.pending_trade
        if idea is None:
            return "There's no pending trade to cancel."
        self.pending_trade = None
        self.log_event(f"User rejected the trade idea for {idea.symbol}.", "INFO")
        self._append_idea_history(idea, outcome="cancelled")
        return f"Cancelled the pending {idea.symbol} trade idea."