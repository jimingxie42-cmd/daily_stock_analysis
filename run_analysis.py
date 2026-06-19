import json, os, subprocess, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
with open("holdings.json") as f:
    h = json.load(f)
stocks = [s["code"] for s in h["stocks"]]
ctx = " ".join(f'{s["name"]}{s["code"]}持{s["shares"]}股成本{s["cost"]}' for s in h["stocks"])
env = os.environ.copy()
env["STOCK_LIST"] = ",".join(stocks)
env["POSITION_CONTEXT"] = ctx
print(f"STOCK_LIST={env['STOCK_LIST']}")
subprocess.run([sys.executable, "main.py", "--force-run"], env=env)
