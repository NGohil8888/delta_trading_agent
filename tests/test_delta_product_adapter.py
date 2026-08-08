"""Tests for the Delta product integration adapter."""

import unittest

from agent.delta_product_adapter import DeltaProductAdapter
from agent.product_specs import ProductSpecError


def btc_product():
    return {
        "id": 27,
        "symbol": "BTCUSD",
        "contract_value": "0.001",
        "contract_unit_currency": "BTC",
        "tick_size": "0.5",
        "contract_type": "perpetual_futures",
        "state": "live",
        "trading_status": "operational",
        "product_specs": {
            "only_reduce_only_orders_allowed": False,
        },
    }


class FakeDeltaClient:
    def __init__(self, products=None):
        self.products = products if products is not None else [btc_product()]
        self.product_calls = 0

    def fetch_products(self):
        return list(self.products)

    def fetch_product(self, symbol):
        self.product_calls += 1
        for product in self.products:
            if product["symbol"].upper() == symbol.upper():
                return dict(product)
        return None


class TestDeltaProductAdapter(unittest.TestCase):
    def test_refresh_loads_normalized_products(self):
        adapter = DeltaProductAdapter(FakeDeltaClient())

        count = adapter.refresh()

        self.assertEqual(count, 1)
        self.assertEqual(adapter.require_product_id("BTCUSD"), 27)
        self.assertAlmostEqual(
            adapter.require_contract_value("BTCUSD"),
            0.001,
        )

    def test_require_lazy_loads_registry(self):
        adapter = DeltaProductAdapter(FakeDeltaClient())

        spec = adapter.require("btcusd")

        self.assertEqual(spec.symbol, "BTCUSD")
        self.assertEqual(spec.product_id, 27)

    def test_missing_contract_value_fails_closed(self):
        raw = btc_product()
        raw.pop("contract_value")

        adapter = DeltaProductAdapter(FakeDeltaClient([raw]))

        with self.assertRaises(ProductSpecError):
            adapter.require_contract_value("BTCUSD")

    def test_non_live_product_is_rejected_for_new_orders(self):
        raw = btc_product()
        raw["state"] = "expired"

        adapter = DeltaProductAdapter(FakeDeltaClient([raw]))

        with self.assertRaises(ProductSpecError):
            adapter.require_orderable_product("BTCUSD")

    def test_non_operational_product_is_rejected(self):
        raw = btc_product()
        raw["trading_status"] = "disrupted_cancel_only"

        adapter = DeltaProductAdapter(FakeDeltaClient([raw]))

        with self.assertRaises(ProductSpecError):
            adapter.require_orderable_product("BTCUSD")

    def test_reduce_only_product_is_rejected_for_new_order(self):
        raw = btc_product()
        raw["product_specs"]["only_reduce_only_orders_allowed"] = True

        adapter = DeltaProductAdapter(FakeDeltaClient([raw]))

        with self.assertRaises(ProductSpecError):
            adapter.require_orderable_product("BTCUSD")

    def test_single_product_refresh_updates_registry(self):
        client = FakeDeltaClient()
        adapter = DeltaProductAdapter(client)

        adapter.refresh()

        updated = btc_product()
        updated["tick_size"] = "1.0"
        client.products = [updated]

        spec = adapter.refresh_product("BTCUSD")

        self.assertAlmostEqual(spec.tick_size, 1.0)
        self.assertAlmostEqual(
            adapter.require("BTCUSD").tick_size,
            1.0,
        )

    def test_failed_refresh_does_not_destroy_existing_registry(self):
        client = FakeDeltaClient()
        adapter = DeltaProductAdapter(client)
        adapter.refresh()

        client.products = []

        with self.assertRaises(ProductSpecError):
            adapter.refresh()

        self.assertEqual(adapter.require_product_id("BTCUSD"), 27)

    def test_missing_product_is_rejected(self):
        adapter = DeltaProductAdapter(FakeDeltaClient())

        with self.assertRaises(ProductSpecError):
            adapter.require("ETHUSD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
