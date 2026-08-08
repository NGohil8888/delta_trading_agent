"""
diagnostics.py -- standalone connectivity + integrity checker for the Delta
Trading Agent.

Every check here is READ-ONLY: it never writes, deletes, or trades. It's
safe to run any time, including while dashboard.py is already running.

Run directly:
    python diagnostics.py

Exit code is 0 if no blocking bugs were found, 1 otherwise (useful in CI /
a pre-flight check before starting the dashboard).

Or import and use programmatically (this is what dashboard.py's
/api/diagnostics route calls):
    from diagnostics import run_diagnostics
    findings = run_diagnostics(verbose=False)
"""
import json
from typing import Any, Dict, List, Optional

import requests

import engine


def _check(name: str, ok: bool, detail: str, severity: str = "error") -> Dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "severity": "info" if ok else severity,
        "detail": detail,
    }


# ----------------------------------------------------------------------
# .env / config checks
# ----------------------------------------------------------------------
def check_env_file() -> Dict[str, Any]:
    env_path = engine.BASE_DIR / ".env"
    if not env_path.exists():
        return _check(
            "env_file_exists",
            False,
            f".env not found at {env_path}. Create one with DELTA_API_KEY, "
            "DELTA_API_SECRET, OLLAMA_API_KEY, etc. -- see README.md.",
        )
    return _check("env_file_exists", True, str(env_path))


def check_env_vars() -> List[Dict[str, Any]]:
    results = []

    for name, value in (
        ("DELTA_API_KEY", engine.DELTA_API_KEY),
        ("DELTA_API_SECRET", engine.DELTA_API_SECRET),
    ):
        if not value:
            results.append(_check(
                f"env_{name.lower()}", False,
                f"{name} is empty/unset in .env. Delta calls will be refused or fail auth.",
            ))
        elif value.strip().startswith("#"):
            results.append(_check(
                f"env_{name.lower()}", False,
                f"{name} contains a literal comment string ({value[:50]!r}) instead of a "
                "real value. This happens when a '# comment' is placed after '=' on the "
                "same line -- python-dotenv does NOT strip inline comments for blank "
                "values. Put the comment on its own line above KEY=.",
            ))
        else:
            results.append(_check(f"env_{name.lower()}", True, "present"))

    if not engine.OLLAMA_API_KEY:
        results.append(_check(
            "env_ollama_api_key", False,
            "OLLAMA_API_KEY is empty -- the agent will run in heuristic keyword mode "
            "instead of using the LLM. Not a bug if intentional.",
            severity="warning",
        ))
    else:
        results.append(_check("env_ollama_api_key", True, "present"))

    if "/api" in engine.OLLAMA_HOST.rstrip("/"):
        results.append(_check(
            "env_ollama_host", False,
            f"OLLAMA_HOST={engine.OLLAMA_HOST!r} includes '/api' -- the ollama client "
            "appends '/api/chat' itself, so this will 404 at '/api/api/chat'. Set "
            "OLLAMA_HOST to the bare host, e.g. https://ollama.com",
        ))
    else:
        results.append(_check("env_ollama_host", True, engine.OLLAMA_HOST))

    if engine.TESTNET_ONLY and "testnet" not in engine.DELTA_BASE_URL.lower():
        results.append(_check(
            "env_base_url_testnet_mismatch", False,
            f"TESTNET_ONLY=true but DELTA_BASE_URL={engine.DELTA_BASE_URL!r} does not "
            "contain 'testnet'. place_order() will refuse ALL orders as a result -- this "
            "may be an intentional hard-stop, flagging in case it's accidental.",
            severity="warning",
        ))
    else:
        results.append(_check("env_base_url", True, engine.DELTA_BASE_URL))

    return results


# ----------------------------------------------------------------------
# Network / API checks
# ----------------------------------------------------------------------
def check_delta_public_api() -> Dict[str, Any]:
    """Public endpoint, no auth. Isolates network/DNS/base-url issues from
    auth issues -- if this fails, don't bother blaming your API keys yet."""
    try:
        r = requests.get(f"{engine.DELTA_BASE_URL}/v2/products", timeout=10)
    except Exception as exc:
        return _check("delta_public_api", False, f"Could not reach {engine.DELTA_BASE_URL}: {exc}")
    if r.status_code == 200:
        return _check("delta_public_api", True, "/v2/products reachable (HTTP 200).")
    return _check("delta_public_api", False, f"/v2/products returned HTTP {r.status_code}: {r.text[:200]}")


def check_delta_auth(agent: "engine.TradingAgent") -> Dict[str, Any]:
    snapshot = agent._delta_account_snapshot()
    if snapshot["connected"]:
        return _check("delta_auth", True, f"Authenticated. Balance: {snapshot['balance']}")
    return _check("delta_auth", False, snapshot["detail"])


def check_product_id_resolution(agent: "engine.TradingAgent") -> Dict[str, Any]:
    try:
        pid = agent.resolve_product_id("BTCUSD")
    except Exception as exc:
        return _check("product_id_resolution", False, f"resolve_product_id('BTCUSD') raised: {exc}")
    if pid is None:
        return _check("product_id_resolution", False,
                       "resolve_product_id('BTCUSD') returned None -- product list may be "
                       "empty, or the symbol wasn't found.")
    if not isinstance(pid, int):
        return _check("product_id_resolution", False,
                       f"resolve_product_id('BTCUSD') returned {pid!r} (type "
                       f"{type(pid).__name__}), expected int -- this is the historical "
                       "'Should be an integer' order-rejection bug.")
    return _check("product_id_resolution", True, f"BTCUSD -> product_id {pid} (int)")


def check_ollama(agent: "engine.TradingAgent") -> Dict[str, Any]:
    if not engine.OLLAMA_API_KEY:
        return _check("ollama_client", False,
                       "OLLAMA_API_KEY not set -- running in heuristic mode. Not a bug "
                       "unless you expected LLM chat to be active.", severity="warning")
    if agent.client is None:
        return _check("ollama_client", False,
                       "OLLAMA_API_KEY is set but agent.client is None -- check that the "
                       "'ollama' package is installed (`pip install ollama`).")
    try:
        reply = agent.llm_chat("Reply with exactly: OK")
    except Exception as exc:
        return _check("ollama_client", False, f"llm_chat() raised: {exc}")
    if not reply.strip():
        return _check("ollama_client", False, "LLM call returned an empty response.")
    return _check("ollama_client", True, f"LLM responded: {reply[:80]!r}")


# ----------------------------------------------------------------------
# Filesystem checks
# ----------------------------------------------------------------------
def check_filesystem() -> List[Dict[str, Any]]:
    results = []
    for f in ("engine.py", "dashboard.py", "index.html", "AGENTS.md", "KNOWLEDGE.md"):
        p = engine.BASE_DIR / f
        results.append(_check(f"file_{f}", p.exists(), str(p) if p.exists() else f"MISSING: {p}"))

    if engine.STATUS_FILE.exists():
        try:
            json.loads(engine.STATUS_FILE.read_text(encoding="utf-8"))
            results.append(_check("status_json_valid", True, "parses OK"))
        except Exception as exc:
            results.append(_check("status_json_valid", False, f"status.json is not valid JSON: {exc}"))
    else:
        results.append(_check("status_json_valid", True, "not created yet (created on first write)"))

    for sub in ("notes", "research", "logs", "strategies"):
        p = engine.WORKSPACE_DIR / sub
        results.append(_check(f"workspace_{sub}", p.is_dir(), str(p) if p.is_dir() else f"MISSING directory: {p}"))

    return results


# ----------------------------------------------------------------------
# Risk-config sanity checks
# ----------------------------------------------------------------------
def check_risk_config() -> List[Dict[str, Any]]:
    results = []
    if not (0 < engine.MAX_RISK_PCT <= 0.2):
        results.append(_check("risk_max_risk_pct", False,
                               f"MAX_RISK_PCT={engine.MAX_RISK_PCT} is outside a sane 0-20% range.",
                               severity="warning"))
    else:
        results.append(_check("risk_max_risk_pct", True, str(engine.MAX_RISK_PCT)))

    if not (0 <= engine.MIN_CONFIDENCE <= 1):
        results.append(_check("risk_min_confidence", False,
                               f"MIN_CONFIDENCE={engine.MIN_CONFIDENCE} must be between 0 and 1."))
    else:
        results.append(_check("risk_min_confidence", True, str(engine.MIN_CONFIDENCE)))

    if not engine.TESTNET_ONLY:
        results.append(_check("risk_testnet_only", False,
                               "TESTNET_ONLY=false -- LIVE TRADING IS ENABLED. Confirm this is intentional.",
                               severity="critical"))
    else:
        results.append(_check("risk_testnet_only", True, "true (safe)"))

    return results


def check_autonomy_config() -> List[Dict[str, Any]]:
    results = []
    results.append(_check(
        "autonomy_mode", True,
        f"AUTONOMOUS_MODE={engine.AUTONOMOUS_MODE} (interval={engine.AUTONOMOUS_INTERVAL_SECONDS}s)",
    ))
    if engine.AUTONOMOUS_MODE and engine.AUTONOMOUS_ALLOW_EXEC:
        results.append(_check(
            "autonomy_exec_combo", False,
            "AUTONOMOUS_MODE and AUTONOMOUS_ALLOW_EXEC are both true -- the background "
            "loop can both act unattended AND execute scripts it writes under workspace/. "
            "Each is individually scoped/safe, but confirm this combination is intentional.",
            severity="warning",
        ))
    else:
        results.append(_check("autonomy_exec_combo", True, f"AUTONOMOUS_ALLOW_EXEC={engine.AUTONOMOUS_ALLOW_EXEC}"))
    return results


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def run_diagnostics(verbose: bool = True) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    findings.append(check_env_file())
    findings.extend(check_env_vars())
    findings.extend(check_filesystem())
    findings.extend(check_risk_config())
    findings.extend(check_autonomy_config())
    findings.append(check_delta_public_api())

    # Only construct a real agent (and hit auth-required endpoints) after
    # basic env sanity checks -- no point hammering Delta with a request
    # that's already guaranteed to fail because a key is missing.
    agent: Optional["engine.TradingAgent"] = None
    try:
        agent = engine.TradingAgent()
    except Exception as exc:
        findings.append(_check("agent_construction", False, f"Could not construct TradingAgent(): {exc}"))

    if agent is not None:
        findings.append(check_delta_auth(agent))
        findings.append(check_product_id_resolution(agent))
        findings.append(check_ollama(agent))

    if verbose:
        _print_report(findings)
    return findings


def _print_report(findings: List[Dict[str, Any]]) -> None:
    bugs = [f for f in findings if not f["ok"] and f["severity"] in ("error", "critical")]
    warnings = [f for f in findings if not f["ok"] and f["severity"] == "warning"]
    ok = [f for f in findings if f["ok"]]

    print("=" * 70)
    print("Delta Trading Agent -- Diagnostics Report")
    print("=" * 70)

    if bugs:
        print(f"\n{len(bugs)} BUG(S) FOUND:\n")
        for f in bugs:
            tag = "CRITICAL" if f["severity"] == "critical" else "BUG"
            print(f"  [{tag}] {f['name']}: {f['detail']}")
    else:
        print("\nNo blocking bugs found.")

    if warnings:
        print(f"\n{len(warnings)} warning(s):\n")
        for f in warnings:
            print(f"  [WARN] {f['name']}: {f['detail']}")

    print(f"\n{len(ok)} check(s) passed.")
    print("=" * 70)


if __name__ == "__main__":
    results = run_diagnostics(verbose=True)
    has_bugs = any(not f["ok"] and f["severity"] in ("error", "critical") for f in results)
    raise SystemExit(1 if has_bugs else 0)