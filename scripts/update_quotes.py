"""Refresh A-share and Hong Kong quotes while preserving research conclusions."""

from __future__ import annotations

import json
import math
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "stocks.json"
META_PATH = ROOT / "data" / "meta.json"
TZ = ZoneInfo("Asia/Shanghai")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def first_column(frame, names):
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"None of {names!r} found; available columns: {list(frame.columns)!r}")


def normalize_a_code(value):
    text = str(value).split(".")[0].strip()
    return text.zfill(6)


def normalize_hk_code(value):
    text = str(value).upper().replace(".HK", "").split(".")[0].strip()
    return text.zfill(5)


def hkd_cny_rate():
    configured = number(os.getenv("HKD_CNY_RATE"))
    if configured:
        return configured
    try:
        with urllib.request.urlopen(
            "https://api.frankfurter.app/latest?from=HKD&to=CNY", timeout=10
        ) as response:
            payload = json.load(response)
        fetched = number(payload.get("rates", {}).get("CNY"))
        if fetched:
            return fetched
    except Exception as exc:  # Keep quote updates working if FX service is down.
        print(f"FX lookup failed, using fallback: {exc}")
    return 0.92


def a_share_quotes():
    frame = ak.stock_zh_a_spot_em()
    code_col = first_column(frame, ["代码", "证券代码"])
    price_col = first_column(frame, ["最新价", "现价", "最新"])
    cap_col = first_column(frame, ["总市值", "总市值(元)"])
    result = {}
    for _, row in frame.iterrows():
        code = normalize_a_code(row[code_col])
        result[code] = {
            "price": number(row[price_col]),
            "marketCap": number(row[cap_col]),
        }
    return result


def hk_quotes():
    frame = ak.stock_hk_spot_em()
    code_col = first_column(frame, ["代码", "证券代码"])
    price_col = first_column(frame, ["最新价", "现价", "最新"])
    cap_col = first_column(frame, ["总市值", "总市值(港元)", "总市值(HKD)"])
    result = {}
    for _, row in frame.iterrows():
        code = normalize_hk_code(row[code_col])
        result[code] = {
            "price": number(row[price_col]),
            "marketCap": number(row[cap_col]),
        }
    return result


def main():
    stocks = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    updated_at = now.isoformat(timespec="seconds")
    failures = []

    try:
        quotes_a = a_share_quotes()
    except Exception as exc:
        quotes_a = {}
        failures.append(f"A股行情失败: {exc}")

    try:
        quotes_hk = hk_quotes()
    except Exception as exc:
        quotes_hk = {}
        failures.append(f"港股行情失败: {exc}")

    fx = hkd_cny_rate()
    updated = 0
    missing = []
    for stock in stocks:
        code = str(stock.get("code", ""))
        is_hk = code.upper().endswith(".HK")
        lookup = quotes_hk if is_hk else quotes_a
        key = normalize_hk_code(code) if is_hk else normalize_a_code(code)
        quote = lookup.get(key)
        if not quote or not quote.get("price"):
            missing.append(code)
            continue

        stock.setdefault("analysisAsOf", stock.get("asOf"))
        stock["price"] = round(quote["price"], 3)
        raw_cap = quote.get("marketCap")
        if raw_cap:
            cap_cny = raw_cap * fx if is_hk else raw_cap
            stock["marketCap"] = round(cap_cny / 100_000_000, 2)
        stock["asOf"] = now.strftime("%Y-%m-%d %H:%M")
        stock["quoteUpdatedAt"] = updated_at
        stock["quoteProvider"] = "AKShare（东方财富行情）"
        updated += 1

    if updated == 0:
        raise RuntimeError("No quotes were updated; refusing to overwrite the data file")

    DATA_PATH.write_text(json.dumps(stocks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    meta.update(
        {
            "quoteProvider": "AKShare（东方财富行情）",
            "lastPriceUpdate": updated_at,
            "stockCount": len(stocks),
            "updatedQuotes": updated,
            "missingQuotes": missing,
            "hkdCnyRate": fx,
            "warnings": failures,
        }
    )
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {updated}/{len(stocks)} quotes; missing {len(missing)}")
    for failure in failures:
        print(f"WARNING: {failure}")


if __name__ == "__main__":
    main()

