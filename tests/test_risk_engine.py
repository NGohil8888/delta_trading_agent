"""
Tests for agent.risk_engine.

Run from the project root with:

    python -m unittest tests.test_risk_engine -v

These tests deliberately use a generic contract_value=0.001 for the example
BTC-style contract so that a $50 risk budget can support multiple integer
contracts. The real Delta Exchange contract value must come from product
metadata and should NOT be guessed in production.
"""

import unittest

from agent.risk_engine import RiskConfig, RiskEngine


class TestRiskEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine(
            RiskConfig(
                max_risk_pct=0.01,
                min_reward_risk=2.0,
            )
        )

    def test_valid_long_trade_is_approved(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
        )

        self.assertTrue(result.approved)
        self.assertIsNotNone(result.position_size)
        self.assertEqual(result.position_size.contracts, 25)
        self.assertAlmostEqual(
            result.position_size.risk_budget,
            50.0,
            places=8,
        )
        self.assertLessEqual(
            result.position_size.total_estimated_risk,
            result.position_size.risk_budget,
        )

    def test_invalid_long_stop_is_rejected(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=101_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any("long stop must be below entry" in reason for reason in result.reasons)
        )

    def test_invalid_short_stop_is_rejected(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="sell",
            entry_price=100_000,
            stop_price=99_000,
            take_profit=94_000,
            contract_value=0.001,
            risk_pct=0.005,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any("short stop must be above entry" in reason for reason in result.reasons)
        )

    def test_poor_reward_risk_is_rejected(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=102_000,
            contract_value=0.001,
            risk_pct=0.005,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any("reward/risk" in reason for reason in result.reasons)
        )

    def test_risk_above_hard_limit_is_rejected(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.02,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any("exceeds the hard maximum" in reason for reason in result.reasons)
        )

    def test_requested_contracts_can_only_reduce_size(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
            requested_contracts=10,
        )

        self.assertTrue(result.approved)
        self.assertEqual(result.position_size.contracts, 10)
        self.assertLessEqual(
            result.position_size.total_estimated_risk,
            result.position_size.risk_budget,
        )

    def test_requested_contracts_cannot_increase_safe_size(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
            requested_contracts=100,
        )

        self.assertTrue(result.approved)
        self.assertEqual(result.position_size.contracts, 25)

    def test_fee_and_slippage_are_included_in_risk(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
            fee_pct=0.001,
            slippage_pct=0.001,
        )

        self.assertTrue(result.approved)
        position = result.position_size

        self.assertGreater(position.estimated_fees, 0)
        self.assertGreater(position.estimated_slippage, 0)
        self.assertGreater(
            position.total_estimated_risk,
            position.gross_stop_risk,
        )
        self.assertLessEqual(
            position.total_estimated_risk,
            position.risk_budget,
        )

    def test_one_contract_rejected_when_risk_budget_is_too_small(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="buy",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=1.0,
            risk_pct=0.005,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any(
                "risk budget is too small for one contract"
                in reason
                for reason in result.reasons
            )
        )

    def test_reward_risk_helper(self) -> None:
        value = self.engine.reward_risk(
            side="buy",
            entry_price=100,
            stop_price=95,
            take_profit=110,
        )

        self.assertAlmostEqual(value, 2.0)

    def test_short_reward_risk_helper(self) -> None:
        value = self.engine.reward_risk(
            side="sell",
            entry_price=100,
            stop_price=105,
            take_profit=90,
        )

        self.assertAlmostEqual(value, 2.0)

    def test_risk_budget_helper(self) -> None:
        self.assertAlmostEqual(
            self.engine.calculate_risk_budget(10_000, 0.005),
            50.0,
        )

    def test_invalid_side_is_rejected(self) -> None:
        result = self.engine.assess_trade(
            account_equity=10_000,
            symbol="BTCUSD",
            side="hold",
            entry_price=100_000,
            stop_price=98_000,
            take_profit=106_000,
            contract_value=0.001,
            risk_pct=0.005,
        )

        self.assertFalse(result.approved)
        self.assertTrue(
            any("side must be 'buy' or 'sell'" in reason for reason in result.reasons)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
