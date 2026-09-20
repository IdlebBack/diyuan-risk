# 地缘风险 —— 供应链地缘风险雷达

“AI+地缘政治风险高校挑战赛”（北京大学国际关系学院）赛道 B 参赛项目。
方向：附录二·参考方向三（全球供应链与产业安全）。

面向高端智能装备制造企业的供应链地缘风险识别与情景推演工具：
帮助采购与供应链管理者看清关键依赖、感知地缘风险信号、量化暴露程度，
并推演不同风险情景下的断供影响与应对方案。

> 模拟企业 XX 智能装备有限公司及其全部经营数据、业务关系、风险事件均为赛题虚构，
> 不对应任何现实企业或实际商业事实。

## 当前状态（里程碑 7：精美化与最终集成）

- [x] Git 仓库与项目结构
- [x] 模拟企业种子数据（组件、供应商、依赖、订单、风险事件）
- [x] 数据模型与数据装载（`chainshield/repository.py`）
- [x] 依赖图谱构建与指标（`chainshield/graph.py`）
- [x] 暴露度评分初版（`chainshield/risk.py`）
- [x] 情景推演引擎 v0（`chainshield/scenario.py`）
- [x] 推演引擎 v1：计入在途订单与持续补货，支持在途损失/延误、替代供应
- [x] 多依赖并行推演（同依赖多事件先自动合并，再聚合订单级影响）
- [x] 应对方案比较：加库存 / 替代供应 / 组合 / 排产协商（成本数量级示意）
- [x] 暴露度模型 v1：五因子（含信息可见性），事件按叠加公式计算
- [x] 权重敏感性分析与反事实案例校验（`chainshield/validation.py`）
- [x] LLM 事件抽取：有 Key 走真实模型，无 Key/失败自动规则占位并标记待核实（`chainshield/llm.py`）
- [x] 风险信号抓取：模拟样例源 + RSS/Atom 真实抓取（`chainshield/signals.py`）
- [x] 信号 → 结构化事件 → 本地事件库导入，语义去重（`chainshield/ingest.py`）
- [x] Streamlit 可视化骨架（`app.py`）
- [x] UI 信号巡检与导入工作台 + 命令行导入工具（`scripts/ingest_cli.py`）
- [x] UI：AI 事件摘要（实验）——单条事件生成“事实/推断/待核实”摘要；无 Key 时离线提示
- [x] UI：推演结果“AI 解读（实验）”——单依赖与多依赖并行推演后可生成
      解读、行动注意事项与参数校准提醒；需人工复核
- [x] AI 请求失败分级提示、超时/重试/输出长度配置；失败不影响确定性推演
- [x] AI 解读结果按推演输入快照缓存；支持下载确定性推演报告（Markdown）
- [x] 默认固定种子数据模式；本地导入事件需侧栏显式开启，案例页始终隔离
- [x] 新导入事件强制进入待核实池；来源 URL、发布时间与来源 ID 不由模型覆盖
- [x] 推演区分“库存归零”与“首次当周缺口”，覆盖零削减、交期下限、空订单及库存追加边界
- [x] GitHub Actions 离线检查：单元测试、案例回归、冒烟演示（Ubuntu Python 3.11/3.12 + Windows Python 3.12）
- [x] CSV 加载前校验：必填列、主键、外键、有限数值与采购份额合计；界面提供可定位的错误提示
- [x] 全零权重回落默认值；“主要风险因子”按当前加权贡献选取；已解除事件不会重新进入待核实池
- [x] 图例与订单数量标签避让；图谱解读随当前数据变化；多事件/巡检输入变化使旧结果失效
- [x] 默认首页增加验收路线、风险优先项与已确认/待核实事件口径提示
- [x] AI 摘要来源链接与最近一次调用状态可见；异常不回显请求原文或密钥
- [x] UI：暴露度权重调节 + 敏感性/校验面板；推演页拆分单依赖/多依赖并行/方案比较
- [x] 统一视觉系统：深海蓝/风险橙/可信绿，品牌侧栏、六页雷达 Hero、卡片与响应式布局
- [x] 事件库精简中文证据字段；隐藏演示工具栏；键盘焦点与 reduced-motion 可访问性
- [x] 产品介绍 PPT 精美版：雷达主视觉、原生库存曲线、风险分解、责任矩阵与边界流程
- [x] 案例测试与边界案例演示：案例 A–D 口径定稿与自动化回归
      （`scripts/cases.py`；上游不明/低置信度事件均不产生确定结论）
- [x] 暴露度报告新增“主要风险因子 / 不确定性提示”，上游不明时给出
      授权链与人工尽调建议
- [x] 待核实事件默认不参与推演；UI 勾选时显式提示；`include_pending=True`
      仅作为“假设分析”
- [x] Streamlit 新增“6 案例与边界演示”页
- [x] 测试与迭代记录：`docs/test_cases.md`、`docs/iteration_log.md`
- [x] 打包脚本与提交包（`scripts/package.py`，产物在本地 `dist/`）
- [x] 在线部署配置（`.streamlit/config.toml`；实际部署见下方步骤）
- [x] 产品介绍 PPT 大纲（`docs/产品介绍PPT_大纲.md`）
- [x] 产品介绍 PPT 成品（西北民族大学：林明强、陈治希、李宇欣；精美版 `docs/地缘风险_产品介绍PPT_20260920_精美版.pptx`）

## 成果交付清单（2026-10-19 17:00 前提交 risk_a_lab@126.com）

- [x] 产品介绍 PPT（16 页精美版 `docs/地缘风险_产品介绍PPT_20260920_精美版.pptx`；大纲见 `docs/产品介绍PPT_大纲.md`）
- [ ] 可运行产品系统（`streamlit run app.py`；如需在线部署再补充访问链接）
- [x] 源代码与运行说明（本仓库即代码包：README + requirements + .env.example；
     提交前用 `python scripts/package.py` 生成 zip）

> 运行验收推荐：默认不勾选“叠加本地导入事件”，先用固定种子数据复现案例；
> 真实 RSS/AI 导入事件必须经过人工核实，不能因为模型返回 `active` 就直接进入确定性结论。

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

## 在线部署（Streamlit Community Cloud，可选但推荐）

仓库已带 `.streamlit/config.toml`，可直接一键部署：

1. 在 [Streamlit Community Cloud](https://streamlit.io/cloud) 用 GitHub 登录；
2. “New app” → 选择仓库 `IdlebBack/diyuan-risk` → Branch `main` →
   Main file `app.py`；
3. 部署成功后，把公开 URL 填入“成果交付清单”的可运行产品系统；
4. 如需真实 LLM：在应用 Settings → Secrets 中配置
   `OPENAI_API_KEY=...`（不写入仓库；无 Key 时自动离线占位）。

> 若你的网络无法访问 Google News/OpenAI，线上部署在美国区节点通常可正常访问；
> 本地无外网时系统仍能运行模拟样例。

案例 A–D 自动化回归（断供点、订单影响、上游信息缺失、待核实事件）：

```bash
python scripts/cases.py
```

离线单元测试：

```bash
python -m unittest discover -s tests -v
```

测试包含六页面 AppTest、图谱布局、推演边界、数据校验、导入原子写入和安全打包。
它们使用固定种子数据或临时合成文件，不需要联网或真实 API Key；测试中的网络/模型请求使用替身。
本机若没有创建符号链接的权限，两项真实链接专项会明确跳过；其余路径检查仍运行。

### 2026-09-13 优化说明与数据要求

- 自动事件推演中，显式 `supply_reduction_pct=0` 就是零削减，不再按严重度猜测损失；
  `lead_time_increase` 不得把已记录的当前交期缩短。
- 无关联订单仍可查看供给时间线，订单影响明确为未评估；“增加 +N 周库存”在输入的
  既有库存上追加，成本仅计本次增量。替代供应成本包含其就绪周，和离散到货时间线一致。
- `resolved` 事件在加载/刷新后保持解除状态，不进入默认推演、假设推演或待核实提醒。
- 核心 CSV 的编号必须非空，实体编号和采购订单编号不得重复，关联编号必须存在。
  数量/库存/金额须为有限非负数，采购份额及可替代性在 0–1 间，同组件采购份额合计不超过 1。
  `upstream_known` 仅接受 0/1；优先级为正整数；交付周 0 表示已到期、负数不接受。
- 允许订单/订单行为空，以及缺少可选的 `pipeline.csv`；同订单同组件的拆分物料行
  在关联视图中汇总，不重复计算订单金额。说明性 `notes` 缺省为空。
- 检查在内存中进行，不修改原 CSV。数据错误时界面指出文件、列和记录行，修正后重新加载。

本轮保持种子数据不变：案例 A 第 18 周、案例 B 第 17 周首次出现当周缺口；
前三批订单的交付周仍未见缺口。它们不是现实交付保证，详情见 `docs/test_cases.md`。

命令行导入风险信号到本地事件库（`data/events_live.csv`，按“标题+日期”去重）：

```bash
# 文本导入（离线时自动用规则占位并标记待核实）
python scripts/ingest_cli.py --text "据（虚构）报道，日本拟扩大高精度编码器出口审查范围……"

# 抓取模拟样例信号并入库
python scripts/ingest_cli.py --samples

# 抓取自定义 RSS 源并入库
python scripts/ingest_cli.py --rss "https://example.com/feed.xml"
```

生成赛道 B 成果提交包（zip）：

```bash
python scripts/package.py
```

产物位于 `dist/地缘风险_提交包_YYYYMMDD.zip`（dist/ 不随 git 提交）。
打包时只选取日期最新的正式 PPT；同日存在多个版本时优先选择 `_精美版`。

本地导入的事件存放在 `data/events_live.csv`（已加入 .gitignore，不随仓库提交）。
确定有价值的条目可人工整理后并入 `data/seed/events.csv` 再提交。

## 目录结构

```text
diyuan-risk/
├─ app.py                 # Streamlit 应用入口
├─ chainshield/           # 核心代码包
│  ├─ repository.py       # 数据模型与 CSV 装载
│  ├─ data_validation.py  # CSV 结构、数值与关联校验
│  ├─ graph.py            # 依赖图谱与集中度指标
│  ├─ risk.py             # 暴露度评分
│  ├─ scenario.py         # 情景推演引擎
│  ├─ events.py           # 风险事件库
│  ├─ signals.py          # 模拟/RSS 信号抓取
│  ├─ ingest.py           # 事件规范化与原子导入
│  ├─ llm.py              # LLM 接口（含离线占位）
│  ├─ reporting.py        # 可复现推演快照与 Markdown 报告
│  ├─ validation.py       # 权重敏感性与反事实检查
│  └─ config.py           # 环境配置
├─ data/seed/             # 种子数据（CSV，全部虚构）
├─ docs/
│  ├─ guide.pdf           # 赛制活动指南
│  ├─ 产品设计方案.md      # 产品设计
│  ├─ test_cases.md       # 案例验收与测试基线
│  └─ iteration_log.md    # 迭代日志
├─ scripts/
│  ├─ demo.py             # 冒烟演示
│  ├─ cases.py            # 案例 A–D 自动化回归
│  ├─ ingest_cli.py       # 命令行导入
│  └─ package.py          # 发布白名单与提交包生成
├─ tests/                 # 核心、UI、图谱、导入、打包与数据边界回归
└─ .github/workflows/tests.yml # GitHub Actions 离线检查
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
