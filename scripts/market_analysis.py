"""Pure market-data validation and automatic analysis helpers."""

from __future__ import annotations

import math
import re
from datetime import datetime


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def sniper_bounds(value):
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*[–-]\s*([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if not match:
        return None
    low, high = map(float, match.groups())
    return (low, high) if low <= high else (high, low)


def parse_tencent_fields(fields, is_hk=False):
    """Map the stable public Tencent quote fields used by this project."""

    def at(index):
        return fields[index] if len(fields) > index else None

    def positive(index):
        value = number(at(index))
        return value if value is not None and value > 0 else None

    return {
        "price": positive(3),
        "previousClose": positive(4),
        "open": positive(5),
        "change": number(at(31)),
        "changePct": number(at(32)),
        "high": positive(33),
        "low": positive(34),
        "volume": positive(36),
        "turnoverAmount": positive(37),
        "turnoverRate": number(at(38)),
        "pe": number(at(39)),
        "pb": number(at(58 if is_hk else 46)),
        "floatMarketCapYi": positive(44),
        "marketCapYi": positive(45),
        "quoteRawTime": at(30),
        "currency": "HKD" if is_hk else "CNY",
    }


def market_cap_is_consistent(
    old_cap_cny_yi,
    old_price,
    new_cap_local_yi,
    new_price,
    fx_rate,
    is_hk,
    new_float_cap_local_yi=None,
):
    """Compare implied shares to catch currency/unit mapping errors."""
    values = [number(old_cap_cny_yi), number(old_price), number(new_cap_local_yi), number(new_price)]
    if any(v is None or v <= 0 for v in values):
        return True
    old_cap_local = values[0] / fx_rate if is_hk else values[0]
    old_implied_shares = old_cap_local / values[1]
    candidate_shares = [values[2] / values[3]]
    float_cap = number(new_float_cap_local_yi)
    if float_cap and float_cap > 0:
        candidate_shares.append(float_cap / values[3])
    return any(abs(shares / old_implied_shares - 1) <= 0.25 for shares in candidate_shares)


def build_market_analysis(stock, market, generated_at):
    price = number(stock.get("price"))
    fair = number(stock.get("fairValue"))
    change_pct = number(market.get("changePct"))
    bounds = sniper_bounds(stock.get("sniperPrice"))
    layer = str(stock.get("layer", ""))
    light = str(stock.get("step0", {}).get("light", ""))
    redline_passed = stock.get("redline", {}).get("passed", True)

    if not price:
        signal, zone = "数据不足", "无有效价格"
    elif not redline_passed:
        signal, zone = "控仓观察", "触发红线"
    elif layer == "非狙击" or light == "红灯" or not bounds:
        signal, zone = "观察", "不在自动狙击区"
    elif price < bounds[0]:
        signal, zone = "等待确认", "低于计划区间"
    elif price > bounds[1]:
        signal, zone = "谨慎追高", "高于计划区间"
    else:
        signal, zone = "区间内", "位于计划区间"

    valuation_gap = round((fair / price - 1) * 100, 2) if price and fair else None
    parts = [zone]
    if change_pct is not None:
        parts.append(f"当日涨跌 {change_pct:+.2f}%")
    if valuation_gap is not None:
        direction = "上方" if valuation_gap >= 0 else "下方"
        parts.append(f"合理中枢位于现价{direction} {abs(valuation_gap):.2f}%")
    if market.get("validationStatus") == "single-source":
        parts.append("当前为单一行情源，交易前需用券商复核")

    return {
        "signal": signal,
        "zone": zone,
        "dailyChangePct": change_pct,
        "valuationGapPct": valuation_gap,
        "summary": "；".join(parts),
        "generatedAt": generated_at,
        "basis": "实时/收盘行情、原研究狙击区间与合理中枢；不自动改写基本面评分",
    }


def parse_quote_time(value, timezone):
    text = re.sub(r"\D", "", str(value or ""))
    if len(text) < 14:
        return None
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone)
    except ValueError:
        return None
