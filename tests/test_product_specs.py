"""Tests for agent.product_specs."""

import unittest

from agent.product_specs import (
    ProductRegistry,
    ProductSpecError,
    product_spec_from_delta,
)


class TestProductSpecs(unittest.TestCase):
    def test_normalizes_product(self):
        spec = product_spec_from_delta({
            "id": 27,
            "symbol": "BTCUSD",
            "contract_value": "0.001",
            "contract_unit": "BTC",
            "tick_size": "0.5",
            "quantity_step": "1",
            "minimum_order_size": "1",
            "maximum_order_size": "100000",
            "contract_type": "perpetual_futures",
            "underlying_asset_symbol": "BTC",
            "settlement_asset_symbol": "USD",
        })
        self.assertEqual(spec.symbol, "BTCUSD")
        self.assertEqual(spec.product_id, 27)
        self.assertAlmostEqual(spec.contract_value, 0.001)
        self.assertAlmostEqual(spec.tick_size, 0.5)
        self.assertTrue(spec.has_contract_value)

    def test_contract_unit_value_fallback(self):
        spec = product_spec_from_delta({
            "id": 28,
            "symbol": "ETHUSD",
            "contract_unit_value": "0.01",
        })
        self.assertAlmostEqual(spec.contract_value, 0.01)

    def test_missing_contract_value_is_not_guessed(self):
        spec = product_spec_from_delta({
            "id": 29,
            "symbol": "TESTUSD",
        })
        self.assertIsNone(spec.contract_value)
        self.assertFalse(spec.has_contract_value)

    def test_missing_identity_is_rejected(self):
        with self.assertRaises(ProductSpecError):
            product_spec_from_delta({"id": 1})
        with self.assertRaises(ProductSpecError):
            product_spec_from_delta({"symbol": "BTCUSD"})

    def test_invalid_order_limits_are_rejected(self):
        with self.assertRaises(ProductSpecError):
            product_spec_from_delta({
                "id": 30,
                "symbol": "BADUSD",
                "minimum_order_size": 100,
                "maximum_order_size": 10,
            })

    def test_registry_lookup(self):
        registry = ProductRegistry()
        spec = registry.add({
            "id": 31,
            "symbol": "BTCUSD",
            "contract_value": "0.001",
        })
        self.assertIs(registry.get("btcusd"), spec)
        self.assertIs(registry.get_by_id(31), spec)
        self.assertEqual(registry.symbols(), ["BTCUSD"])
        self.assertEqual(len(registry), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
