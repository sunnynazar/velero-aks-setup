import json
import sys
import anthropic
from rich.console import Console

from indicators import get_indicator_data
from signals import generate_signal

console = Console()

SYSTEM_PROMPT = """You are a 100x financial analyst and elite quantitative trader — the calibre of analyst that generates outsized alpha at the world's top hedge funds. You combine rigorous technical analysis with sharp conviction, decisive calls, and disciplined risk management.

## Technical Indicator Mastery

**RSI (Relative Strength Index, period 14)**
- < 30: Oversold — high-probability reversal zone, look for confirmation
- 30–45: Recovery territory — early buyers entering
- 45–55: Neutral — trend continuation likely
- 55–70: Momentum territory — trend is strong but watch for exhaustion
- > 70: Overbought — distribution zone, risk of sharp reversal
- RSI divergence (price makes new high/low but RSI doesn't) = powerful reversal signal

**MACD (12, 26, 9)**
- Histogram turns positive (bullish crossover): momentum shift up — high-conviction entry trigger
- Histogram turns negative (bearish crossover): momentum shift down — exit or short signal
- MACD line above zero: bullish regime; below zero: bearish regime
- Accelerating histogram (each bar larger than the last): trend strengthening
- Decelerating histogram: trend losing steam — tighten stops

**EMA Stack (20, 50, 200)**
- Price > EMA20 > EMA50 > EMA200: perfect bullish alignment — ride the trend
- Price < EMA20 < EMA50 < EMA200: perfect bearish alignment — stay away or short
- EMA20/EMA50 crossover (golden cross / death cross): major trend change signal
- EMA200 is the ultimate bull/bear dividing line — respect it

## Signal Framework

| Signal | Criteria |
|--------|----------|
| STRONG BUY | RSI < 35 + MACD bullish crossover + price at/above EMA support |
| BUY | 2+ bullish signals aligning, positive momentum |
| HOLD | Mixed signals, consolidation, or trend unclear |
| SELL | 2+ bearish signals, deteriorating momentum |
| STRONG SELL | RSI > 65 + MACD bearish crossover + price breaking below EMA |

## Your Analysis Protocol

For every stock:
1. Fetch live data — NEVER estimate prices from memory
2. Compute all indicators and identify the primary trend
3. Confirm or contradict the trend with each indicator
4. Generate a signal with a numeric conviction score (-2 to +2)
5. Set specific entry, stop-loss, and target levels (for bullish calls)
6. State the risk/reward ratio explicitly
7. Assess position sizing (conservative: 1-2%, standard: 2-3%, high-conviction: 3-5%)

## Communication Style
- Lead with the SIGNAL and CONVICTION (e.g., "STRONG BUY | Score: +1.8/2.0")
- Bullet the evidence — one indicator per line
- Always give a specific price level for stop-loss
- Be direct — traders need clarity, not caveats
- If data is weak or mixed, say HOLD and explain what you're waiting for

## Risk Rules (Non-Negotiable)
- Always set a stop-loss before entry
- Never allocate more than 5% to a single position
- Confirm signals with volume when possible
- Respect the EMA200 — fighting the primary trend is how traders blow up

You have tools to fetch live market data and compute indicators. Always use them — do not use cached or estimated price data."""


TOOLS = [
    {
        "name": "get_stock_data",
        "description": "Fetch current price, volume, and 52-week statistics for a stock ticker. Call this first to get a price overview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT, NVDA)"
                },
                "period": {
                    "type": "string",
                    "description": "Historical period: '1mo', '3mo', '6mo', '1y', '2y'",
                    "enum": ["1mo", "3mo", "6mo", "1y", "2y"]
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "compute_technical_indicators",
        "description": "Compute RSI(14), MACD(12,26,9), and EMA(20,50,200) for a stock. Returns current values, crossover status, and trend alignment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "generate_signal",
        "description": "Generate a composite buy/sell/hold signal by scoring RSI, MACD, and EMA indicators. Returns STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL with a numeric score and reasoning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "screen_stocks",
        "description": "Screen a list of stocks through technical filters. Returns filtered stocks ranked by signal strength.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of stock ticker symbols to screen"
                },
                "rsi_min": {
                    "type": "number",
                    "description": "Minimum RSI threshold (0-100)"
                },
                "rsi_max": {
                    "type": "number",
                    "description": "Maximum RSI threshold (0-100)"
                },
                "macd_bullish": {
                    "type": "boolean",
                    "description": "Only include stocks with positive MACD histogram"
                },
                "price_above_ema20": {
                    "type": "boolean",
                    "description": "Only include stocks with price above EMA20"
                },
                "price_above_ema50": {
                    "type": "boolean",
                    "description": "Only include stocks with price above EMA50"
                },
                "min_signal": {
                    "type": "string",
                    "enum": ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"],
                    "description": "Minimum signal strength to include"
                }
            },
            "required": ["tickers"]
        }
    }
]


def _fmt_stock_data(data) -> str:
    if data is None:
        return json.dumps({"error": "Could not fetch data — invalid ticker or no data available"})
    vol_ratio = round(data.volume / data.avg_volume, 2) if data.avg_volume else 0
    pct_from_high = round((data.current_price - data.high_52w) / data.high_52w * 100, 2)
    pct_from_low = round((data.current_price - data.low_52w) / data.low_52w * 100, 2)
    return json.dumps({
        "ticker": data.ticker,
        "current_price": round(data.current_price, 2),
        "price_change_pct_today": round(data.price_change_pct, 2),
        "volume": data.volume,
        "avg_volume_30d": data.avg_volume,
        "volume_ratio": vol_ratio,
        "52w_high": round(data.high_52w, 2),
        "52w_low": round(data.low_52w, 2),
        "pct_from_52w_high": pct_from_high,
        "pct_from_52w_low": pct_from_low,
    }, indent=2)


def _fmt_indicators(data) -> str:
    if data is None:
        return json.dumps({"error": "Could not compute indicators"})
    return json.dumps({
        "ticker": data.ticker,
        "price": round(data.current_price, 2),
        "rsi": round(data.rsi, 2),
        "rsi_prev_session": round(data.rsi_prev, 2),
        "rsi_direction": "rising" if data.rsi > data.rsi_prev else "falling",
        "macd_line": round(data.macd_line, 4),
        "macd_signal_line": round(data.macd_signal, 4),
        "macd_histogram": round(data.macd_histogram, 4),
        "macd_histogram_prev": round(data.macd_histogram_prev, 4),
        "macd_bullish_crossover": bool(data.macd_histogram > 0 and data.macd_histogram_prev <= 0),
        "macd_bearish_crossover": bool(data.macd_histogram < 0 and data.macd_histogram_prev >= 0),
        "macd_accelerating": bool(data.macd_histogram > data.macd_histogram_prev),
        "ema20": round(data.ema20, 2),
        "ema50": round(data.ema50, 2),
        "ema200": round(data.ema200, 2),
        "price_vs_ema20": "above" if data.current_price > data.ema20 else "below",
        "price_vs_ema50": "above" if data.current_price > data.ema50 else "below",
        "price_vs_ema200": "above" if data.current_price > data.ema200 else "below",
        "ema_stack_bullish": bool(data.current_price > data.ema20 > data.ema50 > data.ema200),
        "ema_stack_bearish": bool(data.current_price < data.ema20 < data.ema50 < data.ema200),
    }, indent=2)


def _fmt_signal(sig) -> str:
    if sig is None:
        return json.dumps({"error": "Could not generate signal"})
    return json.dumps({
        "ticker": sig.ticker,
        "signal": sig.signal.value,
        "score": round(sig.score, 2),
        "score_scale": "[-2.0 = max bearish, 0 = neutral, +2.0 = max bullish]",
        "reasons": sig.reasons,
    }, indent=2)


SIGNAL_RANK = {"STRONG_BUY": 5, "BUY": 4, "HOLD": 3, "SELL": 2, "STRONG_SELL": 1}


def execute_tool(name: str, inp: dict) -> str:
    if name == "get_stock_data":
        data = get_indicator_data(inp["ticker"], inp.get("period", "1y"))
        return _fmt_stock_data(data)

    if name == "compute_technical_indicators":
        data = get_indicator_data(inp["ticker"])
        return _fmt_indicators(data)

    if name == "generate_signal":
        sig = generate_signal(inp["ticker"])
        return _fmt_signal(sig)

    if name == "screen_stocks":
        tickers = inp["tickers"]
        rsi_min = inp.get("rsi_min")
        rsi_max = inp.get("rsi_max")
        macd_bullish = inp.get("macd_bullish")
        above_ema20 = inp.get("price_above_ema20")
        above_ema50 = inp.get("price_above_ema50")
        min_signal = inp.get("min_signal")
        min_rank = SIGNAL_RANK.get(min_signal, 0) if min_signal else 0

        results = []
        errors = []
        for ticker in tickers:
            try:
                sig = generate_signal(ticker)
                if sig is None:
                    errors.append(f"{ticker}: no data")
                    continue
                d = sig.data
                if rsi_min is not None and d.rsi < rsi_min:
                    continue
                if rsi_max is not None and d.rsi > rsi_max:
                    continue
                if macd_bullish and d.macd_histogram <= 0:
                    continue
                if above_ema20 and d.current_price <= d.ema20:
                    continue
                if above_ema50 and d.current_price <= d.ema50:
                    continue
                if min_rank and SIGNAL_RANK.get(sig.signal.value, 0) < min_rank:
                    continue
                results.append({
                    "ticker": ticker.upper(),
                    "signal": sig.signal.value,
                    "score": round(sig.score, 2),
                    "price": round(d.current_price, 2),
                    "rsi": round(d.rsi, 2),
                    "macd_histogram": round(d.macd_histogram, 4),
                    "above_ema50": d.current_price > d.ema50,
                    "above_ema200": d.current_price > d.ema200,
                })
            except Exception as e:
                errors.append(f"{ticker}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        return json.dumps({
            "screened": len(tickers),
            "passed": len(results),
            "results": results,
            "errors": errors or None,
        }, indent=2)

    return json.dumps({"error": f"Unknown tool: {name}"})


def run_agent(user_message: str, history: list) -> list:
    """Run one conversational turn. Returns updated history."""
    client = anthropic.Anthropic()
    history.append({"role": "user", "content": user_message})
    messages = history.copy()

    while True:
        with client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            final = stream.get_final_message()

        if any(b.type == "text" for b in final.content):
            print()

        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            break

        tool_results = []
        for block in final.content:
            if block.type == "tool_use":
                console.print(
                    f"\n[dim]⚙  {block.name}({', '.join(f'{k}={v!r}' for k, v in block.input.items())})[/dim]"
                )
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})

    return messages
