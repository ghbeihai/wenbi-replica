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
  ├── 每千字归一化 Delta（排除篇幅偏差）
  ├── Burrows Delta（高频虚词词频分布，真正区分作者）
  └── 判别力自检（验证尺子准不准）
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

export SPI_ROOT=./spi-toolkit
export AOT_ROOT=./aot-toolkit
export WFP_ROOT=./wfp-toolkit

# 3. 一键安装（Python 依赖 + Personality Atlas 1.1G + 3072 维嵌入 879M）
bash scripts/install.sh

# 4. 最小闭环（仅 WFP 硬指标，不调 LLM）
python3 scripts/replicate.py --name alice \
  --corpus-dir ./alice_原文 \
  --out-dir ./out

# 5. 完整版（SPI + AoT + WFP 全跑）
#    先跑各 toolkit 的打分脚本，再把结果传给 replicate.py
```

---

## 产出

| 文件 | 说明 |
|---|---|
| `persona_<name>.json` | 结构化人设卡（程序消费） |
| `三件套人设卡_<name>.md` | 人读版 + 可直接投喂的生成指令模板 |
| `wfp_baseline_<name>.json` | 文风指纹基线（含 avg_chars） |
| `回测结果.json` | Delta、判别比、逐项偏离 |

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
