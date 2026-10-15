#!/usr/bin/env bash
# 文笔复刻 一键安装脚本
#
# 用法：bash scripts/install.sh [--venv DIR] [--system] [--with-local] [--persist]
#   --venv DIR    把依赖装进指定虚拟环境（默认：已激活的 venv；未激活时自动建 <本仓>/.venv）
#   --system      不建 venv，直接 pip install --user（PEP 668 系统 Python 可能拒绝）
#   --with-local  额外安装 SPI 本地离线映射（sentence-transformers + 879MB 3072 维嵌入）
#   --persist     把环境变量写进 ~/.bashrc（默认只生成 <本仓>/wenbi.env，需自己 source）
#
# 兄弟仓库位置：优先用已设置的 SPI_ROOT / AOT_ROOT / WFP_ROOT；否则依次找
#   <本仓上级目录>/{spi,aot,wfp}-toolkit、$HOME/toolkits/...、$HOME/Documents/...
set -Eeuo pipefail
trap 'echo "✗ 安装失败（第 $LINENO 行：$BASH_COMMAND）。上面是完整报错输出。" >&2' ERR

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=""; SYSTEM=0; WITH_LOCAL=0; PERSIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --venv) VENV="$2"; shift 2 ;;
    --system) SYSTEM=1; shift ;;
    --with-local) WITH_LOCAL=1; shift ;;
    --persist) PERSIST=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

echo "=== 文笔复刻 一键安装 ==="

# 1. 定位兄弟仓库
echo "【1/6】定位 spi / aot / wfp 三个工具仓库..."
find_root() {  # $1=变量名 $2=目录名 $3=标志文件
  local cur="${!1:-}"
  if [ -n "$cur" ]; then echo "$cur"; return; fi
  for base in "$(dirname "$REPO")" "$HOME/toolkits" "$HOME/Documents"; do
    if [ -e "$base/$2/$3" ]; then echo "$base/$2"; return; fi
  done
  echo ""
}
SPI_ROOT="$(find_root SPI_ROOT spi-toolkit pyproject.toml)"
AOT_ROOT="$(find_root AOT_ROOT aot-toolkit scripts/score_dimensions.py)"
WFP_ROOT="$(find_root WFP_ROOT wfp-toolkit scripts/extract_hard_metrics.py)"
missing=0
for pair in "SPI_ROOT:$SPI_ROOT:pyproject.toml:spi-toolkit" \
            "AOT_ROOT:$AOT_ROOT:scripts/score_dimensions.py:aot-toolkit" \
            "WFP_ROOT:$WFP_ROOT:scripts/field_map.py:wfp-toolkit"; do
  IFS=: read -r var path flag name <<<"$pair"
  if [ -z "$path" ] || [ ! -e "$path/$flag" ]; then
    echo "  ✗ $var 未找到 $name（${path:-未设置}，缺 $flag）" >&2
    echo "    请 git clone 到 $(dirname "$REPO")/$name，或 export $var=<路径> 后重跑" >&2
    missing=1
  else
    echo "  ✓ $var=$path"
  fi
done
[ "$missing" = 0 ] || exit 1

# 2. Python 环境
echo "【2/6】准备 Python 环境..."
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "  ✗ 找不到 $PY" >&2; exit 1; }
in_venv="$("$PY" -c 'import sys; print(int(sys.prefix != sys.base_prefix))')"
PIP_FLAGS=()
if [ -n "$VENV" ] || { [ "$in_venv" = 0 ] && [ "$SYSTEM" = 0 ]; }; then
  VENV="${VENV:-$REPO/.venv}"
  if [ ! -x "$VENV/bin/python" ]; then
    echo "  创建虚拟环境 $VENV"
    "$PY" -m venv "$VENV"
  fi
  PY="$VENV/bin/python"
  echo "  ✓ 使用虚拟环境 $VENV（之后运行脚本请用 $PY 或先 source $VENV/bin/activate）"
elif [ "$in_venv" = 1 ]; then
  echo "  ✓ 使用已激活的虚拟环境 $("$PY" -c 'import sys; print(sys.prefix)')"
else
  PIP_FLAGS=(--user)
  echo "  ⚠ --system：pip install --user（PEP 668 的系统 Python 会拒绝，届时请去掉 --system 用 venv）"
fi
"$PY" -m pip --version >/dev/null || { echo "  ✗ $PY 没有 pip（Debian/Ubuntu：apt install python3-venv python3-pip）" >&2; exit 1; }

# 3. 依赖
echo "【3/6】安装 Python 依赖..."
DEPS=(jieba pyyaml numpy pandas scikit-learn openai python-dotenv)
"$PY" -m pip install "${PIP_FLAGS[@]}" -q --upgrade pip
"$PY" -m pip install "${PIP_FLAGS[@]}" "${DEPS[@]}"
"$PY" -m pip install "${PIP_FLAGS[@]}" -e "$SPI_ROOT"
if [ "$WITH_LOCAL" = 1 ]; then
  "$PY" -m pip install "${PIP_FLAGS[@]}" -e "$SPI_ROOT[spi-local]" huggingface_hub
fi
echo "  ✓ 依赖安装完成"

# 4. Personality Atlas（SPI 因子链，profile 必需，约 1.1GB）
echo "【4/6】Personality Atlas 数据..."
if [ ! -d "$SPI_ROOT/assets/survey" ]; then
  mkdir -p "$SPI_ROOT/assets"
  git clone https://github.com/Wildertrek/survey.git "$SPI_ROOT/assets/survey"
  echo "  ✓ 下载完成"
else
  echo "  ✓ 已存在，跳过"
fi

# 5. 3072 维嵌入（仅 --with-local）
echo "【5/6】3072 维嵌入（SPI 本地离线模式）..."
if [ "$WITH_LOCAL" = 1 ]; then
  if [ ! -d "$SPI_ROOT/assets/hf-3072/Embeddings_3072" ]; then
    "$(dirname "$PY")/huggingface-cli" download Wildertrek/personality-atlas-3072 --repo-type dataset \
      --local-dir "$SPI_ROOT/assets/hf-3072"
  fi
  echo "  ✓ 就绪"
else
  echo "  - 跳过（默认 LLM 判聚类不需要；要离线模式加 --with-local）"
fi

# 6. 环境变量（持久化）+ 自检
echo "【6/6】写环境变量并自检..."
ENV_FILE="$REPO/wenbi.env"
{
  echo "# 由 scripts/install.sh 生成：source $ENV_FILE"
  echo "export SPI_ROOT=\"$SPI_ROOT\""
  echo "export AOT_ROOT=\"$AOT_ROOT\""
  echo "export WFP_ROOT=\"$WFP_ROOT\""
  [ -n "$VENV" ] && echo "source \"$VENV/bin/activate\""
  echo "# DEEPSEEK_API_KEY 请自行 export，或写入任一仓库的 .env（不要提交到 git）"
} > "$ENV_FILE"
if [ "$PERSIST" = 1 ]; then
  line="[ -f \"$ENV_FILE\" ] && source \"$ENV_FILE\"  # wenbi-replica"
  grep -qF "$ENV_FILE" "$HOME/.bashrc" 2>/dev/null || echo "$line" >> "$HOME/.bashrc"
  echo "  ✓ 已写入 ~/.bashrc"
fi
export SPI_ROOT AOT_ROOT WFP_ROOT
"$PY" - <<'PYCHK'
import importlib.util, sys
bad = [m for m in ("jieba", "yaml", "numpy", "pandas", "sklearn", "openai", "dotenv", "spi_quant")
       if importlib.util.find_spec(m) is None]
if bad:
    sys.exit(f"  ✗ 以下模块导入失败：{bad}")
print("  ✓ 依赖导入正常")
PYCHK
"$PY" "$WFP_ROOT/scripts/extract_hard_metrics.py" -h >/dev/null
"$PY" -m spi_quant.cli profile -h >/dev/null
echo "  ✓ 脚本自检通过"

echo ""
echo "=== 安装完成 ==="
echo "下一步："
echo "  1. source $ENV_FILE        （每个新终端都要；或重跑时加 --persist）"
echo "  2. export DEEPSEEK_API_KEY=sk-...   （只有 L3/SPI/AoT 打分需要；WFP 硬指标不需要）"
echo "  3. $PY $REPO/scripts/smoke_test.py   （离线冒烟测试，不花钱）"
echo "  4. $PY $REPO/scripts/wenbi.py doctor --corpus-dir <原文目录>   （检查 key / 语料 / 下一步）"
echo "  5. $PY $REPO/scripts/replicate.py --name <对象名> --corpus-dir <原文目录>   （训练：基线 + 人设卡）"
echo "  6. 训练完成后确定 用途/平台、字数、题目 → $PY $REPO/scripts/closed_loop.py ...（见 SKILL.md ④）"
echo ""
echo "提醒：需要 DeepSeek API Key（https://platform.deepseek.com/），以及要复刻的那个人的原文"
echo "      （.txt/.md 一篇一文件或语料 JSON；建议 ≥20 篇、每篇 ≥300 字、尽量同一体裁）。"
