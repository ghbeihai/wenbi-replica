#!/bin/bash
# 文笔复刻 1.0 一键安装脚本
# 用法：bash scripts/install.sh

set -e

echo "=== 文笔复刻 1.0 一键安装 ==="
echo ""

# 1. 配置环境变量
echo "【1/5】配置环境变量..."
export SPI_ROOT="${SPI_ROOT:-$HOME/Documents/spi-toolkit}"
export AOT_ROOT="${AOT_ROOT:-$HOME/Documents/aot-toolkit}"
export WFP_ROOT="${WFP_ROOT:-$HOME/Documents/wfp-toolkit}"

echo "  SPI_ROOT: $SPI_ROOT"
echo "  AOT_ROOT: $AOT_ROOT"
echo "  WFP_ROOT: $WFP_ROOT"
echo ""

# 2. Python 依赖
echo "【2/5】安装 Python 依赖..."
pip install jieba pyyaml numpy openai python-dotenv sentence-transformers 2>/dev/null || pip3 install jieba pyyaml numpy openai python-dotenv sentence-transformers
echo "  ✓ Python 依赖安装完成"
echo ""

# 3. SPI 人格量化包
echo "【3/5】安装 SPI 人格量化包..."
cd "$SPI_ROOT"
pip install -e . 2>/dev/null || pip3 install -e .
echo "  ✓ SPI 安装完成"
echo ""

# 4. Personality Atlas 数据（1.1GB）
echo "【4/5】下载 Personality Atlas 数据（约 1.1GB）..."
if [ ! -d "$SPI_ROOT/assets/survey" ]; then
    cd "$SPI_ROOT/assets"
    git clone https://github.com/Wildertrek/survey.git
    echo "  ✓ Personality Atlas 下载完成"
else
    echo "  ✓ Personality Atlas 已存在，跳过"
fi
echo ""

# 5. 3072 维嵌入数据（879MB）
echo "【5/5】下载 3072 维嵌入数据（约 879MB）..."
if [ ! -d "$SPI_ROOT/assets/hf-3072/Embeddings_3072" ]; then
    pip install huggingface_hub 2>/dev/null || pip3 install huggingface_hub
    huggingface-cli download Wildertrek/personality-atlas-3072 --repo-type dataset --local-dir "$SPI_ROOT/assets/hf-3072"
    echo "  ✓ 3072 维嵌入下载完成"
else
    echo "  ✓ 3072 维嵌入已存在，跳过"
fi
echo ""

echo "=== 安装完成 ==="
echo ""
echo "下一步："
echo "  1. 配置 DeepSeek API Key: export DEEPSEEK_API_KEY=sk-..."
echo "  2. 准备对标文章（建议 20 篇以上、每篇 300 字以上）"
echo "  3. 运行: python3 scripts/replicate.py --name <对象名> --corpus-dir <原文目录>"
