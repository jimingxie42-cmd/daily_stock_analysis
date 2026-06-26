"""轻量持仓快照推送 —— 仅取实时价+推送，不做AI分析
用于盘中多次推送：9:30 / 10:30 / 13:30
"""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)

# 加载 .env
from dotenv import load_dotenv
load_dotenv(BASE / ".env")

# ── 1. 读持仓 ──
with open(BASE / "holdings.json") as f:
    h = json.load(f)
stocks = h["stocks"]
codes = [s["code"] for s in stocks]

# ── 2. 取实时价 ──
url = "http://hq.sinajs.cn/list=" + ",".join(
    f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes
)
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")

prices = {}
for line in raw.strip().split("\n"):
    parts = line.split('"')
    if len(parts) < 2:
        continue
    p = parts[1].split(",")
    if len(p) < 4:
        continue
    code = line.split("=")[0][-6:]
    try:
        prices[code] = {
            "price": float(p[3]),
            "prev": float(p[2]),
            "high": float(p[4]),
            "low": float(p[5]),
            "name": p[0],
        }
    except (ValueError, IndexError):
        continue

# ── 3. 生成快照 ──
now = datetime.now()
snap = f"## 📊 持仓快照 {now.strftime('%H:%M')}\n\n"
tv = tc = 0

for s in stocks:
    c = s["code"]
    if c not in prices:
        snap += f"**{s['name']}({c})**: 数据获取失败\n"
        continue
    p = prices[c]
    v = s["shares"] * p["price"]
    cost = s["shares"] * s["cost"]
    pnl = v - cost
    pct = (p["price"] / s["cost"] - 1) * 100
    chg = (p["price"] / p["prev"] - 1) * 100
    tv += v
    tc += cost

    emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
    snap += (
        f"{emoji} **{s['name']}**({c})\n"
        f"  现价 {p['price']:.2f} | 今涨 {chg:+.2f}% | "
        f"成本 {s['cost']:.2f} | 浮盈 {pnl:+.0f}({pct:+.1f}%)\n\n"
    )

total_pnl = tv - tc
total_pct = (tv / tc - 1) * 100 if tc > 0 else 0
snap += f"💰 **总市值 {tv:.0f}** | 浮盈 {total_pnl:+.0f}({total_pct:+.1f}%) | 仓位 {tv/(tv+0.01)*100:.0f}%"

# ── 4. 双通道推送 ──
token = os.environ.get("PUSHPLUS_TOKEN", "")
skey = os.environ.get("SERVERCHAN3_SENDKEY", "")
ok = 0

if token:
    try:
        data = json.dumps({"token": token, "title": f"持仓快照 {now.strftime('%H:%M')}", "content": snap}).encode()
        r = urllib.request.urlopen(
            urllib.request.Request("https://www.pushplus.plus/send", data=data,
                                   headers={"Content-Type": "application/json"}),
            timeout=10
        )
        resp = json.loads(r.read())
        if resp.get("code") == 200:
            print("PushPlus ✅")
            ok += 1
        else:
            print(f"PushPlus ❌ {resp.get('msg')}")
    except Exception as e:
        print(f"PushPlus ❌ {e}")

if skey:
    try:
        title = f"持仓快照 {now.strftime('%H:%M')}"
        r = urllib.request.urlopen(
            f"https://sctapi.ftqq.com/{skey}.send?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(snap)}",
            timeout=10
        )
        resp = json.loads(r.read())
        if resp.get("code") == 0:
            print("Server酱3 ✅")
            ok += 1
        else:
            print(f"Server酱3 ❌ {resp.get('message')}")
    except Exception as e:
        print(f"Server酱3 ❌ {e}")

print(f"快照推送完成 ({ok}/2)")
sys.exit(0 if ok > 0 else 1)
