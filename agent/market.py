"""agent/market.py -- MarketMixin: market scanning, ranked by liquidity."""
from typing import Any, Dict, List

from agent.delta_client import DeltaClientError


class MarketMixin:
    def market_snapshot(self, limit: int = 20) -> str:
        try:
            products = self.fetch_products()
        except DeltaClientError as exc:
            # Most commonly: DELTA_API_KEY/SECRET not set yet. `status` and
            # `scan` should degrade gracefully here, not crash the whole
            # chat turn -- this is a connectivity fact, not a bug.
            return f"Delta is not reachable right now: {exc}"
        if not products:
            return "No products available."
        lines = []
        for p in products[:limit]:
            name = p.get("symbol") or p.get("id") or p.get("name") or "unknown"
            lines.append(str(name))
        return "Available symbols: " + ", ".join(lines)

    def _liquid_candidates(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return liquid perpetual-futures tickers, ranked by 24h USD turnover.

        AGENTS.md: "Prefer liquid markets with clean structure and acceptable
        spread" / "Reject noisy, illiquid, or highly unstable setups." The
        raw /v2/products list is dominated by dated options contracts
        (C-BTC-..., P-ETH-...), so scanning it unfiltered surfaced options
        noise instead of tradeable perpetuals. Filtering to
        contract_types=perpetual_futures and sorting by turnover fixes that.
        """
        try:
            tickers = self.fetch_tickers(contract_types="perpetual_futures")
        except DeltaClientError:
            tickers = []
        candidates = []
        for t in tickers:
            symbol = t.get("symbol") or t.get("underlying_asset_symbol")
            if not symbol:
                continue
            turnover = (
                t.get("turnover")
                or t.get("turnover_usd")
                or t.get("volume")
                or 0
            )
            try:
                turnover = float(turnover)
            except (TypeError, ValueError):
                turnover = 0.0
            candidates.append({"symbol": symbol, "turnover": turnover})

        candidates.sort(key=lambda c: c["turnover"], reverse=True)
        return candidates[:limit]

    def scan_market(self, limit: int = 20) -> str:
        candidates = self._liquid_candidates(limit=limit)
        if not candidates:
            # Fall back to the raw product list only if the ticker endpoint
            # gave us nothing, so scanning still works if that endpoint is
            # ever unavailable -- but this path does NOT get the liquidity
            # filter, so say so explicitly rather than presenting it as a
            # normal ranked scan.
            try:
                products = self.fetch_products()
            except DeltaClientError as exc:
                return f"Delta is not reachable right now: {exc}"
            if not products:
                return "No products available for scanning."
            symbols = [p.get("symbol") or p.get("id") or p.get("name") or "unknown" for p in products[:limit]]
            self.add_note(
                "market_scan",
                f"Scanned {len(symbols)} instruments (UNFILTERED fallback -- ticker endpoint returned nothing).\n\n"
                "Candidates:\n- " + "\n- ".join(symbols),
            )
            return (
                "Ticker data was unavailable, so this is an unfiltered raw product dump "
                "(may include illiquid/options contracts): " + ", ".join(symbols)
            )

        lines = [f"- {c['symbol']} (turnover 24h: {int(c['turnover'])})" for c in candidates]
        self.add_note(
            "market_scan",
            f"Scanned {len(candidates)} perpetual futures (filtered by contract_type, ranked by 24h USD turnover).\n\n"
            "Candidates:\n" + "\n".join(lines),
        )
        symbols_only = ", ".join(c["symbol"] for c in candidates)
        return (
            f"Scanned {len(candidates)} liquid perpetual futures, ranked by 24h turnover.\n"
            f"Candidates: {symbols_only}"
        )