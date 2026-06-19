import json
with open("holdings.json") as f:
    stocks = json.load(f)["stocks"]
stock_str = ",".join(s["code"] for s in stocks)

lines = open(".env").readlines()
with open(".env", "w") as f:
    for line in lines:
        if not line.startswith("STOCK_LIST="):
            f.write(line)
    f.write(f"STOCK_LIST={stock_str}\n")

print(f"STOCK_LIST={stock_str}")
