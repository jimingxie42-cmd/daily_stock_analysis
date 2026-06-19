import json, os, subprocess, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("holdings.json") as f:
    h = json.load(f)

stocks = [s["code"] for s in h["stocks"]]
stock_str = ",".join(stocks)

ctx = " ".join(f'{s["name"]}{s["code"]}持{s["shares"]}股成本{s["cost"]}' for s in h["stocks"])

env = os.environ.copy()
env["STOCK_LIST"] = stock_str
env["POSITION_CONTEXT"] = ctx

print(f"STOCK_LIST={stock_str}")

args = [sys.executable, "main.py"]
if os.environ.get("FORCE_RUN", "false") == "true":
    args.append("--force-run")
subprocess.run(args, env=env)
