# Alpha Agent — Delta Trading Agent (Testnet)

A testnet-first trading assistant for Delta Exchange. It scans markets, proposes
structured trade ideas with risk controls, requires explicit human confirmation
before placing any order, and exposes everything through a live Flask dashboard
with chat.

**Nothing in this project places a live trade by default.** Orders are refused
unless `TESTNET_ONLY=true` (the default) *and* the configured base URL is a
recognized testnet endpoint. See [Safety guarantees](#safety-guarantees) below.

---

## Project structure

```
delta-trading-agent/
├── .env                      # your credentials + config (never commit this)
├── engine.py                 # thin compatibility facade -- re-exports agent/ for dashboard.py, diagnostics.py, and `python engine.py` CLI use
├── agent/                     # actual implementation, one module per concern
│   ├── config.py                # every env-derived constant (single source of truth -- see module docstring on why other files must import it as `config.X`, never `from agent.config import X`)
│   ├── models.py                 # TradeIdea dataclass
│   ├── state_store.py             # status.json / journal / ideas-history + the process locks
│   ├── workspace_tools.py          # sandboxed create/read/list/delete/run file toolkit, hard-scoped to workspace/
│   ├── delta_client.py              # Delta API: auth signing, requests, products/tickers, contract-size resolution, place_order
│   ├── market.py                     # liquidity-filtered market scanning
│   ├── trading.py                     # idea generation, risk-based position sizing, confirm/cancel gates
│   ├── llm_chat.py                     # Ollama plumbing, system prompt, action parsing/dispatch, heuristic fallback
│   ├── autonomy.py                      # heartbeat, lessons-learned, failure recovery, the autonomous scan loop
│   └── core.py                           # TradingAgent composed from every mixin above + the CLI chat loop
├── dashboard.py               # Flask app: dashboard API + chat endpoint (unchanged by the split -- still does `import engine`)
├── diagnostics.py              # standalone connectivity + integrity checker (`python diagnostics.py`, or /api/diagnostics)
├── index.html                   # dashboard frontend — served from project root
├── AGENTS.md                     # operating rules the LLM is prompted with every turn
├── README.md                      # this file
├── status.json                     # live agent state + recent log feed (auto-created)
├── templates/
│   └── index.html                    # deprecated tombstone — NOT served, see file header
├── test_engine.py                     # unit tests -- patch `agent.config`, not `engine`, for state isolation (see module docstring)
├── test_dashboard.py                   # unit tests for dashboard.py
├── __init__.py
��── workspace/                            # auto-created on first run, and the ONLY directory the agent's file tools can ever touch
    ├── agent_state.json                    # mirror of status.json
    ├── ideas_history.json                   # every proposed/confirmed/cancelled idea
    ├── notes/
    │   ├── agent_journal.md                    # full internal reasoning/action log
    │   ├── market_scan.md                       # most recent scan results
    │   └── lessons_learned.md                    # deduplicated list of distinct problems the autonomous loop has hit
    ├── logs/
    │   └── heartbeat.log                          # one line per autonomous-loop check-in (JSON lines)
    ├── research/                                   # notes the agent creates on request or autonomously
    └── strategies/                                   # saved strategy files
```

**Why the split:** `engine.py` grew to ~1,400 lines covering Delta's API, risk/sizing math, LLM dispatch, workspace file tools, and the autonomous loop all in one file. Each concern now lives in its own module under `agent/`, composed into one `TradingAgent` class via mixins in `agent/core.py`. `engine.py` stays as a thin facade so nothing importing it (`dashboard.py`, `diagnostics.py`) had to change.

**If you're adding tests:** `agent/config.py`'s docstring explains a real gotcha -- every module reads config via `from agent import config; config.SOMETHING`, never `from agent.config import SOMETHING`. The latter copies the value at import time, so patching `config.WORKSPACE_DIR` afterwards wouldn't be seen by code that already has its own copy. Always patch `agent.config.X`, not `engine.X` (which is now just a static snapshot for read-only external callers).

`dashboard.py` explicitly sets `template_folder='.'`, so `index.html` is served
from the **project root**, not from `templates/`. The file in `templates/` is
an intentional tombstone that explains this if you ever open it by mistake —
don't delete the comment at its top, and don't move the real UI back into
`templates/`.

---

## Setup

**1. Install dependencies**

```bash
pip install flask python-dotenv requests ollama
```

(A virtual environment is recommended: `python -m venv .venv`, then
`.venv\\Scripts\\Activate.ps1` on Windows or `source .venv/bin/activate` on
macOS/Linux, before running the pip install above.)

**2. Create your `.env` file** in the project root (see
[Environment variables](#environment-variables) for the full list):

```env
DELTA_BASE_URL=https://cdn-ind.testnet.deltaex.org
DELTA_API_KEY=your_testnet_key
DELTA_API_SECRET=your_testnet_secret

OLLAMA_HOST=https://ollama.com
OLLAMA_API_KEY=your_ollama_key
OLLAMA_MODEL=minimax-m3:cloud

TESTNET_ONLY=true
MAX_DAILY_TRADES=5
MAX_RISK_PCT=0.01
MIN_CONFIDENCE=0.55
```

Get testnet API keys at the Delta testnet platform (link below) — **never**
use production/mainnet keys here while `TESTNET_ONLY=true` is the intent.

**3. Run the dashboard**

```bash
python dashboard.py
```

Then open **http://localhost:5000**. The dashboard polls `/api/status` every
3 seconds, and the ideas/journal panels refresh every 5 seconds.

**4. (Optional) Run the engine directly from the CLI**, without the web UI:

```bash
python engine.py
```

This drops you into a chat loop (`chat_loop()` in `engine.py`).

---

## Using it

### From the dashboard chat
Type things like:
- `scan` — scan liquid perpetual futures, ranked by 24h turnover
- `status` — daily trade count + available symbols
- `take BTC long with a 60000 entry, 58500 stop, 63000 target`
- `confirm` / `cancel` — approve or drop the currently pending trade idea

The pending-trade card at the top of the dashboard also has **Confirm** /
**Cancel** buttons that call the same endpoints.

### From the CLI (`python engine.py`)
- `scan` — same market scan as above
- `idea BTCUSD` — propose a trade idea for a symbol
- `note <title>` — save a research note to `workspace/notes/`
- `file <name>` — create an arbitrary workspace file
- `auto` — run 3 autonomous scan cycles, 10s apart
- `quit` / `exit` — leave the chat loop

### Without an LLM configured
If `OLLAMA_API_KEY` is unset, the agent runs in **heuristic keyword mode**
instead of failing — it still understands `scan`, `status`, `idea <symbol>`,
`confirm`/`cancel`, and `long`/`short <symbol>`, just without free-form
natural-language understanding. The chat reply says so explicitly when this
mode is active.

---

## How the AI Makes Trade Decisions

The agent operates in two distinct modes depending on whether an LLM is configured:

### 1. Heuristic/Fallback Mode (Default - No LLM Configured)
When `OLLAMA_API_KEY` is not set in `.env`, the agent uses a simple rule-based approach:
- For symbols containing BTC, ETH, SOL, XRP, or DOGE: generates a BUY idea with fixed 0.62 confidence
- For all other symbols: returns no trade idea
- Entry, stop loss, take profit, and size are calculated from:
  - Live ticker data (current market price)
  - Account balance and `MAX_RISK_PCT` for position sizing
- **No historical data, technical indicators, or pattern analysis is used**

### 2. LLM Analysis Mode (When `OLLAMA_API_KEY` is Configured)
When an Ollama API key is provided, the agent uses a language model for decision making:
- The LLM receives a prompt containing:
  - System instructions from `AGENTS.md` (operating rules and risk management)
  - Technical reference from `KNOWLEDGE.md` (Delta Exchange API documentation)
  - Current agent state (daily trade count, connection status, pending trade)
  - Your specific request (e.g., "idea BTCUSD")
- The LLM is instructed to return a JSON trade proposal with: symbol, side, entry, stop_loss, take_profit, size, confidence, and rationale
- **Analysis basis**:
  - General market knowledge from the LLM's training data
  - Reasoning based on the provided context (instructions, API reference, current state)
  - **Does NOT receive**: historical price data, technical indicators, order book data, or news feeds
- The heuristic fallback is used if the LLM call fails or returns invalid JSON

### Important Limitations
- Neither mode accesses historical price data for technical analysis
- The agent does not perform backtesting or strategy optimization
- All trade ideas are subject to risk management gates:
  - Confidence must be ≥ `MIN_CONFIDENCE` (default 0.55)
  - Daily trades must be < `MAX_DAILY_TRADES` (default 5)
  - Orders only execute after explicit human confirmation (unless `AUTONOMOUS_ALLOW_EXEC=true` is configured, which is not recommended for live trading)

### To Improve Analysis Quality
1. Configure an LLM API key (`OLLAMA_API_KEY` in `.env`)
2. Consider enhancing the prompt in `agent/llm_chat.py:_build_system_prompt()` to include:
   - Recent market data
   - Technical indicator calculations
   - Custom trading strategy rules
3. The current design prioritizes transparency and safety over black-box AI decision making

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DELTA_BASE_URL` (or `BASE_URL`) | `https://cdn-ind.testnet.deltaex.org` | Delta API base URL. Must contain `testnet` for orders to be allowed — see [Safety guarantees](#safety-guarantees). |
| `DELTA_API_KEY` | — | Delta Exchange API key. |
| `DELTA_API_SECRET` | — | Delta Exchange API secret, used to HMAC-sign requests. |
| `OLLAMA_HOST` | `https://ollama.com` | Ollama client host. Do **not** include `/api` — the client appends it itself. Use `http://localhost:11434` for a local Ollama install. |
| `OLLAMA_MODEL` | `minimax-m3:cloud` | Model tag to chat with. |
| `OLLAMA_API_KEY` | — | Required for Ollama Cloud. Without it, the agent falls back to heuristic mode (see above). |
| `ACCOUNT_BALANCE` / `BALANCE_OVERRIDE` | — | Manually override the displayed/used balance instead of fetching it live from Delta. `BALANCE_OVERRIDE` wins if both are set. |
| `MAX_DAILY_TRADES` | `5` | Hard cap on confirmed trades per calendar day (resets at midnight local). |
| `MAX_RISK_PCT` | `0.01` | Used both to compute default stop-loss/take-profit distance from entry, and to size positions (see below). |
| `MIN_CONFIDENCE` | `0.55` | Trades proposed below this confidence are refused at confirm time (`blocked_low_confidence`). |
| `TESTNET_ONLY` | `true` | Master safety switch. Must be explicitly set to `false` **and** `DELTA_BASE_URL` must not contain \"testnet\" for any order to go through. |
| `AUTONOMOUS_MODE` | `false` | Enables autonomous scanning and proposal generation (does not auto-execute trades). |
| `AUTONOMOUS_INTERVAL_SECONDS` | `300` | Interval in seconds between autonomous scan cycles when `AUTONOMOUS_MODE=true`. |
| `AUTONOMOUS_ALLOW_EXEC` | `false` | When true, allows autonomous execution of trades without manual confirmation (requires `AUTONOMOUS_MODE=true`). |

### Position sizing
If a trade idea doesn't specify a `size`, the agent computes one instead of
using a fixed default:

```
size = (balance × MAX_RISK_PCT) / |entry − stop_loss|
```

So a $200 balance with `MAX_RISK_PCT=0.01` and a $1,500-wide stop risks $2 of
capital, sized accordingly. If balance or stop distance can't be determined,
it falls back to a conservative `0.01`.

---

## Safety guarantees

- **No live orders by default.** `place_order()` refuses to submit anything
  unless `TESTNET_ONLY=true` *and* `DELTA_BASE_URL` contains `testnet`. Both
  conditions are checked on every single order, not just at startup.
- **Explicit confirmation required.** A trade idea only exists as
  `pending_trade` until the user (via chat or the dashboard button) explicitly
  confirms it. Nothing executes automatically.
- **Confidence and daily-limit gates.** Confirmation is refused if the idea's
  confidence is below `MIN_CONFIDENCE`, or if `MAX_DAILY_TRADES` has already
  been hit for the day.
- **Everything is logged.** Every meaningful action — scans, proposals,
  confirmations, rejections, errors, recovery attempts — is written to both
  `status.json` (for the dashboard) and `workspace/notes/agent_journal.md`
  (full detail).
- **Credentials are off-limits to the agent.** Per `AGENTS.md`, the agent must
  never modify `.env`, rotate/revoke credentials, or write outside the project
  directory without explicit, in-the-moment user confirmation. If you ever see
  the journal claim otherwise, treat it as unverified until you've checked
  `.env` yourself.

---

## Running the tests

```bash
python -m unittest test_engine.py test_dashboard.py -v
```

Both test files patch `engine.WORKSPACE_DIR` **and** `engine.STATUS_FILE` to a
temp directory before touching the agent. Don't remove the `STATUS_FILE` patch
if you add new tests — without it, `handle_failure`/`log_event` write straight
into your real project's `status.json`, which previously caused real dashboard
state to fill up with synthetic test failures.

---

## Official Delta references

- API documentation: https://docs.delta.exchange/
- Testnet platform: https://testnet.delta.exchange/
- Testnet API base URL: `https://cdn-ind.testnet.deltaex.org`
- Delta Exchange (India): https://www.delta.exchange/
- Available indices and symbols: https://www.delta.exchange/indices
- Production API base URL: `https://api.india.delta.exchange`

The same documentation covers both production and testnet — the only
difference is the base URL. Endpoints, parameters, and authentication are
identical, which is exactly why `place_order()`'s testnet check matters: a
correct API call against the wrong base URL is still a live trade.

---

## Operational mandate

- Strict risk management on every trade.
- Testnet-first behavior by default; live trading requires explicit,
  verified opt-in.
- Prefer high-quality, high-confidence setups over trade frequency.
- Never fabricate balances, fills, signals, or file operations — if
  something can't be verified, say so rather than asserting it happened.