#!/usr/bin/env python3
"""
100x Financial Analyst & Trading Agent
Powered by Claude claude-opus-4-7 with RSI, MACD, and EMA signals
"""

import os
import sys
import click
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

from agent import run_agent

console = Console()

BANNER = """[bold cyan]
  ██████╗ ██╗███╗   ██╗ █████╗ ███╗   ██╗ ██████╗███████╗
  ██╔════╝ ██║████╗  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝
  █████╗   ██║██╔██╗ ██║███████║██╔██╗ ██║██║     █████╗
  ██╔══╝   ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██╔══╝
  ██║      ██║██║ ╚████║██║  ██║██║ ╚████║╚██████╗███████╗
  ╚═╝      ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝
[/bold cyan]
[bold white]  100x Financial Analyst & Trading Agent[/bold white]
[dim]  RSI · MACD · EMA · Claude claude-opus-4-7[/dim]
"""


def check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY environment variable not set.")
        console.print("Set it with: [cyan]export ANTHROPIC_API_KEY=your-key[/cyan]")
        sys.exit(1)


@click.group()
def cli():
    """100x Financial Analyst & Trading Agent — RSI, MACD, EMA signals via Claude."""
    pass


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option("--timeframe", "-t", default="1y", show_default=True,
              type=click.Choice(["1mo", "3mo", "6mo", "1y", "2y"]),
              help="Historical data period")
def analyze(tickers, timeframe):
    """Analyze one or more stocks and get buy/sell signals.

    \b
    Examples:
      python main.py analyze AAPL
      python main.py analyze AAPL MSFT NVDA TSLA
      python main.py analyze AAPL --timeframe 3mo
    """
    check_api_key()
    tickers_str = " ".join(t.upper() for t in tickers)

    console.print(BANNER)
    console.print(Panel(
        f"[bold green]Analyzing: {tickers_str}[/bold green]\n[dim]Timeframe: {timeframe}[/dim]",
        expand=False
    ))
    console.print()
    console.print("[bold green]Agent:[/bold green] ", end="")

    prompt = (
        f"Analyze {'this stock' if len(tickers) == 1 else 'these stocks'} and give me your full technical analysis "
        f"with buy/sell signals: {tickers_str}. "
        f"Use the {timeframe} timeframe for context. "
        "For each stock: fetch data, compute indicators, generate a signal, then give me specific "
        "entry levels, stop-loss, and price target if bullish."
    )

    run_agent(prompt, [])
    console.print()


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option("--rsi-min", type=float, default=None, help="Minimum RSI (e.g. 30)")
@click.option("--rsi-max", type=float, default=None, help="Maximum RSI (e.g. 40)")
@click.option("--macd-bullish", is_flag=True, help="Require positive MACD histogram")
@click.option("--above-ema20", is_flag=True, help="Require price above EMA20")
@click.option("--above-ema50", is_flag=True, help="Require price above EMA50")
@click.option("--signal", default=None,
              type=click.Choice(["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]),
              help="Minimum signal strength")
def screen(tickers, rsi_min, rsi_max, macd_bullish, above_ema20, above_ema50, signal):
    """Screen stocks by technical criteria and rank by signal strength.

    \b
    Examples:
      python main.py screen AAPL MSFT GOOGL NVDA AMZN --rsi-max 40
      python main.py screen AAPL MSFT GOOGL --rsi-max 45 --macd-bullish
      python main.py screen AAPL MSFT GOOGL NVDA --signal BUY --above-ema50
    """
    check_api_key()

    filters_applied = []
    if rsi_min is not None:
        filters_applied.append(f"RSI ≥ {rsi_min}")
    if rsi_max is not None:
        filters_applied.append(f"RSI ≤ {rsi_max}")
    if macd_bullish:
        filters_applied.append("MACD histogram > 0")
    if above_ema20:
        filters_applied.append("price > EMA20")
    if above_ema50:
        filters_applied.append("price > EMA50")
    if signal:
        filters_applied.append(f"signal ≥ {signal}")

    filter_desc = " · ".join(filters_applied) if filters_applied else "none (rank all)"
    tickers_str = " ".join(t.upper() for t in tickers)

    console.print(BANNER)
    console.print(Panel(
        f"[bold cyan]Screening {len(tickers)} stocks[/bold cyan]\n"
        f"Tickers: {tickers_str}\n"
        f"Filters: [yellow]{filter_desc}[/yellow]",
        expand=False
    ))
    console.print()
    console.print("[bold green]Agent:[/bold green] ", end="")

    prompt = (
        f"Screen these stocks for me: {tickers_str}\n\n"
        f"Apply these filters: {filter_desc or 'no filters — rank everything'}\n\n"
        "Use the screen_stocks tool to run the filter, then give me:\n"
        "1. The filtered results table (ticker, signal, score, RSI, MACD)\n"
        "2. Brief commentary on your top 3 picks — why they stand out\n"
        "3. Any you'd avoid and why"
    )

    run_agent(prompt, [])
    console.print()


@cli.command()
def chat():
    """Start an interactive multi-turn chat session.

    \b
    Example queries:
      "Is NVDA a buy right now?"
      "Compare AAPL vs MSFT on RSI and MACD"
      "Screen these for oversold: AAPL MSFT GOOGL AMZN META NVDA"
      "What's the EMA trend on TSLA?"
    """
    check_api_key()
    console.print(BANNER)
    console.print(Panel(
        "[bold]Interactive Session[/bold]\n"
        "[dim]Ask me to analyze stocks, generate signals, or screen a watchlist.\n"
        "Type [bold]quit[/bold] to exit.[/dim]",
        expand=False
    ))
    console.print()

    history = []
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q", "bye"):
            console.print("[dim]Session ended.[/dim]")
            break

        console.print("\n[bold green]Agent:[/bold green] ", end="")
        history = run_agent(user_input, history)
        console.print()


if __name__ == "__main__":
    cli()
