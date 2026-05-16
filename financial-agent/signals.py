from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from indicators import IndicatorData, get_indicator_data


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


@dataclass
class Signal:
    ticker: str
    signal: SignalType
    score: float  # -2.0 (max bearish) to +2.0 (max bullish)
    reasons: List[str]
    data: IndicatorData


def generate_signal(ticker: str) -> Optional[Signal]:
    data = get_indicator_data(ticker)
    if data is None:
        return None

    score = 0.0
    reasons = []
    price = data.current_price

    # --- RSI ---
    if data.rsi < 30:
        score += 1.5
        reasons.append(f"RSI deeply oversold ({data.rsi:.1f})")
    elif data.rsi < 40:
        score += 0.75
        reasons.append(f"RSI approaching oversold ({data.rsi:.1f})")
    elif data.rsi > 70:
        score -= 1.5
        reasons.append(f"RSI overbought ({data.rsi:.1f})")
    elif data.rsi > 60:
        score -= 0.75
        reasons.append(f"RSI approaching overbought ({data.rsi:.1f})")

    # RSI trend direction
    rsi_rising = data.rsi > data.rsi_prev
    if data.rsi < 50 and rsi_rising:
        score += 0.25
        reasons.append("RSI rising from oversold territory")
    elif data.rsi > 50 and not rsi_rising:
        score -= 0.25
        reasons.append("RSI declining from overbought territory")

    # --- MACD ---
    bullish_crossover = data.macd_histogram > 0 and data.macd_histogram_prev <= 0
    bearish_crossover = data.macd_histogram < 0 and data.macd_histogram_prev >= 0
    macd_accelerating = data.macd_histogram > data.macd_histogram_prev
    macd_decelerating = data.macd_histogram < data.macd_histogram_prev

    if bullish_crossover:
        score += 1.0
        reasons.append("MACD bullish crossover (histogram just turned positive)")
    elif data.macd_histogram > 0 and macd_accelerating:
        score += 0.5
        reasons.append(f"MACD positive and accelerating (+{data.macd_histogram:.4f})")
    elif data.macd_histogram > 0:
        score += 0.25
        reasons.append(f"MACD positive but decelerating ({data.macd_histogram:.4f})")

    if bearish_crossover:
        score -= 1.0
        reasons.append("MACD bearish crossover (histogram just turned negative)")
    elif data.macd_histogram < 0 and macd_decelerating:
        score -= 0.5
        reasons.append(f"MACD negative and accelerating ({data.macd_histogram:.4f})")
    elif data.macd_histogram < 0:
        score -= 0.25
        reasons.append(f"MACD negative but recovering ({data.macd_histogram:.4f})")

    # MACD line vs zero
    if data.macd_line > 0:
        score += 0.1
        reasons.append("MACD line above zero (bullish regime)")
    else:
        score -= 0.1
        reasons.append("MACD line below zero (bearish regime)")

    # --- EMA Alignment ---
    above_ema20 = price > data.ema20
    above_ema50 = price > data.ema50
    above_ema200 = price > data.ema200

    if above_ema20:
        score += 0.2
        reasons.append(f"Price above EMA20 ({price:.2f} > {data.ema20:.2f})")
    else:
        score -= 0.2
        reasons.append(f"Price below EMA20 ({price:.2f} < {data.ema20:.2f})")

    if above_ema50:
        score += 0.3
        reasons.append(f"Price above EMA50 ({price:.2f} > {data.ema50:.2f})")
    else:
        score -= 0.3
        reasons.append(f"Price below EMA50 ({price:.2f} < {data.ema50:.2f})")

    if above_ema200:
        score += 0.2
        reasons.append("Price above EMA200 — long-term uptrend intact")
    else:
        score -= 0.2
        reasons.append("Price below EMA200 — long-term downtrend")

    # Full EMA stack alignment bonus
    if above_ema20 and above_ema50 and above_ema200:
        score += 0.25
        reasons.append("Full EMA stack aligned bullish (20 > 50 > 200)")
    elif not above_ema20 and not above_ema50 and not above_ema200:
        score -= 0.25
        reasons.append("Full EMA stack aligned bearish")

    # Volume confirmation
    vol_ratio = data.volume / data.avg_volume if data.avg_volume else 1
    if vol_ratio > 1.5 and score > 0:
        score += 0.1
        reasons.append(f"High volume confirmation ({vol_ratio:.1f}x avg)")
    elif vol_ratio > 1.5 and score < 0:
        score -= 0.1
        reasons.append(f"High volume confirms bearish move ({vol_ratio:.1f}x avg)")

    score = max(-2.0, min(2.0, score))

    if score >= 1.5:
        signal = SignalType.STRONG_BUY
    elif score >= 0.5:
        signal = SignalType.BUY
    elif score <= -1.5:
        signal = SignalType.STRONG_SELL
    elif score <= -0.5:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    return Signal(ticker=ticker.upper(), signal=signal, score=score, reasons=reasons, data=data)
