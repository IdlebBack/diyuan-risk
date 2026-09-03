# 地缘风险 —— 供应链地缘风险雷达

“AI+地缘政治风险高校挑战赛”（北京大学国际关系学院）赛道 B 参赛项目。
方向：附录二·参考方向三（全球供应链与产业安全）。

面向高端智能装备制造企业的供应链地缘风险识别与情景推演工具：
帮助采购与供应链管理者看清关键依赖、感知地缘风险信号、量化暴露程度，
并推演不同风险情景下的断供影响与应对方案。

> 模拟企业 XX 智能装备有限公司及其全部经营数据、业务关系、风险事件均为赛题虚构，
> 不对应任何现实企业或实际商业事实。

## 当前状态（里程碑 2：信号抓取与事件导入）

- [x] Git 仓库与项目结构
- [x] 模拟企业种子数据（组件、供应商、依赖、订单、风险事件）
- [x] 数据模型与数据装载（`chainshield/repository.py`）
- [x] 依赖图谱构建与指标（`chainshield/graph.py`）
- [x] 暴露度评分初版（`chainshield/risk.py`）
- [x] 情景推演引擎 v0（`chainshield/scenario.py`）
- [x] LLM 事件抽取：有 Key 走真实模型，无 Key/失败自动规则占位并标记待核实（`chainshield/llm.py`）
- [x] 风险信号抓取：模拟样例源 + RSS/Atom 真实抓取（`chainshield/signals.py`）
- [x] 信号 → 结构化事件 → 本地事件库导入，语义去重（`chainshield/ingest.py`）
- [x] Streamlit 可视化骨架（`app.py`）
- [x] UI 信号巡检与导入工作台 + 命令行导入工具（`scripts/ingest_cli.py`）
- [ ] 暴露度模型调参验证
- [ ] 推演引擎完善（在途订单、多事件叠加、方案比较）
- [ ] 案例测试与边界案例演示
- [ ] 产品介绍 PPT、README 完善、打包提交

## 环境准备

需要 Python 3.10+。

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

LLM API（可选）：复制 `.env.example` 为 `.env` 并填写 Key。
未配置 Key 时系统自动进入“离线占位”模式，功能仍可运行。

## 运行

可视化应用：

```bash
streamlit run app.py
```

命令行冒烟演示（数据装载 → 暴露度 → 情景推演）：

```bash
python scripts/demo.py
```

命令行导入风险信号到本地事件库（`data/events_live.csv`，按“标题+日期”去重）：

```bash
# 文本导入（离线时自动用规则占位并标记待核实）
python scripts/ingest_cli.py --text "据（虚构）报道，日本拟扩大高精度编码器出口审查范围……"

# 抓取模拟样例信号并入库
python scripts/ingest_cli.py --samples

# 抓取自定义 RSS 源并入库
python scripts/ingest_cli.py --rss "https://example.com/feed.xml"
```

本地导入的事件存放在 `data/events_live.csv`（已加入 .gitignore，不随仓库提交）。
确定有价值的条目可人工整理后并入 `data/seed/events.csv` 再提交。

## 目录结构

```text
chainshield/
├─ app.py                 # Streamlit 应用入口
├─ chainshield/           # 核心代码包
│  ├─ repository.py       # 数据模型与 CSV 装载
│  ├─ graph.py            # 依赖图谱与集中度指标
│  ├─ risk.py             # 暴露度评分
│  ├─ scenario.py         # 情景推演引擎
│  ├─ events.py           # 风险事件库
│  ├─ llm.py              # LLM 接口（含离线占位）
│  └─ config.py           # 环境配置
├─ data/seed/             # 种子数据（CSV，全部虚构）
├─ docs/                  # 指南、产品设计方案
└─ scripts/demo.py        # 冒烟演示
```

## 两人协作与 Git 工作流

1. 每次开工前先 `git pull` 拉取队友最新代码。
2. 改动按小步提交，提交信息用中文简述做了什么，例如：
   `feat: 新增风险信号事件库`、`fix: 修正推演引擎库存计算`。
3. 不要把 `.env`、API Key、数据库文件提交到仓库（已在 `.gitignore` 中）。
4. 需要在线合并且无固定分工时：谁改完谁 `git pull --rebase` 后再 `git push`，
   遇到冲突在本地解决后再推。

## 数据口径说明

- `dependencies.csv` 中的 `purchase_share`：该进口件占同类零部件采购比例；
- `weekly_usage = 组件总周用量 × purchase_share`（该进口件的周消耗）；
- `inventory_units = weekly_usage × inventory_weeks`（该进口件库存）；
- 所有交期、库存、金额均为周/万元量级模拟值，用于演示与推演，不构成真实经营建议。
