# 文笔复刻1.0 · 输入输出格式与调用速查

三个模块统一管理在 `<SPI_ROOT>`、`<AoT_ROOT>`、`<WFP_ROOT>`。
本文件记录各模块的语料格式、画像产物结构与调用命令，供流水线接线时核对。

## 一、语料格式

| 模块 | 文件 | 结构 | 示例 |
|---|---|---|---|
| SPI | `SPI/data/results/<obj>_profiles/<obj>_articles_clean.json` | `dict{标题: 正文}`（值可为字符串或字符串列表） | `{"某篇标题": "...", "另一篇": "..."}` |
| AoT | `AoT/data/corpus/<pid>.json`（`--full` 时 `corpus_full/`；均 gitignore，用 `prepare_corpus.py` 生成） | `{"person", "name", "n_total", "n_sampled", "items": [{"id", "title", "text", ...}]}` | 每个对象一个 JSON |
| WFP | `WFP/data/corpus/` | 复用 SPI/AoT 语料，不单独存正文 | — |

新对象接入时：`replicate.py --corpus-dir` 只读原文做 WFP 指纹（doc_id = 文件名 stem），**不生成 SPI/AoT 语料**；
AoT 语料用 `python3 <AoT_ROOT>/scripts/prepare_corpus.py <原文目录> --person <pid> --name <人名>`；SPI 直接对 txt 逐篇 `spi-quant profile`。
`data_sources.yaml` 的 `${SPI_ROOT}`/`${AOT_ROOT}`/`${WFP_OBJ}` 从环境变量展开（未设置报错），也可用 `--spi-path`/`--aot-dir` 覆盖。

## 二、画像产物结构

### SPI
- 单文本画像：`spi-quant profile --file X --out Y` → `Y`（32 因子 × {score 1-7, evidence, confidence} + 聚类命中 + persona）
- 聚类画像：`SPI/data/results/<obj>_profiles/spi_cluster_all.json`
  ```json
  {"n_docs", "n_failed", "top_k": 5, "cluster_summary": [{"cluster", "label", "n_first", "n_top5", "avg_relevance"(1-7 原始契合度均值), "avg_hit_norm"}], ...}
  ```
- 人设描述词典：`SPI/scripts/persona_report.py`（32 因子 × 三档说明）

### AoT
- 人物画像：`aggregate_profiles.py <scores_dir> --names pid=人名 --out people_profiles.json`
  ```json
  {"<key>": {"name": "<人读名>", "top5": [{"dim", "dim_name", "mean", "evidence": [...]}], ...}, ...}
  ```
- 块级评分：`AoT/data/results/scores_dim_v2/<pid>.json`（`--full` 时 `scores_full/`；25 维 × 双轮 × 证据，断点续跑）
- 尺子锚点：`AoT/data/results/ruler/`（维度定义与两极锚）

### WFP
- 单文本指纹：`extract_hard_metrics.py <file> --json` → stdout JSON
  （数值特征：`chars / sentences / L1_SYN_001_avg_sl / L1_LEX_001_sttr100 / L1_SYN_004_question_sents / ...`）
- 篇章级基线：`WFP/data/results/wfp_baseline_spi.json`
  ```json
  {"n_docs": 431, "corpus": "spi", "version": "...", "avg_chars": 3800, "field_map_version": 3,
   "doc_ids": ["篇名1", ...], "missing_features": [],
   "baseline": {"L1_SYN_001_avg_sl": {"mean": 25.1, "sd": 8.2, "n": 431}, ...}}
  ```
  Delta 口径字段由 `<WFP_ROOT>/scripts/field_map.py` 的 `flatten()` 统一生成（见 field_contract.md）。
- L3 软画像基线：`WFP/data/results/l3_baseline.json`
  ```json
  {"n_docs": 9, "n_dims": 17, "baseline": {"D01": {"dim_name": "互动", "mean": 6.51, "sd": 0.4, "n": 9}, ...}}
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
python3 <WFP_ROOT>/scripts/extract_hard_metrics.py --summary 指纹/*.json --name <key> > wfp_baseline_<key>.json

# WFP L3 软评分（需 key；断点续跑；--dry-run 只估算调用次数）
python3 <WFP_ROOT>/scripts/score_stylistics.py --corpus-dir <原文目录> --out-dir <l3_scores> --l3-baseline-out l3_baseline.json
python3 <WFP_ROOT>/scripts/score_stylistics.py --source spi [--spi-path ...]   # 或 --source aot [--aot-dir ...]

# 判别力自检（两关）
python3 <WFP_ROOT>/scripts/validate_discrimination.py --baseline <基线> --held-out <留出.txt> --control <对照> --other-author <他人>

# 中间文件 schema 校验
python3 scripts/validate_schemas.py [--spi ...] [--aot ...] [--wfp ...] [--l3 ...]

# WFP Delta 回测
python3 <WFP_ROOT>/scripts/merge_fingerprint.py <生成文指纹.json> --baseline <基线.json> [--l3dir data/results/l3_scores] [--json]

# SPI 画像（需 key；spi-quant 已安装时）
spi-quant profile --file <文本.txt> --out <profile.json>

# AoT 画像（需 key）
python3 <AoT_ROOT>/scripts/prepare_corpus.py <原文目录> --person <pid> --name <人名>
python3 <AoT_ROOT>/scripts/score_dimensions.py --person <pid>
python3 <AoT_ROOT>/scripts/aggregate_profiles.py <AoT_ROOT>/data/results/scores_dim_v2 --names <pid>=<人名> --out people_profiles.json

# 人设卡合成（通用版）
python3 scripts/build_persona_generic.py --name <key> [--spi-clusters ...] [--aot-profiles ... --aot-person 人名] [--wfp-baseline ...] [--l3-baseline ...] [--people-baseline ... --people-key <key>] --out-dir <目录>

# 一键管线（最小闭环 / 带画像合成 / 带回测）
python3 scripts/replicate.py --name <key> (--corpus-dir <原文目录> [--min-docs 5] | --wfp-baseline <基线>) [--limit N] [--spi-clusters ...] [--aot-profiles ... --aot-person 人名] [--l3-baseline ...] [--people-baseline ... --people-key <key>] [--backtest 生成文.txt] --out-dir <目录>
```

## 四、依赖与环境

- **API key**：三个仓库统一（各自的 `llm_common`）：`DEEPSEEK_API_KEY` 环境变量 → `$WENBI_ENV_FILE` → 本仓 `.env` → `$AOT_ROOT/$SPI_ROOT/$WFP_ROOT` 的 `.env`；
  缺 key 时所有 LLM 打分脚本报错退出 1。`WENBI_MOCK_LLM=1` 为离线假客户端（smoke_test 用）。
  单项打分全部重试失败时记 `"score": null, "failed": true`（SPI 为 `failed: true`），不进基线/画像。
- **SPI 安装**：`uv pip install -e <SPI_ROOT>`（提供 `spi-quant` CLI；未安装则跳过 SPI 画像）。
- **Python 依赖**：`bash scripts/install.sh` 一次装齐（jieba pyyaml numpy pandas scikit-learn openai python-dotenv + SPI）；
  没装 jieba 时 extract 输出告警（replicate 会转发），词 TTR/四字格为 None。
- **词表**：`WFP/data/thuocl_chengyu.txt`（四字格口径词表，勿删）。
