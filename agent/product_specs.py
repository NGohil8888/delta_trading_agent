"""
agent/product_specs.py

Normalized Delta Exchange product specifications.

This module is intentionally independent of HTTP and order execution.
It converts raw Delta product metadata into a stable ProductSpec object.

Important: contract_value is never guessed. If Delta does not provide it,
the value remains None and downstream sizing must refuse to assume one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class ProductSpecError(ValueError):
    """Raised when a product payload cannot be safely normalized."""


@dataclass(frozen=True)
class ProductSpec:
    symbol: str
    product_id: int
    contract_value: Optional[float]
    contract_unit: Optional[str]
    tick_size: Optional[float]
    quantity_step: Optional[float]
    min_order_size: Optional[float]
    max_order_size: Optional[float]
    contract_type: Optional[str]
    underlying_asset_symbol: Optional[str]
    settlement_asset_symbol: Optional[str]
    state: Optional[str]
    trading_status: Optional[str]
    is_reduce_only: bool
    raw: Mapping[str, Any]

    @property
    def has_contract_value(self) -> bool:
        return self.contract_value is not None and self.contract_value > 0

    @property
    def is_live(self) -> bool:
        """Delta reports lifecycle state via `state` (e.g. "live",
        "upcoming", "expired", "settled"). Only "live" products should
        accept new orders."""
        return self.state == "live"

    @property
    def can_place_orders(self) -> bool:
        """Delta reports the market's current trading mode via
        `trading_status` (e.g. "operational", "disrupted_cancel_only",
        "disrupted_post_only"). Only "operational" allows new orders --
        anything else means the exchange has restricted trading on this
        product even though it's still nominally "live"."""
        return self.trading_status == "operational"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "product_id": self.product_id,
            "contract_value": self.contract_value,
            "contract_unit": self.contract_unit,
            "tick_size": self.tick_size,
            "quantity_step": self.quantity_step,
            "min_order_size": self.min_order_size,
            "max_order_size": self.max_order_size,
            "contract_type": self.contract_type,
            "underlying_asset_symbol": self.underlying_asset_symbol,
            "settlement_asset_symbol": self.settlement_asset_symbol,
            "state": self.state,
            "trading_status": self.trading_status,
            "is_reduce_only": self.is_reduce_only,
        }


def _first(product: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = product.get(key)
        if value is not None and value != "":
            return value
    return None


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductSpecError(f"Expected numeric value, got {value!r}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ProductSpecError(f"Value must be positive and finite: {value!r}")
    return number


def _required_int(value: Any, field_name: str) -> int:
    if value is None or value == "":
        raise ProductSpecError(f"Missing product field: {field_name}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProductSpecError(
            f"{field_name} must be an integer: {value!r}"
        ) from exc
    if number <= 0:
        raise ProductSpecError(f"{field_name} must be greater than zero")
    return number


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def product_spec_from_delta(product: Mapping[str, Any]) -> ProductSpec:
    """Normalize one raw Delta /v2/products record."""
    if not isinstance(product, Mapping):
        raise ProductSpecError("Product payload must be a mapping")

    symbol = str(product.get("symbol") or "").strip().upper()
    if not symbol:
        raise ProductSpecError("Missing product field: symbol")

    product_id = _required_int(
        _first(product, "id", "product_id"),
        "id/product_id",
    )

    contract_value = _optional_float(
        _first(product, "contract_value", "contract_unit_value")
    )
    tick_size = _optional_float(
        _first(product, "tick_size", "price_increment")
    )
    quantity_step = _optional_float(
        _first(product, "quantity_step", "size_increment", "lot_size")
    )
    min_order_size = _optional_float(
        _first(
            product,
            "minimum_order_size",
            "min_order_size",
            "minimum_size",
        )
    )
    max_order_size = _optional_float(
        _first(
            product,
            "maximum_order_size",
            "max_order_size",
            "maximum_size",
        )
    )

    if (
        min_order_size is not None
        and max_order_size is not None
        and min_order_size > max_order_size
    ):
        raise ProductSpecError(
            f"{symbol}: minimum order size exceeds maximum order size"
        )

    return ProductSpec(
        symbol=symbol,
        product_id=product_id,
        contract_value=contract_value,
        contract_unit=_optional_string(
            _first(product, "contract_unit", "unit")
        ),
        tick_size=tick_size,
        quantity_step=quantity_step,
        min_order_size=min_order_size,
        max_order_size=max_order_size,
        contract_type=_optional_string(product.get("contract_type")),
        underlying_asset_symbol=_optional_string(
            product.get("underlying_asset_symbol")
        ),
        settlement_asset_symbol=_optional_string(
            product.get("settlement_asset_symbol")
        ),
        state=_optional_string(product.get("state")),
        trading_status=_optional_string(product.get("trading_status")),
        is_reduce_only=bool(
            (product.get("product_specs") or {}).get(
                "only_reduce_only_orders_allowed", False
            )
        ),
        raw=dict(product),
    )


class ProductRegistry:
    """In-memory registry of normalized product specifications."""

    def __init__(self) -> None:
        self._by_symbol: dict[str, ProductSpec] = {}
        self._by_id: dict[int, ProductSpec] = {}

    def add(self, product: Mapping[str, Any] | ProductSpec) -> ProductSpec:
        spec = (
            product
            if isinstance(product, ProductSpec)
            else product_spec_from_delta(product)
        )
        self._by_symbol[spec.symbol] = spec
        self._by_id[spec.product_id] = spec
        return spec

    def add_many(self, products: list[Mapping[str, Any]]) -> list[ProductSpec]:
        return [self.add(product) for product in products]

    def get(self, symbol: str) -> Optional[ProductSpec]:
        return self._by_symbol.get(str(symbol or "").strip().upper())

    def get_by_id(self, product_id: int) -> Optional[ProductSpec]:
        try:
            return self._by_id.get(int(product_id))
        except (TypeError, ValueError):
            return None

    def require(self, symbol: str) -> ProductSpec:
        spec = self.get(symbol)
        if spec is None:
            raise ProductSpecError(f"No product specification loaded for {symbol}")
        return spec

    def symbols(self) -> list[str]:
        return sorted(self._by_symbol)

    def __len__(self) -> int:
        return len(self._by_symbol)


__all__ = [
    "ProductSpec",
    "ProductSpecError",
    "ProductRegistry",
    "product_spec_from_delta",
]
