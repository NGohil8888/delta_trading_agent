"""Tests for agent.delta_client."""

import unittest

from agent.delta_client import (
    DeltaAPIError,
    DeltaClient,
    DeltaClientError,
    DeltaResponseError,
)


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
        "product_specs": {"only_reduce_only_orders_allowed": False},
    }


class FakeTransport:
    def __init__(self):
        self.responses = {}
        self.posts = []

    def get(self, path, params=None):
        response = self.responses.get(("GET", path))
        if response is None:
            raise AssertionError(f"Unexpected GET: {path}")
        return response

    def post(self, path, payload):
        self.posts.append((path, dict(payload)))
        response = self.responses.get(("POST", path))
        if response is None:
            raise AssertionError(f"Unexpected POST: {path}")
        return response


def configured_client():
    transport = FakeTransport()
    transport.responses[("GET", "/v2/products")] = {
        "success": True, "result": [btc_product()]
    }
    transport.responses[("GET", "/v2/products/BTCUSD")] = {
        "success": True, "result": btc_product()
    }
    transport.responses[("GET", "/v2/tickers/BTCUSD")] = {
        "success": True, "result": {"symbol": "BTCUSD", "mark_price": "100000"}
    }
    transport.responses[("GET", "/v2/wallet/balances")] = {
        "success": True,
        "result": [{"asset_symbol": "USD", "equity": "10000", "available_balance": "9500"}],
    }
    transport.responses[("POST", "/v2/orders")] = {
        "success": True,
        "result": {"id": 123, "product_id": 27, "size": 10, "side": "buy"},
    }
    return DeltaClient(transport), transport


class TestDeltaClient(unittest.TestCase):
    def test_fetch_products_returns_raw_products(self):
        client, _ = configured_client()
        products = client.fetch_products()
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["symbol"], "BTCUSD")

    def test_product_metadata_is_normalized(self):
        client, _ = configured_client()
        spec = client.get_product("BTCUSD")
        self.assertEqual(spec.product_id, 27)
        self.assertAlmostEqual(spec.contract_value, 0.001)

    def test_contract_value_is_not_guessed(self):
        transport = FakeTransport()
        raw = btc_product()
        raw.pop("contract_value")
        transport.responses[("GET", "/v2/products")] = {"success": True, "result": [raw]}
        client = DeltaClient(transport)
        with self.assertRaises(Exception):
            client.get_contract_value("BTCUSD")

    def test_ticker_is_returned(self):
        client, _ = configured_client()
        ticker = client.fetch_ticker("BTCUSD")
        self.assertEqual(ticker["symbol"], "BTCUSD")

    def test_account_balance_is_normalized(self):
        client, _ = configured_client()
        account = client.fetch_account_balance("USD")
        self.assertEqual(account.equity, 10000.0)
        self.assertEqual(account.available_balance, 9500.0)

    def test_order_uses_delta_product_id(self):
        client, transport = configured_client()
        result = client.place_order(
            symbol="BTCUSD", side="buy", size=10, order_type="market_order"
        )
        self.assertEqual(result["id"], 123)
        path, payload = transport.posts[0]
        self.assertEqual(path, "/v2/orders")
        self.assertEqual(payload["product_id"], 27)
        self.assertEqual(payload["size"], 10)

    def test_invalid_order_size_is_rejected(self):
        client, _ = configured_client()
        with self.assertRaises(DeltaClientError):
            client.place_order(
                symbol="BTCUSD", side="buy", size=0, order_type="market_order"
            )

    def test_invalid_side_is_rejected(self):
        client, _ = configured_client()
        with self.assertRaises(DeltaClientError):
            client.place_order(
                symbol="BTCUSD", side="hold", size=1, order_type="market_order"
            )

    def test_limit_order_requires_price(self):
        client, _ = configured_client()
        with self.assertRaises(DeltaClientError):
            client.place_order(
                symbol="BTCUSD", side="buy", size=1, order_type="limit_order"
            )

    def test_reduce_only_is_not_silently_submitted(self):
        client, _ = configured_client()
        with self.assertRaises(DeltaClientError):
            client.place_order(
                symbol="BTCUSD", side="sell", size=1,
                order_type="market_order", reduce_only=True
            )

    def test_api_error_is_raised(self):
        transport = FakeTransport()
        transport.responses[("GET", "/v2/products")] = {
            "success": False, "error": "authentication failed"
        }
        client = DeltaClient(transport)
        with self.assertRaises(DeltaAPIError):
            client.fetch_products()

    def test_missing_result_is_rejected(self):
        transport = FakeTransport()
        transport.responses[("GET", "/v2/products")] = {"success": True}
        client = DeltaClient(transport)
        with self.assertRaises(DeltaResponseError):
            client.fetch_products()

    def test_missing_balance_is_rejected(self):
        transport = FakeTransport()
        transport.responses[("GET", "/v2/wallet/balances")] = {
            "success": True, "result": []
        }
        client = DeltaClient(transport)
        with self.assertRaises(DeltaResponseError):
            client.fetch_account_balance("USD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
