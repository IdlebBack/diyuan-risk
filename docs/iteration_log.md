# 迭代日志

按赛制要求记录“开发—测试—反思—迭代”过程。所有企业、订单、事件数据均为赛题虚构。

## 2026-09-08｜评审整改（第二轮：无需 Key 的可完成项）

### 改动

- 启用 `data/sources.json` 中的 Google News RSS 源（日本精密零部件出口审查），
  网络可达时即可做“真实抓取 → 规则/LLM 抽取”演示；
- `app.py` 新增“AI 事件摘要（实验）”入口，接通 `llm.summarize_event`；
  未配置 Key 时明确提示离线占位，不产生结论；
- 新增 `.streamlit/config.toml` 与 README“在线部署”步骤，为
  Streamlit Community Cloud 一键部署做准备；
- 新增 `docs/需求调研访谈提纲.md`（访谈 + 问卷精简版 + 结果整理规范），
  供团队自行开展真实企业调研；
- 提交包包含 `.streamlit/`。

### 验证

- 六个页面在离线模式下全部打开无异常，事件摘要入口正常显示离线提示；
- `python scripts/cases.py` 与 `python scripts/demo.py` 退出码 0；
- `python -m compileall -q app.py chainshield scripts` 通过。

### 待办（等待用户提供有效 API Key）

- 填入新 Key 后做真实“RSS 抓取 → LLM 抽取 → 入库”端到端验证；
- 之后再把“AI 结果解读”接入推演结果页。

## 2026-09-08｜真实 LLM 链路验证（DeepSeek）

### 结果

- 配置 DeepSeek API Key（只写入本地 `.env`，已被 .gitignore 忽略）；
- 真实 Google News RSS 抓取成功（单次约 0.8 秒返回 10 条）；
- “真实抓取 → DeepSeek 抽取 → 规范化入库”链路跑通，入库 2 条本地事件，
  其中 1 条自动关联到 DEP-01；不确定信息按 low/medium 置信度标记待核实；
- `extract_risk_event` 与 `summarize_event` 均返回模型真实结果。
- 新增 `interpret_scenario` 并接入推演页：单依赖与多依赖并行结果可生成
  “AI 解读与行动注意事项”，输出附参数校准与人工复核提醒。
- 修复：案例页 A/B 同页渲染单依赖解读时按钮 key 冲突，改为 case_a/case_b 独立 key。
- 修复：AI 解读/事件摘要的网络超时异常未接住会导致页面崩溃，改为捕获后
  返回“调用模型失败”提示；新增 `OPENAI_TIMEOUT` 配置（默认 60 秒，可调）。

### 兼容性修复

- 真实模型可能把 `countries/related_dependencies` 返回为列表，入库前统一转成分号字符串；
- `related_dependencies` 只保留 DEP-01/DEP-02/DEP-03，其余由关键词兜底；
- `effect_kind` 增加别名映射，如 export_control → export_license；
- `Repository(include_live=False)` 供自动化回归使用，保证在本地导入真实事件后
  案例基线仍可复现。

## 2026-09-08｜评审整改（第一轮）

### 背景

收到外部评审意见后，按“可复现、可验证”的优先级处理代码与措辞问题，
避免文档承诺与实际行为不一致。

### 改动

- `scripts/cases.py`：stdout/stderr 显式 UTF-8 化，修复 Windows GBK 控制台下
  `UnicodeEncodeError` 导致退出码 1 的问题；
- `chainshield/graph.py`：中文字体改为按 matplotlib 字体表实际探测，
  不再执行无效的 rcParams 回退；缺失字体时给出明确警告；
- `chainshield/validation.py` 与 UI：排序稳定性改为“最高风险依赖（top1）”
  口径，避免在仅 3 条依赖时宣传“前三名稳定”；
- 推演命名统一为“多依赖并行推演”，同一依赖上的多事件先在
  `shocks_from_events` 合并，避免“多事件叠加”造成模型能力误解；
- `chainshield/risk.py` 与设计文档补充五因子权重依据，并说明是面向
  赛题场景的可调主观设定；
- 设计文档收敛 AI 边界表述：AI 承担结构化抽取与预留摘要能力，
  评分/推演/方案比较为确定性规则。

### 验证

- Windows GBK 控制台下 `python scripts/cases.py`：21 项 PASS，退出码 0；
- `python -m compileall -q app.py chainshield scripts`：通过；
- 敏感性分析 top1 稳定：True（DEP-02）。

## 2026-09-08｜里程碑 5：提交材料整理（PPT 成品）

### 背景

里程碑 4（案例 A–D 回归与边界演示）完成，里程碑 5 收尾项为产品介绍 PPT、
README 与提交包。学校与成员信息确认为：西北民族大学、陈冶希、李宇欣。

### 改动

- 生成 16 页产品介绍 PPT（`docs/地缘风险_产品介绍PPT_20260908.pptx`），
  内容覆盖摘要、风险议题、目标用户、痛点、解决思路、AI 边界、五个核心功能、
  案例 A–D 与测试迭代；
- 从本地运行应用实拍 6 个产品页面，作为系统可运行性证据放入 PPT；
- README 交付清单与仓库状态同步更新。

### 验证

- 页面结构校验：16 页、3 张原生表格、全部文本使用微软雅黑，0 告警；
- 六页 Streamlit 应用逐一打开确认无异常后截图；
- 数据口径与 `docs/test_cases.md`、`scripts/cases.py` 保持一致。

### 下一步

- 网络恢复后推送本地提交至 GitHub；
- 可选：接入真实 LLM Key 做端到端信号演示；
- 10/19 前按 README 清单复查并发送至 risk_a_lab@126.com。

## 2026-09-07｜里程碑 4：案例验证与边界处理

### 背景

里程碑 3 完成后，README 剩余项为“案例测试与边界案例演示”。Step 1 基线测试发现：

- 案例 A（编码器）与案例 B（芯片航运延误）在现有种子数据下均在第 17 周断供，
  而三批现有订单交付期（8/12/16 周）早于断供点，受影响订单数为 0；
- 案例 C 的上游信息缺失已有量化，但缺少面向用户的行动建议；
- 案例 D 的 verify 事件虽不参与评分，但可在 UI 中被直接勾选做推演。

### 决策

采用推荐口径：不改动赛题“三批订单”种子设定，案例 A/B 以“断供点预警 + 断供后
新增订单无缓冲 + 应对方案比较”为验收点；C/D 补齐边界提示。

### 改动

- `chainshield/risk.py`
  - 暴露度报告新增“主要风险因子”（分数最高的因子）与“不确定性提示”：
    - 上游未知 → “建议索取授权链或人工尽调”；
    - 存在 verify 事件 → “N 条待核实事件未计入评分，需人工确认”。
- `chainshield/scenario.py`
  - `_build_messages`：断供且现有订单不受影响时，追加“断供后新增订单无库存支撑”警告；
  - `shocks_from_events`：默认过滤 `status=verify` 的事件；
  - 新增 `include_pending=True` 显式假设分析模式；
  - 新增 `pending_event_ids` 供 UI 提示被忽略的待核实事件。
- `app.py`
  - 多事件推演：勾选待核实事件时提示“已忽略，不构成推演结论”；
  - 新增导航页“6 案例与边界演示”，一键展示 A–D 的推演结果、解释与方案比较。
- 新增 `scripts/cases.py`：A–D 自动化回归，退出码可被 CI/人工检查复用。
- 文档：`docs/test_cases.md` 定稿口径与结果；新增本迭代日志。

### 验证

- `python scripts/cases.py`：A/B/C/D 全部 PASS（断供周次、现有订单不受影响、
  上游行动建议、待核实事件默认排除/显式启用等 21 项断言）。
- `python scripts/demo.py`：主流程冒烟通过，暴露度与推演输出保持里程碑 3 基线。
- `python -m compileall -q app.py chainshield scripts`：语法编译通过。

### 反思 / 已知局限

- 案例 A/B 中“现有订单不受影响”是推荐口径下的真实结论，但 PPT 演示如需更直观的
  “受影响订单金额”，可在案例页用假设订单说明，而不改种子数据。
- 冲突报道（同一议题多来源相互矛盾）尚未建专门数据结构；目前以
  `verify + confidence=low` 保守处理。可作为后续迭代项。
- 回归脚本中“第 17 周”来自当前种子数据；若后续调整库存/交期/在途口径，
  需同步更新 `docs/test_cases.md` 与 `scripts/cases.py`。

### 下一步

- 里程碑 5：README 收尾、产品介绍 PPT（约 15 页）、打包与提交前检查。

## 2026-09-03｜里程碑 1–3（按 git 历史补录）

> 初版迭代日志从里程碑 4 才开始，这里按 2026-09-03 的 git 提交与仓库文档
> 回溯整理，便于评审看到完整“开发—测试—反思—迭代”链。

### 里程碑 1：仓库与数据模型（edf357d）

- 阅读活动指南并选定赛道 B、参考方向三（全球供应链与产业安全）；
- 建立仓库与目录结构，设计模拟企业种子数据（组件/供应商/依赖/订单/事件）；
- 数据模型与 CSV 装载可用，Streamlit 骨架可运行。

### 里程碑 2：风险信号与事件导入（11f5b96）

- 样例源 + RSS/Atom 巡检管道可用；
- LLM 结构化抽取接口含 OpenAI 与离线占位两种实现，无 Key 自动降级；
- 信号去重与本地事件库导入打通。

### 里程碑 3：暴露度与推演引擎（699a519、19e8e7d）

- 五因子暴露度模型 v1 与透明评分报告；
- 离散周推演 v1：计入在途订单、持续补货、替代供应与多事件冲击合并；
- 权重敏感性与反事实校验 4/4 PASS；
- 项目更名为“地缘风险”，仓库更名 diyuan-risk。

### 回溯反思

- 早期把“推演”与“方案比较”设计得比 MVP 大，实际以离散周确定性模型收敛，
  优先保证可在 10 月中旬前演示；
- 数据与 UI 未分家时迭代较慢，里程碑 3 后固定为“CSV 种子数据 + 核心包 +
  Streamlit 薄界面”的结构。
