#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成迭代闭环：回测 → 找出偏项 → 生成修正 prompt → 再生成，最多 3 轮。

用法：
  python3 scripts/iterative_generate.py \
    --baseline <基线.json> \
    --gen-fp <生成文指纹.json> \
    --original-prompt <原始生成prompt.txt> \
    --round 1 [--json]

输出：偏项分析 + 修正后的 prompt（喂给 LLM 生成下一版）
"""
import argparse
import json
import os
import sys
from pathlib import Path

_WFP = os.environ.get("WFP_ROOT", "")
if _WFP:
    sys.path.insert(0, os.path.join(_WFP, "scripts"))
try:
    from field_map import flatten as _flatten, baseline_stat as _bstat
except ImportError:  # 没有 WFP_ROOT / 旧版 wfp：退回原始字段逐项对比
    _flatten = _bstat = None
    print("[警告] 未找到 $WFP_ROOT/scripts/field_map.py（WFP_ROOT 未设置或 wfp-toolkit 过旧）："
          "退回原始字段逐项对比，与回测 Delta 口径不一致。请 export WFP_ROOT=<wfp-toolkit 路径>。", file=sys.stderr)
try:
    from field_map import label as _label
except ImportError:
    def _label(k):
        return k


def find_top_deviations(gen_fp: dict, baseline: dict, top_n: int = 5) -> list:
    """找出偏得最多的 top_n 项。有 field_map 时与回测同口径（每千字、字典求和、排除篇幅量）。"""
    bl = baseline.get("baseline", baseline)
    deviations = []
    vec = _flatten(gen_fp) if _flatten else gen_fp

    for k, v in vec.items():
        if not isinstance(v, (int, float)):
            continue
        if _bstat:
            st = _bstat(baseline, k)
            if not st:
                continue
            mean, sd = st
        elif k in bl and isinstance(bl[k], dict):
            mean, sd = bl[k].get("mean", 0), bl[k].get("sd", 0)
        else:
            continue

        if sd > 0:
            z = abs(v - mean) / sd
            deviations.append({
                "feature": k,
                "label": _label(k),
                "gen_value": round(v, 2),
                "target_mean": round(mean, 2),
                "z_score": round(z, 2),
                "direction": "偏高" if v > mean else "偏低",
            })

    deviations.sort(key=lambda x: -x["z_score"])
    return deviations[:top_n]


def build_correction_prompt(original_prompt: str, deviations: list) -> str:
    """根据偏项生成修正 prompt"""
    corrections = []
    for d in deviations:
        corrections.append(
            f"- {d.get('label') or d['feature']}：{d['direction']}（当前 {d['gen_value']}，目标约 {d['target_mean']}），"
            f"请{'减少' if d['direction'] == '偏高' else '增加'}"
        )

    correction_block = "\n".join(corrections)

    return f"""{original_prompt}

【本轮修正要求】
上一版生成文在以下 {len(deviations)} 项偏离目标，请调整：
{correction_block}

注意：只调整上述偏离项，其他风格保持不变。"""


def main():
    ap = argparse.ArgumentParser(description="生成迭代闭环")
    ap.add_argument("--baseline", required=True, help="基线 JSON")
    ap.add_argument("--gen-fp", required=True, help="当前生成文指纹 JSON")
    ap.add_argument("--original-prompt", required=True, help="原始生成 prompt 文件")
    ap.add_argument("--round", type=int, default=1, help="当前第几轮（1-3）")
    ap.add_argument("--top", type=int, default=5, help="找出 top N 偏项")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.round > 3:
        print("最多迭代 3 轮，请保留当前最优版本。", file=sys.stderr)
        sys.exit(1)

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    gen_fp = json.loads(Path(args.gen_fp).read_text(encoding="utf-8"))
    original_prompt = Path(args.original_prompt).read_text(encoding="utf-8")

    if args.round < 1:
        print("--round 必须 ≥1", file=sys.stderr)
        sys.exit(1)
    deviations = find_top_deviations(gen_fp, baseline, args.top)
    if not deviations:
        print("[警告] 没有可对比的特征（基线与指纹口径不匹配？），修正 prompt 与原 prompt 相同", file=sys.stderr)
    corrected_prompt = build_correction_prompt(original_prompt, deviations)

    result = {
        "round": args.round,
        "top_deviations": deviations,
        "corrected_prompt": corrected_prompt,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"=== 第 {args.round} 轮迭代 ===")
    print(f"\n偏得最多的 {len(deviations)} 项：")
    for d in deviations:
        print(f"  {d['label']}（{d['feature']}）: {d['direction']}（{d['gen_value']} vs 目标 {d['target_mean']}，z={d['z_score']}）")

    print("\n修正后的 prompt（喂给 LLM 生成下一版）：")
    print("-" * 50)
    print(corrected_prompt)
    print("-" * 50)


if __name__ == "__main__":
    main()
