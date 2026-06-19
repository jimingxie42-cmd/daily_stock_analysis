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

# ── 拉 K 线数据 计算技术指标 ──
def get_kline(code):
    """获取30日K线，返回MA5/MA10/MA20/量比"""
    mkt = "sh" if code.startswith("6") else "sz"
    try:
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={mkt}{code}&scale=30&ma=no&datalen=30"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not data: return None
        closes = [float(d["close"]) for d in data]
        volumes = [float(d["volume"]) for d in data]
        latest = data[-1]
        close = float(latest["close"])
        ma5 = sum(closes[-5:])/5 if len(closes)>=5 else close
        ma10 = sum(closes[-10:])/10 if len(closes)>=10 else close
        ma20 = sum(closes[-20:])/20 if len(closes)>=20 else close
        # 量比：今日量 / 近5日均量
        vol_ratio = volumes[-1] / (sum(volumes[-6:-1])/5) if len(volumes)>=6 else 1.0
        # 均线排列
        if ma5 > ma10 > ma20: trend = "多头排列 📈"
        elif ma5 < ma10 < ma20: trend = "空头排列 📉"
        else: trend = "均线缠绕"
        return {
            "close": close, "open": float(latest["open"]), "high": float(latest["high"]), "low": float(latest["low"]),
            "ma5": round(ma5,2), "ma10": round(ma10,2), "ma20": round(ma20,2),
            "bias_ma5": round((close-ma5)/ma5*100,2),
            "vol_ratio": round(vol_ratio,2), "trend": trend,
            "volume": int(volumes[-1])
        }
    except:
        return None

tech_data = {}
for s in holdings:
    k = get_kline(s["code"])
    if k:
        tech_data[s["code"]] = k

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

# ── 市场热点选股 ──
def get_top_movers():
    """从新浪拉涨幅榜+换手率榜，筛选潜在标的"""
    candidates = []
    try:
        # 涨幅榜前40
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=40&sort=changepercent&asc=0&node=hs_a"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        data = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
        stocks = json.loads(data)
        for s in stocks:
            code = s["code"]; name = s["name"]
            chg = float(s["changepercent"]); vol = int(s["volume"])/100 if s["volume"] else 0
            turnover = float(s.get("turnoverratio", 0) or 0)
            price = float(s["trade"])
            # 筛选：涨幅2-8%（健康上涨非涨停）、主板优先、换手>3%
            if 2 < chg < 8 and turnover > 3 and (code.startswith("60") or code.startswith("00")):
                candidates.append({"code": code, "name": name, "price": price, "chg_pct": chg, "turnover": turnover, "vol": vol})
            if len(candidates) >= 8:
                break
    except Exception as e:
        print(f"选股失败: {e}")
    return candidates[:5]

# 选股：仅在9:00和15:30（UTC 1点、7点）执行
picks_text = ""
utc_hour = time.gmtime().tm_hour
if utc_hour in [1, 7]:  # 9:00 或 15:30 BJT
    picks = get_top_movers()
    if picks:
        picks_text = "## 今日市场强势候选（涨幅2-8%，换手>3%，主板）\n"
        picks_text += "\n".join(f"- {p['name']}({p['code']}) | 价格{p['price']} | 涨{p['chg_pct']:+.1f}% | 换手{p['turnover']:.1f}%" for p in picks)
        picks_text += "\n\n请结合这些候选股，对比用户持仓，给出是否应该换仓的建议。"

# ── 调 DeepSeek ──
prompt = f"""你是专业的A股投资顾问。以下是用户的持仓数据和今日行情，请给每只股票给出操作建议。

## 用户持仓
{holdings_text}

## 今日行情
""" + "\n".join(f"{v['name']}({k}): 现价{v['price']} 今开{v['open']} 最高{v['high']} 最低{v['low']}" for k,v in prices.items()) + f"""

## 技术指标
""" + "\n".join(f"{prices.get(c,{}).get('name',c)}({c}): MA5={t['ma5']} MA10={t['ma10']} MA20={t['ma20']} | 乖离率(MA5)={t['bias_ma5']}% | 量比={t['vol_ratio']} | 均线={t['trend']}" for c,t in tech_data.items()) + f"""

## 相关新闻
{news_text}

{picks_text}

请按以下格式输出完整的【决策仪表盘】：

## 综合评分与操作建议
| 股票 | 评分(0-100) | 建议 | 持仓成本 | 现价 | 浮盈(%) | 理由 |
|------|:---:|------|------|------|------|------|
（每只一行，评分必须基于用户实际持仓成本）

## 详细分析
（每只股票一段话，必须结合用户的持仓成本给出个性化建议。例如「您的成本32.26元，现价53.50元，浮盈65.9%，建议持有并设止盈位58元」）

## 买卖点位
| 股票 | 买入点 | 加仓位 | 止盈位 | 止损位 |
|------|------|------|------|------|
（给出具体价格）

## 今日候选股（对比持仓）
（对比今日强势候选股，判断是否需要换仓。如果候选股明显优于持仓中的某只，请明确指出）

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

print(result)
for pusher in [push_serverchan, push_pushplus]:
    try:
        pusher(title, full)
    except Exception as e:
        print(f"推送失败({pusher.__name__}): {e}")

print("\n✅ 分析完成")