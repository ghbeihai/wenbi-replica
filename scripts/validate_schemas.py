#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中间文件 JSON schema 校验：检查各环节输出是否符合预期格式。

用法：
  python3 scripts/validate_schemas.py --spi spi_cluster_all.json --aot people_profiles.json --wfp wfp_baseline.json
"""
import argparse
import json
import sys
from pathlib import Path


def validate_spi(path: str) -> list:
    """校验 SPI 聚类画像"""
    errors = []
    if not Path(path).exists():
        return [f"文件不存在: {path}"]
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return [f"JSON 解析失败: {e}"]

    if "cluster_summary" not in data:
        errors.append("缺少 cluster_summary 字段")
    elif not data["cluster_summary"]:
        errors.append("cluster_summary 为空")
    else:
        for i, cs in enumerate(data["cluster_summary"][:3]):
            for field in ["cluster", "label", "n_first", "n_top5", "avg_relevance"]:
                if field not in cs:
                    errors.append(f"cluster_summary[{i}] 缺少字段: {field}")
    return errors


def validate_aot(path: str) -> list:
    """校验 AoT 人物画像"""
    errors = []
    if not Path(path).exists():
        return [f"文件不存在: {path}"]
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return [f"JSON 解析失败: {e}"]

    if not data:
        errors.append("文件为空")
    else:
        for pid, profile in list(data.items())[:2]:
            if "top5" not in profile:
                errors.append(f"{pid} 缺少 top5 字段")
            elif not profile["top5"]:
                errors.append(f"{pid} top5 为空")
    return errors


def validate_wfp(path: str) -> list:
    """校验 WFP 基线"""
    errors = []
    if not Path(path).exists():
        return [f"文件不存在: {path}"]
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return [f"JSON 解析失败: {e}"]

    if "baseline" not in data:
        errors.append("缺少 baseline 字段")
    elif not data["baseline"]:
        errors.append("baseline 为空")

    if "avg_chars" not in data:
        errors.append("缺少 avg_chars 字段（按篇指标换算需要）")

    return errors


def main():
    ap = argparse.ArgumentParser(description="中间文件 schema 校验")
    ap.add_argument("--spi", help="SPI 聚类画像 JSON")
    ap.add_argument("--aot", help="AoT 人物画像 JSON")
    ap.add_argument("--wfp", help="WFP 基线 JSON")
    args = ap.parse_args()

    all_errors = []

    if args.spi:
        errors = validate_spi(args.spi)
        print(f"SPI: {'✓ 通过' if not errors else '✗ 错误'}")
        for e in errors:
            print(f"  - {e}")
        all_errors.extend(errors)

    if args.aot:
        errors = validate_aot(args.aot)
        print(f"AoT: {'✓ 通过' if not errors else '✗ 错误'}")
        for e in errors:
            print(f"  - {e}")
        all_errors.extend(errors)

    if args.wfp:
        errors = validate_wfp(args.wfp)
        print(f"WFP: {'✓ 通过' if not errors else '✗ 错误'}")
        for e in errors:
            print(f"  - {e}")
        all_errors.extend(errors)

    if all_errors:
        print(f"\n总计 {len(all_errors)} 个错误，请修复后再继续。")
        sys.exit(1)
    else:
        print("\n全部通过。")


if __name__ == "__main__":
    main()
