# 文笔复刻1.0 · 输入输出格式与调用速查

三个模块统一管理在 `<SPI_ROOT>`、`<AoT_ROOT>`、`<WFP_ROOT>`。
本文件记录各模块的语料格式、画像产物结构与调用命令，供流水线接线时核对。

## 一、语料格式

| 模块 | 文件 | 结构 | 示例 |
|---|---|---|---|
| SPI | `SPI/data/results/<obj>_profiles/<obj>_articles_clean.json` | `dict{标题: 正文}`（值可为字符串或字符串列表） | `{"某篇标题": "...", "另一篇": "..."}` |
| AoT | `AoT/data/corpus_full/*.json` | `{"person", "name", "n_total", "n_sampled", "items": [{"id", "title", "text", ...}]}` | 每个对象一个 JSON |
| WFP | `WFP/data/corpus/` | 复用 SPI/AoT 语料，不单独存正文 | — |

新对象接入时：正文目录/文件 → 归并为 SPI dict（每篇一个 key）+ AoT 块（items 数组）。
`scripts/replicate.py --corpus-dir` 自动完成这两种归一。

## 二、画像产物结构

### SPI
- 单文本画像：`spi-quant profile --file X --out Y` → `Y`（32 因子 × {score 1-7, evidence, confidence} + 聚类命中 + persona）
- 聚类画像：`SPI/data/results/<obj>_profiles/spi_cluster_all.json`
  ```json
  {"cluster_summary": [{"cluster", "label", "n_first", "n_top5", "avg_relevance", ...}], ...}
  ```
- 人设描述词典：`SPI/scripts/persona_report.py`（32 因子 × 三档说明）

### AoT
- 七人画像：`AoT/data/results/profiles_full/people_profiles.json`
  ```json
  {"<key>": {"name": "<人读名>", "top5": [{"dim", "dim_name", "mean", "evidence": [...]}], ...}, ...}
  ```
- 全量评分：`AoT/data/results/scores_full/`（25 维 × 双轮 × 证据，断点续跑）
- 尺子锚点：`AoT/data/results/ruler/`（维度定义与两极锚）

### WFP
- 单文本指纹：`extract_hard_metrics.py <file> --json` → stdout JSON
  （数值特征：`chars / sentences / L1_SYN_001_avg_sl / L1_LEX_001_sttr100 / L1_SYN_004_question_sents / ...`）
- 篇章级基线：`WFP/data/results/wfp_baseline_spi.json`
  ```json
  {"n_docs": 431, "corpus": "spi", "version": "...", "baseline": {"L1_SYN_001_avg_sl": {"mean": 25.1, "sd": 8.2, "n": 431}, ...}}
  ```
- L3 软画像基线：`WFP/data/results/l3_baseline.json`
  ```json
  {"dimensions": {"D01": {"name": "互动", "mean": 6.51, ...}, ...}}
  ```
- 块级七人基线：`WFP/data/results/wfp_baseline_people.json`
  ```json
  {"people": {"<key>": {"n_blocks": 0, "hard": {"L1_LEX_004_yqci_per_k": 11.169, ...}}}}
  ```
- 分层基线（异质语料）：`按块长分层的基线 JSON`
- 人设卡：`persona_<name>.json` + `三件套人设卡_<name>.md`（含生成指令模板）

## 三、调用命令速查

```bash
# WFP 硬指标（单文本 / 全量 / 聚合基线）
python3 <WFP_ROOT>/scripts/extract_hard_metrics.py <file> --json
python3 <WFP_ROOT>/scripts/extract_hard_metrics.py --corpus-spi [--limit N]
python3 <WFP_ROOT>/scripts/extract_hard_metrics.py --corpus-aot [--limit N]
python3 <WFP_ROOT>/scripts/extract_hard_metrics.py --summary "指纹/*.json"

# WFP L3 软评分（需 key；--source spi|aot；断点续跑）
python3 <WFP_ROOT>/scripts/score_stylistics.py --source spi
python3 <WFP_ROOT>/scripts/score_stylistics.py --source aot

# WFP Delta 回测
python3 <WFP_ROOT>/scripts/merge_fingerprint.py <生成文指纹.json> --baseline <基线.json> [--l3dir data/results/l3_scores] [--json]

# SPI 画像（需 key；spi-quant 已安装时）
spi-quant profile --file <文本.txt> --out <profile.json>

# AoT 画像（需 key；全量语料 → 25 维评分）
python3 <AoT_ROOT>/scripts/score_dimensions.py --full

# 人设卡合成（通用版）
python3 scripts/build_persona_generic.py --name <key> [--spi-clusters ...] [--aot-profiles ... --aot-person 人名] [--wfp-baseline ...] [--l3-baseline ...] [--people-baseline ... --people-key <key>] --out-dir <目录>

# 一键管线（最小闭环 / 带画像合成 / 带回测）
python3 scripts/replicate.py --name <key> --corpus-dir <原文目录> [--limit N] [--spi-clusters ...] [--aot-profiles ... --aot-person 人名] [--l3-baseline ...] [--people-baseline ... --people-key <key>] [--backtest 生成文.txt] --out-dir <目录>
```

## 四、依赖与环境

- **API key**：<SPI_ROOT>/.env 与 <AoT_ROOT>/.env（`DEEPSEEK_API_KEY=sk-...`）；
  WFP 的 L3 打分复用 AoT 的 `.env`。缺失时自动模拟模式（`simulated: true`）。
- **SPI 安装**：`uv pip install -e <SPI_ROOT>`（提供 `spi-quant` CLI；未安装则跳过 SPI 画像）。
- **Python 依赖**：`pyyaml`、`jieba`（四字格口径）、`numpy` 为 WFP 必需。
- **词表**：`WFP/data/thuocl_chengyu.txt`（四字格口径词表，勿删）。
