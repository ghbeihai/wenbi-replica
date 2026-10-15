#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPI + AoT 先导：就本题分析「此人会怎么想」，产出思维大纲（硬约束）。

顺序（文笔复刻硬规则）：
  1) SPI 人格簇 + AoT 思维维 → 对本题的框架/判断/拆解（思维大纲）
  2) WFP 只负责表层落地（句长、语气词、标点等），不得主导写什么、先写什么

用法：
  python3 scripts/topic_outline.py --persona-json persona_x.json --topic "白癜风患者要补充什么营养？" \\
      [--purpose 口播稿] [--extra ...] [--out outline.json]
  （需 DeepSeek key；WENBI_MOCK_LLM=1 可离线）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WFP = os.environ.get("WFP_ROOT", "")
if not WFP:
    sys.exit("错误：请设置 WFP_ROOT")
sys.path.insert(0, os.path.join(WFP, "scripts"))
import llm_common  # noqa: E402

SYS = ("你是文笔复刻的「思维大纲」分析器（SPI+AoT 先导任务）。"
       "只根据给定人格簇与思维维度，推断这位作者面对本题会如何立意、拆解、判断与收束。"
       "不要写文风数值，不要写句长/标点/语气词，不要写成品正文。"
       "输出严格 JSON。")


def load_persona(path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not (d.get("spi_personality") or d.get("aot_thinking")):
        raise ValueError("人设 JSON 缺少 spi_personality / aot_thinking，无法做 SPI+AoT 先导分析")
    return d


def pack_persona(p: dict) -> str:
    lines = [f"作者：{p.get('display_name') or p.get('name')}"]
    spi = p.get("spi_personality") or []
    if spi:
        lines.append("【SPI 人格簇】（他是谁；高相关优先）")
        for c in spi[:8]:
            lines.append(f"- {c.get('label')}（首命中 {c.get('n_first')}，相关度 {c.get('avg_relevance')}）")
    aot = p.get("aot_thinking") or []
    if aot:
        lines.append("【AoT 思维维】（他怎么想；高分多用、低分少用）")
        for t in aot[:10]:
            ev = (t.get("evidence") or [""])[0]
            lines.append(f"- {t.get('dim_name')}（{t.get('mean')}/7）例：「{str(ev)[:60]}」")
    return "\n".join(lines)


def analyze(client, cfg, persona: dict, topic: str, purpose: str = "", extra: str = "") -> dict:
    user = (f"{pack_persona(persona)}\n\n"
            f"【本题】{topic}\n"
            + (f"【用途/平台】{purpose}\n" if purpose else "")
            + (f"【其他要求】{extra}\n" if extra else "")
            + "\n请输出 JSON：\n"
            "{\n"
            '  "stance": "一句话立场/总判断（此人会怎么看这题）",\n'
            '  "frame": "立意框架（从哪切入，用什么人格倾向）",\n'
            '  "decompose": ["拆解步骤1", "步骤2", "步骤3"],\n'
            '  "must_include": ["必须落到的判断或提醒"],\n'
            '  "must_avoid": ["此人不会怎么讲（对照其低分维/人格）"],\n'
            '  "closing": "收束方式",\n'
            '  "spi_used": ["用到的人格簇标签"],\n'
            '  "aot_used": ["用到的思维维名"],\n'
            '  "outline_text": "给写作者看的中文大纲（分点，硬约束，200-400字）"\n'
            "}")
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user}]
    d = llm_common.chat_json(client, cfg, msgs, temperature=0.3, log_prefix="[outline] ")
    for k in ("stance", "outline_text"):
        if not str(d.get(k, "")).strip():
            raise RuntimeError(f"大纲缺少字段 {k}")
    d.setdefault("decompose", [])
    d.setdefault("must_include", [])
    d.setdefault("must_avoid", [])
    d.setdefault("spi_used", [])
    d.setdefault("aot_used", [])
    return d


def outline_block(d: dict) -> str:
    """写入生成 prompt 的硬约束块（先于 WFP）。"""
    L = ["【思维大纲 · 硬约束｜SPI+AoT 先导，必须先按此想再落笔；不得改成立意】",
         f"- 立场：{d.get('stance', '')}",
         f"- 框架：{d.get('frame', '')}"]
    if d.get("decompose"):
        L.append("- 拆解：" + " → ".join(str(x) for x in d["decompose"]))
    if d.get("must_include"):
        L.append("- 必须包含：" + "；".join(str(x) for x in d["must_include"]))
    if d.get("must_avoid"):
        L.append("- 禁止：" + "；".join(str(x) for x in d["must_avoid"]))
    if d.get("closing"):
        L.append(f"- 收束：{d['closing']}")
    if d.get("outline_text"):
        L += ["", d["outline_text"]]
    L.append("（说明：上面是此人会怎么想；下面的数值约束只是表层说法，不能推翻大纲。）")
    return "\n".join(L)


def judge_adherence(client, cfg, persona: dict, outline: dict, text: str) -> dict:
    """LLM 评判生成文对 SPI+AoT 大纲的依从（1–7，越高越贴；独立于 WFP）。"""
    sys_p = ("你是文笔复刻的「思维依从」评审（SPI+AoT 依从任务）。"
             "只评生成文是否按大纲的立场/框架/拆解/必含/禁区来想问题，"
             "不要评句长、标点、语气词等表层文风。输出严格 JSON。")
    user = (f"{pack_persona(persona)}\n\n【本题应有的思维大纲】\n{outline_block(outline)}\n\n"
            f"【生成文】\n{text[:3500]}\n\n"
            "输出 JSON：{\"score\":1到7整数,\"confidence\":0到1,"
            "\"hits\":[\"写对了的思维点\"],\"misses\":[\"偏离或遗漏\"],"
            "\"fix_hints\":[\"下一稿如何改回想路（不要提标点句长）\"],"
            "\"summary\":\"一句话总评\"}")
    d = llm_common.chat_json(client, cfg, [{"role": "system", "content": sys_p},
                                           {"role": "user", "content": user}],
                             temperature=0.0, log_prefix="[adhere] ")
    try:
        sc = int(d.get("score", 0))
    except (TypeError, ValueError):
        sc = 0
    if not 1 <= sc <= 7:
        sc = max(1, min(7, sc or 4))
    d["score"] = sc
    d.setdefault("hits", [])
    d.setdefault("misses", [])
    d.setdefault("fix_hints", [])
    return d


def find_persona_json(persona_md: str | None, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    if not persona_md:
        return None
    md = Path(persona_md)
    # 同目录 persona_*.json
    cands = sorted(md.parent.glob("persona_*.json"))
    return cands[0] if cands else None


def main():
    ap = argparse.ArgumentParser(description="SPI+AoT 先导：就本题产出思维大纲（硬约束）")
    ap.add_argument("--persona-json", required=True, help="persona_*.json（含 spi_personality / aot_thinking）")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--purpose", default="")
    ap.add_argument("--extra", default="")
    ap.add_argument("--out", help="写出 outline.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    persona = load_persona(a.persona_json)
    cfg = llm_common.load_llm_cfg(Path(WFP) / "config" / "llm.yaml")
    client = llm_common.make_client(llm_common.require_key(Path(WFP)), cfg)
    d = analyze(client, cfg, persona, a.topic, a.purpose, a.extra)
    d["topic"] = a.topic
    d["purpose"] = a.purpose
    if a.out:
        Path(a.out).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] 大纲 → {a.out}", file=sys.stderr)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(outline_block(d))


if __name__ == "__main__":
    main()
