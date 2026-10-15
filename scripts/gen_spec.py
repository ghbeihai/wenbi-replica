#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成配置（用途/平台、字数、题目、读者、语气、格式）+ few-shot 挑选。

原则：SPI+AoT 先定本题怎么想；WFP 只负责表层怎么说；用途/平台由用户决定；这里只描述「这次写给谁、发在哪、多长、写什么」，由用户在生成时决定。
优先级：命令行字段 > 生成配置文件（--gen-config，yaml/json）> 用途预设（config/purpose_presets.yaml）。

单独运行可预览拼出来的写作要求：
  python3 scripts/gen_spec.py --purpose 公众号文章 --topic "谈读书" --length 1500 [--corpus-dir 原文目录]
  python3 scripts/gen_spec.py --list   # 列出预设
"""
import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRESETS = REPO / "config" / "purpose_presets.yaml"
FIELDS = ("purpose", "topic", "length", "audience", "tone", "format_notes", "extra", "relax",
          "with_optional_format", "fewshot", "corpus_dir")
FEWSHOT_RE = re.compile(r"【few-shot 示例】.*?(?=\n【|\Z)", re.S)


def load_presets(path=None) -> dict:
    import yaml
    p = Path(path) if path else PRESETS
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("presets", {})


def load_config(path) -> dict:
    if not path:
        return {}
    t = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".json"):
        return json.loads(t)
    import yaml
    return yaml.safe_load(t) or {}


def add_args(ap):
    g = ap.add_argument_group("生成配置（用途/平台等由用户决定；命令行 > --gen-config > 预设）")
    g.add_argument("--gen-config", help="生成配置文件 yaml/json（字段同下列参数）")
    g.add_argument("--purpose", help="用途/平台预设：口播稿 / 公众号文章 / 朋友圈 / 小红书图文 / 知乎回答 / 演讲稿 / custom（见 config/purpose_presets.yaml）")
    g.add_argument("--topic", help="题目/主题")
    g.add_argument("--length", type=int, help="目标字数")
    g.add_argument("--audience", help="目标读者")
    g.add_argument("--tone", help="语气/额外风格要求（用户自填，覆盖预设）")
    g.add_argument("--format-notes", help="格式说明（覆盖预设）")
    g.add_argument("--extra", help="其他要求（自由文本，优先级最高）")
    g.add_argument("--relax", action="append", help="额外指定「只报告不强制修正」的特征键（可重复）")
    g.add_argument("--with-optional-format", action="store_true", help="启用预设里的可选格式（如小红书 emoji/话题标签）")
    g.add_argument("--fewshot", type=int, help="few-shot 段数（默认 3；0=不放）")
    g.add_argument("--corpus-dir", help="作者原文目录：从中挑 few-shot（优先与用途相近的体裁、与题目相关的段落）")
    g.add_argument("--presets", help="自定义预设文件（默认 config/purpose_presets.yaml）")


def resolve(a, task=None) -> dict:
    """合并 预设 ← 配置文件 ← 命令行。返回 spec。"""
    cfg = load_config(getattr(a, "gen_config", None))
    cli = {k: getattr(a, k, None) for k in FIELDS}
    purpose = cli.get("purpose") or cfg.get("purpose")
    presets = load_presets(getattr(a, "presets", None))
    if purpose and purpose not in presets:
        sys.exit(f"错误：未知用途预设「{purpose}」；可选：{'、'.join(presets)}（或用 custom + 自填字段）")
    spec = dict(presets.get(purpose, {})) if purpose else {}
    spec["purpose"] = purpose
    for src in (cfg, cli):
        for k, v in src.items():
            if v not in (None, "", []) and k != "relax":
                spec[k] = v
    spec["relax"] = list(dict.fromkeys((spec.get("relax") or []) + (cfg.get("relax") or []) + (cli.get("relax") or [])))
    if task:
        spec["extra"] = (spec.get("extra", "") + "；" + task).strip("；") if spec.get("extra") else task
    if not spec.get("topic") and not spec.get("extra"):
        sys.exit("错误：请给出写作题目（--topic）或写作任务（--task / --extra）。\n"
                 "生成前请先确定：用途/平台（--purpose）、字数（--length）、题目（--topic）、读者与其他要求。")
    spec.setdefault("fewshot", 3)
    return spec


def task_text(spec: dict) -> str:
    L = ["【写作要求】（本次由用户指定，优先于人设卡里的数值约束；冲突时以此为准，但保持作者本人的用词、语气与思维习惯）"]
    if spec.get("purpose"):
        L.append(f"- 用途/平台：{spec.get('name') or spec['purpose']}")
    if spec.get("topic"):
        L.append(f"- 题目/主题：{spec['topic']}")
    if spec.get("length"):
        L.append(f"- 字数：约 {spec['length']} 字")
    if spec.get("audience"):
        L.append(f"- 读者：{spec['audience']}")
    if spec.get("tone"):
        L.append(f"- 语气/风格补充：{spec['tone']}")
    if spec.get("format_notes"):
        L.append(f"- 格式：{spec['format_notes']}")
    if spec.get("with_optional_format") and spec.get("optional_notes"):
        L.append(f"- 可选格式（用户已启用）：{spec['optional_notes']}")
    if spec.get("extra"):
        L.append(f"- 其他要求（最高优先级）：{spec['extra']}")
    L.append("- 只输出正文。")
    return "\n".join(L)


def _bigrams(t):
    t = re.sub(r"\W", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def pick_fewshot(corpus_dir, spec, n=3, seed=42, prefer_edge=True):
    """从作者原文挑 n 段：优先棱角段（判断/反问/强硬），再 genre_pref，再题目重合。"""
    if not corpus_dir or n <= 0:
        return []
    sys.path.insert(0, os.path.join(os.environ.get("WFP_ROOT", ""), "scripts"))
    import genre as genre_mod
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import edge_profile
    p = Path(corpus_dir)
    files = [p] if p.is_file() else sorted(f for f in p.iterdir() if f.suffix.lower() in (".txt", ".md"))
    want = spec.get("genre_pref") or ""
    topic = _bigrams((spec.get("topic") or "") + (spec.get("extra") or ""))
    rng = random.Random(seed)
    cands = []
    for f in files:
        t = f.read_text(encoding="utf-8", errors="ignore")
        if not t.strip():
            continue
        g = genre_mod.classify_rule(t)["genre"]
        paras = [x.strip() for x in t.split("\n") if 80 <= len(x.strip()) <= 300]
        if not paras:
            continue
        def _key(x):
            edge_sc = edge_profile.edge_score_text(x)["score"] if prefer_edge else 0
            # 段内：题目重合优先，其次棱角（同篇只取一段）
            return (len(_bigrams(x) & topic), edge_sc, rng.random())
        best = max(paras, key=_key)
        es = edge_profile.edge_score_text(best)["score"] if prefer_edge else 0
        # 跨篇：体裁匹配优先，再棱角，再题目重合
        cands.append(((g == want) if want else 0, es, len(_bigrams(best) & topic), rng.random(), f.stem, g, best))
    cands.sort(reverse=True)
    return [{"doc_id": c[4], "genre": c[5], "text": c[6], "edge_score": c[1]} for c in cands[:n]]


def apply_fewshot(prompt: str, shots: list) -> str:
    if not shots:
        return FEWSHOT_RE.sub("", prompt).rstrip()
    block = "【few-shot 示例】（作者本人原文片段，体会语气与用词，不要照抄内容）：\n" + \
        "\n".join(f"示例{i + 1}：{s['text']}" for i, s in enumerate(shots))
    if FEWSHOT_RE.search(prompt):
        return FEWSHOT_RE.sub(lambda _: block, prompt, count=1)
    return prompt.rstrip() + "\n" + block


def main():
    ap = argparse.ArgumentParser(description="预览生成配置拼出的写作要求与 few-shot")
    add_args(ap)
    ap.add_argument("--task", help="自由文本写作任务（并入「其他要求」）")
    ap.add_argument("--list", action="store_true", help="列出用途预设")
    a = ap.parse_args()
    if a.list:
        for k, v in load_presets(a.presets).items():
            print(f"{k}：{v.get('name', k)}｜默认 {v.get('length')} 字｜few-shot 优先体裁 {v.get('genre_pref') or '不限'}"
                  f"｜只报告不强制：{v.get('relax') or '无'}" + (f"｜可选格式：{v['optional_notes']}" if v.get("optional_notes") else ""))
        return
    spec = resolve(a, a.task)
    print(task_text(spec))
    for s in pick_fewshot(a.corpus_dir, spec, int(spec.get("fewshot", 3))):
        print(f"[few-shot] {s['doc_id']}（{s['genre']}）：{s['text'][:40]}…")


if __name__ == "__main__":
    main()
