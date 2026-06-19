import json, os, subprocess, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("holdings.json") as f:
    h = json.load(f)

stocks = [s["code"] for s in h["stocks"]]
stock_str = ",".join(stocks)

env = os.environ.copy()
env["STOCK_LIST"] = stock_str

print(f"STOCK_LIST={stock_str}")

subprocess.run([sys.executable, "main.py", "--force-run"], env=env)
