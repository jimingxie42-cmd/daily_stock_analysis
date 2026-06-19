#!/bin/bash
# 联合运行：AlphaSift选股 + 持仓分析

echo "===== AlphaSift 全市场扫描 ====="
cd /home/runner/work/daily_stock_analysis/daily_stock_analysis

# 安装 AlphaSift
pip install -q -e ./alphasift 2>/dev/null

# 运行选股（4个策略，不用LLM排序以节省API调用）
echo "## 今日候选股" > /tmp/picks.md
for strategy in capital_heat volume_breakout momentum_quality oversold_reversal; do
    echo "" >> /tmp/picks.md
    echo "### $strategy" >> /tmp/picks.md
    alphasift screen $strategy --no-llm --max 3 2>/dev/null | head -20 >> /tmp/picks.md || echo "  策略跳过" >> /tmp/picks.md
done

# 合并到环境变量，供main.py读取
export MARKET_PICKS=$(cat /tmp/picks.md)

echo "===== 持仓分析 ====="
python main.py --force-run
