"""FX discretionary trade support CLI (dependency-free).

Usage:
  python app.py --csv data.csv --balance 300000 --risk-pct 1 --entry 156.20 --stop 155.95 --take 156.80
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List

PIP_VALUE_PER_LOT = 1000.0  # Simplified JPY-pair estimate for MVP
REQUIRED_COLUMNS = ("time", "open", "high", "low", "close", "volume")


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_csv(path: str) -> List[Candle]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV header is missing")

        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"Missing columns: {', '.join(missing)}")

        candles: List[Candle] = []
        for row in reader:
            try:
                candles.append(
                    Candle(
                        time=datetime.fromisoformat(row["time"].replace("Z", "+00:00")),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            except Exception as exc:  # data quality guard for MVP
                raise ValueError(f"Invalid row: {row}") from exc

    candles.sort(key=lambda c: c.time)
    if len(candles) < 60:
        raise ValueError("At least 60 rows are required for stable EMA/RSI/ATR output")
    return candles


def ema(values: Iterable[float], period: int) -> List[float]:
    values = list(values)
    k = 2 / (period + 1)
    out: List[float] = []
    prev = values[0]
    for v in values:
        prev = (v * k) + (prev * (1 - k))
        out.append(prev)
    return out


def rsi(values: List[float], period: int = 14) -> List[float]:
    if len(values) < period + 1:
        return [50.0] * len(values)

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    out = [50.0] * (period + 1)
    for i in range(period, len(deltas)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100 - (100 / (1 + rs)))

    if len(out) < len(values):
        out += [out[-1]] * (len(values) - len(out))
    return out[: len(values)]


def atr(candles: List[Candle], period: int = 14) -> List[float]:
    trs: List[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            tr = c.high - c.low
        else:
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return [0.0] * len(trs)

    first = sum(trs[:period]) / period
    out = [first] * period
    prev = first
    for tr in trs[period:]:
        prev = ((prev * (period - 1)) + tr) / period
        out.append(prev)
    return out


def trend_label(close: float, ema20: float, ema50: float) -> str:
    if ema20 > ema50 and close > ema20:
        return "上昇トレンド寄り"
    if ema20 < ema50 and close < ema20:
        return "下降トレンド寄り"
    return "レンジ/遷移"


def main() -> int:
    parser = argparse.ArgumentParser(description="FX discretionary support tool (CLI)")
    parser.add_argument("--csv", required=True, help="Path to OHLCV csv")
    parser.add_argument("--balance", type=float, default=300000)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--entry", type=float, default=None)
    parser.add_argument("--stop", type=float, default=None)
    parser.add_argument("--take", type=float, default=None)
    args = parser.parse_args()

    candles = parse_csv(args.csv)
    closes = [c.close for c in candles]

    ema20_list = ema(closes, 20)
    ema50_list = ema(closes, 50)
    rsi14_list = rsi(closes, 14)
    atr14_list = atr(candles, 14)

    latest = candles[-1]
    latest_ema20 = ema20_list[-1]
    latest_ema50 = ema50_list[-1]
    latest_rsi14 = rsi14_list[-1]
    latest_atr14 = atr14_list[-1]

    entry = args.entry if args.entry is not None else latest.close
    stop = args.stop if args.stop is not None else latest.close - 0.05
    take = args.take if args.take is not None else latest.close + 0.10

    risk_amount = args.balance * (args.risk_pct / 100.0)
    stop_pips = abs(entry - stop) * 100  # simplified JPY pair
    reward_pips = abs(take - entry) * 100
    rr = (reward_pips / stop_pips) if stop_pips > 0 else 0.0
    estimated_lot = (risk_amount / (stop_pips * PIP_VALUE_PER_LOT)) if stop_pips > 0 else 0.0

    print("FX 裁量売買支援ツール (CLI)")
    print("=" * 36)
    print(f"最新時刻: {latest.time.isoformat()}")
    print(f"現在価格: {latest.close:.5f}")
    print(f"EMA20: {latest_ema20:.5f}")
    print(f"EMA50: {latest_ema50:.5f}")
    print(f"RSI14: {latest_rsi14:.2f}")
    print(f"ATR14: {latest_atr14:.5f}")
    print(f"トレンド判定: {trend_label(latest.close, latest_ema20, latest_ema50)}")
    print("-" * 36)
    print(f"許容損失額: {risk_amount:,.0f} JPY")
    print(f"損切り幅: {stop_pips:.1f} pips")
    print(f"利確幅: {reward_pips:.1f} pips")
    print(f"RR比: {rr:.2f}")
    print(f"推奨ロット（概算）: {estimated_lot:.3f} lot")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
