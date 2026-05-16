import pandas as pd
import numpy as np
import yfinance as yf
from dataclasses import dataclass
from typing import Optional


@dataclass
class IndicatorData:
    ticker: str
    current_price: float
    price_change_pct: float
    volume: int
    avg_volume: int
    rsi: float
    rsi_prev: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    macd_histogram_prev: float
    ema20: float
    ema50: float
    ema200: float
    high_52w: float
    low_52w: float


def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=True).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=True).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_ema(prices: pd.Series, period: int) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()


def get_indicator_data(ticker: str, period: str = "1y") -> Optional[IndicatorData]:
    try:
        hist = yf.Ticker(ticker).history(period=period)

        if hist.empty or len(hist) < 50:
            return None

        closes = hist["Close"]
        volumes = hist["Volume"]

        rsi = compute_rsi(closes)
        macd_line, macd_signal, macd_hist = compute_macd(closes)
        ema20 = compute_ema(closes, 20)
        ema50 = compute_ema(closes, 50)
        ema200 = compute_ema(closes, 200)

        current_price = float(closes.iloc[-1])
        prev_price = float(closes.iloc[-2])

        return IndicatorData(
            ticker=ticker.upper(),
            current_price=current_price,
            price_change_pct=(current_price - prev_price) / prev_price * 100,
            volume=int(volumes.iloc[-1]),
            avg_volume=int(volumes.mean()),
            rsi=float(rsi.iloc[-1]),
            rsi_prev=float(rsi.iloc[-2]),
            macd_line=float(macd_line.iloc[-1]),
            macd_signal=float(macd_signal.iloc[-1]),
            macd_histogram=float(macd_hist.iloc[-1]),
            macd_histogram_prev=float(macd_hist.iloc[-2]),
            ema20=float(ema20.iloc[-1]),
            ema50=float(ema50.iloc[-1]),
            ema200=float(ema200.iloc[-1]),
            high_52w=float(hist["High"].max()),
            low_52w=float(hist["Low"].min()),
        )
    except Exception:
        return None
