---
name: wenbi-replica
description: 文笔复刻（Writing Style Replication）通用流水线：给定某人一批真实原文，产出该人风格的模仿文与可验证的画像报告。整合 SPI（人格底色，他是谁）、AoT（思维模式，他怎么想）、WFP（文风指纹，他怎么说）三个量化模块。当用户要求"复刻/模仿某人的文笔或写作风格""按 XX 的文风写一段""给一批文章仿写该作者风格""文笔复刻"时使用。也用于为自媒体账号、作家、KOL 建立可复用的文风画像卡。
---

## ⚠️ 首次使用流程（agent 必读，加载本 skill 后第一件事）

**先跑自检，再按提示一次性向用户列清所有缺失项，不要跑一步报一个错，也不要直接开跑。**

```bash
python3 scripts/wenbi.py doctor [--corpus-dir <原文目录>] [--out-dir <训练输出目录>]   # 不调 LLM、不显示 key
```
自检逐项报告 ✓/!/✗：三个 toolkit 路径、DeepSeek API Key、Python 依赖、SPI Personality Atlas、原文语料（篇数/字数/体裁）、
训练产物；最后打印「下一步」。有 ✗ 时退出码 1。环境没装好先 `bash scripts/install.sh && source wenbi.env`。

### 第 1 步：提醒用户提供 DeepSeek API Key（缺 key 时）
用中文这样提醒：
> 文笔复刻要用 DeepSeek API Key 给人格、思维、文风软指标和隐喻打分，生成也要用它。
> 请到 https://platform.deepseek.com/ → API Keys 创建一个 key，然后执行 `export DEEPSEEK_API_KEY=sk-...`，
> 或在 wenbi-replica/.env 里写一行 `DEEPSEEK_API_KEY=sk-...`。（我不会显示或保存你的 key 内容。）

只有用户明确说"先跑最小闭环（只要句长/问句这类统计）"时，才允许无 key 只跑 WFP L1/L2 纯规则硬指标。

### 第 2 步：请用户提供原文（缺语料时）
> 请把你想复刻的那个人的原文发给我：
> - 格式：.txt / .md（一篇一个文件，文件名就是篇目编号），或语料 JSON（`{"items":[{"id":..,"text":..}]}` 或 `{编号: 正文}`）；
> - 数量：至少 5 篇才能建基线，建议 20 篇以上、每篇 300 字以上，越多越稳；
> - 体裁：尽量是同一种体裁（比如全是讲课稿，或全是文章）。混在一起也能跑，但会按体裁分组，篇数少的体裁只做分析。

拿到原文后再跑一次 `doctor --corpus-dir`，把篇数、字数、体裁分布告诉用户；有告警（篇数少、体裁混杂）要明说。

### 第 3 步：训练（建基线 + 画像 + 人设卡）
按下文「完整流程」①–③ 执行（`replicate.py`，完整版先跑 SPI/AoT/L3/L4）。

### 第 4 步：训练完成后，先问清这次要写什么，再生成
**不要直接生成。** 用中文问用户：
> 训练完成了。生成前请告诉我这次要写什么：
> 1. 用途/平台：口播稿 / 公众号文章 / 朋友圈 / 小红书图文 / 知乎回答 / 演讲稿 / 其他（你描述）；
> 2. 字数：大约多少字；
> 3. 题目或主题；
> 4. 读者是谁（可选）；
> 5. 语气、格式或其他要求（可选，比如要不要小标题、要不要 emoji 和话题标签）。
> 预设只是可以改的模板，你写的要求优先。

用户回答后用 `closed_loop.py --purpose ... --topic ... --length ... [--audience/--tone/--format-notes/--extra]` 生成（见 ④）。
**作者风格只来自人设卡 + 闭环偏差，不要自己往 prompt 里加"口语化/少标点"之类的风格要求**；平台/用途的外在要求由用户决定。

### 其他环境项
- 三个 toolkit 路径 `SPI_ROOT` / `AOT_ROOT` / `WFP_ROOT`：install.sh 生成 `wenbi.env`，`source` 即可。
- SPI Personality Atlas（必需，约 1.1GB）：`cd $SPI_ROOT/assets && git clone https://github.com/Wildertrek/survey.git`。
- SPI 3072 维嵌入（可选，约 879MB）：只有 `--spi-mode local` 需要，`bash scripts/install.sh --with-local`。
- 离线冒烟：`python3 scripts/smoke_test.py`（不需要 key、不花钱）。

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

产出：`wfp_baseline_<key>.json`（硬指标基线，主体裁）、`wfp_baseline_<key>__<体裁>.json`（每个够篇数的体裁一份）、
`genre_report.json`（体裁分布与闸门）、`persona_<key>.json` + `三件套人设卡_<key>.md`（含生成指令模板）、生成文回测 Delta。

**体裁闸门（默认 `--genre auto`）**：逐篇识别 讲稿/随笔/新闻/对话/诗歌/其他（规则；`--genre-llm` 对低置信篇再问 LLM）。
主基线只用主体裁篇目；某体裁 < `--min-docs` 篇只做分析不建基线；主体裁占比 <60% 或没有够篇数的体裁 →
人设卡标 **analysis_only（仅供分析）** 并显式告警，此时不要拿它生成/判冒名。回测与闭环自动选同体裁基线，找不到就告警"跨体裁不可靠"。
`--genre off` 恢复旧行为（全部篇目一个基线）。用户声明整份语料同一体裁时用 `--genre-force lecture`（或 essay/…）+ `--genre-force-note "说明"`：跳过自动识别，全部进主基线，genre_report 记 forced=true。

**缓存**：指纹、LLM 调用、基线都按内容哈希缓存（`$WENBI_CACHE_DIR`，默认 `~/.cache/wenbi`；`WENBI_NO_CACHE=1` 关闭），
未变的文本不重算（343 篇建基线：首次 3m13s → 复跑 25s）。

## 完整流程（五步）

### ① 语料归一
对象原文（.txt/.md/语料 JSON）由 `replicate.py --corpus-dir` 读入做 WFP 指纹（doc_id = 文件名 stem）。
**replicate.py 不生成 AoT 块、也不触发任何 LLM 打分**：AoT 语料用 `$AOT_ROOT/scripts/prepare_corpus.py` 生成，SPI 直接逐篇喂 txt。
语料要求：对象本人真实文本，建议 ≥20 篇、单篇 ≥300 字（不足时参考 `references/limits.md` 第 11 条兜底）。

### ② 三件套画像（各模块独立跑，可并行）

**所有脚本都在各自 toolkit 的 scripts/ 目录下，直接调用，不要自己拼格式。**

- **WFP 硬指标基线**：`replicate.py` 自动完成（逐篇指纹 + `field_map.aggregate_baseline` 聚合，<5 篇非空原文直接报错）。
  口径（field_map v4；篇内句长 sd 为样本标准差，v3 基线需重建）：原始词 TTR 不进 Delta（随篇长下降，用 STTR）；我:你、正:负比值 +1 平滑；6 个句长相关特征共享权重。
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

### ④ 生成模仿文（先问清用途/平台、字数、题目）

**生成顺序硬规则（SPI+AoT 先导 · 棱角保留，WFP 表层次尺）**：
1. 从 SPI/AoT 抽出**棱角画像**（高偏置维、尖锐证据、低维硬禁；默认 `config/edge_preserve.yaml` 开启）；
2. 就本题产出完整**篇章框架**（解题思路 + 分节结构 + 允许的尖锐主张 + 禁平滑）——不是条目堆砌，防流水账与中庸平均稿；
3. 再用 WFP 数值与软画像约束**怎么说**——不得主导立意，**不得为文风分磨掉主见**；
4. 闭环主尺=思维依从 + 棱角保留 + 结构连贯（1–7）；次尺=WFP 综合分；回灌先改思路/棱角再改文风；棱角模式默认抬高生成温度，few-shot 优先棱角段。
`closed_loop.py` 默认先跑 `edge_profile.py` + `topic_outline.py`（需 `persona_*.json`）；`--no-edge-preserve` 可关。不要再暗示「文风数值主导生成」。

生成配置由用户在生成时决定（命令行 > `--gen-config` 配置文件 > 用途预设）：

| 字段 | 参数 | 说明 |
|---|---|---|
| 作者身份/职业 | `--role` | 用户自填；进框架与生成（专业照护权威，非局外喷子） |
| 用途/平台 | `--purpose` | 预设：口播稿 / 公众号文章 / 朋友圈 / 小红书图文 / 知乎回答 / 演讲稿 / custom（`config/purpose_presets.yaml`，可编辑） |
| 题目 | `--topic` | 必填（或用 `--extra`/`--task` 自由描述） |
| 字数 | `--length` | 不给则用预设默认 |
| 读者 / 语气 / 格式 | `--audience` `--tone` `--format-notes` | 用户自填，覆盖预设 |
| 其他要求 | `--extra` | 自由文本，优先级最高 |
| 可选格式 | `--with-optional-format` | 例如小红书 emoji/话题标签，只有用户想要才开 |
| 只报告不强制的特征 | `--relax <特征键>` | 预设已为各平台列出与平台形态冲突的特征（如公众号的标点密度） |

- few-shot：`--corpus-dir <原文目录>` 自动从作者本人原文挑 3 段（`--fewshot N`），优先与用途相近的体裁、与题目相关的段落。
- 预览拼出来的写作要求：`python3 scripts/gen_spec.py --purpose 公众号文章 --topic ... --corpus-dir ...`；列预设：`python3 scripts/wenbi.py presets`。
- 也可以按人设卡"四、生成指令模板"手动投喂任意 LLM。

作者风格约束（来自人设卡，与上面的用途/平台要求分开；用途由用户决定，这里不写平台口味）：
- 目标字数 ≥800 字再回测（判别力，见 `references/limits.md` 第 5 条）；
- 硬指标数值约束直接写进 prompt（句长/问句/语气词/隐喻/我:你 命中后 Delta 显著下降）；
- 低分维度要写"少用"设锚；软特征用负向锚 + 中低位目标值，避免顶格过冲（`references/limits.md` 第五节）。

**生成 prompt 的 3 条经验（跨平台通用）**：
1. **低数值特征必须显式写"少用"**：反问 0.2/篇、四字格 3.95/千字这类低值，不写"少用" LLM 默认往中间靠，会过量。写法：`修辞反问 ≤0.3 个/篇（少用）；四字格 ≤5 个/千字（不堆砌）`。
2. **数值密度加 few-shot 体感**："正情 26/千字"这种数字 LLM 没概念，prompt 里抄 1-2 句原文当例子，让它对密度有体感。
3. **短块语料回测跳过整体 Delta**：原文每篇 <500 字时，直接逐项对比关键指标（句长/正情密度/隐喻密度），报告里注明"语料偏短，Delta 参考意义有限"。

**生成闭环（推荐，需 key）**：
```bash
python3 scripts/closed_loop.py --persona-md 三件套人设卡_<key>.md --baseline wfp_baseline_<key>.json \
  --corpus-dir <原文目录> --purpose 公众号文章 --topic "……" --length 1500 --out-dir loop_out \
  [--rounds 3] [--weights ruler_weights.json] [--l3-baseline l3_baseline.json] [--blind-reference <原文目录>]
```
人设卡第四节指令 + 用户写作要求 → 生成 → 多尺子打分 → 偏差最大的层/特征以中文"当前值/原作者值/增减方向"回灌 → 再生成；
最多 3 轮，保留综合分最低的一轮（`best.txt`），`loop_report.md` 列逐轮综合分与分层分。
- `--l3-baseline`：每轮做 L3 软评分（17 维 × 2 次调用），L3 偏差也进回灌。
- 与所选平台形态冲突的特征（预设 relax，如公众号的标点密度、句长起伏）：偏差照常报告，但**不写进修正指令**，报告里单列说明。
- 用途对应的体裁与作者基线体裁不同时：有同体裁基线就自动改用；没有就按主体裁打分，报告注明。
- 给 `--blind-reference` 时对最佳轮再做 LLM 盲测。

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
- **多尺子（推荐）**：自检后用 `$WFP_ROOT/scripts/ruler.py learn` 由留出 vs 对照/异作者的判别力学习分层权重
  （不可判别或与篇长相关的特征自动降权，**只降不删**），`validate_discrimination.py --weights w.json` / `ruler.py score` 出综合分 + 分层分；
  `ruler.py extend --metaphor-dir` 把 LLM 隐喻密度并入基线。报告里要写各层权重占比。
- **LLM 盲测尺**（独立信号）：`$WFP_ROOT/scripts/blind_test.py --reference <原文目录> --real <真文> --fake <生成文>`，P(识破)≈0.5 表示以假乱真。
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
