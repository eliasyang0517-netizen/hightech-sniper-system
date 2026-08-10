# 股票狙击系统维护说明

## 目录

- `index.html`：新版页面，只负责展示。
- `data/stocks.json`：93 只股票的行情和研究结论。
- `data/news.json`：每只股票的近期公告和新闻。
- `data/meta.json`：最近更新时间、数据源和异常记录。
- `legacy/index.html`：改造前的完整静态版本。
- `scripts/update_quotes.py`：更新 A 股、港股行情，执行双源/滞后/异常跳变/市值单位校验，并生成自动市场分析。
- `scripts/market_analysis.py`：不联网的行情解析、校验与自动分析函数。
- `tests/`：行情字段解析和安全校验测试。
- `scripts/update_news.py`：更新 A 股公告和股票新闻。
- `.github/workflows/`：GitHub Actions 定时任务。

## 自动更新时间

- 行情：工作日北京时间 09:00–15:00，每小时整点触发一次（共 7 次）。
- 公告和新闻：工作日北京时间 18:45 触发一次。
- GitHub 的定时任务可能延迟数分钟，不是交易所级实时行情。

## 数据来源

- 行情：腾讯公开行情为稳定来源；AKShare 封装的东方财富行情可用时进行双源价格校验。
- A 股公告：巨潮资讯。
- 新闻：东方财富。
- 港股市值按动态 HKD/CNY 汇率折算为亿元人民币。脚本依次尝试 Frankfurter、Open Exchange Rate API 和 ExchangeRate API；全部不可用时才使用 `0.92`，页面会明确标为“后备”。

行情任务还会检查：双源价格偏差、行情是否滞后、相对旧价格是否异常跳变，以及“市值÷股价”隐含股本是否出现异常变化。异常价格会拒绝写入；市值单位异常时只保留旧市值，不影响有效股价更新。

这些免费来源可能改版、限流或短暂不可用，不适合直接作为下单依据。交易前应以券商行情和交易所公告复核。

## 手动运行

在仓库的 **Actions** 页面选择对应任务，再点击 **Run workflow**：

1. `Update stock quotes`
2. `Update stock announcements and news`

也可以在本机运行：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python scripts/update_quotes.py
python scripts/update_news.py
```

## 如何修改研究结论

自动任务只更新 `price`、`marketCap`、`market`、`autoAnalysis`、`asOf`、公告和新闻，不会改动 S1–S5、灯色、红线、狙击价或原始基本面结论。`autoAnalysis` 只是基于现价、涨跌、原狙击区间、合理中枢和红线状态生成的行情层提示。

需要调整分析时，编辑 `data/stocks.json` 中对应股票的字段并提交。建议保留 `analysisAsOf`，注明研究结论所依据的日期。

## 故障排查

在 GitHub 的 **Actions** 页面查看失败任务。常见原因：

- 免费数据源接口字段变化；
- 数据源限流或临时不可用；
- 仓库的 Workflow permissions 未允许 `Read and write permissions`。

如果出现最后一种情况，进入仓库 **Settings → Actions → General → Workflow permissions**，选择读写权限后保存。
