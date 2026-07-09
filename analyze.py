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
    """获取30日K线，返回MA5/MA10/MA20/量比/近期高低点/连涨跌"""
    mkt = "sh" if code.startswith("6") else "sz"
    try:
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={mkt}{code}&scale=30&ma=no&datalen=30"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not data: return None
        closes = [float(d["close"]) for d in data]
        highs = [float(d["high"]) for d in data]
        lows = [float(d["low"]) for d in data]
        volumes = [float(d["volume"]) for d in data]
        opens = [float(d["open"]) for d in data]
        latest = data[-1]
        close = float(latest["close"])
        ma5 = sum(closes[-5:])/5 if len(closes)>=5 else close
        ma10 = sum(closes[-10:])/10 if len(closes)>=10 else close
        ma20 = sum(closes[-20:])/20 if len(closes)>=20 else close
        # 近期高低点
        high_5d = max(highs[-5:]) if len(highs)>=5 else close
        low_5d = min(lows[-5:]) if len(lows)>=5 else close
        high_10d = max(highs[-10:]) if len(highs)>=10 else close
        low_10d = min(lows[-10:]) if len(lows)>=10 else close
        high_20d = max(highs[-20:]) if len(highs)>=20 else close
        low_20d = min(lows[-20:]) if len(lows)>=20 else close
        # 量比
        vol_ratio = volumes[-1] / (sum(volumes[-6:-1])/5) if len(volumes)>=6 else 1.0
        # 连涨连跌天数
        streak = 0
        for i in range(len(closes)-1, 0, -1):
            if closes[i] > closes[i-1]:
                if streak >= 0: streak += 1
                else: break
            elif closes[i] < closes[i-1]:
                if streak <= 0: streak -= 1
                else: break
            else:
                break
        streak_label = f"连涨{streak}天" if streak>0 else (f"连跌{abs(streak)}天" if streak<0 else "平盘")
        # 均线排列
        if ma5 > ma10 > ma20: trend = "多头排列 📈"
        elif ma5 < ma10 < ma20: trend = "空头排列 📉"
        else: trend = "均线缠绕 ⚠️"
        # 近5日振幅
        amp_5d = round((high_5d/low_5d - 1)*100, 2) if low_5d > 0 else 0
        # 距20日高/低的百分比位置
        pos_20d = round((close - low_20d) / (high_20d - low_20d) * 100, 1) if high_20d != low_20d else 50
        return {
            "close": close, "open": float(latest["open"]), "high": float(latest["high"]), "low": float(latest["low"]),
            "ma5": round(ma5,2), "ma10": round(ma10,2), "ma20": round(ma20,2),
            "bias_ma5": round((close-ma5)/ma5*100,2),
            "vol_ratio": round(vol_ratio,2), "trend": trend,
            "volume": int(volumes[-1]),
            "high_5d": round(high_5d,2), "low_5d": round(low_5d,2),
            "high_10d": round(high_10d,2), "low_10d": round(low_10d,2),
            "high_20d": round(high_20d,2), "low_20d": round(low_20d,2),
            "streak": streak_label, "amp_5d": amp_5d, "pos_20d": pos_20d
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

# ── 调 DeepSeek（短线操作框架）──
SYSTEM_PROMPT = """你是专业的A股短线交易教练，采用以下五层分析框架。你必须基于用户实际持仓成本，给出可执行的操作指导。

注意：即使部分数据获取失败，也必须基于现有数据和你的内置知识继续完整分析，不得拒绝分析。

【第一层：盘面结构与关键价位】
- 从K线数据中识别：近期最高价/最低价、前高阻力、前低支撑
- 判断当前价格在什么位置（高位/中位/低位），距关键位的距离
- 日内多空分界线：开盘价是关键锚点，高开/低开的含义不同
- 连续涨跌天数：连涨防回调，连跌等企稳

【第二层：量价关系与资金意图】
- 量比 <0.8 缩量 → 交投清淡，方向不明，不宜操作
- 量比 0.8-1.5 正常 → 延续原趋势概率大
- 量比 1.5-3 放量 → 趋势加速或转折信号，结合涨跌判断
- 量比 >3 巨量 → 警惕出货或恐慌抛售，需看分时结构
- 关键规则：缩量下跌可等，放量下跌必跑；缩量上涨可持，放量滞涨必减

【第三层：均线系统与趋势判断】
- 多头排列(MA5>MA10>MA20)：持仓为主，回踩均线是加仓点
- 空头排列(MA5<MA10<MA20)：观望或减仓，反弹到均线是减仓点
- 均线缠绕：震荡市，高抛低吸，降低仓位
- 乖离率(MA5)：>+5% 短线过热不追，<−5% 超跌等反弹
- 股价与MA20的关系：线上不做空，线下不做多

【第四层：短线催化剂】
- 当日新闻和公告是否构成短线驱动（板块联动、业绩预告、重大合同等）
- 判断催化剂级别：日内(1天) / 短线(3-5天) / 波段(1-3周)
- 利好出尽是利空，利空出尽是利好——关注预期差

【第五层：操作策略与风控】
- 每条建议必须包含：做什么 + 什么价格 + 什么条件 + 错了怎么办
- 仓位管理铁律：
  - 单票仓位超过50%时要格外谨慎，分散风险
  - 浮亏超过5%→设硬止损，浮亏超过8%→无条件减半仓
  - 浮盈超过10%→上移止盈位到成本价上方，保本第一
- 止损比止盈重要十倍：每一笔交易入場前必须先想好 exit plan

【短线交易核心纪律】（每次分析结尾必须提醒）
1. 顺势而为，不抄底不逃顶
2. 放量破位必须走，不要等反弹
3. 亏损加仓是加速虧損的最快方式
4. 当天买当天不卖(T+1)，决定入场就要承担隔夜风险
5. 看不懂的时候空仓就是最好的操作

输出必须严格按以下结构。**最重要的规则：速览卡必须在最开头，让用户30秒内看到全部结论。**

各时段输出重点：
- 8:30盘前：侧重操作策略和当日计划
- 9:30/10:30盘中：侧重实时信号和调整建议
- 13:30午后：侧重尾盘策略
- 14:30收盘：侧重复盘和明日预判

---

# ⚡ 速览卡

| 股票 | 成本 | 现价 | 浮盈% | 操作 | 评分 | 🎯止盈 | 🛑止损 |
|------|------|------|------|:---:|:---:|------|------|
（每只一行，止盈和止损给出具体价格。操作用：🟢买入 🔵加仓 🟡持有 🟠减仓 🔴卖出）

> 💡 **一句话决策**：（用一句话说清楚今天对每只股票该做什么）

---

## 一、今日盘面速览
（当前价、涨跌幅、量比、均线排列状态、距关键位的距离。一句话总结今日盘面。）

## 二、关键价位与量价信号
| 股票 | 支撑1 | 支撑2 | 现价 | 阻力1 | 阻力2 | 量比 | 信号解读 |
|------|------|------|------|------|------|------|------|
（支撑/阻力基于均线、前高前低、整数关口。量比>2或<0.5必须标注⚠️）

## 三、情景应对
（每只：如果涨→怎么做 | 如果横→怎么做 | 如果跌→怎么做。具体价格触发条件。）

## 四、资金与仓位
- 当前总仓位建议：X%
- 可用资金分配方案
- 调仓优先级排序

## 五、短线候选关注（如有候选股数据）
（今日强势候选 vs 当前持仓，是否存在换仓机会）

## 六、明日预判与监测
- [ ] 今夜关注（外盘/期货/消息）
- [ ] 明日关键价位
- [ ] 明日开盘应对预案

## 七、纪律提醒
（对照短线交易核心纪律，逐条检查当前持仓是否存在违规操作）"""

prompt = f"""## 用户持仓
{holdings_text}

## 今日行情
""" + "\n".join(f"{v['name']}({k}): 现价{v['price']} 今开{v['open']} 最高{v['high']} 最低{v['low']}" for k,v in prices.items()) + f"""

## 技术指标
""" + "\n".join(f"{prices.get(c,{}).get('name',c)}({c}): MA5={t['ma5']} MA10={t['ma10']} MA20={t['ma20']} | 乖离率(MA5)={t['bias_ma5']}% | 量比={t['vol_ratio']} | 均线={t['trend']} | {t['streak']} | 5日高{t['high_5d']}低{t['low_5d']} | 20日高{t['high_20d']}低{t['low_20d']} | 20日位置{t['pos_20d']}% | 5日振幅{t['amp_5d']}%" for c,t in tech_data.items()) + f"""

## 相关新闻
{news_text}

{picks_text}

请严格按以上结构输出（先速览卡→再七段分析）。针对每个时段(现在是北京时间{time.strftime('%H:%M')})，侧重该时段的输出重点。"""

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