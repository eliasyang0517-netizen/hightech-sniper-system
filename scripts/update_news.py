"""Refresh official A-share announcements and recent market news."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak


ROOT = Path(__file__).resolve().parents[1]
STOCKS_PATH = ROOT / "data" / "stocks.json"
NEWS_PATH = ROOT / "data" / "news.json"
META_PATH = ROOT / "data" / "meta.json"
TZ = ZoneInfo("Asia/Shanghai")


def value(row, candidates, default=""):
    for key in candidates:
        if key in row and str(row[key]).lower() not in {"nan", "none"}:
            return str(row[key]).strip()
    return default


def recent_announcements(code, start_date, end_date):
    frame = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code,
        market="沪深京",
        category="",
        start_date=start_date,
        end_date=end_date,
    )
    items = []
    for _, row in frame.head(8).iterrows():
        row = row.to_dict()
        title = value(row, ["公告标题", "标题"])
        url = value(row, ["公告链接", "网址", "链接"])
        if title and url:
            items.append(
                {
                    "type": "announcement",
                    "title": title,
                    "url": url,
                    "publishedAt": value(row, ["公告时间", "公告日期", "时间"]),
                    "source": "巨潮资讯",
                }
            )
    return items


def recent_news(code):
    frame = ak.stock_news_em(symbol=code)
    items = []
    for _, row in frame.head(8).iterrows():
        row = row.to_dict()
        title = value(row, ["新闻标题", "标题"])
        url = value(row, ["新闻链接", "链接", "网址"])
        if title and url:
            items.append(
                {
                    "type": "news",
                    "title": title,
                    "url": url,
                    "publishedAt": value(row, ["发布时间", "时间", "日期"]),
                    "source": value(row, ["文章来源", "来源"], "东方财富"),
                }
            )
    return items


def main():
    stocks = json.loads(STOCKS_PATH.read_text(encoding="utf-8"))
    existing = json.loads(NEWS_PATH.read_text(encoding="utf-8")) if NEWS_PATH.exists() else {}
    now = datetime.now(TZ)
    start = (now - timedelta(days=14)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    refreshed = 0
    failures = []

    for stock in stocks:
        full_code = str(stock.get("code", ""))
        bare_code = full_code.upper().replace(".HK", "")
        previous = existing.get(full_code, {})
        announcements = previous.get("announcements", [])
        news = previous.get("news", [])
        try:
            if not full_code.upper().endswith(".HK"):
                announcements = recent_announcements(bare_code, start, end)
        except Exception as exc:
            failures.append(f"{full_code} 公告: {exc}")
        try:
            news = recent_news(bare_code)
        except Exception as exc:
            failures.append(f"{full_code} 新闻: {exc}")

        existing[full_code] = {
            "name": stock.get("name", ""),
            "announcements": announcements[:5],
            "news": news[:5],
        }
        refreshed += 1
        time.sleep(0.15)

    NEWS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    meta.update(
        {
            "lastNewsUpdate": now.isoformat(timespec="seconds"),
            "newsProvider": "巨潮资讯（A股公告）/ 东方财富（新闻）",
            "newsWarnings": failures,
        }
    )
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Refreshed news containers for {refreshed} stocks; warnings: {len(failures)}")


if __name__ == "__main__":
    main()

