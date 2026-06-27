"""持仓注入 → AI分析 → 快照推送 → Obsidian同步"""
import json, os, subprocess, sys, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

env = os.environ.copy()
now = datetime.now()
today_str = now.strftime("%Y-%m-%d")
time_str = now.strftime("%H:%M")

# ── 1. 持仓注入 ──
with open(BASE / "holdings.json") as f:
    h = json.load(f)
stocks = h["stocks"]

# 清除代理干扰（DSA 的东财接口走代理会失败）
for k in ["https_proxy", "http_proxy", "HTTPS_PROXY", "HTTP_PROXY"]:
    env.pop(k, None)

env["STOCK_LIST"] = ",".join(s["code"] for s in stocks)
print(f"STOCK_LIST={env['STOCK_LIST']}")

# ── 2. 跑主程序（AI分析+推送）──
args = [str(BASE / ".venv/bin/python"), "main.py"]
if os.environ.get("FORCE_RUN", "false") == "true":
    args.append("--force-run")
result = subprocess.run(args, env=env, capture_output=True, text=True)
if result.returncode != 0:
    print(f"⚠️  AI分析异常 (exit {result.returncode})")
    # 不阻断，继续推送快照

# ── 3. 实时快照推送 ──
snap_content = ""
try:
    codes = [s["code"] for s in stocks]
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
            prices[code] = {"price": float(p[3]), "prev": float(p[2]),
                            "high": float(p[4]), "low": float(p[5]), "name": p[0]}
        except (ValueError, IndexError):
            continue

    snap = f"## 📊 持仓快照 {time_str}\n\n"
    tv = tc = 0
    for s in stocks:
        c = s["code"]
        if c not in prices:
            snap += f"**{s['name']}({c})**: 数据获取失败\n\n"
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
            f"{emoji} **{s['name']}**({c})  {p['price']:.2f}\n"
            f"  今涨 {chg:+.2f}% | 成本 {s['cost']:.2f} | 浮盈 {pnl:+.0f}({pct:+.1f}%)\n\n"
        )
    total_pnl = tv - tc
    total_pct = (tv / tc - 1) * 100 if tc > 0 else 0
    snap += f"💰 总市值 **{tv:.0f}** | 浮盈 {total_pnl:+.0f}({total_pct:+.1f}%)\n"
    snap_content = snap

    # 推送
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    skey = os.environ.get("SERVERCHAN3_SENDKEY", "")
    ok = 0
    title = f"持仓分析 {time_str}"

    if token:
        try:
            data = json.dumps({"token": token, "title": title, "content": snap}).encode()
            r = urllib.request.urlopen(
                urllib.request.Request("https://www.pushplus.plus/send", data=data,
                                       headers={"Content-Type": "application/json"}),
                timeout=10
            )
            resp = json.loads(r.read())
            print(f"PushPlus {'✅' if resp.get('code') == 200 else '❌ ' + resp.get('msg', '')}")
        except Exception as e:
            print(f"PushPlus ❌ {e}")

    if skey:
        try:
            r = urllib.request.urlopen(
                f"https://sctapi.ftqq.com/{skey}.send?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(snap)}",
                timeout=10
            )
            resp = json.loads(r.read())
            print(f"Server酱3 {'✅' if resp.get('code') == 0 else '❌ ' + resp.get('message', '')}")
        except Exception as e:
            print(f"Server酱3 ❌ {e}")

except Exception as e:
    print(f"快照: {e}")

# ── 4. 同步到 Obsidian Vault ──
try:
    vault_dir = Path.home() / "Documents/ObsidianVault/03_领域/投资理财"
    vault_dir.mkdir(parents=True, exist_ok=True)

    ob_lines = [
        "---",
        f"date: {today_str}",
        f"time: {time_str}",
        "tags: [投资, 持仓分析, 推送]",
        "---",
        "",
        f"# 📊 {today_str} 持仓分析",
        "",
        f"> 生成时间：{time_str}",
        "",
        "## 当前持仓",
        "",
    ]

    # 持仓表格
    ob_lines.append("| 股票 | 代码 | 持仓(股) | 成本 |")
    ob_lines.append("|------|------|----------|------|")
    for s in stocks:
        ob_lines.append(f"| {s['name']} | {s['code']} | {s['shares']} | {s['cost']} |")

    ob_lines.extend(["", "## 快照", "", snap_content if snap_content else "（快照数据获取失败）", ""])

    # 如果有 AI 分析结果，链接到报告
    reports_dir = BASE / "reports"
    latest_report = None
    if reports_dir.exists():
        reports = sorted(reports_dir.glob("report_*.md"), reverse=True)
        if reports:
            latest_report = reports[0]

    if latest_report:
        with open(latest_report) as rf:
            report_text = rf.read()
        ob_lines.extend([
            "## 🤖 AI 分析与操作建议",
            "",
            report_text,
            "",
        ])
    else:
        ob_lines.extend([
            "## 🤖 AI 分析与操作建议",
            "",
            "> ⚠️ AI 分析未成功运行，仅含实时快照数据。",
            "",
            "### 策略思考",
            "",
            "- 紫金矿业：有色金属龙头，关注金/铜价格走势",
            "- 天齐锂业：锂矿龙头，关注锂价拐点和新能源汽车需求",
            "",
        ])

    ob_lines.extend([
        "---",
        "",
        "## 📋 操作记录",
        "",
        "| 时间 | 操作 | 说明 |",
        "|------|------|------|",
        f"| {time_str} | 推送 | 快照已推送至 PushPlus + Server酱3 |",
        "",
    ])

    ob_path = vault_dir / f"{today_str}-持仓分析.md"
    with open(ob_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ob_lines))
    print(f"📓 Obsidian 已同步 → {ob_path}")

except Exception as e:
    print(f"Obsidian 同步失败: {e}")
