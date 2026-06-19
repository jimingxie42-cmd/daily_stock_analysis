"""自定义持仓分析 - 直接调 DeepSeek API，含持仓成本+买卖建议"""
import json, os, urllib.request, urllib.parse, time, hashlib, sys

# ── 读持仓 ──
BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "holdings.json")) as f:
    holdings = json.load(f)["stocks"]

# ── 拉实时价（新浪） ──
codes = [s["code"] for s in holdings]
url = "http://hq.sinajs.cn/list=" + ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes)
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
prices = {}
for line in raw.strip().split("\n"):
    parts = line.split('"')[1].split(",")
    code = line.split("=")[0][-6:]
    prices[code] = {"name": parts[0], "price": float(parts[3]), "open": float(parts[1]),
                     "high": float(parts[4]), "low": float(parts[5]), "prev_close": float(parts[2])}

# ── 搜新闻（Tavily） ──
def search_news(query):
    try:
        key = os.environ.get("TAVILY_API_KEYS", "").split(",")[0]
        data = json.dumps({"query": query, "max_results": 3, "search_depth": "basic"})
        req = urllib.request.Request("https://api.tavily.com/search", data=data.encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return [r.get("title","") + ": " + r.get("content","")[:200] for r in resp.get("results",[])]
    except:
        return ["(新闻获取失败)"]

# ── 构建持仓摘要 ──
holdings_text = ""
total_value = 0
total_cost = 0
for s in holdings:
    c = s["code"]
    if c in prices:
        p = prices[c]
        value = s["shares"] * p["price"]
        cost = s["shares"] * s["cost"]
        pnl = value - cost
        pnl_pct = (p["price"] / s["cost"] - 1) * 100
        total_value += value
        total_cost += cost
        holdings_text += f"{s['name']}({c}) | 持{s['shares']}股 | 成本{s['cost']} | 现价{p['price']} | 市值{value:.0f} | 浮盈{pnl:+.0f}({pnl_pct:+.1f}%) | 今涨{((p['price']/p['prev_close']-1)*100):+.1f}%\n"

total_pnl = total_value - total_cost
holdings_text += f"\n总市值{total_value:.0f} | 总成本{total_cost:.0f} | 总浮盈{total_pnl:+.0f}"

# ── 搜每只票的新闻 ──
news_text = ""
for s in holdings:
    c = s["code"]
    name = prices.get(c, {}).get("name", s["name"])
    items = search_news(f"{name} {c} A股 最新消息 公告 2026")
    if items:
        news_text += f"\n### {name}({c})\n" + "\n".join(f"- {i}" for i in items[:2])

# ── 调 DeepSeek ──
prompt = f"""你是专业的A股投资顾问。以下是用户的持仓数据和今日行情，请给每只股票给出操作建议。

## 用户持仓
{holdings_text}

## 今日行情
""" + "\n".join(f"{v['name']}({k}): 现价{v['price']} 今开{v['open']} 最高{v['high']} 最低{v['low']}" for k,v in prices.items()) + f"""

## 相关新闻
{news_text}

请按以下格式输出：
## 综合评分与操作建议
| 股票 | 评分(0-100) | 建议 | 理由 |
|------|:---:|------|------|
（每只一行）

## 详细分析
（每只股票一段话：结合持仓成本给出买入/持有/卖出/减仓建议，说明止损位和目标价）

## 风险提示
（整体风险提示）"""

api_key = os.environ.get("OPENAI_API_KEY", "")
api_base = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
api_model = os.environ.get("LITELLM_MODEL", "openai/deepseek-chat")
# 如果模型名有前缀，去掉
if "/" in api_model:
    api_model = api_model.split("/")[-1]

payload = {
    "model": api_model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.3,
    "max_tokens": 2000,
}
req = urllib.request.Request(f"{api_base}/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
result = resp["choices"][0]["message"]["content"]

# ── 推送 ──
def push_serverchan(title, content):
    key = os.environ.get("SERVERCHAN3_SENDKEY", "")
    if key:
        urllib.request.urlopen(f"https://sctapi.ftqq.com/{key}.send?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(content[:5000])}", timeout=10)

def push_pushplus(title, content):
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if token:
        data = json.dumps({"token": token, "title": title, "content": content[:5000]})
        req = urllib.request.Request("https://www.pushplus.plus/send", data=data.encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)

title = f"投资分析 {time.strftime('%H:%M')}"
full = f"{result}\n\n---\n持仓数据来源: 新浪实时行情 | 分析: DeepSeek"
push_serverchan(title, full)
push_pushplus(title, full)

print(result)
print("\n✅ 推送完成")