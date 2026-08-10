"""Refresh A/H-share market data without changing fundamental conclusions."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak

from market_analysis import (
    build_market_analysis,
    market_cap_is_consistent,
    parse_quote_time,
    parse_tencent_fields,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "stocks.json"
META_PATH = ROOT / "data" / "meta.json"
TZ = ZoneInfo("Asia/Shanghai")
FALLBACK_HKD_CNY = 0.92
SOURCE_DISAGREEMENT_LIMIT_PCT = 3.0
STALE_WARNING_HOURS = 96
STALE_REJECTION_HOURS = 240


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def first_column(frame, names, required=True):
    for name in names:
        if name in frame.columns:
            return name
    if required:
        raise KeyError(f"None of {names!r} found; available columns: {list(frame.columns)!r}")
    return None


def row_number(row, column):
    return number(row[column]) if column else None


def normalize_a_code(value):
    return str(value).split(".")[0].strip().zfill(6)


def normalize_hk_code(value):
    return str(value).upper().replace(".HK", "").split(".")[0].strip().zfill(5)


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; hightech-sniper-system/2.0)"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def hkd_cny_rate():
    configured = number(os.getenv("HKD_CNY_RATE"))
    if configured and 0.7 <= configured <= 1.2:
        return {
            "rate": configured,
            "provider": "环境变量 HKD_CNY_RATE",
            "isFallback": False,
        }

    providers = [
        (
            "Frankfurter（欧洲央行参考汇率）",
            "https://api.frankfurter.app/latest?from=HKD&to=CNY",
            lambda payload: payload.get("rates", {}).get("CNY"),
        ),
        (
            "Open Exchange Rate API",
            "https://open.er-api.com/v6/latest/HKD",
            lambda payload: payload.get("rates", {}).get("CNY"),
        ),
        (
            "ExchangeRate API",
            "https://api.exchangerate-api.com/v4/latest/HKD",
            lambda payload: payload.get("rates", {}).get("CNY"),
        ),
    ]
    errors = []
    for provider, url, parser in providers:
        try:
            fetched = number(parser(fetch_json(url)))
            if fetched and 0.7 <= fetched <= 1.2:
                return {"rate": fetched, "provider": provider, "isFallback": False}
            errors.append(f"{provider}: 返回值异常")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    return {
        "rate": FALLBACK_HKD_CNY,
        "provider": "固定后备汇率",
        "isFallback": True,
        "errors": errors,
    }


def akshare_quotes(frame, is_hk=False):
    code_col = first_column(frame, ["代码", "证券代码"])
    price_col = first_column(frame, ["最新价", "现价", "最新"])
    cap_col = first_column(frame, ["总市值", "总市值(元)", "总市值(港元)", "总市值(HKD)"], False)
    previous_col = first_column(frame, ["昨收", "昨日收盘价"], False)
    open_col = first_column(frame, ["今开", "开盘价"], False)
    high_col = first_column(frame, ["最高", "最高价"], False)
    low_col = first_column(frame, ["最低", "最低价"], False)
    change_col = first_column(frame, ["涨跌额"], False)
    change_pct_col = first_column(frame, ["涨跌幅"], False)
    turnover_col = first_column(frame, ["换手率"], False)
    pe_col = first_column(frame, ["市盈率-动态", "市盈率", "PE"], False)
    pb_col = first_column(frame, ["市净率", "PB"], False)
    result = {}
    for _, row in frame.iterrows():
        code = normalize_hk_code(row[code_col]) if is_hk else normalize_a_code(row[code_col])
        raw_cap = row_number(row, cap_col)
        result[code] = {
            "price": row_number(row, price_col),
            "previousClose": row_number(row, previous_col),
            "open": row_number(row, open_col),
            "high": row_number(row, high_col),
            "low": row_number(row, low_col),
            "change": row_number(row, change_col),
            "changePct": row_number(row, change_pct_col),
            "turnoverRate": row_number(row, turnover_col),
            "pe": row_number(row, pe_col),
            "pb": row_number(row, pb_col),
            "marketCapYi": raw_cap / 100_000_000 if raw_cap else None,
            "currency": "HKD" if is_hk else "CNY",
            "provider": "AKShare（东方财富行情）",
        }
    return result


def a_share_quotes():
    return akshare_quotes(ak.stock_zh_a_spot_em(), is_hk=False)


def hk_quotes():
    return akshare_quotes(ak.stock_hk_spot_em(), is_hk=True)


def tencent_symbol(code):
    text = str(code).upper()
    if text.endswith(".HK"):
        return "hk" + normalize_hk_code(text)
    bare = normalize_a_code(text)
    if bare.startswith(("4", "8", "92")):
        return "bj" + bare
    if bare.startswith(("5", "6", "9")):
        return "sh" + bare
    return "sz" + bare


def tencent_quotes(stocks):
    """Tencent public quotes, used as the resilient primary/fallback source."""
    symbol_to_code = {tencent_symbol(stock["code"]): str(stock["code"]) for stock in stocks}
    symbols = list(symbol_to_code)
    result = {}
    for offset in range(0, len(symbols), 50):
        batch = symbols[offset : offset + 50]
        request = urllib.request.Request(
            "https://qt.gtimg.cn/q=" + ",".join(batch),
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; hightech-sniper-system/2.0)",
                "Referer": "https://finance.qq.com/",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("gb18030", errors="replace")
        for symbol, payload in re.findall(r'v_([^=]+)="([^"]*)"', body):
            original_code = symbol_to_code.get(symbol.lower()) or symbol_to_code.get(symbol)
            if not original_code:
                continue
            is_hk = original_code.upper().endswith(".HK")
            quote = parse_tencent_fields(payload.split("~"), is_hk=is_hk)
            if quote.get("price"):
                quote["provider"] = "腾讯行情"
                result[original_code] = quote
    return result


def relative_difference_pct(left, right):
    if not left or not right:
        return None
    return abs(left - right) / ((abs(left) + abs(right)) / 2) * 100


def suspicious_price_jump(old_price, new_price, previous_close):
    old_jump = relative_difference_pct(number(old_price), number(new_price))
    if old_jump is None or old_jump <= 50:
        return False
    session_jump = relative_difference_pct(number(previous_close), number(new_price))
    return session_jump is None or session_jump > 35


def merge_quotes(tencent, akshare_quote, now):
    if not tencent and not akshare_quote:
        return None, "无可用行情源"

    source_prices = {}
    if tencent and tencent.get("price"):
        source_prices["腾讯行情"] = tencent["price"]
    if akshare_quote and akshare_quote.get("price"):
        source_prices["AKShare（东方财富行情）"] = akshare_quote["price"]

    source_difference = None
    if len(source_prices) == 2:
        source_difference = relative_difference_pct(*source_prices.values())
        if source_difference is not None and source_difference > SOURCE_DISAGREEMENT_LIMIT_PCT:
            return None, f"双源价格偏差 {source_difference:.2f}% 超过阈值"

    primary = dict(tencent or akshare_quote)
    secondary = akshare_quote if tencent else None
    if secondary:
        for key, value in secondary.items():
            if primary.get(key) is None and value is not None:
                primary[key] = value

    quote_time = parse_quote_time(primary.get("quoteRawTime"), TZ)
    age_hours = (now - quote_time).total_seconds() / 3600 if quote_time else None
    if age_hours is not None and age_hours > STALE_REJECTION_HOURS:
        return None, f"行情时间滞后 {age_hours:.1f} 小时"

    primary.update(
        {
            "provider": " + ".join(source_prices),
            "validationStatus": "dual-source" if len(source_prices) == 2 else "single-source",
            "validationLabel": "双源一致" if len(source_prices) == 2 else "单源有效",
            "sourcePrices": source_prices,
            "sourceDifferencePct": round(source_difference, 4) if source_difference is not None else None,
            "quoteTime": quote_time.isoformat(timespec="seconds") if quote_time else None,
            "quoteAgeHours": round(age_hours, 2) if age_hours is not None else None,
            "stale": bool(age_hours is not None and age_hours > STALE_WARNING_HOURS),
        }
    )
    return primary, None


def main():
    stocks = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    updated_at = now.isoformat(timespec="seconds")
    failures = []

    try:
        quotes_a = a_share_quotes()
    except Exception as exc:
        quotes_a = {}
        failures.append(f"A股 AKShare 行情失败: {exc}")

    try:
        quotes_hk = hk_quotes()
    except Exception as exc:
        quotes_hk = {}
        failures.append(f"港股 AKShare 行情失败: {exc}")

    try:
        quotes_tencent = tencent_quotes(stocks)
    except Exception as exc:
        quotes_tencent = {}
        failures.append(f"腾讯行情失败: {exc}")

    fx_info = hkd_cny_rate()
    fx = fx_info["rate"]
    if fx_info.get("isFallback"):
        failures.append("动态 HKD/CNY 汇率源均不可用，已使用固定后备汇率 0.92")

    updated = 0
    missing = []
    rejected = []
    market_cap_rejected = []
    dual_source = 0
    single_source = 0
    stale = 0
    source_differences = []

    for stock in stocks:
        code = str(stock.get("code", ""))
        is_hk = code.upper().endswith(".HK")
        lookup = quotes_hk if is_hk else quotes_a
        key = normalize_hk_code(code) if is_hk else normalize_a_code(code)
        quote, rejection_reason = merge_quotes(quotes_tencent.get(code), lookup.get(key), now)
        if rejection_reason:
            missing.append(code)
            rejected.append({"code": code, "reason": rejection_reason})
            continue
        if not quote or not quote.get("price"):
            missing.append(code)
            continue
        if suspicious_price_jump(stock.get("price"), quote["price"], quote.get("previousClose")):
            missing.append(code)
            rejected.append({"code": code, "reason": "相对旧价格出现异常跳变"})
            continue

        old_price = stock.get("price")
        old_cap = stock.get("marketCap")
        local_cap_yi = quote.get("marketCapYi")
        cap_ok = market_cap_is_consistent(
            old_cap,
            old_price,
            local_cap_yi,
            quote["price"],
            fx,
            is_hk,
            quote.get("floatMarketCapYi"),
        )

        stock.setdefault("analysisAsOf", stock.get("asOf"))
        stock["price"] = round(quote["price"], 3)
        if local_cap_yi and cap_ok:
            stock["marketCap"] = round(local_cap_yi * fx if is_hk else local_cap_yi, 2)
        elif local_cap_yi and not cap_ok:
            market_cap_rejected.append(code)

        market = {
            key_name: quote.get(key_name)
            for key_name in (
                "previousClose", "open", "high", "low", "change", "changePct", "volume",
                "turnoverAmount", "turnoverRate", "pe", "pb", "currency", "quoteTime",
                "quoteAgeHours", "stale", "provider", "validationStatus", "validationLabel",
                "sourcePrices", "sourceDifferencePct",
            )
        }
        market.update(
            {
                "marketCapLocalYi": round(local_cap_yi, 4) if local_cap_yi else None,
                "floatMarketCapLocalYi": round(quote.get("floatMarketCapYi"), 4)
                if quote.get("floatMarketCapYi")
                else None,
                "marketCapAccepted": bool(local_cap_yi and cap_ok),
                "fxRateApplied": fx if is_hk else 1.0,
                "updatedAt": updated_at,
            }
        )
        stock["market"] = market
        stock["autoAnalysis"] = build_market_analysis(stock, market, updated_at)
        stock["asOf"] = now.strftime("%Y-%m-%d %H:%M")
        stock["quoteUpdatedAt"] = updated_at
        stock["quoteProvider"] = quote.get("provider")

        updated += 1
        dual_source += market["validationStatus"] == "dual-source"
        single_source += market["validationStatus"] == "single-source"
        stale += bool(market.get("stale"))
        if market.get("sourceDifferencePct") is not None:
            source_differences.append(market["sourceDifferencePct"])

    if updated == 0:
        for failure in failures:
            print(f"WARNING: {failure}")
        raise RuntimeError("No quotes were updated; refusing to overwrite the data file")

    DATA_PATH.write_text(json.dumps(stocks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    meta.update(
        {
            "quoteProvider": "腾讯行情；AKShare/东方财富可用时进行双源校验",
            "lastPriceUpdate": updated_at,
            "stockCount": len(stocks),
            "updatedQuotes": updated,
            "missingQuotes": missing,
            "coveragePct": round(updated / len(stocks) * 100, 2),
            "hkdCnyRate": fx,
            "fx": {
                "rate": fx,
                "provider": fx_info["provider"],
                "isFallback": fx_info.get("isFallback", False),
                "checkedAt": updated_at,
            },
            "validation": {
                "dualSourceQuotes": dual_source,
                "singleSourceQuotes": single_source,
                "staleQuotes": stale,
                "rejectedQuotes": rejected,
                "marketCapRejected": market_cap_rejected,
                "maxSourceDifferencePct": max(source_differences, default=None),
            },
            "warnings": failures,
            "note": "自动任务仅更新市场行情与自动市场分析，不改写 S1–S5、红线、狙击价和原始基本面结论。",
        }
    )
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Updated {updated}/{len(stocks)} quotes; missing {len(missing)}; "
        f"dual-source {dual_source}; single-source {single_source}; stale {stale}"
    )
    for failure in failures:
        print(f"WARNING: {failure}")


if __name__ == "__main__":
    main()
