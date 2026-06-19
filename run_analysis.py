import json, os, subprocess, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("holdings.json") as f:
    h = json.load(f)

stocks = [s["code"] for s in h["stocks"]]
ctx = " ".join(f'{s["name"]}{s["code"]}持{s["shares"]}股成本{s["cost"]}' for s in h["stocks"])
stock_str = ",".join(stocks)

# 写入 .env — runtime覆盖STOCK_LIST，main.py直接读
env_lines = open(".env").readlines()
new_lines = []
seen_stock = False
for line in env_lines:
    if line.startswith("STOCK_LIST="):
        new_lines.append(f"STOCK_LIST={stock_str}\n")
        seen_stock = True
    elif line.startswith("# STOCK_LIST") and not seen_stock:
        new_lines.append(f"STOCK_LIST={stock_str}\n")
        seen_stock = True
    else:
        new_lines.append(line)
if not seen_stock:
    new_lines.append(f"STOCK_LIST={stock_str}\n")
open(".env","w").writelines(new_lines)

# 同时传环境变量（双保险）
env = os.environ.copy()
env["STOCK_LIST"] = stock_str
env["POSITION_CONTEXT"] = ctx

print(f"✅ STOCK_LIST={stock_str}")
print(f"✅ POSITION_CONTEXT={ctx}")

subprocess.run([sys.executable, "main.py", "--force-run"], env=env)
