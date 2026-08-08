"""agent/models.py -- shared data structures used across mixins."""
from dataclasses import dataclass


@dataclass
class TradeIdea:
    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    confidence: float
    rationale: str