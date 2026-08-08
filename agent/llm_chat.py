"""
agent/llm_chat.py -- LLMMixin: everything that talks to the LLM and turns
its output into an action. Includes the heuristic (no-LLM) fallback path
used when OLLAMA_API_KEY isn't configured.
"""
import json
from typing import Any, Dict, Optional

from agent import config
from agent.models import TradeIdea


class LLMMixin:
    def _extract_content(self, resp) -> str:
        """Pull the assistant text out of whatever shape the ollama client returned.

        The client may yield a ChatResponse (a dict-like dataclass with .message.content),
        a plain dict, or a streaming generator of either. Walk all of them.
        """
        if resp is None:
            return ""
        if isinstance(resp, str):
            return resp
        if isinstance(resp, (list, tuple)):
            return "".join(self._extract_content(x) for x in resp)
        if hasattr(resp, "keys") or hasattr(resp, "__getitem__"):
            try:
                msg = resp["message"]
            except Exception:
                msg = None
            if msg is not None:
                return self._extract_content(msg)
            for key in ("content", "response", "text"):
                try:
                    if resp[key]:
                        return str(resp[key])
                except Exception:
                    pass
            return ""
        for attr in ("message", "content", "response", "text"):
            if hasattr(resp, attr):
                value = getattr(resp, attr)
                if value:
                    return self._extract_content(value)
        return ""

    def llm_chat(self, user_text: str, system: Optional[str] = None) -> str:
        if self.client is None:
            return "Ollama cloud client is not available. Configure OLLAMA_API_KEY and the cloud host to enable AI responses."

        system_prompt = system or (
            "You are a cautious trading assistant. "
            "You can analyze markets, explain your reasoning, and suggest trades. "
            "Never place trades unless the user confirms. "
            "Return concise JSON when asked for a trade idea."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

        # Preferred path: non-streaming. The ollama client aggregates the
        # response into a single ChatResponse / dict.
        try:
            resp = self.client.chat(model=config.OLLAMA_MODEL, messages=messages, stream=False)
            content = self._extract_content(resp)
            if content:
                return content
        except TypeError:
            pass
        except Exception:
            pass

        # Streaming fallback: walk chunks and concatenate content.
        try:
            stream = self.client.chat(model=config.OLLAMA_MODEL, messages=messages, stream=True)
            parts = []
            for chunk in stream:
                piece = self._extract_content(chunk)
                if piece:
                    parts.append(piece)
                done = False
                if isinstance(chunk, dict):
                    done = bool(chunk.get("done"))
                else:
                    done = bool(getattr(chunk, "done", False))
                if done:
                    break
            return "".join(parts)
        except Exception:
            resp = self.client.chat(model=config.OLLAMA_MODEL, messages=messages)
            return self._extract_content(resp)

    def _build_system_prompt(self) -> str:
        try:
            agents_md = (config.BASE_DIR / "AGENTS.md").read_text(encoding="utf-8")
        except Exception:
            agents_md = "(AGENTS.md not found)"

        try:
            knowledge_md = (config.BASE_DIR / "KNOWLEDGE.md").read_text(encoding="utf-8")
        except Exception:
            knowledge_md = "(KNOWLEDGE.md not found)"

        pending_desc = "none"
        if self.pending_trade:
            p = self.pending_trade
            pending_desc = f"{p.symbol} {p.side} entry={p.entry} sl={p.stop_loss} tp={p.take_profit} size={p.size}"

        history = self._trade_history_summary()
        if history["total_executed"] == 0:
            history_desc = "No trades have ever been executed by this agent."
        else:
            recent = history["most_recent"] or {}
            history_desc = (
                f"{history['total_executed']} trade(s) executed all-time, "
                f"{history['executed_today']} today. Most recent: {recent.get('symbol')} "
                f"{recent.get('side')} at {recent.get('timestamp')}."
            )

        return f"""You are Alpha Agent, the Delta Trading Agent. Follow the operating instructions below exactly.

--- AGENTS.md ---
{agents_md}
--- end AGENTS.md ---

--- KNOWLEDGE.md (Delta Exchange API reference -- ground technical claims in this, don't guess at endpoint/field names) ---
{knowledge_md}
--- end KNOWLEDGE.md ---

Current state:
- Daily trades used: {self.daily_trades}/{config.MAX_DAILY_TRADES}
- All-time trade history: {history_desc}
- Pending unconfirmed trade: {pending_desc}
- Mode: {"TESTNET" if config.TESTNET_ONLY else "LIVE (blocked unless DELTA_BASE_URL is a testnet host)"}

Respond with ONLY a single JSON object -- no prose outside it, no markdown fences. Schema:
{{
  "action": "chat" | "status" | "scan" | "propose_trade" | "confirm_trade" | "cancel_trade" | "create_note" | "create_strategy",
  "reply": "short natural-language message to show the user",
  "symbol": "optional, for propose_trade, e.g. BTCUSD",
  "side": "buy|sell, for propose_trade",
  "entry": number or null,
  "stop_loss": number or null,
  "take_profit": number or null,
  "size": number or null,
  "confidence": number between 0 and 1 or null,
  "rationale": "short reason, for propose_trade",
  "title": "optional, for create_note/create_strategy",
  "content": "optional, for create_note/create_strategy"
}}

Rules:
- Use "propose_trade" whenever the user asks you to take/open/enter a position (e.g. "take BTC long", "short ETH with a 2% stop"). If they don't give exact entry/stop/target numbers, leave those fields null -- the engine will fill entry from the live ticker and compute a default stop/target.
- Never claim a trade has been executed. Only "confirm_trade" executes anything, and only once the user has explicitly approved the CURRENT pending trade shown above.
- Use "confirm_trade" only when the user is clearly approving that pending trade.
- Use "cancel_trade" when the user rejects, cancels, or wants to change the pending trade.
- Use "create_strategy" when the user wants a trading strategy written down and saved.
- Use "create_note" for research notes / observations they want saved.
- Use "status" for account/session summaries, "scan" for a market sweep.
- "Daily trades used" resets every calendar day AND on process restart it reflects only today's count, not history. If asked "have you ever taken a trade" or anything about history, answer from "All-time trade history" above -- do not infer "never traded" just because today's counter is 0.
- For "status" and "scan", "reply" is shown to the user ABOVE the actual data (connection info / candidate list), so answer what they actually asked (e.g. "are you connected to Delta?") in "reply" -- don't leave it generic filler, the raw data alone doesn't answer conversational questions.
- Otherwise use "chat" and just answer helpfully and concisely.
"""

    def _parse_action(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        def _try_parse(candidate: str) -> Optional[Dict[str, Any]]:
            try:
                data = json.loads(candidate)
            except Exception:
                return None
            if isinstance(data, dict) and data.get("action") in config.VALID_ACTIONS:
                return data
            return None

        data = _try_parse(text)
        if data is not None:
            return data

        # The model sometimes emits a valid JSON object plus stray text
        # around it. Recovering the outermost {...} span catches most of
        # these instead of giving up on the whole response.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = _try_parse(text[start:end + 1])
            if data is not None:
                return data

        if not text:
            return {
                "action": "chat",
                "reply": (
                    "I didn't get a reply from the model. "
                    "The model may still be warming up, or OLLAMA_MODEL/OLLAMA_API_KEY needs adjustment. "
                    "Try again, or check the server logs."
                ),
            }

        # Genuinely unparseable. Don't dump raw JSON-shaped text (stray
        # braces/quotes) straight into the chat -- log the real payload for
        # debugging and give an honest, clean message instead.
        self.log_event(f"LLM returned unparseable action JSON: {text[:300]!r}", "WARN")
        return {
            "action": "chat",
            "reply": (
                "I got a malformed response from the model that I couldn't parse cleanly. "
                "It's been logged for review -- try rephrasing, or ask again."
            ),
        }

    def _status_text(self) -> str:
        self._maybe_reset_daily_counters()
        snapshot = self._delta_account_snapshot()
        if snapshot["connected"]:
            conn_line = f"Delta connection: OK (authenticated, balance {snapshot['balance'] or 'n/a'} USDT)."
        else:
            conn_line = f"Delta connection: NOT connected -- {snapshot['detail']}"
        # Sync status.json's delta_connected badge with what we just checked.
        self.write_agent_state(
            "monitoring" if snapshot["connected"] else "disconnected",
            conn_line,
            snapshot=snapshot,
        )
        return f"{conn_line}\nTrades today: {self.daily_trades}/{config.MAX_DAILY_TRADES}\n{self.market_snapshot()}"

    def _dispatch_action(self, data: Dict[str, Any], raw: str) -> Dict[str, Any]:
        action = str(data.get("action") or "chat").lower()
        try:
            if action == "status":
                lead = data.get("reply") or ""
                reply = (lead + "\n\n" if lead else "") + self._status_text()
            elif action == "scan":
                lead = data.get("reply") or ""
                reply = (lead + "\n\n" if lead else "") + self.scan_market(limit=20)
            elif action == "propose_trade":
                idea = self._build_trade_idea(data)
                self.pending_trade = idea
                self._append_idea_history(idea, outcome="proposed")
                self.log_event(f"Prepared a trade idea for {idea.symbol} from chat request.", "TRADE")
                self.write_agent_state("monitoring", f"Prepared trade idea for {idea.symbol}.")
                lead = data.get("reply") or ""
                reply = (lead + "\n\n" if lead else "") + self._idea_text(idea)
            elif action == "confirm_trade":
                reply = self._confirm_pending()
            elif action == "cancel_trade":
                reply = self._cancel_pending()
            elif action == "create_note":
                title = data.get("title") or "note"
                content = data.get("content") or data.get("reply") or ""
                path = self.add_note(title, content)
                self.log_event(f"Created research note: {path}", "SYSTEM")
                reply = f"Saved note to {path}"
            elif action == "create_strategy":
                title = data.get("title") or "strategy"
                content = data.get("content") or data.get("reply") or ""
                path = self.create_strategy_file(title, content)
                self.log_event(f"Created strategy file: {path}", "SYSTEM")
                reply = f"Saved strategy to {path}"
            else:
                reply = data.get("reply") or raw
        except Exception as exc:
            self.handle_failure(f"agent action '{action}'", exc)
            reply = f"Something went wrong handling that ({exc}). It's been logged for review."

        return {"reply": reply, "pending_trade": self._pending_dict(), "action": action}

    def _heuristic_respond(self, message: str) -> Dict[str, Any]:
        """Fallback used when no LLM client is configured (no OLLAMA_API_KEY)."""
        lowered = message.lower().strip()
        if lowered in {"scan", "start scan", "start scanning", "scan now"}:
            reply = self.scan_market(limit=20)
        elif lowered == "status":
            reply = self._status_text()
        elif lowered.startswith("idea "):
            symbol = message.split(" ", 1)[1].strip()
            idea = self.propose_trade(symbol) or self.fallback_trade_idea(symbol)
            if idea:
                self.pending_trade = idea
                self._append_idea_history(idea, outcome="proposed")
                reply = self._idea_text(idea)
            else:
                reply = f"No trade idea found for {symbol}."
        elif lowered in {"confirm", "i confirm", "yes", "yes please", "go ahead"} and self.pending_trade:
            reply = self._confirm_pending()
        elif lowered in {"cancel", "no", "never mind", "stop"} and self.pending_trade:
            reply = self._cancel_pending()
        elif any(k in lowered for k in ["long", "short", "buy", "sell", "trade", "future", "futures"]):
            symbol = "BTCUSD"
            for token, sym in (("eth", "ETHUSD"), ("sol", "SOLUSD"), ("btc", "BTCUSD")):
                if token in lowered:
                    symbol = sym
                    break
            side = "sell" if any(k in lowered for k in ["short", "sell"]) else "buy"
            idea = self.fallback_trade_idea(symbol) or TradeIdea(symbol, side, 0, 0, 0, 0.01, 0.6, "Heuristic fallback (LLM not configured).")
            idea.side = side
            self.pending_trade = idea
            self._append_idea_history(idea, outcome="proposed")
            self.log_event(f"Prepared heuristic trade proposal for {symbol}.", "TRADE")
            reply = self._idea_text(idea)
        else:
            reply = (
                "The LLM isn't configured (set OLLAMA_API_KEY in .env), so I'm running in basic keyword mode. "
                "Try: 'scan', 'status', 'idea BTCUSD', or 'long BTC' / 'short ETH'."
            )
        return {"reply": reply, "pending_trade": self._pending_dict()}

    def agent_respond(self, user_message: str) -> Dict[str, Any]:
        """Main entry point for chat -- used by both the dashboard and the CLI."""
        if self.client is None:
            return self._heuristic_respond(user_message)

        system = self._build_system_prompt()
        try:
            raw = self.llm_chat(user_message, system=system)
        except Exception as exc:
            self.handle_failure("llm chat", exc)
            return {"reply": f"The LLM call failed ({exc}). Falling back to basic mode.", **self._heuristic_respond(user_message)}

        data = self._parse_action(raw)
        return self._dispatch_action(data, raw)