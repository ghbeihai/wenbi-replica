# wenbi-replica · 文笔复刻 1.0

给定某人一批真实原文，产出该人风格的模仿文与可验证的画像报告。

## 架构

```
wenbi-replica（本仓）= 编排层：语料归一 → 三件套画像 → 人设卡 → 模仿文 → 回测
├── spi-toolkit   人格底色（他是谁）
├── aot-toolkit   思维模式（他怎么想）
└──  v0.1.0  文风指纹（他怎么说）
```

- SPI + AoT = **「里」**，解释作者内核
- WFP = **「表」**，数值化表层文风

## 快速开始

```bash
# 1. 【第一优先】设置 DeepSeek API Key
#    没有 key，人格/思维/隐喻打分全部跑不了（只有 L1/L2 纯规则硬指标能用）
#    到 https://platform.deepseek.com/ 创建 key，然后：
export DEEPSEEK_API_KEY=sk-你的key

# 2. 克隆三个 toolkit 并设置路径环境变量
export SPI_ROOT=/path/to/spi-toolkit
export AOT_ROOT=/path/to/aot-toolkit
export WFP_ROOT=/path/to/wfp-toolkit

# 3. 安装依赖
pip install jieba pyyaml numpy openai
# SPI 作为可编辑包安装（提供 spi-quant CLI）
cd $SPI_ROOT && pip install -e .

# 4. 最小闭环（仅 WFP L1/L2 硬指标，不调 LLM）
python3 scripts/replicate.py --name alice \
  --corpus-dir /path/to/alice_原文 \
  --out-dir ./out

# 5. 完整版（SPI 人格 + AoT 思维 + WFP L3/L4，全部调 DeepSeek）
#    先跑各 toolkit 的打分脚本产出画像，再用 --spi-clusters / --aot-profiles 传入
```

## 产出

- `persona_<key>.json` — 结构化人设卡（程序消费）
- `三件套人设卡_<key>.md` — 人读版 + 可直接投喂的生成指令模板
- `wfp_baseline_<key>.json` — 文风指纹基线
- 生成文回测 Delta

## 环境变量

| 变量 | 说明 |
|---|---|
| `WFP_ROOT` |  v0.1.0根目录 |
| `SPI_ROOT` | spi-toolkit 根目录 |
| `AoT_ROOT` | aot-toolkit 根目录 |
| `DEEPSEEK_API_KEY` | LLM 打分 key（无 key 自动进入模拟模式） |

## 不内置什么

- **违禁词表**：使用方按自己行业（医疗/金融/教育…）自备，生成环节自行过滤。
- **示例人物语料 / 旧基线**：每次使用都从当次输入的原文重新提取基线，不携带任何测试人物数据。

## 已知局限

见 `references/limits.md`（精度边界、判别失效条件、语料要求、生成端校准结论）。

## License

MIT

## 版本号规则

每次 push 前更新 VERSION 文件：

| 改动类型 | 版本号变化 | 示例 |
|---|---|---|
| 修 bug / 改文档 | PATCH +1 | 1.0.0 → 1.0.1 |
| 新增功能 / 加脚本 | MINOR +1 | 1.0.0 → 1.1.0 |
| 流水线大改 / 换框架 | MAJOR +1 | 1.0.0 → 2.0.0 |

当前版本见根目录 `VERSION` 文件。

## 配套 toolkit 版本

当前主仓 v1.0.0 配套以下 toolkit 版本：

| 仓库 | 版本 | 说明 |
|---|---|---|
| spi-toolkit | v0.1.1 | 人格量化（32 因子 × 15 聚类） |
| aot-toolkit | v0.1.1 | 思维模式（25 维） |
|  v0.1.0| v0.1.0 | 文风指纹（硬指标 + L3 软评分 + L4 隐喻） |

版本错位可能导致脚本调用失败，升级时请同步更新。
