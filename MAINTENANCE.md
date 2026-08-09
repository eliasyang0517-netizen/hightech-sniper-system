# 股票狙击系统维护说明

## 目录

- `index.html`：新版页面，只负责展示。
- `data/stocks.json`：93 只股票的行情和研究结论。
- `data/news.json`：每只股票的近期公告和新闻。
- `data/meta.json`：最近更新时间、数据源和异常记录。
- `legacy/index.html`：改造前的完整静态版本。
- `scripts/update_quotes.py`：更新 A 股、港股价格和总市值。
- `scripts/update_news.py`：更新 A 股公告和股票新闻。
- `.github/workflows/`：GitHub Actions 定时任务。

## 自动更新时间

- 行情：工作日北京时间 09:00–15:59，每 15 分钟触发一次。
- 公告和新闻：工作日北京时间 18:45 触发一次。
- GitHub 的定时任务可能延迟数分钟，不是交易所级实时行情。

## 数据来源

- 行情：AKShare 封装的东方财富公开行情。
- A 股公告：巨潮资讯。
- 新闻：东方财富。
- 港股市值按 HKD/CNY 汇率折算为亿元人民币；汇率接口不可用时使用 `0.92`。

这些免费来源可能改版、限流或短暂不可用，不适合直接作为下单依据。交易前应以券商行情和交易所公告复核。

## 手动运行

在仓库的 **Actions** 页面选择对应任务，再点击 **Run workflow**：

1. `Update stock quotes`
2. `Update stock announcements and news`

也可以在本机运行：

```powershell
python -m pip install -r requirements.txt
python scripts/update_quotes.py
python scripts/update_news.py
```

## 如何修改研究结论

自动任务只更新 `price`、`marketCap`、`asOf`、公告和新闻，不会改动 S1–S5、灯色、红线、狙击价或结论。

需要调整分析时，编辑 `data/stocks.json` 中对应股票的字段并提交。建议保留 `analysisAsOf`，注明研究结论所依据的日期。

## 故障排查

在 GitHub 的 **Actions** 页面查看失败任务。常见原因：

- 免费数据源接口字段变化；
- 数据源限流或临时不可用；
- 仓库的 Workflow permissions 未允许 `Read and write permissions`。

如果出现最后一种情况，进入仓库 **Settings → Actions → General → Workflow permissions**，选择读写权限后保存。
