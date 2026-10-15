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

3. **Python 依赖**：推荐直接 `bash scripts/install.sh`（自动建/用 venv，装齐 `jieba pyyaml numpy pandas scikit-learn openai python-dotenv` + `pip install -e $SPI_ROOT`，检查三个兄弟仓库，生成 `wenbi.env`，装完自检）。装完 `source wenbi.env`；离线冒烟：`python3 scripts/smoke_test.py`（不需要 key、不花钱）。

4. **SPI 的 Personality Atlas 数据仓库（必需，~1.1GB）**：检查 `$SPI_ROOT/assets/survey/results/spi_table.json` 是否存在。
   - 不存在 → **提醒用户**："SPI 人格打分依赖 Personality Atlas 数据（约 1.1GB），首次使用需执行：`cd $SPI_ROOT/assets && git clone https://github.com/Wildertrek/survey.git`"
   - 这是必需数据，不是可选对照；没有它 SPI 人格打分跑不了。

5. **SPI 的 3072 维嵌入数据（可选，~879MB）**：只有 `--spi-mode local` / `spi-quant spi --mode local` 离线映射才需要；默认 LLM 判聚类不需要。需要时 `bash scripts/install.sh --with-local`。

**只有上述 1-4 项齐备，才进入正式流水线。** 提醒时一次性列清所有缺失项，不要跑一步报一个错。

**环境齐备后，立即主动问用户要对标文章**："环境已就绪。请提供你想复刻的那个人的原文（建议 20 篇以上、每篇 300 字以上，文件或链接均可），我会基于这批原文重新提取风格基线，然后生成模仿文。"

---

# 文笔复刻

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
对象原文（.txt/.md/语料 JSON）由 `replicate.py --corpus-dir` 读入做 WFP 指纹（doc_id = 文件名 stem）。
**replicate.py 不生成 AoT 块、也不触发任何 LLM 打分**：AoT 语料用 `$AOT_ROOT/scripts/prepare_corpus.py` 生成，SPI 直接逐篇喂 txt。
语料要求：对象本人真实文本，建议 ≥20 篇、单篇 ≥300 字（不足时参考 `references/limits.md` 第 11 条兜底）。

### ② 三件套画像（各模块独立跑，可并行）

**所有脚本都在各自 toolkit 的 scripts/ 目录下，直接调用，不要自己拼格式。**

- **WFP 硬指标基线**：`replicate.py` 自动完成（逐篇指纹 + `field_map.aggregate_baseline` 聚合，<5 篇非空原文直接报错）。
  口径（field_map v3）：原始词 TTR 不进 Delta（随篇长下降，用 STTR）；我:你、正:负比值 +1 平滑；6 个句长相关特征共享权重。
- **SPI 人格**（需 DeepSeek key，`spi-quant` 已安装）：
  ```bash
  spi-quant profile --file <文章.txt> --out <profile.json>     # 逐篇打分
  python3 $SPI_ROOT/scripts/aggregate_spi_profiles.py <profiles_dir> --out spi_cluster_all.json  # 汇总被测人画像
  ```
- **AoT 思维**（需 key）：
  ```bash
  python3 $AOT_ROOT/scripts/prepare_corpus.py <原文目录> --person <pid> --name <人名>   # → $AOT_ROOT/data/corpus/<pid>.json
  python3 $AOT_ROOT/scripts/score_dimensions.py --person <pid> --dry-run   # 先看调用次数
  python3 $AOT_ROOT/scripts/score_dimensions.py --person <pid>             # → data/results/scores_dim_v2/<pid>.json（25 维，断点续跑）
  python3 $AOT_ROOT/scripts/aggregate_profiles.py $AOT_ROOT/data/results/scores_dim_v2 \
      --names <pid>=<人名> --out people_profiles.json                       # 人设卡用 --aot-person <人名>
  # 可选：score_criterion.py（效标代理 → data/results/criterion/）、score_thinking.py（12 种子构念 → data/results/scores/）
  # --full 只是改用 data/corpus_full 语料目录（需自己用 prepare_corpus.py --out-dir data/corpus_full 准备）
  ```
- **WFP L3 软评分**（需 key）：
  ```bash
  python3 $WFP_ROOT/scripts/score_stylistics.py --corpus-dir <原文目录> --dry-run      # 先看调用次数
  python3 $WFP_ROOT/scripts/score_stylistics.py --corpus-dir <原文目录> \
      --out-dir <l3_scores> --l3-baseline-out l3_baseline.json                   # 17 维逐篇评分 + L3 基线
  ```
- **WFP L4 隐喻识别**（需 key）：
  ```bash
  python3 $WFP_ROOT/scripts/score_metaphor.py <文章.txt> --out metaphor.json  # → 12 根域隐喻密度 + 例句（独立参考，不进 Delta/人设卡）
  ```

无 key 时 SPI/AoT/L3/L4 这些 LLM 打分环节**直接报错退出（退出码 1）**；只有 WFP L1/L2 纯规则硬指标可无 key 运行。
LLM 调用统一走各仓 `llm_common`：模型/温度/并发来自各仓 config，429/5xx/截断自动指数退避，输入超 6000 字截断并在结果里标 `truncated`；有打分项最终失败时退出码 3（重跑即续跑）。

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
`--people-baseline <块级基线.json> --people-key <key>`（可选）：篇章级基线缺某项硬指标时用块级值补齐（stderr 会列出补了哪些）。
也可以一步到位：`replicate.py --name <key> --wfp-baseline <已有基线> --spi-clusters ... --aot-profiles ... --aot-person ... --l3-baseline ...`（无 `--corpus-dir` 时必须给 `--wfp-baseline`；L3 基线不能代替 WFP 基线）。

### ④ 生成模仿文
按人设卡"四、生成指令模板"投喂 LLM（DeepSeek/豆包/Claude 等均可）。生成要求：
- 目标字数 ≥800 字再回测（判别力，见 `references/limits.md` 第 5 条）；
- 硬指标数值约束直接写进 prompt（句长/问句/语气词/隐喻/我:你 命中后 Delta 显著下降）；
- 低分维度要写"少用"设锚；软特征用负向锚 + 中低位目标值，避免顶格过冲（`references/limits.md` 第五节）。

**生成 prompt 的 3 条经验（跨平台通用）**：
1. **低数值特征必须显式写"少用"**：反问 0.2/篇、四字格 3.95/千字这类低值，不写"少用" LLM 默认往中间靠，会过量。写法：`修辞反问 ≤0.3 个/篇（少用）；四字格 ≤5 个/千字（不堆砌）`。
2. **数值密度加 few-shot 体感**："正情 26/千字"这种数字 LLM 没概念，prompt 里抄 1-2 句原文当例子，让它对密度有体感。
3. **短块语料回测跳过整体 Delta**：原文每篇 <500 字时，直接逐项对比关键指标（句长/正情密度/隐喻密度），报告里注明"语料偏短，Delta 参考意义有限"。

### ⑤ 指纹回测
```bash
python3 $WFP_ROOT/scripts/extract_hard_metrics.py <生成文.txt> --json > gen_fp.json
python3 $WFP_ROOT/scripts/merge_fingerprint.py gen_fp.json --baseline <wfp_baseline_<key>.json> [--l3dir <l3_scores 目录>] --json
```
判断口径：**Delta 越低越像**（同质长文实测：真实文基线 ~1.5 / 模仿文收敛至 ~1.3 / 对照文 ~7+，判别比可达 4×）。
异质语料时 Delta 会失效（判别比≈1×），改用分层基线（≥800 字）或非参数判据。

**⚠️ 篇幅差异陷阱**：如果原文每篇平均 <500 字，而生成文 >1000 字，按"每篇"算的指标（问句/篇、修辞反问/篇）会被篇幅放大，导致 Delta 失真。这时**改用"每千字"归一化指标对比**（语气词/千字、衔接词/千字、隐喻/千字），不要看绝对 Delta 数值。

`replicate.py --backtest <生成文.txt>` 可自动完成 ⑤。

**⚠️ 回测前必须先做判别力自检**（尺子不准，Delta 结果不可信）：
```bash
# 手动：一条命令两关都跑（--control / --other-author 可以是文件或目录）
python3 $WFP_ROOT/scripts/validate_discrimination.py \
  --baseline <基线.json> \
  --held-out <原作者留出文章.txt（不能在基线语料里）> \
  --control <对照文.txt> \
  --other-author <另一作者文章.txt>
# 自动：从「不在基线里」的原作者文章随机留出，与另一作者对比，多轮（seed 可复现）
python3 $WFP_ROOT/scripts/validate_discrimination.py --baseline <基线.json> \
  --corpus <原作者留出语料目录> --other-author <另一作者目录> --rounds 5 --seed 42
```
- 关 1：留出 vs 对照判别比 ≥1.5（`--threshold`）；关 2：留出 vs 异作者判别比 ≥1.2（`--threshold-other`）；给了几关就要几关都过
- 留出文若在基线的 `doc_ids` 里会被剔除（自己比自己没意义）；基线 <5 篇 / 可用特征 <10 / 空文本直接报错
- 退出码：0 正常（结论看输出）、1 输入错误；加 `--strict` 时 FAIL 退出 2
- **两关过不了，Delta 直接标"不可信"，不硬报数值**
- 生成文偏项迭代：`python3 scripts/iterative_generate.py --baseline <基线> --gen-fp gen_fp.json --original-prompt <prompt.txt> --round 1`（修正要求用中文标签与增减方向）

## 交付报告必须包含的内容（不能自由发挥）

最终给用户的文风画像报告，必须包含以下 5 部分，缺任何一项都要说明原因：

1. **一句话概括**：这个人是谁、怎么说话（1-2 句）
2. **人格底色（SPI）**：top3-6 语义簇 + 关键因子分数（如神经质 1.93/7）
3. **思维模式（AoT）**：top5 思维维度 + 1-2 句典型表现
4. **文风指纹（WFP）**：
   - **硬指标具体数值**：平均句长 ~X 字、问句 X/篇、语气词 X/千字、我:你 X:X、四字格 X/千字
   - **L3 软画像**：top6 维度分数（1-7）
   - **L4 隐喻**：12 根域密度 top3 + 总隐喻数/千字
5. **生成指令模板**：可直接复制投喂 LLM 的 prompt（数值约束 + 软画像 + 思维底色 + 人格底色 + 禁止项）

**不要只给文字解读，不给数值。** 用户要的是"可复现的风格画像"，不是散文评论。

## 违禁词 / 合规词表

本工具**不内置违禁词表**。使用方根据自己的行业（如医疗、金融、教育）自备违禁词清单，在生成环节自行过滤。

## 模块分工与重叠带
- WFP 测**特征值**（L1 语言表层 / L2 语篇结构 / L3 叙事修辞软评分 / L4 隐喻根域），只测不解释。
- SPI/AoT 解释**构念分**（他是谁 / 他怎么想）；重叠带（隐喻/情绪/姿态）由 WFP 供原料、SPI/AoT 解读。
- 叙事套路不在三件套内：用**对象原文 few-shot + 体裁分析**补足。

## 参考文件
- `references/field_contract.md` —— **字段命名规范（接口契约）**：所有中间文件的字段名、格式、错误处理原则，改脚本前必读。
- `references/limits.md` —— 已知局限与适用边界（**使用前必读**：精度边界、判别失效条件、评分器缺陷、运行条件、生成端校准结论）。
- `references/input_formats.md` —— 三模块语料/画像/基线的 JSON 结构与全部调用命令速查。

## 交付
输出 = 人设卡（json + md）+ 模仿文 + 回测结果。默认在对话框交付；如需文件，写入指定目录。
