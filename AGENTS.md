# AGENTS.md — 给协作者的约定

这是“AI+地缘政治风险高校挑战赛”赛道 B 的参赛项目（供应链地缘风险雷达）。

## 先读

- 开发前先读 `README.md`，理解里程碑与目录结构。
- 赛制与要求见 `docs/guide.pdf`；产品设计见 `docs/产品设计方案.md`。

## 硬性约定

1. 种子数据全部来自赛题虚构的“XX 智能装备有限公司”，不得与真实企业挂钩。
2. `.env`、API Key、secrets 严禁提交（`.gitignore` 已处理）。
3. 所有 AI 输出必须可溯源：区分事实/推断/待核实，标注来源与置信度；
   不确定时提示人工核实，绝不把大模型结论表述为确定事实。
4. 代码用词保持英文标识符，用户界面文案用中文。
5. 改动后运行 `python -m unittest discover -s tests -v`、
   `python scripts/cases.py` 与 `python scripts/demo.py`，确认边界与主流程均不退化。
   测试必须离线、隔离本地导入事件；外部请求用替身，不使用真实 Key。

## 常用命令

```bash
streamlit run app.py        # 启动应用
python scripts/demo.py      # 冒烟演示
python scripts/cases.py     # 固定种子案例 A–D
python -m unittest discover -s tests -v  # 核心、图谱、UI、导入与打包边界
```

LLM 未配置 Key 时走 `chainshield/llm.py` 的离线占位实现，先保证主流程可跑。
