# wenbi-replica · 文笔复刻

**给定某人一批真实原文，量化还原他的写作风格，并生成风格一致的新文案。**

不是简单的"模仿语气"，而是从三个维度拆解一个人的文风：

| 维度 | 模块 | 测什么 |
|---|---|---|
| **他是谁** | SPI（人格量化） | 32 个人格因子 × 15 个语义簇 → 情感温暖/行动导向/宜人性/神经质… |
| **他怎么想** | AoT（思维模式） | 25 个思维维度 → 判断快/慢、论证链长短、是否写反例、是否自我怀疑… |
| **他怎么说** | WFP（文风指纹） | 句长分布、问句频率、语气词密度、隐喻根域、叙事修辞软评分… |

SPI + AoT 是「里」，解释作者内核；WFP 是「表」，数值化表层文风。三层合起来，才能从"像"到"是"。

---

## 流水线

```
原文语料
  ↓
① 语料归一（自动）
  ↓
② 三件套画像
  ├── SPI 人格量化（需 DeepSeek key）
  ├── AoT 思维模式（需 DeepSeek key）
  └── WFP 文风指纹（L1/L2 纯规则硬指标 + L3/L4 LLM 软评分）
  ↓
③ 人设卡合成
  → 人格底色 + 思维模式 + 文风数值约束 + 生成指令模板
  ↓
④ 生成模仿文（投喂给任意 LLM）
  ↓
⑤ 回测校验
  ├── Delta：27 个每千字/比例特征的加权平均 |z|（field_map v3，排除篇幅量、原始 TTR，句长簇降权）
  └── 判别力自检两关（留出 vs 对照 ≥1.5、留出 vs 异作者 ≥1.2）
  ↓
迭代闭环：偏项自动写回 prompt → 再生成，最多 3 轮
```

---

## 快速开始

```bash
# 1. 设置 DeepSeek API Key
export DEEPSEEK_API_KEY=sk-你的key

# 2. 克隆四个仓库，设置路径
git clone https://github.com/ghbeihai/wenbi-replica.git
git clone https://github.com/ghbeihai/spi-toolkit.git
git clone https://github.com/ghbeihai/aot-toolkit.git
git clone https://github.com/ghbeihai/wfp-toolkit.git

# 3. 一键安装：自动找同级目录的三个 toolkit、建/用 venv、装依赖 + Personality Atlas（1.1G），生成 wenbi.env
#    （--with-local 额外装 SPI 离线映射的 3072 维嵌入 879M；--persist 写入 ~/.bashrc）
cd wenbi-replica && bash scripts/install.sh
source wenbi.env
python3 scripts/smoke_test.py      # 离线冒烟测试（mock LLM，不需要 key）
python3 scripts/wenbi.py doctor --corpus-dir ./alice_原文   # 自检：key / toolkit / 依赖 / 原文篇数与体裁 / 下一步
#   需要：DeepSeek API Key（https://platform.deepseek.com/，export DEEPSEEK_API_KEY=sk-... 或写进 .env）
#         要复刻的那个人的原文（.txt/.md 一篇一文件或语料 JSON；建议 ≥20 篇、每篇 ≥300 字、尽量同一体裁）

# 4. 最小闭环（仅 WFP 硬指标，不调 LLM）
python3 scripts/replicate.py --name alice \
  --corpus-dir ./alice_原文 \
  --out-dir ./out

# 5. 完整版（SPI + AoT + WFP 全跑）：先按 SKILL.md ② 跑各 toolkit 的打分脚本，再合成
python3 scripts/replicate.py --name alice --wfp-baseline ./out/wfp_baseline_alice.json \
  --spi-clusters spi_cluster_all.json --aot-profiles people_profiles.json --aot-person 爱丽丝 \
  --l3-baseline l3_baseline.json --out-dir ./out --backtest 生成文.txt

# 6. 训练完成后先定 用途/平台、字数、题目（预设：python3 scripts/wenbi.py presets），再闭环生成
#    （生成 → 多尺子打分 → 分层偏差回灌 → 再生成，≤3 轮，保留最佳；与平台形态冲突的偏差只报告不强制改）
python3 scripts/closed_loop.py --persona-md ./out/三件套人设卡_alice.md \
  --baseline ./out/wfp_baseline_alice.json --corpus-dir ./alice_原文 \
  --purpose 公众号文章 --topic "谈读书" --length 1500 [--audience ..] [--tone ..] [--extra ..] --out-dir ./loop
```

---

## 产出

| 文件 | 说明 |
|---|---|
| `persona_<name>.json` | 结构化人设卡（程序消费） |
| `三件套人设卡_<name>.md` | 人读版 + 可直接投喂的生成指令模板 |
| `wfp_baseline_<name>.json` | 文风指纹基线（主体裁；含 avg_chars、doc_ids、field_map_version、genre、input_hash） |
| `wfp_baseline_<name>__<体裁>.json` | 每个达到最少篇数的体裁一份基线（回测/闭环自动选同体裁） |
| `genre_report.json` | 逐篇体裁、分组、闸门状态（ok / mixed / analysis_only）与告警 |
| `config/purpose_presets.yaml` | 用途/平台预设（可编辑模板：默认字数、格式、few-shot 优先体裁、只报告不强制的特征） |
| `loop_out/` | `closed_loop.py`：逐轮生成文与指纹、`loop_report.{json,md}`、`best.txt` |
| `fingerprints/` | 逐篇指纹 |
| `_backtest_fp.json` | `--backtest` 时生成文指纹；Delta 打印在终端 |

---

## 使用场景

- **自媒体账号风格统一**：给主理人建文风画像，团队写稿不跑偏
- **KOL/作家代写**：还原作者语气，写出来的东西像本人
- **品牌内容调性**：把品牌创始人的"话风"量化成 prompt，新员工照着写
- **教育/培训**：还原优秀教师的讲课风格，辅助备课

---

## 未内置

- **违禁词表**：按自己行业（医疗/金融/教育…）自备，生成环节自行过滤
- **测试人物语料**：每次使用都从当次输入的原文重新提取基线，不携带任何旧数据

---

## 已知局限

见 `references/limits.md`（精度边界、判别失效条件、语料要求、生成端校准结论）。

---

## License

MIT
