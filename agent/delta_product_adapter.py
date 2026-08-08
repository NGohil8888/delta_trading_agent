"""
agent/delta_product_adapter.py

Safe product-metadata adapter for Delta Exchange.

Responsibilities:
- obtain raw products from an object exposing fetch_products/fetch_product
- normalize them through ProductSpec/ProductRegistry
- refuse to invent contract values
- provide one authoritative product lookup for risk/execution layers

This module does not place orders and does not calculate trading signals.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol

from agent.product_specs import (
    ProductRegistry,
    ProductSpec,
    ProductSpecError,
)


class DeltaProductClient(Protocol):
    def fetch_products(self) -> list[Mapping[str, Any]]:
        ...

    def fetch_product(self, symbol: str) -> Optional[Mapping[str, Any]]:
        ...


class DeltaProductAdapter:
    """Cache and normalize Delta product metadata."""

    def __init__(self, client: DeltaProductClient) -> None:
        self.client = client
        self.registry = ProductRegistry()
        self._loaded = False

    def refresh(self) -> int:
        """Reload all available products from Delta.

        Returns the number of successfully loaded products.

        An empty/failed API response is not treated as valid metadata.
        Existing cached metadata is retained in that case.
        """
        products = self.client.fetch_products()

        if not products:
            raise ProductSpecError(
                "Delta returned no products; refusing to replace the "
                "existing product registry."
            )

        new_registry = ProductRegistry()
        loaded = new_registry.add_many(list(products))

        self.registry = new_registry
        self._loaded = True
        return len(loaded)

    def get(self, symbol: str) -> Optional[ProductSpec]:
        """Return cached product metadata, or None if not loaded."""
        if not self._loaded:
            return None
        return self.registry.get(symbol)

    def require(self, symbol: str) -> ProductSpec:
        """Return cached metadata and fail closed when unavailable."""
        if not self._loaded:
            self.refresh()

        spec = self.registry.get(symbol)
        if spec is None:
            raise ProductSpecError(
                f"Delta product metadata unavailable for {symbol}."
            )
        return spec

    def refresh_product(self, symbol: str) -> ProductSpec:
        """Fetch one product directly and update the registry."""
        raw = self.client.fetch_product(symbol)

        if not raw:
            raise ProductSpecError(
                f"Delta returned no product metadata for {symbol}."
            )

        return self.registry.add(raw)

    def require_contract_value(self, symbol: str) -> float:
        """Return the live product contract value; never guess it."""
        spec = self.require(symbol)

        if not spec.has_contract_value:
            raise ProductSpecError(
                f"{spec.symbol}: Delta did not provide a valid "
                "contract_value; refusing to calculate contract size."
            )

        return float(spec.contract_value)

    def require_product_id(self, symbol: str) -> int:
        """Return the Delta product ID from normalized metadata."""
        return self.require(symbol).product_id

    def require_orderable_product(self, symbol: str) -> ProductSpec:
        """Fail closed unless Delta reports normal trading availability."""
        spec = self.require(symbol)

        if not spec.is_live:
            raise ProductSpecError(
                f"{spec.symbol}: product state is {spec.state!r}; "
                "new orders are not permitted."
            )

        if not spec.can_place_orders:
            raise ProductSpecError(
                f"{spec.symbol}: trading status is "
                f"{spec.trading_status!r}; new orders are not permitted."
            )

        if spec.is_reduce_only:
            raise ProductSpecError(
                f"{spec.symbol}: product currently permits "
                "reduce-only orders."
            )

        return spec

    def symbols(self) -> list[str]:
        return self.registry.symbols()

    def clear(self) -> None:
        self.registry.clear()
        self._loaded = False


__all__ = [
    "DeltaProductAdapter",
    "DeltaProductClient",
]
