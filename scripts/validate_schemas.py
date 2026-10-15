#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中间文件 JSON schema 校验：检查各环节输出是否符合预期格式（规则定义在 schemas.py，逐项全量检查）。

用法：
  python3 scripts/validate_schemas.py --spi spi_cluster_all.json --aot people_profiles.json \
      --wfp wfp_baseline.json --l3 l3_baseline.json

WFP 基线额外检查（需 WFP_ROOT）：field_map.check_baseline（篇数 ≥5、可用特征 ≥10），即 Delta 是否有意义。
退出码：0 全部通过；1 有错误。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schemas  # noqa: E402


def _load(path: str):
    if not Path(path).exists():
        return None, [f"文件不存在: {path}"]
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), []
    except Exception as e:  # noqa: BLE001
        return None, [f"JSON 解析失败: {e}"]


def validate_spi(path: str) -> list:
    data, err = _load(path)
    return err or schemas.check(data, schemas.SPI_CLUSTER_SCHEMA)


def validate_aot(path: str) -> list:
    data, err = _load(path)
    return err or schemas.check(data, schemas.AOT_PROFILES_SCHEMA)


def validate_l3(path: str) -> list:
    data, err = _load(path)
    if err:
        return err
    errors = schemas.check(data, schemas.L3_BASELINE_SCHEMA)
    if not errors:
        for k, v in data["baseline"].items():
            if not (1 <= v["mean"] <= 7):
                errors.append(f"baseline['{k}'].mean={v['mean']} 不在 1-7")
    return errors


def validate_wfp(path: str) -> list:
    data, err = _load(path)
    if err:
        return err
    errors = schemas.check(data, schemas.WFP_BASELINE_SCHEMA)
    if errors:
        return errors
    wfp = os.environ.get("WFP_ROOT")
    if not wfp:
        print("  [提示] 未设置 WFP_ROOT，跳过退化基线检查（check_baseline）", file=sys.stderr)
        return errors
    sys.path.insert(0, os.path.join(wfp, "scripts"))
    try:
        from field_map import check_baseline, DegenerateBaseline
    except ImportError:
        print("  [提示] wfp-toolkit 的 field_map 没有 check_baseline（过旧），跳过退化检查", file=sys.stderr)
        return errors
    try:
        check_baseline(data)
    except DegenerateBaseline as e:
        errors.append(f"退化基线：{e}")
    if data.get("missing_features"):
        print(f"  [提示] 基线缺 Delta 特征：{data['missing_features']}", file=sys.stderr)
    return errors


def main():
    ap = argparse.ArgumentParser(description="中间文件 schema 校验")
    ap.add_argument("--spi", help="SPI 聚类画像 JSON（aggregate_spi_profiles 输出）")
    ap.add_argument("--aot", help="AoT 人物画像 JSON（aggregate_profiles 输出）")
    ap.add_argument("--wfp", help="WFP 硬指标基线 JSON")
    ap.add_argument("--l3", help="L3 软评分基线 JSON（build_l3_baseline / score_stylistics --l3-baseline-out 输出）")
    args = ap.parse_args()
    if not any((args.spi, args.aot, args.wfp, args.l3)):
        ap.error("至少给一个 --spi / --aot / --wfp / --l3")

    all_errors = []
    for label, path, fn in (("SPI", args.spi, validate_spi), ("AoT", args.aot, validate_aot),
                            ("WFP", args.wfp, validate_wfp), ("L3", args.l3, validate_l3)):
        if not path:
            continue
        errors = fn(path)
        print(f"{label}: {'✓ 通过' if not errors else '✗ 错误'}")
        for e in errors:
            print(f"  - {e}")
        all_errors.extend(errors)

    if all_errors:
        print(f"\n总计 {len(all_errors)} 个错误，请修复后再继续。")
        sys.exit(1)
    print("\n全部通过。")


if __name__ == "__main__":
    main()
