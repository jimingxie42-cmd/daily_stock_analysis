"""持仓注入 + 新浪式选股 → daily_stock_analysis主引擎"""
import json, os, subprocess, sys, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

env = os.environ.copy()

# ── 1. 持仓注入 ──
with open("holdings.json") as f:
    h = json.load(f)
stocks = [s["code"] for s in h["stocks"]]
env["STOCK_LIST"] = ",".join(stocks)
ctx = " ".join(f'{s["name"]}{s["code"]}持{s["shares"]}股成本{s["cost"]}' for s in h["stocks"])
env["POSITION_CONTEXT"] = ctx
print(f"STOCK_LIST={env['STOCK_LIST']}")

# ── 2. 新浪选股（主板涨幅2-8%，量比>1.5，换手>3%）──
try:
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=60&sort=changepercent&asc=0&node=hs_a"
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("gbk"))
    picks = []
    for s in data:
        chg = float(s["changepercent"]); vol = float(s.get("volume",0) or 0); turnover = float(s.get("turnoverratio",0) or 0)
        code = s["code"]
        if 2 < chg < 8 and turnover > 3 and vol > 1000000 and (code.startswith("60") or code.startswith("00")):
            picks.append(f"{s['name']}({code}) 涨{chg:+.1f}% 换手{turnover:.1f}% 量比{vol/1000000:.0f}M")
            if len(picks) >= 8: break
    if picks:
        env["SELECTED_STOCKS"] = "\n".join(picks)
        print(f"选股{len(picks)}只")
    else:
        env["SELECTED_STOCKS"] = "(今日筛选无符合条件个股)"
except Exception as e:
    env["SELECTED_STOCKS"] = f"(选股失败: {e})"
    print(f"选股失败: {e}")

# ── 3. 跑主程序 ──
args = [sys.executable, "main.py"]
if os.environ.get("FORCE_RUN", "false") == "true":
    args.append("--force-run")
subprocess.run(args, env=env)
