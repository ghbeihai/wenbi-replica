#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻 · 生成闭环
人设卡第四节生成指令 → LLM 生成 → 多尺子打分（ruler 分层：L1句法/L1词汇/L2/L3/L4）
→ 把偏差最大的层/特征翻译成中文修正意见回灌 prompt → 再生成；最多 3 轮，保留综合分最低（最像）的一轮。

用法：
  python3 scripts/closed_loop.py --persona-md 三件套人设卡_alice.md --baseline wfp_baseline_alice.json \\
      --task "写一篇谈读书的短文，约 800 字" --out-dir loop_out [--rounds 3] [--weights ruler_weights.json] \\
      [--temperature 0.8] [--blind-reference 原文目录]
  （或用 --prompt-file 直接给生成指令）

产物：loop_out/round_<k>.txt、round_<k>_fp.json、loop_report.json、loop_report.md、best.txt
说明：
  - 每轮分数为 ruler 综合分（越低越像；与 Delta 同量级）及分层分，各轮始终对同一目标基线打分（保证可比）；
    生成文体裁偏离目标体裁时告警、把"改回目标体裁"写进下一轮修正，同体裁基线分只作参考记录。
  - 不给 --weights 时用 field_map 默认先验权重。
  - --blind-reference：对最佳轮再跑 LLM 盲测尺（与原文成对判断，正反顺序），作为独立信号写入报告。
  - 需要 DeepSeek key（或 WENBI_MOCK_LLM=1 走离线 mock）。
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

WFP = os.environ.get("WFP_ROOT", "")
if not WFP:
    sys.exit("错误：请设置环境变量 WFP_ROOT 指向 wfp-toolkit 根目录。")
WFP_SCRIPTS = os.path.join(WFP, "scripts")
sys.path.insert(0, WFP_SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_map as fm  # noqa: E402
import genre as genre_mod  # noqa: E402
import llm_common  # noqa: E402
import ruler  # noqa: E402

EXTRACT = os.path.join(WFP_SCRIPTS, "extract_hard_metrics.py")
MAX_ROUNDS = 3
SYS = "你是一位文风模仿写作者。严格遵守给定的人设与文风约束写作，只输出正文，不要解释、不要标题外的说明。"


def prompt_from_md(md: str) -> str:
    """取人设卡「## 四、生成指令模板」后第一对三引号之间的内容。"""
    i = md.find("## 四、")
    if i < 0:
        sys.exit("错误：人设卡里没有「## 四、生成指令模板」节")
    m = re.search(r'"""\n(.*?)\n"""', md[i:], re.S)
    if not m or not m.group(1).strip():
        sys.exit("错误：人设卡第四节没有三引号包裹的生成指令")
    return m.group(1).strip()


def fingerprint(text: str, path: str) -> dict:
    open(path, "w", encoding="utf-8").write(text)
    r = subprocess.run([sys.executable, EXTRACT, path, "--json"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"指纹提取失败：{r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)


def feedback(vec, baseline, sc, weights, top=6) -> list:
    """把偏差最大（z×权重）的特征翻成中文修正意见：值、目标、方向。"""
    W = (weights or {}).get("features", {})
    items = []
    for k, z in sc["per_feature"].items():
        st = ruler.stat(baseline, k)
        if not st or z < 1.0:
            continue
        w = W[k]["weight"] if k in W else ruler.prior(k)
        items.append((z * w, k, z, vec[k], st[0]))
    items.sort(reverse=True)
    out = []
    for _, k, z, x, mu in items[:top]:
        lab = fm.label(k) if not k.startswith("L3::") and k != ruler.META_KEY else ("隐喻密度/千字" if k == ruler.META_KEY else k[4:])
        d = "偏高，请降低" if x > mu else "偏低，请提高"
        out.append({"feature": k, "label": lab, "layer": ruler.LAYERS.get(ruler.layer_of(k), ""),
                    "value": round(x, 3), "target": round(mu, 3), "z": round(z, 2),
                    "text": f"{lab}：当前 {round(x, 3)}，原作者约 {round(mu, 3)}（{d}）"})
    return out


def revise(base_prompt: str, task: str, fb: list, sc: dict, prev_text: str) -> str:
    worst = sorted(sc["layers"].items(), key=lambda kv: -kv[1]["score"])[:2]
    lines = [base_prompt, "", f"【写作任务】{task}", "",
             "【上一稿文风偏差（按与原作者的距离排序，请重点修正）】"]
    lines += ["- 偏离最大的层：" + "、".join(f"{v['label']}（{v['score']}）" for _, v in worst)]
    lines += [f"- {f['text']}" for f in fb] or ["- （无显著偏差特征）"]
    lines += ["", "【上一稿开头（供参考，不要照抄，重写全文）】", prev_text[:300]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="文笔复刻 生成闭环（生成→多尺子打分→分层偏差回灌→再生成，≤3 轮）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--persona-md", help="三件套人设卡 .md（取第四节生成指令）")
    src.add_argument("--prompt-file", help="直接给生成指令文本文件")
    ap.add_argument("--baseline", required=True, help="WFP 基线 JSON（建议同体裁基线）")
    ap.add_argument("--task", required=True, help="写作任务（题目/要求/字数）")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rounds", type=int, default=3, help=f"最多轮数（1–{MAX_ROUNDS}，默认 3）")
    ap.add_argument("--weights", help="ruler learn 产出的权重 JSON（默认用先验权重）")
    ap.add_argument("--temperature", type=float, default=None, help="生成温度（默认 config generation_temperature 或 0.8）")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--stop-below", type=float, default=0.0, help="综合分低于此值提前停止（默认 0=不提前停）")
    ap.add_argument("--genre", choices=["auto", "off"], default="auto", help="生成文体裁校验/切同体裁基线")
    ap.add_argument("--blind-reference", help="原文目录：对最佳轮跑 LLM 盲测尺（独立信号）")
    ap.add_argument("--blind-pairs", type=int, default=2, help="盲测配对原文篇数（默认 2，每篇正反 2 次调用）")
    a = ap.parse_args()
    rounds = max(1, min(a.rounds, MAX_ROUNDS))
    if a.rounds > MAX_ROUNDS:
        print(f"[warn] --rounds 上限 {MAX_ROUNDS}，已截为 {MAX_ROUNDS}", file=sys.stderr)

    base_prompt = (prompt_from_md(Path(a.persona_md).read_text(encoding="utf-8")) if a.persona_md
                   else Path(a.prompt_file).read_text(encoding="utf-8").strip())
    baseline_path = a.baseline
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    fm.check_baseline(baseline)
    weights = json.loads(Path(a.weights).read_text(encoding="utf-8")) if a.weights else None
    os.makedirs(a.out_dir, exist_ok=True)

    cfg = llm_common.load_llm_cfg(Path(WFP) / "config" / "llm.yaml")
    temp = a.temperature if a.temperature is not None else float(cfg.get("generation_temperature", 0.8))
    client = llm_common.make_client(llm_common.require_key(Path(WFP)), cfg)

    prompt = "\n".join([base_prompt, "", f"【写作任务】{a.task}"])
    hist = []
    for k in range(1, rounds + 1):
        msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": prompt}]
        text = llm_common.chat_text(client, cfg, msgs, temperature=temp, max_tokens=a.max_tokens,
                                    log_prefix=f"[loop r{k}] ").strip()
        if not text:
            print(f"[warn] 第 {k} 轮生成为空，停止", file=sys.stderr)
            break
        tp = os.path.join(a.out_dir, f"round_{k}.txt")
        fp = fingerprint(text, tp)
        json.dump(fp, open(os.path.join(a.out_dir, f"round_{k}_fp.json"), "w", encoding="utf-8"), ensure_ascii=False)
        genre_note, alt_comp = None, None
        if a.genre != "off":
            g = genre_mod.classify(text)["genre"]
            bg = baseline.get("genre")
            if bg and g != bg:
                # 选最佳轮必须用同一把尺子：打分/回灌始终对目标基线；同体裁基线分只作参考记录
                stem = os.path.basename(baseline_path)[:-5].split("__")[0]
                alt = os.path.join(os.path.dirname(baseline_path), f"{stem}__{g}.json")
                gz, bz = genre_mod.GENRE_ZH.get(g, g), genre_mod.GENRE_ZH.get(bg, bg)
                print(f"[warn] 第 {k} 轮生成文体裁「{gz}」≠ 目标体裁「{bz}」：仍按目标基线打分，并在下一轮要求改回「{bz}」",
                      file=sys.stderr)
                genre_note = {"genre": g, "target": bg, "text": f"体裁偏离：上一稿写成了「{gz}」，请写成「{bz}」"}
                if os.path.exists(alt):
                    alt_comp = ruler.score(ruler.vector(fp), json.loads(Path(alt).read_text(encoding="utf-8")),
                                           weights)["composite"]
        vec = ruler.vector(fp)
        sc = ruler.score(vec, baseline, weights)
        fb = feedback(vec, baseline, sc, weights)
        if genre_note:
            fb.insert(0, {"feature": "genre", "label": "体裁", "layer": "", "value": genre_note["genre"],
                          "target": genre_note["target"], "z": None, "text": genre_note["text"]})
        hist.append({"round": k, "file": tp, "genre_mismatch": genre_note, "same_genre_baseline_composite": alt_comp,
                     "composite": sc["composite"], "n_features": sc["n"],
                     "layers": {n: {"label": v["label"], "score": v["score"]} for n, v in sc["layers"].items()},
                     "feedback": fb, "prompt_chars": len(prompt)})
        print(f"[round {k}] 综合分 {sc['composite']}（{sc['n']} 特征）| "
              + " | ".join(f"{v['label']} {v['score']}" for v in sc["layers"].values()))
        if sc["composite"] is not None and sc["composite"] < a.stop_below:
            print(f"[ok] 综合分 < {a.stop_below}，提前停止")
            break
        if k < rounds:
            prompt = revise(base_prompt, a.task, fb, sc, text)
            open(os.path.join(a.out_dir, f"round_{k + 1}_prompt.txt"), "w", encoding="utf-8").write(prompt)

    if not hist:
        sys.exit("错误：没有任何一轮生成成功")
    best = min(hist, key=lambda h: h["composite"] if h["composite"] is not None else float("inf"))
    best_text = Path(best["file"]).read_text(encoding="utf-8")
    open(os.path.join(a.out_dir, "best.txt"), "w", encoding="utf-8").write(best_text)
    report = {"baseline": baseline_path, "weights": a.weights or "prior", "temperature": temp,
              "rounds": hist, "best_round": best["round"], "best_composite": best["composite"]}

    if a.blind_reference:
        import blind_test
        refs_dir = Path(a.blind_reference)
        files = sorted(f for f in refs_dir.iterdir() if f.suffix.lower() in (".txt", ".md"))
        rng = random.Random(42)
        reals = rng.sample(files, min(a.blind_pairs, len(files)))
        res = []
        for rf in reals:
            refs, _ = blind_test.load_refs(str(refs_dir), 3, exclude=[rf.stem])
            try:
                r = blind_test.judge(client, cfg, refs, rf.read_text(encoding="utf-8"), best_text)
            except Exception as e:  # noqa: BLE001
                r = {"p_real": None, "error": f"{type(e).__name__}: {str(e)[:100]}"}
            r["real"] = rf.name
            res.append(r)
        ok = [r["p_real"] for r in res if r.get("p_real") is not None]
        report["blind_test"] = {"pairs": res, "mean_p_detect": round(sum(ok) / len(ok), 3) if ok else None,
                                "note": "P(识破)：LLM 选中真文的概率；越接近 0.5 越以假乱真（独立信号，不并入综合分）"}

    json.dump(report, open(os.path.join(a.out_dir, "loop_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    L = ["# 生成闭环报告", "", f"- 基线：{baseline_path}", f"- 权重：{a.weights or '先验（field_map）'}",
         f"- 最佳轮：第 {best['round']} 轮（综合分 {best['composite']}，越低越像）", "",
         "| 轮 | 综合分 | " + " | ".join(v["label"] for v in hist[0]["layers"].values()) + " |",
         "|---|---|" + "---|" * len(hist[0]["layers"])]
    for h in hist:
        L.append(f"| {h['round']} | {h['composite']} | " + " | ".join(str(h['layers'].get(n, {}).get('score', '')) for n in hist[0]["layers"]) + " |")
    if report.get("blind_test"):
        L += ["", f"- LLM 盲测 P(识破)：{report['blind_test']['mean_p_detect']}（越接近 0.5 越以假乱真）"]
    open(os.path.join(a.out_dir, "loop_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"[ok] 最佳：第 {best['round']} 轮 综合分 {best['composite']} → {a.out_dir}/best.txt；报告 loop_report.md")


if __name__ == "__main__":
    main()
