# stockanalysis.com API 爬虫

逆向分析 [stockanalysis.com](https://stockanalysis.com) 的内部 REST API，通过 Playwright 模拟已登录的浏览器会话，自动发现并记录所有 `/api/` 端点。

## 背景

stockanalysis.com 是一个基于 SvelteKit 的 SPA。大部分页面数据通过 SSR 和 SvelteKit 的 `__data.json` 机制传输，而非传统 REST 调用。本工具识别前端在运行时实际请求的 `/api/` 端点（实时报价、历史价格、市场迷你图、搜索等）。

## 已发现的端点

完整文档见 [`output/api_docs.md`](output/api_docs.md)。

| 端点 | 说明 |
|---|---|
| `GET /api/search?q={query}` | 全局搜索 — 股票、ETF、国际证券 |
| `GET /api/quotes/s/{ticker}` | 股票实时报价 |
| `GET /api/quotes/e/{ticker}` | ETF 实时报价 |
| `GET /api/symbol/s/{ticker}/history?type=chart\|annual\|quarterly` | 股票历史价格 |
| `GET /api/symbol/e/{ticker}/history?type=chart` | ETF 历史价格 |
| `GET /api/mc/pre?c=1` | 盘前迷你图 (SPY) |
| `GET /api/mc/post?c=1` | 盘后迷你图 (SPY) |
| `GET /api/mc/1d?c=1` | 盘中迷你图 (SPY) |

## 工作原理

```
a.sh  →  cookie_parser.py  →  crawler.py  →  normalizer.py  →  generate_docs.py
                                  ↓
                          output/raw_requests.json
                          output/normalized.json
                          output/api_docs.md
```

1. **`cookie_parser.py`** — 解析从浏览器 DevTools 导出的 `curl` 命令中的 Cookie 字符串
2. **`crawler.py`** — 通过 Playwright 启动无头 Chromium，注入 Cookie 后分三个阶段运行：
   - **阶段 1**：加载完整页面，捕获浏览器自动发出的 XHR/fetch 请求（`/api/quotes/`、`/api/mc/` 等）
   - **阶段 2**：在已认证的浏览器上下文中请求每个路由的 `__data.json`，发现 SvelteKit 数据端点
   - **阶段 3**：直接探测已知的 `/api/` URL 模式
3. **`normalizer.py`** — 过滤出 `stockanalysis.com/api/*` 请求，将动态路径段替换为占位符（`{ticker}`、`{id}`），去重
4. **`generate_docs.py`** — 从标准化数据生成 `output/api_docs.md` 文档
5. **`run.py`** — 按顺序编排以上四个步骤

## 快速开始

**环境要求：** Python 3.12+

```bash
# 1. 克隆仓库
git clone https://github.com/haskaomni/stockanalysis.git
cd stockanalysis

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 4. 添加登�� Cookie
#    - 在 Chrome 中打开 stockanalysis.com 并登录
#    - 打开 DevTools → Network → 右键任意请求 → "Copy as cURL"
#    - 将结果粘贴到 a.sh 中
cp a.sh.example a.sh
# 编辑 a.sh，替换 -b '...' 中的 Cookie 字符串为你的真实 Cookie

# 5. 运行
python run.py
```

输出文件在 `output/` 目录下：

| 文件 | 说明 |
|---|---|
| `raw_requests.json` | 所有捕获的网络请求（已 gitignore，可能 15MB+） |
| `normalized.json` | 去重后的端点模式（已 gitignore） |
| `api_docs.md` | 人类可读的 API 参考文档 ✅ |

## 单独重新生成文档

如果已有 `output/raw_requests.json`，只想重新标准化或格式化文档：

```bash
python normalizer.py          # 从 raw_requests.json 重新生成 normalized.json
python generate_docs.py       # 从 normalized.json 重新生成 api_docs.md
```

## 注意事项

- 爬虫运行约 3 分钟（无头 Chromium 加载约 40 个页面）
- 会话 Cookie 会过期。如果出现 401/403 响应，请从浏览器重新导出 Cookie
- Screener（`/stocks/screener/`、`/etf/screener/`）和所有财务报表页面通过 SvelteKit SSR 提供数据，没有单独的 `/api/` 端点

## 许可证

MIT
