"""
agent/risk_engine.py

Deterministic risk-management layer for the trading agent.

Design goals
------------
1. The LLM may propose a trade, but it cannot decide how much capital to risk.
2. Stop-loss distance determines position size; risk percentage determines
   the maximum loss budget.
3. The engine validates trade direction, stop/target placement, risk/reward,
   account risk, and contract sizing.
4. This module does not place orders and does not call the exchange.
   It is intentionally deterministic and should sit between strategy/LLM
   output and the execution layer.

Important
---------
`contract_value` must come from the exchange's product metadata and must
represent the amount of underlying exposure represented by one contract.
For products where that interpretation is different, the exchange adapter
must normalize the value before passing it here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from agent import config


@dataclass(frozen=True)
class RiskConfig:
    """Hard risk-policy limits.

    Values are percentages expressed as decimals:
        0.01 == 1% of account equity.
    """

    max_risk_pct: float = config.MAX_RISK_PCT
    min_risk_pct: float = 0.0
    min_reward_risk: float = 2.0
    max_confidence_floor: float = 0.0

    # A position's stop distance is also sanity-checked. These are not
    # substitutes for a technical stop; they prevent obviously malformed
    # proposals from reaching execution.
    min_stop_distance_pct: float = 0.0001  # 0.01%
    max_stop_distance_pct: float = 0.25    # 25%

    # Cost assumptions used only when supplied by the caller.
    default_fee_pct: float = 0.0
    default_slippage_pct: float = 0.0


@dataclass(frozen=True)
class PositionSize:
    """Deterministic sizing result."""

    account_equity: float
    risk_pct: float
    risk_budget: float
    entry_price: float
    stop_price: float
    stop_distance: float
    stop_distance_pct: float

    # Underlying quantity before contract conversion.
    underlying_quantity: float

    # Integer exchange quantity after contract conversion.
    contracts: int

    contract_value: float

    # Risk represented by the rounded contract quantity.
    gross_stop_risk: float
    estimated_fees: float
    estimated_slippage: float
    total_estimated_risk: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_equity": self.account_equity,
            "risk_pct": self.risk_pct,
            "risk_budget": self.risk_budget,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "stop_distance": self.stop_distance,
            "stop_distance_pct": self.stop_distance_pct,
            "underlying_quantity": self.underlying_quantity,
            "contracts": self.contracts,
            "contract_value": self.contract_value,
            "gross_stop_risk": self.gross_stop_risk,
            "estimated_fees": self.estimated_fees,
            "estimated_slippage": self.estimated_slippage,
            "total_estimated_risk": self.total_estimated_risk,
        }


@dataclass
class RiskAssessment:
    """Result of validating a proposed trade."""

    approved: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    position_size: Optional[PositionSize] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "position_size": (
                self.position_size.as_dict()
                if self.position_size is not None
                else None
            ),
        }


class RiskEngine:
    """Pure deterministic risk engine.

    The engine deliberately accepts plain values rather than an exchange
    client. That keeps the safety calculation independently testable and
    prevents accidental network/order side effects.
    """

    def __init__(self, risk_config: Optional[RiskConfig] = None) -> None:
        self.policy = risk_config or RiskConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess_trade(
        self,
        *,
        account_equity: float,
        symbol: str,
        side: str,
        entry_price: float,
        stop_price: float,
        take_profit: float,
        contract_value: float = 1.0,
        confidence: Optional[float] = None,
        risk_pct: Optional[float] = None,
        fee_pct: Optional[float] = None,
        slippage_pct: Optional[float] = None,
        requested_contracts: Optional[int] = None,
    ) -> RiskAssessment:
        """Validate and size one proposed trade.

        Parameters
        ----------
        account_equity:
            Current account equity available for risk calculations.

        symbol:
            Exchange symbol, used for human-readable error messages.

        side:
            `buy` or `sell`.

        entry_price:
            Expected entry/fill reference price.

        stop_price:
            Technical invalidation level.

        take_profit:
            Intended profit target.

        contract_value:
            Underlying amount represented by one exchange contract.

        confidence:
            Optional strategy/LLM confidence. This engine never treats
            confidence as proof of profitability; it is only a configurable
            lower-bound gate.

        requested_contracts:
            Optional externally requested size. If supplied, it can only
            reduce the automatically calculated safe size; it can never
            increase it.
        """
        reasons: list[str] = []
        warnings: list[str] = []

        side = str(side or "").strip().lower()
        symbol = str(symbol or "").strip().upper()

        equity = self._positive_float(account_equity, "account_equity", reasons)
        entry = self._positive_float(entry_price, "entry_price", reasons)
        stop = self._positive_float(stop_price, "stop_price", reasons)
        target = self._positive_float(take_profit, "take_profit", reasons)
        cv = self._positive_float(contract_value, "contract_value", reasons)

        if side not in {"buy", "sell"}:
            reasons.append(f"{symbol}: side must be 'buy' or 'sell'.")

        if reasons:
            return RiskAssessment(False, reasons=reasons, warnings=warnings)

        effective_risk_pct = (
            self.policy.max_risk_pct if risk_pct is None else float(risk_pct)
        )

        if not math.isfinite(effective_risk_pct):
            reasons.append("risk_pct must be finite.")
        elif effective_risk_pct <= 0:
            reasons.append("risk_pct must be greater than zero.")
        elif effective_risk_pct < self.policy.min_risk_pct:
            reasons.append(
                f"risk_pct {effective_risk_pct:.4%} is below the configured "
                f"minimum {self.policy.min_risk_pct:.4%}."
            )
        elif effective_risk_pct > self.policy.max_risk_pct:
            reasons.append(
                f"risk_pct {effective_risk_pct:.4%} exceeds the hard maximum "
                f"{self.policy.max_risk_pct:.4%}."
            )

        if confidence is not None:
            try:
                conf = float(confidence)
            except (TypeError, ValueError):
                reasons.append("confidence must be numeric when supplied.")
            else:
                if not 0.0 <= conf <= 1.0:
                    reasons.append("confidence must be between 0 and 1.")
                elif conf < self.policy.max_confidence_floor:
                    reasons.append(
                        f"confidence {conf:.3f} is below the configured "
                        f"floor {self.policy.max_confidence_floor:.3f}."
                    )

        # Directional validation.
        if side == "buy":
            if stop >= entry:
                reasons.append(
                    f"{symbol}: long stop must be below entry "
                    f"({stop} >= {entry})."
                )
            if target <= entry:
                reasons.append(
                    f"{symbol}: long take-profit must be above entry "
                    f"({target} <= {entry})."
                )
        else:
            if stop <= entry:
                reasons.append(
                    f"{symbol}: short stop must be above entry "
                    f"({stop} <= {entry})."
                )
            if target >= entry:
                reasons.append(
                    f"{symbol}: short take-profit must be below entry "
                    f"({target} >= {entry})."
                )

        stop_distance = abs(entry - stop)
        stop_distance_pct = stop_distance / entry if entry else math.inf

        if stop_distance <= 0:
            reasons.append(f"{symbol}: stop distance must be greater than zero.")
        elif stop_distance_pct < self.policy.min_stop_distance_pct:
            reasons.append(
                f"{symbol}: stop is too close to entry "
                f"({stop_distance_pct:.4%})."
            )
        elif stop_distance_pct > self.policy.max_stop_distance_pct:
            reasons.append(
                f"{symbol}: stop is too far from entry "
                f"({stop_distance_pct:.2%}); maximum is "
                f"{self.policy.max_stop_distance_pct:.2%}."
            )

        reward_distance = abs(target - entry)
        reward_risk = (
            reward_distance / stop_distance
            if stop_distance > 0
            else 0.0
        )

        if reward_risk < self.policy.min_reward_risk:
            reasons.append(
                f"{symbol}: reward/risk {reward_risk:.2f} is below the "
                f"minimum {self.policy.min_reward_risk:.2f}."
            )

        if reasons:
            return RiskAssessment(False, reasons=reasons, warnings=warnings)

        fee_rate = (
            self.policy.default_fee_pct
            if fee_pct is None
            else max(0.0, float(fee_pct))
        )
        slippage_rate = (
            self.policy.default_slippage_pct
            if slippage_pct is None
            else max(0.0, float(slippage_pct))
        )

        risk_budget = equity * effective_risk_pct

        # Risk per unit of underlying.
        risk_per_underlying_unit = stop_distance

        # Fees/slippage are estimated conservatively against the entry
        # notional. They are included in the final risk calculation so the
        # engine does not pretend that the stop is the only cost.
        cost_per_underlying_unit = (
            entry * fee_rate + entry * slippage_rate
        )

        risk_per_unit_total = (
            risk_per_underlying_unit + cost_per_underlying_unit
        )

        if risk_per_unit_total <= 0:
            return RiskAssessment(
                False,
                reasons=[f"{symbol}: calculated risk per unit is invalid."],
                warnings=warnings,
            )

        underlying_quantity = risk_budget / risk_per_unit_total

        # Convert the safe underlying quantity to integer exchange
        # contracts. Floor rather than round: rounding upward can violate
        # the risk budget.
        raw_contracts = underlying_quantity / cv
        contracts = math.floor(raw_contracts)

        if requested_contracts is not None:
            try:
                requested = int(requested_contracts)
            except (TypeError, ValueError):
                requested = 0
                warnings.append(
                    f"{symbol}: requested_contracts was invalid and ignored."
                )

            if requested > 0:
                contracts = min(contracts, requested)

        if contracts < 1:
            reasons.append(
                f"{symbol}: risk budget is too small for one contract at "
                f"the supplied stop distance/contract value."
            )
            return RiskAssessment(False, reasons=reasons, warnings=warnings)

        actual_underlying = contracts * cv
        gross_stop_risk = actual_underlying * stop_distance
        estimated_fees = actual_underlying * entry * fee_rate
        estimated_slippage = actual_underlying * entry * slippage_rate
        total_estimated_risk = (
            gross_stop_risk + estimated_fees + estimated_slippage
        )

        # This is a hard post-sizing check. It catches mistakes in contract
        # conversion and guarantees that the final integer quantity cannot
        # silently exceed the risk budget.
        if total_estimated_risk > risk_budget + 1e-12:
            return RiskAssessment(
                False,
                reasons=[
                    f"{symbol}: final contract quantity would exceed the "
                    f"risk budget ({total_estimated_risk:.8f} > "
                    f"{risk_budget:.8f})."
                ],
                warnings=warnings,
            )

        if total_estimated_risk > risk_budget * 0.95:
            warnings.append(
                f"{symbol}: rounded contract quantity uses more than 95% "
                "of the available risk budget."
            )

        result = PositionSize(
            account_equity=equity,
            risk_pct=effective_risk_pct,
            risk_budget=risk_budget,
            entry_price=entry,
            stop_price=stop,
            stop_distance=stop_distance,
            stop_distance_pct=stop_distance_pct,
            underlying_quantity=underlying_quantity,
            contracts=contracts,
            contract_value=cv,
            gross_stop_risk=gross_stop_risk,
            estimated_fees=estimated_fees,
            estimated_slippage=estimated_slippage,
            total_estimated_risk=total_estimated_risk,
        )

        reasons.append(
            f"{symbol}: risk approved at {effective_risk_pct:.2%} of equity "
            f"with {reward_risk:.2f}R expected reward/risk."
        )

        return RiskAssessment(
            approved=True,
            reasons=reasons,
            warnings=warnings,
            position_size=result,
        )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def calculate_risk_budget(
        self,
        account_equity: float,
        risk_pct: Optional[float] = None,
    ) -> float:
        """Return the maximum loss budget for a trade."""
        equity = self._require_positive(account_equity, "account_equity")
        pct = self.policy.max_risk_pct if risk_pct is None else float(risk_pct)

        if pct <= 0:
            raise ValueError("risk_pct must be greater than zero.")
        if pct > self.policy.max_risk_pct:
            raise ValueError(
                f"risk_pct {pct:.4%} exceeds hard maximum "
                f"{self.policy.max_risk_pct:.4%}."
            )

        return equity * pct

    @staticmethod
    def reward_risk(
        *,
        side: str,
        entry_price: float,
        stop_price: float,
        take_profit: float,
    ) -> float:
        """Calculate R multiple for a proposed trade."""
        side = str(side or "").lower()
        entry = float(entry_price)
        stop = float(stop_price)
        target = float(take_profit)

        if entry <= 0 or stop <= 0 or target <= 0:
            raise ValueError("Prices must be greater than zero.")

        if side == "buy":
            if stop >= entry or target <= entry:
                raise ValueError("Invalid long stop/target placement.")
        elif side == "sell":
            if stop <= entry or target >= entry:
                raise ValueError("Invalid short stop/target placement.")
        else:
            raise ValueError("side must be 'buy' or 'sell'.")

        risk = abs(entry - stop)
        reward = abs(target - entry)
        return reward / risk

    @staticmethod
    def _positive_float(
        value: Any,
        name: str,
        reasons: list[str],
    ) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            reasons.append(f"{name} must be numeric.")
            return 0.0

        if not math.isfinite(number) or number <= 0:
            reasons.append(f"{name} must be a finite value greater than zero.")
            return 0.0

        return number

    @staticmethod
    def _require_positive(value: Any, name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric.") from exc

        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{name} must be greater than zero.")

        return number


def build_risk_engine() -> RiskEngine:
    """Factory used by the rest of the application."""
    return RiskEngine()


__all__ = [
    "RiskConfig",
    "PositionSize",
    "RiskAssessment",
    "RiskEngine",
    "build_risk_engine",
]
