#!/usr/bin/env python3
"""根据 holdings.json 的实际持仓做分析并推送"""

import json, os, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)

# ── 1. 读实际持仓 ──
with open(BASE / "holdings.json") as f:
    h = json.load(f)
stocks = h["stocks"]

print(f"持仓股票：{[s['name'] for s in stocks]}")

# ── 2. 取新浪实时行情 ──
codes = [s["code"] for s in stocks]
url = "http://hq.sinajs.cn/list=" + ",".join(
    f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes
)
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")

prices = {}
for line in raw.strip().split("\n"):
    parts = line.split('"')
    if len(parts) < 2: continue
    p = parts[1].split(",")
    if len(p) < 4: continue
    code = line.split("=")[0][-6:]
    try:
        prices[code] = {
            "price": float(p[3]), "prev": float(p[2]),
            "open": float(p[1]), "high": float(p[4]), "low": float(p[5]),
            "volume": int(p[8]) if len(p) > 8 else 0,
            "amount": float(p[9]) if len(p) > 9 else 0,
            "name": p[0].replace("XD", "").strip(),
        }
    except: continue

# ── 3. 生成面向手机推送的精简内容 ──
now = datetime.now()
time_str = now.strftime("%H:%M")
today_str = now.strftime("%Y-%m-%d")

lines = []
lines.append(f"## 📊 {today_str} 持仓分析")
lines.append(f"")
lines.append(f"⏰ {time_str}")
lines.append(f"")

tv = tc = 0
for s in stocks:
    c = s["code"]
    n = s["name"]
    if c not in prices:
        lines.append(f"**{n}({c})**：数据获取失败")
        continue
    p = prices[c]
    v = s["shares"] * p["price"]
    cost = s["shares"] * s["cost"]
    pnl = v - cost
    pct = (p["price"] / s["cost"] - 1) * 100
    chg = (p["price"] / p["prev"] - 1) * 100
    tv += v; tc += cost

    emoji = "🟢" if pnl >= 0 else "🔴"
    trend = "📈" if chg >= 0 else "📉"

    lines.append(f"{emoji} **{n}**({c}) {trend}")
    lines.append(f"   现价 {p['price']:.2f}  今涨 {chg:+.2f}%")
    lines.append(f"   成本 {s['cost']:.2f}  浮盈 {pnl:+,.0f}({pct:+.1f}%)")
    lines.append(f"   今开 {p['open']:.2f}  区间 {p['low']:.2f}-{p['high']:.2f}")
    lines.append(f"")

total_pnl = tv - tc
total_pct = (tv / tc - 1) * 100 if tc > 0 else 0
total_emoji = "✅" if total_pnl >= 0 else "⚠️"
lines.append(f"---")
lines.append(f"**汇总** {total_emoji}")
lines.append(f"总市值 {tv:,.0f} | 总成本 {tc:,.0f}")
lines.append(f"浮盈 {total_pnl:+,.0f}({total_pct:+.1f}%)")
lines.append(f"仓位 {tv/(tv+tc)*100:.0f}%")
lines.append(f"")

# 简评
lines.append(f"**简评**")
for s in stocks:
    c = s["code"]
    if c not in prices: continue
    p = prices[c]
    chg = (p["price"] / p["prev"] - 1) * 100
    pct = (p["price"] / s["cost"] - 1) * 100
    remarks = []
    if chg < -3:
        remarks.append("今日大跌，注意短线风险")
    elif chg < -1:
        remarks.append("走势偏弱")
    elif chg > 3:
        remarks.append("今日大涨，趋势强劲")
    elif chg > 1:
        remarks.append("走势较强")
    else:
        remarks.append("窄幅震荡")
    if pct < -10:
        remarks.append("浮亏较大，评估是否需止损")
    elif pct < -5:
        remarks.append("浮亏中，关注反弹机会")
    elif pct > 10:
        remarks.append("浮盈可观，考虑分批止盈")
    lines.append(f"- **{s['name']}**：现价 {p['price']:.2f}，{'、'.join(remarks)}")

lines.append(f"")
lines.append(f"*由 Codex 自动生成*")

content = "\n".join(lines)
print("\n=== 推送内容 ===\n")
print(content)
print("\n================")

# ── 4. 推送 PushPlus ──
from dotenv import load_dotenv
load_dotenv(BASE / ".env")
token = os.environ.get("PUSHPLUS_TOKEN", "")

if token:
    title = f"持仓分析 {today_str} {time_str}"
    data = json.dumps({"token": token, "title": title, "content": content,
                        "template": "markdown"}).encode()
    r = urllib.request.urlopen(
        urllib.request.Request("https://www.pushplus.plus/send", data=data,
                               headers={"Content-Type": "application/json"}), timeout=10)
    resp = json.loads(r.read())
    ok = resp.get("code") == 200
    print(f"\nPushPlus: {'✅ 推送成功' if ok else '❌ ' + resp.get('msg', '')}")
else:
    print("\nPushPlus: ⏭️ 未配置 Token")

# ── 5. 同步到 Obsidian ──
vault_path = Path.home() / "Documents/ObsidianVault/03_领域/投资理财" / f"{today_str}-持仓分析.md"
with open(vault_path, "w", encoding="utf-8") as f:
    ob_content = f"""---
date: {today_str}
time: {time_str}
tags: [投资, 持仓分析, 推送]
---

{content}
"""
    f.write(ob_content)
print(f"📓 Obsidian → {vault_path}")
