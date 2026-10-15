#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻1.0 · 一键管线（通用版）
原文目录 → WFP 硬指标基线 →（可选三件套画像）→ 人设卡 → 生成文回测

用法：
  python3 scripts/replicate.py \
    --name alice \
    --corpus-dir /path/to/原文目录 \
    --out-dir /path/to/输出目录 \
    [--limit 5] \
    [--spi-clusters ...json] [--aot-profiles ...json --aot-person 人名] \
    [--l3-baseline ...json] [--people-baseline ...json --people-key key] \
    [--backtest 生成文.txt]

说明：
  - 最小闭环只需 --name + --corpus-dir：产出 WFP 硬指标基线 + 人设卡（仅 WFP 部分）+ 回测入口。
  - SPI/AoT 画像与 L3 软评分是重计算环节（需 DeepSeek key、耗时），本脚本不触发打分，
    由 SKILL.md 指导按模块脚本先行产画像，再以 --spi-clusters / --aot-profiles / --l3-baseline 传入合成。
  - --backtest 传入生成文后，自动提取指纹并计算与基线的 Delta 距离。
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys

WFP = os.environ.get("WFP_ROOT", "")
if not WFP:
    print("错误：请设置环境变量 WFP_ROOT 指向 wfp-toolkit 根目录。", file=sys.stderr)
    sys.exit(1)
WFP_SCRIPTS = os.path.join(WFP, "scripts")
EXTRACT = os.path.join(WFP_SCRIPTS, "extract_hard_metrics.py")
MERGE = os.path.join(WFP_SCRIPTS, "merge_fingerprint.py")
PERSONA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_persona_generic.py")


def scan_corpus(corpus_dir, limit):
    """扫描目录，归一为 list[(doc_id, text)]。支持 .txt/.md 与 SPI dict / AoT 块 JSON。"""
    items = []
    if os.path.isfile(corpus_dir):
        files = [corpus_dir]
    else:
        files = sorted(f for f in os.listdir(corpus_dir)
                       if f.lower().endswith((".txt", ".md", ".json")))
    for fn in files:
        path = fn if os.path.isfile(corpus_dir) else os.path.join(corpus_dir, fn)
        if fn.lower().endswith(".json"):
            try:
                d = json.load(open(path, encoding="utf-8"))
            except Exception as e:
                print(f"[warn] 跳过 {fn}: {e}", file=sys.stderr)
                continue
            if isinstance(d, dict) and "items" in d:
                for it in d["items"]:
                    txt = it.get("text") or it.get("content") or ""
                    if txt:
                        items.append((it.get("title") or it.get("id") or fn, txt))
            elif isinstance(d, dict):
                for k, v in d.items():
                    txt = " ".join(v) if isinstance(v, list) else str(v)
                    if txt.strip():
                        items.append((k, txt))
            continue
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception as e:
            print(f"[warn] 跳过 {fn}: {e}", file=sys.stderr)
            continue
        if txt.strip():
            items.append((os.path.splitext(fn)[0], txt))
        if limit and len(items) >= limit:
            break
    return items[:limit] if limit else items


def run_wfp_hard(items, out_dir, name):
    """逐篇调 extract_hard_metrics.py 单文件模式，聚合生成基线。"""
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    fp_dir = os.path.join(out_dir, "fingerprints")
    os.makedirs(fp_dir, exist_ok=True)
    for i, (doc_id, text) in enumerate(items):
        tmp = os.path.join(out_dir, f"_doc_{i}.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([sys.executable, EXTRACT, tmp, "--json"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(f"[warn] 指纹提取失败 {doc_id}: {r.stderr[:200]}", file=sys.stderr)
            os.remove(tmp)
            continue
        fp = json.loads(r.stdout)
        safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", str(doc_id))[:60]
        fp_path = os.path.join(fp_dir, f"{name}_{safe}.json")
        json.dump(fp, open(fp_path, "w", encoding="utf-8"), ensure_ascii=False)
        rows.append(fp)
        os.remove(tmp)
    if not rows:
        print("错误：无有效文本可提取指纹。", file=sys.stderr)
        sys.exit(1)
    keys = [k for k in rows[0] if isinstance(rows[0][k], (int, float))]
    baseline = {}
    for k in keys:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float)) and r[k] is not None]
        if vals:
            baseline[k] = {
                "mean": round(statistics.mean(vals), 4),
                "sd": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
                "n": len(vals),
            }
    out = {"n_docs": len(rows), "corpus": name, "version": "wenbi-replica-1.0",
           "note": "由文笔复刻1.0 replicate.py 聚合生成", "baseline": baseline}
    bl_path = os.path.join(out_dir, f"wfp_baseline_{name}.json")
    json.dump(out, open(bl_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[ok] 硬指标基线: {bl_path}（{len(rows)} 篇 / {len(baseline)} 特征）")
    return bl_path


def run_persona(name, display, out_dir, **kw):
    cmd = [sys.executable, PERSONA, "--name", name,
           "--out-dir", out_dir, "--wfp-baseline", kw.get("wfp_baseline")]
    if display:
        cmd += ["--display-name", display]
    for opt, key in [("--spi-clusters", "spi_clusters"), ("--aot-profiles", "aot_profiles"),
                     ("--aot-person", "aot_person"), ("--l3-baseline", "l3_baseline"),
                     ("--people-baseline", "people_baseline"), ("--people-key", "people_key")]:
        if kw.get(key):
            cmd += [opt, str(kw[key])]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)


def run_backtest(gen_file, baseline_path, out_dir):
    tmp = os.path.join(out_dir, "_backtest_doc.txt")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(open(gen_file, encoding="utf-8").read())
    r = subprocess.run([sys.executable, EXTRACT, tmp, "--json"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"[warn] 生成文指纹提取失败: {r.stderr[:200]}", file=sys.stderr)
        return
    fp = json.loads(r.stdout)
    fp_path = os.path.join(out_dir, "_backtest_fp.json")
    json.dump(fp, open(fp_path, "w", encoding="utf-8"), ensure_ascii=False)
    r2 = subprocess.run([sys.executable, MERGE, fp_path, "--baseline", baseline_path, "--json"],
                        capture_output=True, text=True, encoding="utf-8")
    os.remove(tmp)
    if r2.returncode != 0:
        print(f"[warn] Delta 计算失败: {r2.stderr[:200]}", file=sys.stderr)
        return
    res = json.loads(r2.stdout)
    print(f"[ok] 回测完成（生成文 {os.path.basename(gen_file)}）")
    if isinstance(res, list) and res:
        r0 = res[0]
        for k in ("delta", "n_features"):
            if k in r0:
                print(f"      {k}: {r0[k]}")
        sm = r0.get("summary") or {}
        if sm:
            print(f"      摘要: 句长 {sm.get('avg_sl')} | 问句 {sm.get('questions')} | 隐喻/千字 {sm.get('meta_per_k')} | 我:你 {sm.get('wo_ni')}")
    elif isinstance(res, dict):
        for k in ("delta", "n_features"):
            if k in res:
                print(f"      {k}: {res[k]}")
    print(f"      完整结果: {fp_path} + merge_fingerprint.py --baseline {baseline_path}")


def main():
    ap = argparse.ArgumentParser(description="文笔复刻1.0 一键管线")
    ap.add_argument("--name", required=True, help="对象标识（ASCII，如 alice）")
    ap.add_argument("--display-name", default="", help="人读名")
    ap.add_argument("--corpus-dir", help="原文目录或单个文本/语料 JSON")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 当前目录/data/results/<name>）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理篇数（0=全量）")
    ap.add_argument("--spi-clusters", help="已有 SPI 聚类画像 JSON")
    ap.add_argument("--aot-profiles", help="已有 AoT people_profiles.json")
    ap.add_argument("--aot-person", help="AoT 画像人名")
    ap.add_argument("--l3-baseline", help="已有 L3 软评分基线 JSON")
    ap.add_argument("--people-baseline", help="已有块级七人基线 JSON")
    ap.add_argument("--people-key", help="块级基线对象 key")
    ap.add_argument("--backtest", help="生成文 .txt，回测 Delta")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join("data", "results", args.name)
    os.makedirs(out_dir, exist_ok=True)

    if args.corpus_dir:
        items = scan_corpus(args.corpus_dir, args.limit)
        if not items:
            print("错误：语料目录无可识别文本。", file=sys.stderr)
            sys.exit(1)
        print(f"[ok] 语料就绪：{len(items)} 篇（来源 {args.corpus_dir}）")
        bl = run_wfp_hard(items, out_dir, args.name)
    else:
        bl = args.l3_baseline  # 无语料时至少需要现成基线才能继续

    kw = dict(spi_clusters=args.spi_clusters, aot_profiles=args.aot_profiles,
              aot_person=args.aot_person, l3_baseline=args.l3_baseline,
              people_baseline=args.people_baseline, people_key=args.people_key,
              wfp_baseline=bl or "")
    run_persona(args.name, args.display_name, out_dir, **kw)

    if args.backtest:
        if not (bl and os.path.exists(bl)):
            print("[warn] 无基线，跳过回测。", file=sys.stderr)
        else:
            run_backtest(args.backtest, bl, out_dir)

    print(f"\n完成。产物目录：{out_dir}")


if __name__ == "__main__":
    main()
