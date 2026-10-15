#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻：中间文件 JSON Schema 定义 + 校验函数。

所有脚本的输入输出必须符合这里的 schema，不符合就报错退出。
"""
import sys
from typing import Any


# WFP 基线 JSON 必须包含的字段
WFP_BASELINE_SCHEMA = {
    "required_top": ["n_docs", "baseline", "avg_chars"],
    "baseline_type": dict,
}

# SPI 聚类画像 JSON 必须包含的字段
SPI_CLUSTER_SCHEMA = {
    "required_top": ["cluster_summary"],
    "cluster_summary_type": list,
    "cluster_item_fields": ["cluster", "label", "n_first", "n_top5", "avg_relevance"],
}

# AoT 人物画像 JSON 必须包含的字段
AOT_PROFILES_SCHEMA = {
    "is_dict": True,
    "person_fields": ["name", "n_dims", "top5"],
    "top5_item_fields": ["dim", "dim_name", "mean", "evidence"],
}

# L3 基线 JSON 必须包含的字段
L3_BASELINE_SCHEMA = {
    "required_top": ["n_docs", "baseline"],
    "baseline_type": dict,
}


def validate(data: Any, schema: dict, name: str) -> None:
    """校验数据是否符合 schema，不符合直接报错退出。"""
    errors = []

    # 顶层必填字段
    for field in schema.get("required_top", []):
        if field not in data:
            errors.append(f"缺顶层字段 '{field}'")

    # 基线类型
    if "baseline_type" in schema and "baseline" in data:
        if not isinstance(data["baseline"], schema["baseline_type"]):
            errors.append(f"baseline 字段类型应该是 {schema['baseline_type'].__name__}，实际是 {type(data['baseline']).__name__}")

    # cluster_summary 类型
    if "cluster_summary_type" in schema and "cluster_summary" in data:
        cs = data["cluster_summary"]
        if not isinstance(cs, schema["cluster_summary_type"]):
            errors.append("cluster_summary 应该是列表")
        elif not cs:
            errors.append("cluster_summary 为空")
        else:
            # 每项必须有指定字段
            required = schema.get("cluster_item_fields", [])
            for i, item in enumerate(cs[:3]):
                if not isinstance(item, dict):
                    errors.append(f"cluster_summary[{i}] 不是字典")
                    continue
                for f in required:
                    if f not in item:
                        errors.append(f"cluster_summary[{i}] 缺字段 '{f}'")

    # AoT 人物画像
    if schema.get("is_dict"):
        if not isinstance(data, dict):
            errors.append("数据应该是字典 {pid: profile}")
        elif not data:
            errors.append("人物画像为空")
        else:
            for pid, profile in list(data.items())[:2]:
                for f in schema.get("person_fields", []):
                    if f not in profile:
                        errors.append(f"{pid} 缺字段 '{f}'")
                # top5 每项校验
                top5 = profile.get("top5", [])
                if isinstance(top5, list):
                    for i, item in enumerate(top5[:2]):
                        for f in schema.get("top5_item_fields", []):
                            if f not in item:
                                errors.append(f"{pid}.top5[{i}] 缺字段 '{f}'")

    if errors:
        print(f"\n[{name}] schema 校验失败：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\n请检查上游脚本是否跑通，不要静默跳过。", file=sys.stderr)
        sys.exit(1)


def validate_wfp_baseline(data: dict) -> None:
    validate(data, WFP_BASELINE_SCHEMA, "WFP 基线")


def validate_spi_clusters(data: dict) -> None:
    validate(data, SPI_CLUSTER_SCHEMA, "SPI 聚类画像")


def validate_aot_profiles(data: dict) -> None:
    validate(data, AOT_PROFILES_SCHEMA, "AoT 人物画像")


def validate_l3_baseline(data: dict) -> None:
    validate(data, L3_BASELINE_SCHEMA, "L3 基线")
