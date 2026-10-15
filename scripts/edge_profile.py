#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
棱角画像（edge profile）：从 SPI/AoT 抽出高偏置维、尖锐证据句、低维硬禁区。
通用：不绑定任何具体作者；供 topic_outline / closed_loop / few-shot 使用。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CFG = REPO / "config" / "edge_preserve.yaml"

# 尖锐证据：含判断/反问/强硬否定/对比
_SHARP = re.compile(
    r"(不是|别|不要|没那回事|错了|对不对|是不是|你说|我说|必须|一定|根本|才怪|胡说|扯淡|"
    r"哪有|哪能|怎么可能|千万|绝不能|少来|别信|别指望|说白了|实话|硬核)"
)


def load_cfg(path=None) -> dict:
    import yaml
    p = Path(path) if path else DEFAULT_CFG
    d = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return d or {}


def build(persona: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    hi = float(cfg.get("aot_high", 5.0))
    lo = float(cfg.get("aot_low", 3.5))
    top_n = int(cfg.get("spi_top_n", 4))
    spi = list(persona.get("spi_personality") or [])
    aot = list(persona.get("aot_thinking") or [])
    spi_sorted = sorted(spi, key=lambda c: (-float(c.get("avg_relevance") or 0), -int(c.get("n_first") or 0)))
    high_spi = spi_sorted[:top_n]
    high_aot = [t for t in aot if float(t.get("mean") or 0) >= hi]
    low_aot = [t for t in aot if float(t.get("mean") or 0) <= lo]
    # 若高维太少，取 top 按 mean
    if len(high_aot) < 2 and aot:
        high_aot = sorted(aot, key=lambda t: -float(t.get("mean") or 0))[:3]
    sharp_ev = []
    for t in high_aot + aot:
        for ev in (t.get("evidence") or []):
            ev = str(ev).strip()
            if ev and _SHARP.search(ev) and ev not in sharp_ev:
                sharp_ev.append(ev)
            if len(sharp_ev) >= 6:
                break
        if len(sharp_ev) >= 6:
            break
    if not sharp_ev:  # 退而求其次：高维首条证据
        for t in high_aot:
            for ev in (t.get("evidence") or [])[:1]:
                if str(ev).strip():
                    sharp_ev.append(str(ev).strip())
    bans = [f"少用/避免「{t.get('dim_name')}」式写法（该维仅 {t.get('mean')}/7）" for t in low_aot[:5]]
    bans += list(cfg.get("no_smoothing_rules") or [])
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "high_spi": [{"label": c.get("label"), "avg_relevance": c.get("avg_relevance"),
                      "n_first": c.get("n_first")} for c in high_spi],
        "high_aot": [{"dim_name": t.get("dim_name"), "mean": t.get("mean"),
                      "evidence": (t.get("evidence") or [])[:2]} for t in high_aot],
        "low_aot": [{"dim_name": t.get("dim_name"), "mean": t.get("mean")} for t in low_aot],
        "sharp_evidence": sharp_ev[:6],
        "hard_bans": bans,
        "voice_hint": "用此人会说的硬判断句，保留棱角与主见；不要平滑成谁都对的平均稿。",
        "cfg": {"aot_high": hi, "aot_low": lo, "generation_temperature": cfg.get("generation_temperature"),
                "candidates_per_round": cfg.get("candidates_per_round", 1),
                "fewshot_prefer_edge": cfg.get("fewshot_prefer_edge", True)},
    }


def block(edge: dict) -> str:
    if not edge or not edge.get("enabled"):
        return ""
    L = ["【棱角画像 · 硬约束｜禁止平滑成平均人】",
         f"- 声音：{edge.get('voice_hint', '')}"]
    if edge.get("high_spi"):
        L.append("- 高偏置人格：" + "、".join(c["label"] for c in edge["high_spi"] if c.get("label")))
    if edge.get("high_aot"):
        L.append("- 高偏置思维：" + "、".join(f"{t['dim_name']}({t['mean']})" for t in edge["high_aot"]))
    if edge.get("sharp_evidence"):
        L.append("- 尖锐证据（语气校准，勿照抄内容）：")
        for ev in edge["sharp_evidence"][:4]:
            L.append(f"  · 「{ev[:80]}」")
    if edge.get("hard_bans"):
        L.append("- 硬禁区：" + "；".join(edge["hard_bans"][:6]))
    return "\n".join(L)


def edge_score_text(text: str) -> dict:
    """无 LLM 的棱角启发式（辅助主尺）：判断句密度、反问、强硬否定、禁中庸套话。"""
    t = text or ""
    n = max(len(re.sub(r"\s+", "", t)), 1)
    sharp_n = len(_SHARP.findall(t))
    q = t.count("？") + t.count("?")
    hedge = len(re.findall(r"也许|可能|或许|仁者见仁|都有道理|综合来看|综上所述|一方面.*另一方面", t))
    return {
        "sharp_per_k": round(sharp_n * 1000 / n, 2),
        "questions": q,
        "hedge_hits": hedge,
        "score": max(1, min(7, int(3 + min(3, sharp_n // 3) + min(1, q // 2) - min(2, hedge)))),
    }


def main():
    ap = argparse.ArgumentParser(description="从 persona JSON 抽出棱角画像")
    ap.add_argument("--persona-json", required=True)
    ap.add_argument("--config", help="edge_preserve.yaml")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    edge = build(json.loads(Path(a.persona_json).read_text(encoding="utf-8")), load_cfg(a.config))
    if a.out:
        Path(a.out).write_text(json.dumps(edge, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.json:
        print(json.dumps(edge, ensure_ascii=False, indent=2))
    else:
        print(block(edge))


if __name__ == "__main__":
    main()
