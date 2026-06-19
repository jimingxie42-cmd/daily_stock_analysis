"""持仓注入 → daily_stock_analysis → 追加持仓快照推送"""
import json, os, subprocess, sys, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

env = os.environ.copy()

# ── 1. 持仓注入 ──
with open("holdings.json") as f:
    h = json.load(f)
stocks = [s["code"] for s in h["stocks"]]
env["STOCK_LIST"] = ",".join(stocks)
print(f"STOCK_LIST={env['STOCK_LIST']}")

# ── 2. 跑主程序 ──
args = [sys.executable, "main.py"]
if os.environ.get("FORCE_RUN", "false") == "true":
    args.append("--force-run")
subprocess.run(args, env=env)

# ── 3. 追加持仓快照 ──
try:
    codes = env["STOCK_LIST"].split(",")
    url = "http://hq.sinajs.cn/list=" + ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes)
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
    prices = {}
    for line in raw.strip().split("\n"):
        p = line.split('"')[1].split(",")
        prices[line.split("=")[0][-6:]] = {"price": float(p[3]), "prev": float(p[2])}

    snap = "## 持仓快照\n"
    tv = tc = 0
    for s in h:
        c = s["code"]
        if c in prices:
            v = s["shares"] * prices[c]["price"]
            cost = s["shares"] * s["cost"]
            pnl = v - cost
            pct = (prices[c]["price"] / s["cost"] - 1) * 100
            chg = (prices[c]["price"] / prices[c]["prev"] - 1) * 100
            tv += v; tc += cost
            snap += f"{s['name']}({c}): {prices[c]['price']} 今涨{chg:+.1f}% | 成本{s['cost']} | 浮盈{pnl:+.0f}({pct:+.1f}%)\n"
    snap += f"\n总:{tv:.0f} | 浮盈{tv-tc:+.0f}"

    token = os.environ.get("PUSHPLUS_TOKEN","")
    skey = os.environ.get("SERVERCHAN3_SENDKEY","")
    if token:
        data = json.dumps({"token": token, "title": "持仓快照", "content": snap}).encode()
        urllib.request.urlopen(urllib.request.Request("https://www.pushplus.plus/send", data=data, headers={"Content-Type":"application/json"}), timeout=10)
    if skey:
        urllib.request.urlopen(f"https://sctapi.ftqq.com/{skey}.send?title=持仓快照&desp={urllib.parse.quote(snap)}", timeout=10)
    print("持仓快照已推送")
except Exception as e:
    print(f"快照: {e}")
