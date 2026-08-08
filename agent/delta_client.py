"""Delta Exchange API client boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

from agent import config
from agent.delta_product_adapter import DeltaProductAdapter
from agent.product_specs import ProductSpec, ProductSpecError


class DeltaAPITransport(Protocol):
    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]: ...
    def post(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class DeltaAccount:
    equity: float
    available_balance: Optional[float] = None


class DeltaClientError(RuntimeError):
    pass


class DeltaAPIError(DeltaClientError):
    pass


class DeltaResponseError(DeltaClientError):
    pass


class DeltaClient:
    PRODUCTS_PATH = "/v2/products"
    PRODUCT_PATH = "/v2/products/{symbol}"
    TICKERS_PATH = "/v2/tickers"
    TICKER_PATH = "/v2/tickers/{symbol}"
    ORDERS_PATH = "/v2/orders"
    ACCOUNT_BALANCE_PATH = "/v2/wallet/balances"

    def __init__(self, transport: DeltaAPITransport) -> None:
        self.transport = transport
        self.products = DeltaProductAdapter(self)

    def fetch_products(self) -> list[Mapping[str, Any]]:
        response = self.transport.get(self.PRODUCTS_PATH)
        data = self._extract_result(response)
        if not isinstance(data, list):
            raise DeltaResponseError("Delta products response did not contain a list.")
        return [item for item in data if isinstance(item, Mapping)]

    def fetch_product(self, symbol: str) -> Optional[Mapping[str, Any]]:
        symbol = self._require_symbol(symbol)
        response = self.transport.get(self.PRODUCT_PATH.format(symbol=symbol))
        data = self._extract_result(response)
        if data is None:
            return None
        if not isinstance(data, Mapping):
            raise DeltaResponseError(f"Delta product response for {symbol} was not an object.")
        return data

    def refresh_products(self) -> int:
        return self.products.refresh()

    def get_product(self, symbol: str) -> ProductSpec:
        return self.products.require(symbol)

    def get_orderable_product(self, symbol: str) -> ProductSpec:
        return self.products.require_orderable_product(symbol)

    def get_contract_value(self, symbol: str) -> float:
        return self.products.require_contract_value(symbol)

    def get_product_id(self, symbol: str) -> int:
        return self.products.require_product_id(symbol)

    def fetch_tickers(self, contract_types: Optional[str] = None) -> list[Mapping[str, Any]]:
        """Bulk ticker list, optionally filtered (e.g. contract_types=
        'perpetual_futures'). See KNOWLEDGE.md: the raw /v2/products list
        is dominated by dated options contracts, so market.py filters here
        rather than scanning every product individually."""
        params = {"contract_types": contract_types} if contract_types else None
        response = self.transport.get(self.TICKERS_PATH, params)
        data = self._extract_result(response)
        if not isinstance(data, list):
            raise DeltaResponseError("Delta tickers response did not contain a list.")
        return [item for item in data if isinstance(item, Mapping)]

    def fetch_ticker(self, symbol: str) -> Mapping[str, Any]:
        symbol = self._require_symbol(symbol)
        response = self.transport.get(self.TICKER_PATH.format(symbol=symbol))
        data = self._extract_result(response)
        if not isinstance(data, Mapping):
            raise DeltaResponseError(f"Delta ticker response for {symbol} was not an object.")
        return data

    def fetch_account_balance(self, asset_symbol: str = "USD") -> DeltaAccount:
        response = self.transport.get(self.ACCOUNT_BALANCE_PATH)
        data = self._extract_result(response)
        if not isinstance(data, list):
            raise DeltaResponseError("Delta balance response did not contain a list.")

        wanted = asset_symbol.upper()
        for balance in data:
            if not isinstance(balance, Mapping):
                continue
            symbol = str(
                balance.get("asset_symbol")
                or balance.get("symbol")
                or balance.get("asset")
                or ""
            ).upper()
            if symbol != wanted:
                continue

            equity = self._first_number(
                balance, ("equity", "balance", "wallet_balance", "available_balance")
            )
            if equity is None:
                raise DeltaResponseError(
                    f"Delta balance for {wanted} did not expose a usable equity/balance value."
                )

            available = self._first_number(
                balance, ("available_balance", "available", "free")
            )
            return DeltaAccount(equity=equity, available_balance=available)

        raise DeltaResponseError(f"Delta account balance for {wanted} was not found.")

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        size: int,
        order_type: str,
        limit_price: Optional[float] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> Mapping[str, Any]:
        spec = self.get_orderable_product(symbol)

        if size <= 0:
            raise DeltaClientError("Order size must be greater than zero.")

        side = side.lower().strip()
        if side not in {"buy", "sell"}:
            raise DeltaClientError("Order side must be 'buy' or 'sell'.")

        order_type = order_type.lower().strip()
        if order_type not in {"market_order", "limit_order"}:
            raise DeltaClientError(
                "Order type must be 'market_order' or 'limit_order'."
            )

        if order_type == "limit_order" and (limit_price is None or limit_price <= 0):
            raise DeltaClientError(
                "A positive limit_price is required for limit orders."
            )

        if reduce_only:
            raise DeltaClientError(
                "reduce_only orders are not accepted by place_order(); "
                "use a dedicated close-position path."
            )

        payload: dict[str, Any] = {
            "product_id": spec.product_id,
            "size": int(size),
            "side": side,
            "order_type": order_type,
        }
        if limit_price is not None:
            payload["limit_price"] = limit_price
        if client_order_id:
            payload["client_order_id"] = client_order_id

        return self._extract_result_object(
            self.transport.post(self.ORDERS_PATH, payload)
        )

    @staticmethod
    def _extract_result(response: Mapping[str, Any]) -> Any:
        if not isinstance(response, Mapping):
            raise DeltaResponseError("Delta response was not a mapping.")

        if response.get("success") is False:
            message = response.get("error") or response.get("message") or "Delta API request failed."
            raise DeltaAPIError(str(message))

        if "result" not in response:
            raise DeltaResponseError("Delta response did not contain a result field.")

        return response["result"]

    @classmethod
    def _extract_result_object(cls, response: Mapping[str, Any]) -> Mapping[str, Any]:
        data = cls._extract_result(response)
        if not isinstance(data, Mapping):
            raise DeltaResponseError("Delta response did not contain an object.")
        return data

    @staticmethod
    def _first_number(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Optional[float]:
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _require_symbol(symbol: str) -> str:
        normalized = str(symbol).strip().upper()
        if not normalized:
            raise DeltaClientError("Symbol is required.")
        return normalized


class DeltaMixin:
    """Wires the transport-agnostic DeltaClient above into TradingAgent,
    and restores the TESTNET_ONLY safety gate the README documents.

    DeltaClient itself is intentionally transport-agnostic and has no
    opinion about testnet vs mainnet -- that's a policy decision, not a
    protocol detail, so it belongs here, not in delta_client.DeltaClient.
    place_order() below re-checks it on every call (not just once at
    startup), so flipping DELTA_BASE_URL mid-session can't bypass it.

    This mixin also exposes the plain method names market.py, trading.py,
    and core.py's CLI already call (fetch_products, fetch_tickers,
    fetch_ticker, fetch_account_balance, place_order(idea)) instead of
    DeltaClient's lower-level, exception-raising interface, so callers
    don't need their own try/except around every call.
    """

    _delta: Optional["DeltaClient"] = None

    def _get_delta(self) -> "DeltaClient":
        if self._delta is None:
            if not config.DELTA_API_KEY or not config.DELTA_API_SECRET:
                raise DeltaClientError(
                    "DELTA_API_KEY / DELTA_API_SECRET are not set in .env -- "
                    "cannot talk to the Delta API without them."
                )
            # Imported lazily so importing agent.delta_client (and running
            # its unit tests against FakeTransport) never requires the
            # `requests` package to be installed.
            from agent.delta_transport import DeltaRequestsTransport

            transport = DeltaRequestsTransport(
                base_url=config.DELTA_BASE_URL,
                api_key=config.DELTA_API_KEY,
                api_secret=config.DELTA_API_SECRET,
            )
            self._delta = DeltaClient(transport)
        return self._delta

    def fetch_products(self) -> list[Mapping[str, Any]]:
        return self._get_delta().fetch_products()

    def fetch_tickers(self, contract_types: Optional[str] = None) -> list[Mapping[str, Any]]:
        return self._get_delta().fetch_tickers(contract_types=contract_types)

    def fetch_ticker(self, symbol: str) -> Mapping[str, Any]:
        return self._get_delta().fetch_ticker(symbol)

    def _delta_account_snapshot(self) -> Dict[str, Any]:
        """Cheap connectivity/balance check used by the dashboard status
        badge (state_store.write_agent_state), the heartbeat log
        (autonomy.heartbeat), and the `status` chat command
        (llm_chat._status_text). Never raises -- callers need a snapshot
        even when Delta isn't configured or is unreachable, so failures
        are reported in the "connected": False / "detail" fields instead."""
        if not config.DELTA_API_KEY or not config.DELTA_API_SECRET:
            return {
                "connected": False,
                "detail": "DELTA_API_KEY/DELTA_API_SECRET not set in .env.",
                "balance": None,
            }
        try:
            balance = self.fetch_account_balance()
            return {"connected": True, "detail": "OK", "balance": balance}
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: this
            # is a status/health check, not a code path that should ever
            # crash the caller (dashboard polling, heartbeat log, chat
            # "status" command all need a snapshot regardless of *why*
            # Delta is unreachable).
            return {"connected": False, "detail": str(exc), "balance": None}

    def fetch_account_balance(self, asset_symbol: str = "USD") -> float:
        # Legacy callers (agent/trading.py's _compute_position_size) expect
        # a plain number they can pass straight to float(), not a
        # DeltaAccount object.
        return self._get_delta().fetch_account_balance(asset_symbol).equity

    def place_order(self, idea: Any) -> Tuple[int, Mapping[str, Any]]:
        """Legacy-compatible surface: returns (http_like_code, response)
        instead of raising, because agent/trading.py's _confirm_pending
        branches on a (code, res) tuple rather than a try/except.

        Safety gate, checked on every call: README says orders are
        refused unless TESTNET_ONLY=true AND DELTA_BASE_URL is a
        recognized testnet endpoint. That is enforced here -- this build
        intentionally has no path to a live order; enabling that is a
        deliberate code change, not just an env var flip.
        """
        if not (config.TESTNET_ONLY and "testnet" in config.DELTA_BASE_URL.lower()):
            return 403, {
                "error": (
                    "Refusing to place order: TESTNET_ONLY must be true and "
                    "DELTA_BASE_URL must be a testnet endpoint. "
                    f"(TESTNET_ONLY={config.TESTNET_ONLY!r}, "
                    f"DELTA_BASE_URL={config.DELTA_BASE_URL!r})"
                )
            }

        try:
            client = self._get_delta()
            spec = client.get_orderable_product(idea.symbol)
            side = "buy" if str(idea.side).lower() == "buy" else "sell"

            # KNOWLEDGE.md: Delta's order `size` is an INTEGER count of
            # contracts, not a fractional underlying quantity -- convert
            # using contract_value, falling back to treating the given
            # size as already being a contract count if Delta didn't
            # provide contract_value for this product.
            if spec.has_contract_value:
                contracts = max(1, round(abs(float(idea.size)) / spec.contract_value))
            else:
                contracts = max(1, round(abs(float(idea.size))))

            result = client.place_order(
                symbol=idea.symbol,
                side=side,
                size=contracts,
                order_type="market_order",
            )
            return 200, dict(result)
        except DeltaClientError as exc:
            return 400, {"error": str(exc)}

    def attach_bracket_to_position(
        self, symbol: str, side: str, stop_loss: float, take_profit: float
    ) -> Tuple[int, Mapping[str, Any]]:
        # Referenced by core.py's `protect SYMBOL SIDE STOP TARGET` CLI
        # command but was never implemented -- and I'm not implementing it
        # now either. Delta's bracket/conditional-order request shape
        # (endpoint, field names, trigger semantics) isn't in KNOWLEDGE.md
        # and I won't guess it: a malformed conditional order on a real
        # account is worse than this command just refusing. Verify the
        # exact payload against https://docs.delta.exchange/ before
        # wiring this up for real.
        raise NotImplementedError(
            "attach_bracket_to_position is not implemented. Delta's bracket-"
            "order API shape needs to be confirmed against "
            "https://docs.delta.exchange/ first -- see the comment here "
            "and in KNOWLEDGE.md before adding it."
        )


__all__ = [
    "DeltaAPIError",
    "DeltaAPITransport",
    "DeltaAccount",
    "DeltaClient",
    "DeltaClientError",
    "DeltaMixin",
    "DeltaResponseError",
]
