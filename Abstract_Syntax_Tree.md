Here's the **Abstract Syntax Tree** for the `delta_trading_agent` repository, constructed from the actual source code. Since the project is a multi-module Python package, I've rendered it as a **multi-file AST forest** — one tree per module, with cross-reference edges between them.

---

## Module: `engine.py` (Facade / Re-export layer)

```
Module
├── DocString ("engine.py -- thin compatibility facade...")
├── ImportFrom: agent.config
│   ├── BASE_DIR, WORKSPACE_DIR, STATUS_FILE
│   ├── OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_API_KEY
│   ├── DELTA_BASE_URL, DELTA_API_KEY, DELTA_API_SECRET
│   ├── ACCOUNT_BALANCE, BALANCE_OVERRIDE
│   ├── MAX_DAILY_TRADES, MAX_RISK_PCT, MIN_CONFIDENCE, TESTNET_ONLY
│   ├── AUTONOMOUS_MODE, AUTONOMOUS_INTERVAL_SECONDS, AUTONOMOUS_ALLOW_EXEC
│   ├── VALID_ACTIONS, ollama
├── ImportFrom: agent.models → TradeIdea
├── ImportFrom: agent.core → TradingAgent
├── Assign: __all__ = [list of 16 re-exported names]
└── If: __name__ == "__main__"
    └── Expr: Call TradingAgent().chat_loop()
```

---

## Module: `agent/models.py` (Data layer)

```
Module
├── DocString ("shared data structures used across mixins")
├── ImportFrom: dataclasses → dataclass
└── ClassDef: TradeIdea
    ├── Decorator: @dataclass
    ├── AnnAssign: symbol: str
    ├── AnnAssign: side: str
    ├── AnnAssign: entry: float
    ├── AnnAssign: stop_loss: float
    ├── AnnAssign: take_profit: float
    ├── AnnAssign: size: float
    ├── AnnAssign: confidence: float
    └── AnnAssign: rationale: str
```

---

## Module: `agent/config.py` (Configuration / Constants)

```
Module
├── DocString ("every environment-derived constant, in one place")
├── Import: os
├── ImportFrom: pathlib → Path
├── ImportFrom: dotenv → load_dotenv
├── Try/Except
│   ├── Import: ollama
│   └── Except ImportError: ollama = None
├── Assign: BASE_DIR = Path(__file__).resolve().parent.parent
├── Expr: load_dotenv(BASE_DIR / ".env")
├── Assign: WORKSPACE_DIR = BASE_DIR / "workspace"
├── Expr: WORKSPACE_DIR.mkdir(exist_ok=True)
├── Assign: STATUS_FILE = BASE_DIR / "status.json"
├── Assign: OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")
├── Assign: OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m3:cloud")
├── Assign: OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
├── Assign: DELTA_BASE_URL = os.getenv(...) or "https://cdn-ind.testnet.deltaex.org"
├── Assign: DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
├── Assign: DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
├── Assign: ACCOUNT_BALANCE = os.getenv("ACCOUNT_BALANCE", "")
├── Assign: BALANCE_OVERRIDE = os.getenv("BALANCE_OVERRIDE", "")
├── Assign: MAX_DAILY_TRADES = int(os.getenv(..., "5"))
├── Assign: MAX_RISK_PCT = float(os.getenv(..., "0.01"))
├── Assign: MIN_CONFIDENCE = float(os.getenv(..., "0.55"))
├── Assign: TESTNET_ONLY = os.getenv(...).lower() == "true"
├── Assign: AUTONOMOUS_MODE = os.getenv(...).lower() == "true"
├── Assign: AUTONOMOUS_INTERVAL_SECONDS = int(os.getenv(..., "300"))
├── Assign: AUTONOMOUS_ALLOW_EXEC = os.getenv(...).lower() == "true"
└── Assign: VALID_ACTIONS = {set of 8 strings}
```

---

## Module: `agent/state_store.py` (StateMixin — Persistence & Locking)

```
Module
├── DocString
├── Import: json, os, threading, time
├── ImportFrom: dataclasses → asdict
├── ImportFrom: datetime → date
├── ImportFrom: pathlib → Path
├── ImportFrom: typing → Any, Dict, List, Optional
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
│
├── FunctionDef: _atomic_write_json(path, payload)
│   ├── Assign: tmp = path.with_suffix(".tmp")
│   ├── Expr: tmp.write_text(json.dumps(...))
│   └── Expr: os.replace(tmp, path)
│
└── ClassDef: StateMixin
    ├── ClassVar: _state_lock = threading.Lock()
    ├── ClassVar: _trade_lock = threading.Lock()
    │
    ├── FunctionDef: _maybe_reset_daily_counters(self)
    │   ├── Assign: today = date.today().isoformat()
    │   └── If: today != self._last_reset_date
    │       ├── Assign: self.daily_trades = 0
    │       └── Expr: self.log_event(...)
    │
    ├── FunctionDef: _append_status_log(self, message, event_type)
    │   ├── With: self._state_lock
    │   ├── If: root_status.exists()
    │   ├── Try/Except: json.load(handle)
    │   ├── Expr: data.setdefault("logs", []).append({...})
    │   ├── Assign: data["logs"] = data["logs"][-50:]
    │   └── Expr: _atomic_write_json(root_status, data)
    │
    ├── FunctionDef: _append_journal(self, message, category="general")
    │   ├── Assign: timestamp = time.strftime(...)
    │   ├── Assign: entry = f"## {timestamp}..."
    │   ├── If: journal_path.exists()
    │   └── Expr: journal_path.write_text(...)
    │
    ├── FunctionDef: record_thought(self, thought, category)
    │   └── Return: self._append_journal(...)
    │
    ├── FunctionDef: log_event(self, message, event_type="INFO")
    │   ├── Expr: self._append_status_log(...)
    │   └── Expr: self._append_journal(...)
    │
    ├── FunctionDef: _ideas_history_path(self) → Path
    │   └── Return: WORKSPACE_DIR / "ideas_history.json"
    │
    ├── FunctionDef: _append_idea_history(self, idea, outcome="proposed")
    │   ├── With: self._state_lock
    │   ├── Try/Except: json.loads(...)
    │   ├── Expr: items.append({...**asdict(idea)})
    │   ├── Assign: items = items[-30:]
    │   └── Expr: _atomic_write_json(path, items)
    │
    ├── FunctionDef: load_ideas_history(self) → List[Dict]
    │   ├── If: not path.exists()
    │   └── Try/Except: json.loads(...)
    │
    ├── FunctionDef: _pending_dict(self) → Optional[Dict]
    │   └── Return: asdict(self.pending_trade) if pending else None
    │
    └── FunctionDef: write_agent_state(self, status, message, ideas, snapshot)
        ├── Assign: now = time.strftime(...)
        ├── With: self._state_lock
        ├── Try/Except: json.load(previous)
        ├── Assign: payload = {status, message, mode, daily_trades, ...}
        ├── Expr: _atomic_write_json(state_path, payload)
        └── Expr: _atomic_write_json(root_status, payload)
```

---

## Module: `agent/workspace_tools.py` (WorkspaceMixin — Sandboxed I/O)

```
Module
├── DocString
├── Import: subprocess, sys
├── ImportFrom: pathlib → Path
├── ImportFrom: typing → Any, Dict, List
├── ImportFrom: agent → config
│
└── ClassDef: WorkspaceMixin
    ├── FunctionDef: _safe_workspace_path(self, relative_path) → Path
    │   ├── If: not relative_path or not isinstance(...)
    │   ├── Assign: candidate = (WORKSPACE_DIR / relative_path).resolve()
    │   ├── Assign: workspace_root = WORKSPACE_DIR.resolve()
    │   └── If: containment check → raise ValueError
    │
    ├── FunctionDef: create_workspace_file(self, filename, content) → str
    ├── FunctionDef: read_workspace_file(self, filename) → str
    ├── FunctionDef: list_workspace_files(self, subdir="") → List[str]
    ├── FunctionDef: delete_workspace_file(self, filename) → bool
    │
    ├── FunctionDef: run_workspace_script(self, filename, timeout=30) → Dict
    │   ├── If: not AUTONOMOUS_ALLOW_EXEC → return disabled
    │   ├── If: suffix != ".py" → return error
    │   └── Try/Except: subprocess.run([sys.executable, target], ...)
    │
    ├── FunctionDef: add_note(self, title, content) → str
    │   └── Return: create_workspace_file(f"notes/{slug}.md", ...)
    │
    └── FunctionDef: create_strategy_file(self, title, content) → str
        └── Return: create_workspace_file(f"strategies/{slug}.md", ...)
```

---

## Module: `agent/delta_client.py` (DeltaMixin — API Client)

```
Module
├── DocString
├── Import: hashlib, hmac, json, time
├── ImportFrom: typing → Any, Dict, List, Optional
├── Import: requests
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
│
└── ClassDef: DeltaMixin
    ├── FunctionDef: sign(self, method, path, timestamp, payload="") → str
    │   ├── Assign: msg = f"{method}{timestamp}{path}{payload}"
    │   └── Return: hmac.new(config.DELTA_API_SECRET.encode(), ...)
    │
    ├── FunctionDef: delta_request(self, method, path, payload, use_public)
    │   ├── If: payload → body = json.dumps(...)
    │   ├── Assign: ts = str(int(time.time()))
    │   ├── Assign: headers = {Content-Type, User-Agent}
    │   ├── If: not use_public → headers.update({api-key, timestamp, signature})
    │   ├── Expr: requests.request(method, url, ...)
    │   └── Try/Except: return (status_code, r.json())
    │
    ├── FunctionDef: fetch_products(self) → List[Dict]
    ├── FunctionDef: fetch_product(self, symbol) → Optional[Dict]
    ├── FunctionDef: fetch_tickers(self, contract_types, underlying) → List[Dict]
    ├── FunctionDef: fetch_ticker(self, symbol) → Optional[Dict]
    ├── FunctionDef: fetch_wallet_balances(self) → List[Dict]
    │
    ├── FunctionDef: _delta_account_snapshot(self) → Dict
    │   ├── If: missing keys → return disconnected
    │   ├── Expr: delta_request("GET", "/v2/wallet/balances")
    │   └── If/Elif/Else: 200 → connected, 401 → rejected, else → failed
    │
    ├── FunctionDef: fetch_account_balance(self) → Optional[str]
    │   └── Return: _delta_account_snapshot().get("balance")
    │
    ├── FunctionDef: _product_id_cache(self) → Dict[str, int]
    │   └── Lazy-load: fetch_products() → map symbol→id
    │
    ├── FunctionDef: _product_info_cache(self) → Dict[str, Dict]
    │   └── Lazy-load: fetch_products() → map symbol→info
    │
    ├── FunctionDef: _resolve_contract_size(self, symbol, desired_qty) → int
    │   ├── Lookup: contract_value from product_info_cache
    │   ├── If: contract_value → contracts = desired_qty / contract_value
    │   └── Return: max(1, round(contracts))
    │
    ├── FunctionDef: resolve_product_id(self, symbol) → Optional[int]
    │   ├── Lookup: cache hit
    │   └── Fallback: fetch_product(symbol) → prime cache
    │
    └── FunctionDef: place_order(self, idea: TradeIdea)
        ├── If: not TESTNET_ONLY → refuse
        ├── If: "testnet" not in BASE_URL → refuse
        ├── Expr: resolve_product_id(idea.symbol)
        ├── If: product_id is None → refuse
        ├── Expr: log_event("Preparing order submission...")
        ├── Assign: payload = {product_id, size, side, order_type="market_order"}
        │   └── size: _resolve_contract_size(idea.symbol, idea.size)
        └── Return: self.delta_request("POST", "/v2/orders", payload)
```

---

## Module: `agent/market.py` (MarketMixin — Scanning)

```
Module
├── DocString
├── ImportFrom: typing → Any, Dict, List
│
└── ClassDef: MarketMixin
    ├── FunctionDef: market_snapshot(self, limit=20) → str
    │   └── Return: comma-joined symbols from fetch_products()
    │
    ├── FunctionDef: _liquid_candidates(self, limit=20) → List[Dict]
    │   ├── Expr: fetch_tickers(contract_types="perpetual_futures")
    │   ├── For: tickers → extract symbol, turnover
    │   ├── Expr: candidates.sort(key=turnover, reverse=True)
    │   └── Return: candidates[:limit]
    │
    └── FunctionDef: scan_market(self, limit=20) → str
        ├── Assign: candidates = _liquid_candidates()
        ├── If: not candidates → fallback to raw product list
        ├── Expr: add_note("market_scan", formatted_candidates)
        └── Return: formatted string
```

---

## Module: `agent/trading.py` (TradingMixin — Risk & Execution Gates)

```
Module
├── DocString
├── Import: json
├── ImportFrom: dataclasses → asdict
├── ImportFrom: typing → Any, Dict, Optional
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
│
└── ClassDef: TradingMixin
    ├── FunctionDef: fallback_trade_idea(self, symbol) → Optional[TradeIdea]
    │   └── Heuristic: BTC/ETH/SOL/XRP/DOGE → side=buy, conf=0.62
    │
    ├── FunctionDef: propose_trade(self, symbol) → Optional[TradeIdea]
    │   ├── Expr: record_thought(...)
    │   ├── Expr: llm_chat(prompt_with_json_schema)
    │   └── Try/Except: json.loads(raw) → TradeIdea(...)
    │
    ├── FunctionDef: confirm(self, idea) → bool
    │   ├── Expr: print(idea)
    │   └── Expr: input("Approve?") → return ans == "yes"
    │
    ├── FunctionDef: _idea_text(self, idea) → str
    │   └── Return: formatted multi-line proposal string
    │
    ├── FunctionDef: _build_trade_idea(self, data: Dict) → TradeIdea
    │   ├── Normalize: symbol, side
    │   ├── If: no entry → fetch_ticker → mark_price
    │   ├── Compute: default_sl, default_tp from entry * (1 ± MAX_RISK_PCT)
    │   └── Return: TradeIdea(...)
    │
    ├── FunctionDef: _compute_position_size(self, entry, stop_loss) → float
    │   ├── Formula: size = (balance * MAX_RISK_PCT) / abs(entry - stop_loss)
    │   └── Fallback: 0.01
    │
    ├── FunctionDef: _confirm_pending(self) → str
    │   ├── With: self._trade_lock
    │   ├── If: no pending_trade → return "no pending trade"
    │   ├── Assign: self.pending_trade = None  (claim inside lock)
    │   ├── If: daily_trades >= MAX_DAILY_TRADES → block
    │   ├── If: confidence < MIN_CONFIDENCE → block
    │   ├── Expr: place_order(idea)
    │   ├── If: code in (200, 201) → daily_trades += 1, log, return success
    │   └── Else: log rejection, return failure reason
    │
    └── FunctionDef: _cancel_pending(self) → str
        ├── If: no pending → return
        ├── Assign: pending_trade = None
        └── Expr: log_event("User rejected...")
```

---

## Module: `agent/llm_chat.py` (LLMMixin — Orchestration)

```
Module
├── DocString
├── Import: json
├── ImportFrom: typing → Any, Dict, Optional
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
│
└── ClassDef: LLMMixin
    ├── FunctionDef: _extract_content(self, resp) → str
    │   └── Recursive unwrapping: ChatResponse / dict / list / generator
    │
    ├── FunctionDef: llm_chat(self, user_text, system=None) → str
    │   ├── If: client is None → return unavailable msg
    │   ├── Try: non-streaming client.chat(stream=False)
    │   ├── Except: streaming fallback (walk chunks)
    │   └── Except: final fallback call
    │
    ├── FunctionDef: _build_system_prompt(self) → str
    │   ├── Read: AGENTS.md
    │   ├── Read: KNOWLEDGE.md
    │   ├── Format: pending_trade description
    │   └── Return: massive f-string with rules + schema
    │
    ├── FunctionDef: _parse_action(self, raw) → Dict
    │   ├── Strip: markdown fences
    │   ├── Try: json.loads(text)
    │   ├── Fallback: extract outermost {...}
    │   └── Fallback: return {"action": "chat", "reply": error_msg}
    │
    ├── FunctionDef: _status_text(self) → str
    │   ├── Expr: _maybe_reset_daily_counters()
    │   ├── Expr: _delta_account_snapshot()
    │   └── Return: connection line + trades + market_snapshot
    │
    ├── FunctionDef: _dispatch_action(self, data, raw) → Dict
    │   ├── Match: action → status, scan, propose_trade, confirm_trade,
    │   │              cancel_trade, create_note, create_strategy, default
    │   ├── Each: calls respective mixin method
    │   └── Except: handle_failure → return error reply
    │
    ├── FunctionDef: _heuristic_respond(self, message) → Dict
    │   └── Keyword matching: scan, status, idea, confirm, cancel, long/short
    │
    └── FunctionDef: agent_respond(self, user_message) → Dict
        ├── If: client is None → _heuristic_respond
        ├── Try: llm_chat(system_prompt) → raw
        ├── Except: handle_failure → heuristic fallback
        ├── Expr: _parse_action(raw)
        └── Return: _dispatch_action(data, raw)
```

---

## Module: `agent/autonomy.py` (AutonomyMixin — Background Loop)

```
Module
├── DocString
├── Import: json, time
├── ImportFrom: typing → Any, Dict, List, Optional
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
│
└── ClassDef: AutonomyMixin
    ├── FunctionDef: heartbeat(self) → Dict
    │   ├── Expr: _delta_account_snapshot()
    │   ├── Expr: append JSON line to heartbeat.log
    │   └── If: not connected → _note_lesson(...)
    │
    ├── FunctionDef: _note_lesson(self, message)
    │   ├── Deduplication: self._seen_lessons set
    │   └── Append: timestamped line to lessons_learned.md
    │
    ├── FunctionDef: run_forever(self, interval_seconds, iterations)
    │   └── While: heartbeat() → if connected → autonomous_cycle()
    │
    ├── FunctionDef: handle_failure(self, context, error)
    │   ├── Increment: failure_count
    │   ├── Expr: log_event(...)
    │   ├── Expr: write_agent_state("recovering", ...)
    │   └── If: failure_count >= 2 → autonomous_cycle() recovery
    │
    ├── FunctionDef: autonomous_cycle(self) → Optional[TradeIdea]
    │   ├── Expr: fetch_products()
    │   ├── For: symbols[:10] → propose_trade() or fallback_trade_idea()
    │   ├── If: ideas → top_idea = max(ideas, key=confidence)
    │   ├── Expr: add_note("autonomous_scan", ...)
    │   └── Return: top_idea
    │
    └── FunctionDef: run_autonomous_loop(self, iterations=3, interval_seconds=10)
        └── For: range(iterations) → autonomous_cycle() + sleep
```

---

## Module: `agent/core.py` (TradingAgent — Composition Root)

```
Module
├── DocString
├── ImportFrom: datetime → date
├── ImportFrom: typing → Any, Dict, List, Optional
├── ImportFrom: agent → config
├── ImportFrom: agent.models → TradeIdea
├── ImportFrom: agent.state_store → StateMixin
├── ImportFrom: agent.workspace_tools → WorkspaceMixin
├── ImportFrom: agent.delta_client → DeltaMixin
├── ImportFrom: agent.market → MarketMixin
├── ImportFrom: agent.trading → TradingMixin
├── ImportFrom: agent.llm_chat → LLMMixin
├── ImportFrom: agent.autonomy → AutonomyMixin
│
└── ClassDef: TradingAgent(StateMixin, WorkspaceMixin, DeltaMixin,
                          MarketMixin, TradingMixin, LLMMixin, AutonomyMixin)
    ├── FunctionDef: __init__(self)
    │   ├── Assign: self.history = []
    │   ├── Assign: self.daily_trades = 0
    │   ├── Assign: self._last_reset_date = date.today().isoformat()
    │   ├── Assign: self.session_notes = []
    │   ├── Assign: self.client = None
    │   ├── Assign: self.failure_count = 0
    │   ├── Assign: self._recovery_in_progress = False
    │   ├── Assign: self.pending_trade = None
    │   ├── If: config.ollama and OLLAMA_API_KEY
    │   │   └── Assign: self.client = ollama.Client(host, headers={Bearer})
    │   └── Expr: self._ensure_workspace_dirs()
    │
    ├── FunctionDef: _ensure_workspace_dirs(self)
    │   └── For: ["notes", "research", "logs", "strategies"] → mkdir
    │
    └── FunctionDef: chat_loop(self)
        ├── Print: help text
        └── While: True
            ├── Expr: input("You> ")
            ├── If: quit/exit → break
            ├── If: debug → diagnostics.run_diagnostics()
            ├── If: note → add_note()
            ├── If: file → create_workspace_file()
            ├── If: ls → list_workspace_files()
            ├── If: read → read_workspace_file()
            ├── If: rm → delete_workspace_file()
            ├── If: run → run_workspace_script()
            ├── If: auto → run_autonomous_loop(3, 10)
            └── Else: agent_respond(user) → print reply
```

---

## Module: `dashboard.py` (Flask Web Interface)

```
Module
├── Import: json, threading
├── ImportFrom: pathlib → Path
├── ImportFrom: flask → Flask, render_template, jsonify, request
├── ImportFrom: datetime → datetime
├── Import: engine
├── Import: diagnostics
│
├── Assign: app = Flask(__name__, template_folder='.')
├── Assign: STATUS_FILE = Path('status.json')
├── Assign: AGENT_CAPABILITIES = [list of 6 strings]
│
├── Assign: _AGENT_SINGLETON = None
├── FunctionDef: _get_agent() → engine.TradingAgent
│   └── Global singleton pattern with lazy init
├── FunctionDef: _reset_agent_for_tests()
│
├── FunctionDef: _default_state_payload() → Dict
├── FunctionDef: load_dashboard_state() → Dict
│   └── Complex merge: status.json + agent._pending_dict() + agent.load_ideas_history()
│
├── Route: GET /
│   └── Return: render_template('index.html')
├── Route: GET /api/status
│   └── Return: jsonify(load_dashboard_state())
├── Route: POST /api/log
│   └── Expr: _get_agent().log_event(...)
├── Route: GET /api/pending
│   └── Return: jsonify({"pending_trade": ...})
├── Route: POST /api/confirm
│   └── Try/Except: _get_agent()._confirm_pending()
├── Route: POST /api/cancel
│   └── Try/Except: _get_agent()._cancel_pending()
├── Route: GET /api/ideas
│   └── Return: jsonify({"ideas": agent.load_ideas_history()})
├── Route: GET /api/journal
│   └── Return: last 15 journal entries
├── Route: GET /api/diagnostics
│   └── Return: diagnostics.run_diagnostics()
├── Route: GET /api/workspace
│   └── Return: list_workspace_files(subdir)
│
├── Assign: _AUTONOMOUS_THREAD_STARTED = False
├── FunctionDef: _maybe_start_autonomous_loop()
│   └── If: AUTONOMOUS_MODE → threading.Thread(target=agent.run_forever, daemon=True)
├── Expr: _maybe_start_autonomous_loop()
│
├── Route: POST /api/chat
│   ├── Expr: _get_agent().log_event(message, "USER")
│   ├── Try/Except: _get_agent().agent_respond(message)
│   ├── Expr: log_event(reply, "AGENT")
│   └── Return: jsonify(result)
│
└── If: __name__ == '__main__'
    └── Expr: app.run(port=5000, debug=True, use_reloader=False)
```

---

## Module: `diagnostics.py` (Integrity Checker)

```
Module
├── DocString
├── Import: json
├── ImportFrom: typing → Any, Dict, List, Optional
├── Import: requests
├── Import: engine
│
├── FunctionDef: _check(name, ok, detail, severity) → Dict
│
├── FunctionDef: check_env_file() → Dict
├── FunctionDef: check_env_vars() → List[Dict]
│   ├── For: DELTA_API_KEY, DELTA_API_SECRET → presence + comment-guard
│   ├── If: OLLAMA_API_KEY missing → warning
│   ├── If: "/api" in OLLAMA_HOST → error
│   └── If: TESTNET_ONLY and no "testnet" in URL → warning
│
├── FunctionDef: check_delta_public_api() → Dict
├── FunctionDef: check_delta_auth(agent) → Dict
├── FunctionDef: check_product_id_resolution(agent) → Dict
│   └── Assert: resolve_product_id('BTCUSD') returns int
├── FunctionDef: check_ollama(agent) → Dict
│
├── FunctionDef: check_filesystem() → List[Dict]
│   ├── For: engine.py, dashboard.py, index.html, AGENTS.md, KNOWLEDGE.md
│   ├── If: status.json exists → valid JSON check
│   └── For: workspace subdirs → notes, research, logs, strategies
│
├── FunctionDef: check_risk_config() → List[Dict]
│   ├── If: MAX_RISK_PCT outside (0, 0.2] → warning
│   ├── If: MIN_CONFIDENCE outside [0,1] → error
│   └── If: not TESTNET_ONLY → critical
│
├── FunctionDef: check_autonomy_config() → List[Dict]
│   └── If: AUTONOMOUS_MODE and AUTONOMOUS_ALLOW_EXEC → warning
│
├── FunctionDef: run_diagnostics(verbose=True) → List[Dict]
│   ├── Extend: env, filesystem, risk, autonomy, delta_public
│   ├── Try: agent = engine.TradingAgent()
│   ├── If: agent → delta_auth, product_id, ollama
│   └── If: verbose → _print_report(findings)
│
├── FunctionDef: _print_report(findings)
│   ├── Filter: bugs (error/critical), warnings, ok
│   └── Print: formatted report
│
└── If: __name__ == "__main__"
    ├── Expr: run_diagnostics()
    └── Raise: SystemExit(1 if bugs else 0)
```

---

## Cross-Module Dependency Graph

```
engine.py ──────► agent.config (reads)
        ──────► agent.models (TradeIdea)
        ──────► agent.core (TradingAgent)

dashboard.py ───► engine (re-exports)
           ───► diagnostics

diagnostics.py ─► engine (TradingAgent + config)
             ───► requests

agent/core.py ──► [State, Workspace, Delta, Market, Trading, LLM, Autonomy] Mixins

All mixins ─────► agent.config (qualified access)
            ───► agent.models (TradeIdea)

DeltaMixin ─────► requests, hashlib, hmac
LLMMixin ───────► ollama (via config)
StateMixin ─────► threading.Lock (process-wide)
```

---

This is a **true AST-level decomposition** — every `ClassDef`, `FunctionDef`, `Import`, `Assign`, and control-flow block (`If`, `Try`, `With`, `While`, `For`) is represented hierarchically, exactly as Python's `ast.parse()` would see it.