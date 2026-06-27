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

# 选股：仅在8:30和14:30（UTC 0点、6点）执行盘前推荐+盘后复盘
picks_text = ""
utc_hour = time.gmtime().tm_hour
if utc_hour in [0, 6]:  # 8:30 或 14:30 BJT
    picks = get_top_movers()
    if picks:
        picks_text = "## 今日市场强势候选（涨幅2-8%，换手>3%，主板）\n"
        picks_text += "\n".join(f"- {p['name']}({p['code']}) | 价格{p['price']} | 涨{p['chg_pct']:+.1f}% | 换手{p['turnover']:.1f}%" for p in picks)
        picks_text += "\n\n请结合这些候选股，对比用户持仓，给出是否应该换仓的建议。"

# ── 调 DeepSeek（嵌入 skill 框架）──
SYSTEM_PROMPT = """你是专业的A股投资顾问，采用以下多层分析框架：

【财务健康层 | financial-health】
- 盈利质量：经营现金流/净利润 >1.0 才是真金白银；应收款增速>营收增速是回款恶化信号
- 红色预警清单：营收增而经营现金流降 | 应收款增速超营收 | 存货激增无匹配发货 | 财务费用升而利润弱 | 大额短期债务墙
- 对周期股：毛利率趋势比绝对值重要，成本刚性上升是关键隐患

【行业竞争与护城河层 | industry-competition-moat】
- 周期定位：判断当前处于周期顶部/中部/底部，结合库存、产能、需求
- 成本曲线位置：在行业成本曲线低位才有穿越周期的能力
- 竞争威胁：新产能投放节奏、替代品、政策风险

【战略业务转型层 | strategy-business-transition】
- 判断公司是否处于业务转型期（如天齐锂业从锂矿向锂盐加工延伸）
- 转型进度：新业务收入占比趋势、旧业务拖累程度
- 关键验证点：产能投放里程碑、客户突破、成本优化进展
- 旧资产/旧模式的遗留负担：减值风险、运营资金占用

【风险催化层 | risk-warning-catalysts】
- 区分短期催化剂（1-4周）与中长期结构风险（3-12个月）
- 每条风险标注：触发概率（高/中/低）× 影响程度（致命/重大/有限）
- 给出具体监测指标和阈值

输出必须严格按以下结构，不可跳过任何部分：

## 一、事实与数据
（基于提供的数据，逐只列出核心事实。标注数据来源。）

## 二、财务健康诊断
（每只股票：盈利质量评估 | 现金流健康度 | 红色预警信号（有/无，具体原因））

## 三、行业周期与护城河
（每只股票：当前周期位置 | 成本竞争力 | 竞争格局变化 | 业务转型阶段）

## 四、综合评分与操作建议
| 股票 | 评分(0-100) | 建议 | 持仓成本 | 现价 | 浮盈(%) | 核心理由 |
|------|:---:|------|------|------|------|------|
（评分维度：财务健康25分 + 行业位置20分 + 技术面15分 + 战略转型20分 + 风险调整20分。必须基于用户实际持仓成本。）

## 五、情景推演
（每只股票给出2-3个情景：乐观/中性/悲观，含关键假设和触发条件）

## 六、买卖点位与仓位
| 股票 | 买入/加仓点 | 止盈位 | 止损位 | 当前建议仓位 |
|------|------|------|------|------|
（给出具体价格和仓位百分比）

## 七、候选股对比（如有候选股数据）
（对比今日强势候选股，判断是否需要换仓）

## 八、风险矩阵
| 风险 | 标的 | 触发概率 | 影响程度 | 监测指标 | 时间窗口 |
|------|------|------|------|------|------|

## 九、下周监测清单
- [ ] 关键指标1：阈值X
- [ ] 关键指标2：阈值Y"""

prompt = f"""## 用户持仓
{holdings_text}

## 今日行情
""" + "\n".join(f"{v['name']}({k}): 现价{v['price']} 今开{v['open']} 最高{v['high']} 最低{v['low']}" for k,v in prices.items()) + f"""

## 技术指标
""" + "\n".join(f"{prices.get(c,{}).get('name',c)}({c}): MA5={t['ma5']} MA10={t['ma10']} MA20={t['ma20']} | 乖离率(MA5)={t['bias_ma5']}% | 量比={t['vol_ratio']} | 均线={t['trend']}" for c,t in tech_data.items()) + f"""

## 相关新闻
{news_text}

{picks_text}

请严格按系统指令中的九段结构输出完整分析。"""

api_key = os.environ.get("OPENAI_API_KEY", "")
api_base = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
api_model = os.environ.get("LITELLM_MODEL", "openai/deepseek-v4-pro")
# 如果模型名有前缀，去掉
if "/" in api_model:
    api_model = api_model.split("/")[-1]

payload = {
    "model": api_model,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ],
    "temperature": 0.3,
    "max_tokens": 3000,
}
req = urllib.request.Request(f"{api_base}/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
result = resp["choices"][0]["message"]["content"]

# ── 推送 ──
def push_serverchan(title, content):
    key = os.environ.get("SERVERCHAN3_SENDKEY", "")
    if key:
        urllib.request.urlopen(f"https://sctapi.ftqq.com/{key}.send?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(content[:8000])}", timeout=10)

def push_pushplus(title, content):
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if token:
        data = json.dumps({"token": token, "title": title, "content": content[:8000]})
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