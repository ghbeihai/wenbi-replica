#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPI + AoT 先导：就本题产出「解题思路 + 篇章结构」全框架（硬约束），并注入棱角画像。

顺序硬规则：
  1) 棱角画像（高偏置 SPI/AoT + 尖锐证据 + 低维禁区）
  2) 全文章框架（thesis 弧线、分节逻辑、允许的尖锐主张、禁平滑）——不是条目堆砌
  3) WFP 只负责表层落地，不得主导写什么、先写什么，也不得把棱角拉回均值

用法：
  python3 scripts/topic_outline.py --persona-json persona_x.json --topic "…" [--purpose 口播稿] [--out outline.json]
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_common  # noqa: E402
import edge_profile  # noqa: E402

SYS = ("你是文笔复刻的「篇章框架」分析器（SPI+AoT 先导 · 棱角保留任务）。"
       "根据人格簇与思维维度，为这位有主见的作者设计本题的完整文章框架："
       "解题思路 + 篇章结构，防止写成流水账或中庸平均稿。"
       "必须保留棱角与鲜明主张；禁止把立场磨平。"
       "若提供了作者身份/职业，立场与尖锐主张必须从该身份发出（专业服务/照护权威可硬、可戳瞎补，但不是局外喷子骂患者）。"
       "不要写文风数值，不要写句长/标点/语气词，不要写成品正文。输出严格 JSON。")


def load_persona(path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not (d.get("spi_personality") or d.get("aot_thinking")):
        raise ValueError("人设 JSON 缺少 spi_personality / aot_thinking，无法做 SPI+AoT 先导分析")
    return d


def pack_persona(p: dict, edge: dict | None = None, role: str = "") -> str:
    lines = [f"作者：{p.get('display_name') or p.get('name')}"]
    role = (role or p.get("role") or p.get("profession") or "").strip()
    if role:
        lines.append(f"【作者身份/职业 · 硬约束】{role}")
        lines.append("（棱角与主见保留，但说话位置是专业照护者/服务者，不是局外喷子；"
                     "戳瞎补与噱头时，站在「我负责给你管方案」一侧，对象是患者不是「你们这帮白痴」。）")
    if edge and edge.get("enabled"):
        lines.append(edge_profile.block(edge))
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


def analyze(client, cfg, persona: dict, topic: str, purpose: str = "", extra: str = "",
            edge: dict | None = None, role: str = "") -> dict:
    edge = edge if edge is not None else edge_profile.build(persona)
    role = (role or persona.get("role") or persona.get("profession") or "").strip()
    user = (f"{pack_persona(persona, edge, role=role)}\n\n"
            f"【本题】{topic}\n"
            + (f"【作者身份/职业】{role}\n" if role else "")
            + (f"【用途/平台】{purpose}\n" if purpose else "")
            + (f"【其他要求】{extra}\n" if extra else "")
            + "\n请输出完整篇章框架 JSON（不是条目清单）：\n"
            "{\n"
            '  "stance": "一句话鲜明立场（有棱角；若给了职业身份，必须从该身份说话，专业照护权威，不是局外骂街）",\n'
            '  "thesis_arc": "全文解题弧线：开题如何破、中段如何推进、收束如何钉死（一段话）",\n'
            '  "sections": [\n'
            '    {"role": "开题/破题/展开/纠偏/收束等", "purpose": "本节在解题中的作用",\n'
            '     "point": "本节主见（一句硬判断）", "move": "如何接到下一节"}\n'
            "  ],\n"
            '  "sharp_claims": ["允许且鼓励的尖锐主张（对齐高偏置维）"],\n'
            '  "must_include": ["必须落到的判断或提醒"],\n'
            '  "must_avoid": ["禁区：低维写法 + 平滑/流水账"],\n'
            '  "no_smoothing": ["本篇专属的禁平滑细则"],\n'
            '  "closing": "收束方式（带主见，不要和稀泥）",\n'
            '  "spi_used": ["用到的人格簇"],\n'
            '  "aot_used": ["用到的思维维"],\n'
            '  "outline_text": "给写作者的中文全框架（解题思路+分节结构，300-500字，像在讲怎么写这篇，而不是要点列表）"\n'
            "}")
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user}]
    d = llm_common.chat_json(client, cfg, msgs, temperature=0.4, log_prefix="[outline] ")
    for k in ("stance", "outline_text"):
        if not str(d.get(k, "")).strip():
            raise RuntimeError(f"框架缺少字段 {k}")
    for k, default in (("sections", []), ("sharp_claims", []), ("must_include", []), ("must_avoid", []),
                       ("no_smoothing", []), ("spi_used", []), ("aot_used", []), ("decompose", [])):
        d.setdefault(k, default)
    # 兼容旧字段：无 sections 时用 decompose 填
    if not d["sections"] and d.get("decompose"):
        d["sections"] = [{"role": "展开", "purpose": "推进", "point": x, "move": ""} for x in d["decompose"]]
    d["edge"] = edge
    d["frame"] = d.get("frame") or d.get("thesis_arc") or ""
    d["role"] = role
    return d


def outline_block(d: dict) -> str:
    """写入生成 prompt 的硬约束块（先于 WFP）。"""
    L = ["【篇章框架 · 硬约束｜SPI+AoT 先导 · 解题思路+结构｜禁止流水账与平滑平均】"]
    if d.get("role"):
        L.append(f"- 作者身份：{d['role']}（专业照护权威；可硬可戳，勿变局外喷子）")
    L.append(f"- 鲜明立场：{d.get('stance', '')}")
    if d.get("thesis_arc"):
        L.append(f"- 解题弧线：{d['thesis_arc']}")
    elif d.get("frame"):
        L.append(f"- 框架：{d['frame']}")
    secs = d.get("sections") or []
    if secs:
        L.append("- 篇章结构（按节推进，每节必须有主见）：")
        for i, s in enumerate(secs, 1):
            if isinstance(s, dict):
                L.append(f"  {i}. 【{s.get('role') or '节'}】{s.get('point') or ''}｜作用：{s.get('purpose') or ''}"
                         + (f"｜接下：{s['move']}" if s.get("move") else ""))
            else:
                L.append(f"  {i}. {s}")
    elif d.get("decompose"):
        L.append("- 拆解：" + " → ".join(str(x) for x in d["decompose"]))
    if d.get("sharp_claims"):
        L.append("- 允许的尖锐主张：" + "；".join(str(x) for x in d["sharp_claims"]))
    if d.get("must_include"):
        L.append("- 必须包含：" + "；".join(str(x) for x in d["must_include"]))
    if d.get("must_avoid"):
        L.append("- 禁止：" + "；".join(str(x) for x in d["must_avoid"]))
    if d.get("no_smoothing"):
        L.append("- 禁平滑：" + "；".join(str(x) for x in d["no_smoothing"]))
    if d.get("closing"):
        L.append(f"- 收束：{d['closing']}")
    if d.get("edge"):
        eb = edge_profile.block(d["edge"])
        if eb:
            L += ["", eb]
    if d.get("outline_text"):
        L += ["", "【写给执笔的完整框架】", d["outline_text"]]
    L.append("（说明：上面是此人会怎么想、怎么铺篇；下面的数值约束只是表层说法，"
             "不能推翻框架，也不能为了文风分把棱角磨掉。）")
    return "\n".join(L)


def judge_adherence(client, cfg, persona: dict, outline: dict, text: str) -> dict:
    """主尺之一：思维依从 + 结构 coherence（1–7）。"""
    sys_p = ("你是文笔复刻的「思维依从」评审（SPI+AoT 依从任务）。"
             "评生成文是否按篇章框架的立场/弧线/分节主见来想问题，是否避免流水账。"
             "不要评句长、标点、语气词。输出严格 JSON。")
    user = (f"{pack_persona(persona, outline.get('edge'), role=outline.get('role') or '')}\n\n【本题篇章框架】\n{outline_block(outline)}\n\n"
            f"【生成文】\n{text[:3500]}\n\n"
            "输出 JSON：{\"score\":1到7,\"structure_score\":1到7,\"confidence\":0到1,"
            "\"hits\":[\"写对了的思维/结构点\"],\"misses\":[\"偏离或流水账处\"],"
            "\"fix_hints\":[\"下一稿如何改回想路与结构（不要提标点句长）\"],"
            "\"summary\":\"一句话总评\"}")
    d = llm_common.chat_json(client, cfg, [{"role": "system", "content": sys_p},
                                           {"role": "user", "content": user}],
                             temperature=0.0, log_prefix="[adhere] ")
    try:
        sc = int(d.get("score", 0))
    except (TypeError, ValueError):
        sc = 0
    d["score"] = max(1, min(7, sc or 4))
    try:
        d["structure_score"] = max(1, min(7, int(d.get("structure_score") or d["score"])))
    except (TypeError, ValueError):
        d["structure_score"] = d["score"]
    d.setdefault("hits", [])
    d.setdefault("misses", [])
    d.setdefault("fix_hints", [])
    return d


def judge_edge(client, cfg, persona: dict, outline: dict, text: str) -> dict:
    """主尺之二：棱角保留（1–7）——有主见、未平滑、尖锐主张仍在。"""
    sys_p = ("你是文笔复刻的「棱角保留」评审（棱角保留任务）。"
             "评生成文是否保留此人的鲜明主张与硬判断，有没有被磨成中庸平均稿或流水账。"
             "不要评句长标点。输出严格 JSON。")
    claims = "；".join(str(x) for x in (outline.get("sharp_claims") or outline.get("must_include") or [])[:5])
    user = (f"{pack_persona(persona, outline.get('edge'), role=outline.get('role') or '')}\n\n"
            f"【应有立场】{outline.get('stance')}\n【应有尖锐主张】{claims}\n\n"
            f"【生成文】\n{text[:3500]}\n\n"
            "输出 JSON：{\"score\":1到7,\"confidence\":0到1,"
            "\"kept_edges\":[\"保留住的棱角\"],\"smoothed\":[\"被磨平/中庸化的地方\"],"
            "\"fix_hints\":[\"如何把主见写得更利（不要提标点）\"],"
            "\"summary\":\"一句话总评\"}")
    d = llm_common.chat_json(client, cfg, [{"role": "system", "content": sys_p},
                                           {"role": "user", "content": user}],
                             temperature=0.0, log_prefix="[edge] ")
    try:
        sc = int(d.get("score", 0))
    except (TypeError, ValueError):
        sc = 0
    d["score"] = max(1, min(7, sc or 4))
    # 与启发式混合（轻度）
    h = edge_profile.edge_score_text(text)
    d["heuristic"] = h
    d["score"] = max(1, min(7, int(round(0.75 * d["score"] + 0.25 * h["score"]))))
    d.setdefault("kept_edges", [])
    d.setdefault("smoothed", [])
    d.setdefault("fix_hints", [])
    return d


def find_persona_json(persona_md: str | None, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    if not persona_md:
        return None
    cands = sorted(Path(persona_md).parent.glob("persona_*.json"))
    return cands[0] if cands else None


def main():
    ap = argparse.ArgumentParser(description="SPI+AoT 先导：篇章框架（解题思路+结构）+ 棱角")
    ap.add_argument("--persona-json", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--purpose", default="")
    ap.add_argument("--role", default="", help="作者职业/身份")
    ap.add_argument("--extra", default="")
    ap.add_argument("--edge-config", help="edge_preserve.yaml")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    persona = load_persona(a.persona_json)
    edge = edge_profile.build(persona, edge_profile.load_cfg(a.edge_config))
    cfg = llm_common.load_llm_cfg(Path(WFP) / "config" / "llm.yaml")
    client = llm_common.make_client(llm_common.require_key(Path(WFP)), cfg)
    d = analyze(client, cfg, persona, a.topic, a.purpose, a.extra, edge=edge, role=a.role)
    d["topic"] = a.topic
    d["purpose"] = a.purpose
    if a.out:
        Path(a.out).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] 框架 → {a.out}", file=sys.stderr)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(outline_block(d))


if __name__ == "__main__":
    main()
