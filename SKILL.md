---
name: wenbi-replica
description: 文笔复刻（Writing Style Replication）通用流水线：给定某人一批真实原文，产出该人风格的模仿文与可验证的画像报告。整合 SPI（人格底色，他是谁）、AoT（思维模式，他怎么想）、WFP（文风指纹，他怎么说）三个量化模块。当用户要求"复刻/模仿某人的文笔或写作风格""按 XX 的文风写一段""给一批文章仿写该作者风格""文笔复刻"时使用。也用于为自媒体账号、作家、KOL 建立可复用的文风画像卡。
---

## ⚠️ 首次使用必查（agent 必读，加载本 skill 后第一件事）

**在做任何分析之前，先逐项检查环境，缺哪项就主动提醒用户配置，不要直接开跑。**

1. **DeepSeek API Key**：检查环境变量 `DEEPSEEK_API_KEY` 是否已设置。
   - 未设置 → **立即提醒用户**："文笔复刻需要 DeepSeek API Key 才能做人格/思维/隐喻打分（L3/L4）。请到 https://platform.deepseek.com/ 创建 key，然后执行 `export DEEPSEEK_API_KEY=sk-...` 或写入 `.env` 文件。"
   - 只有用户明确说"先跑最小闭环（仅句长/问句统计）"时，才允许在无 key 情况下跑 L1/L2 纯规则硬指标。

2. **三个 toolkit 路径**：检查 `SPI_ROOT`、`AOT_ROOT`、`WFP_ROOT` 三个环境变量是否指向对应 toolkit 根目录。
   - 未设置 → 提醒用户："请设置三个 toolkit 的路径：`export SPI_ROOT=... AOT_ROOT=... WFP_ROOT=...`"

3. **Python 依赖**：首次运行前确保已安装 `jieba pyyaml numpy openai`，且 SPI 已 `pip install -e` 安装。

4. **SPI 的 Personality Atlas 数据仓库（必需，~1.1GB）**：检查 `$SPI_ROOT/assets/survey/results/spi_table.json` 是否存在。
   - 不存在 → **提醒用户**："SPI 人格打分依赖 Personality Atlas 数据（约 1.1GB），首次使用需执行：`cd $SPI_ROOT/assets && git clone https://github.com/Wildertrek/survey.git`"
   - 这是必需数据，不是可选对照；没有它 SPI 人格打分跑不了。

**只有上述四项齐备，才进入正式流水线。** 提醒时一次性列清所有缺失项，不要跑一步报一个错。

---

# 文笔复刻 1.0

三件套整合流水线：**SPI（他是谁）+ AoT（他怎么想）+ WFP（他怎么说）→ 人设卡 → 模仿文 → 回测校验**。

- SPI + AoT = **「里」**（人格 + 思维，解释作者内核）
- WFP = **「表」**（表层文风数值化）

三个模块分别是独立 toolkit，本仓只做整合编排。模块路径通过环境变量或 config 指定，不硬编码。

## 流水线总览

```
原文 → ①语料归一 → ②三件套画像（WFP L1/L2 硬指标 / SPI 人格 / AoT 思维 / WFP L3 软评分 / WFP L4 隐喻）
     → ③人设卡合成 → ④按人设卡生成模仿文 → ⑤指纹回测（Delta/判别比）→ 报告
```

- **最小闭环**（无需 key）：①+②WFP L1/L2 纯规则硬指标（句长/问句/语气词/四字格）+③+④+⑤，够出"数值约束 + 模仿文 + Delta"。
- **完整版**：再加 SPI/AoT 画像、WFP L3 软评分（17维）、WFP L4 隐喻（12根域）——这三步都需 DeepSeek key，人设卡更立体，回测含 L3/L4 兑现检验。

## 快速开始（最小闭环）

```bash
python3 scripts/replicate.py --name <对象key> --corpus-dir <原文目录> \
  --out-dir <输出目录> --backtest <生成文.txt>
```

产出：`wfp_baseline_<key>.json`（硬指标基线）、`persona_<key>.json` + `三件套人设卡_<key>.md`（含生成指令模板）、生成文回测 Delta。

## 完整流程（五步）

### ① 语料归一
对象原文（.txt/.md/语料 JSON）由 `replicate.py --corpus-dir` 自动归并为 SPI dict + AoT 块。
语料要求：对象本人真实文本，建议 ≥20 篇、单篇 ≥300 字（不足时参考 `references/limits.md` 第 11 条兜底）。

### ② 三件套画像（各模块独立跑，可并行）
- **WFP 硬指标基线**：`replicate.py` 自动完成（逐篇指纹 + 聚合）。
- **SPI 人格**（需 DeepSeek key，`spi-quant` 已安装）：
  `spi-quant profile --file <文本> --out <out>` 逐篇批处理，聚类画像产出 `spi_cluster_all.json`。
- **AoT 思维**（需 key）：`<AoT_ROOT>/scripts/score_dimensions.py --full`
  → `people_profiles.json`（25 维 × top5）。
- **WFP L3 软评分**（需 key）：`<WFP_ROOT>/scripts/score_stylistics.py --source spi`
  → `l3_baseline.json`（17 维）。
- **WFP L4 隐喻识别**（需 key）：`<WFP_ROOT>/scripts/score_metaphor.py 文章.txt --json`
  → `l3_baseline.json`（17 维）。断点续跑，重复执行只补未完成项。

无 key 时 SPI/AoT/L3/L4 这些 LLM 打分环节**直接报错退出**；只有 WFP L1/L2 纯规则硬指标可无 key 运行。

### ③ 人设卡合成
```bash
python3 scripts/build_persona_generic.py --name <key> --display-name "人读名" \
  --spi-clusters <spi_cluster_all.json> \
  --aot-profiles <people_profiles.json> --aot-person <人名> \
  --wfp-baseline <wfp_baseline_<key>.json> \
  --l3-baseline <l3_baseline.json> \
  --out-dir <输出目录>
```
人设卡 = 人格底色（SPI top6 簇）+ 思维模式（AoT top5 维）+ 文风指纹（硬指标数值约束 + L3 软画像）+ **可直接投喂的生成指令模板**。所有输入可选，缺哪块就只合成哪块。

### ④ 生成模仿文
按人设卡"四、生成指令模板"投喂 LLM（DeepSeek/豆包/Claude 等均可）。生成要求：
- 目标字数 ≥800 字再回测（判别力，见 `references/limits.md` 第 5 条）；
- 硬指标数值约束直接写进 prompt（句长/问句/语气词/隐喻/我:你 命中后 Delta 显著下降）；
- 低分维度要写"少用"设锚；软特征用负向锚 + 中低位目标值，避免顶格过冲（`references/limits.md` 第五节）。

### ⑤ 指纹回测
```bash
<WFP_ROOT>/scripts/extract_hard_metrics.py <生成文.txt> --json > gen_fp.json
<WFP_ROOT>/scripts/merge_fingerprint.py gen_fp.json --baseline <wfp_baseline_<key>.json> [--l3dir <l3_scores 目录>] --json
```
判断口径：**Delta 越低越像**（同质长文实测：真实文基线 ~1.5 / 模仿文收敛至 ~1.3 / 对照文 ~7+，判别比可达 4×）。
异质语料时 Delta 会失效（判别比≈1×），改用分层基线（≥800 字）或非参数判据。

`replicate.py --backtest <生成文.txt>` 可自动完成 ⑤。

## 违禁词 / 合规词表

本工具**不内置违禁词表**。使用方根据自己的行业（如医疗、金融、教育）自备违禁词清单，在生成环节自行过滤。

## 模块分工与重叠带
- WFP 测**特征值**（L1 语言表层 / L2 语篇结构 / L3 叙事修辞软评分 / L4 隐喻根域），只测不解释。
- SPI/AoT 解释**构念分**（他是谁 / 他怎么想）；重叠带（隐喻/情绪/姿态）由 WFP 供原料、SPI/AoT 解读。
- 叙事套路不在三件套内：用**对象原文 few-shot + 体裁分析**补足。

## 参考文件
- `references/limits.md` —— 已知局限与适用边界（**使用前必读**：精度边界、判别失效条件、评分器缺陷、运行条件、生成端校准结论）。
- `references/input_formats.md` —— 三模块语料/画像/基线的 JSON 结构与全部调用命令速查。

## 交付
输出 = 人设卡（json + md）+ 模仿文 + 回测结果。默认在对话框交付；如需文件，写入指定目录。
