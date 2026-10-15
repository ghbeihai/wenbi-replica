#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻 · 一键管线（通用版）
原文目录 → WFP 硬指标基线 →（可选三件套画像）→ 人设卡 → 生成文回测

用法：
  python3 scripts/replicate.py \
    --name alice \
    --corpus-dir /path/to/原文目录 \
    --out-dir /path/to/输出目录 \
    [--limit 5] \
    [--spi-clusters ...json] [--aot-profiles ...json --aot-person 人名] \
    [--l3-baseline ...json] [--people-baseline ...json --people-key key] \
    [--wfp-baseline 已有WFP基线.json] [--min-docs 5] [--backtest 生成文.txt]

说明：
  - 最小闭环只需 --name + --corpus-dir：产出 WFP 硬指标基线 + 人设卡（仅 WFP 部分）+ 回测入口。
  - 不给 --corpus-dir 时必须给 --wfp-baseline（已有 WFP 基线）；L3 基线只用于人设卡软画像，不能当 WFP 基线。
  - 基线 doc_ids = 原文文件名 stem（JSON 语料为 id/title/键），与 validate_discrimination 的重叠检查一致。
  - 基线由 field_map.aggregate_baseline 生成（与 extract_hard_metrics --summary 同一实现）；<--min-docs 篇报错。
  - SPI/AoT 画像与 L3 软评分是重计算环节（需 DeepSeek key、耗时），本脚本不触发打分，
    由 SKILL.md 指导按模块脚本先行产画像，再以 --spi-clusters / --aot-profiles / --l3-baseline 传入合成。
  - --backtest 传入生成文后，自动提取指纹并计算与基线的 Delta 距离。
  - 体裁（--genre auto，默认）：逐篇识别体裁（讲稿/随笔/新闻/对话/诗歌/其他；规则启发式，--genre-llm 对低置信篇
    再问 LLM），按体裁分组：主基线 wfp_baseline_<name>.json 只用主体裁的篇目，另为每个达到 --min-docs 的体裁写
    wfp_baseline_<name>__<体裁>.json。体裁组过小或语料混杂 → 人设卡标注 analysis_only 并显式告警。
    回测自动识别生成文体裁并选同体裁基线。--genre off 恢复旧行为（全部篇目一个基线）。
  - 缓存：单篇指纹按内容哈希缓存（extract_hard_metrics）；基线记录 input_hash，输入不变时直接复用。
"""
import hashlib
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

WFP = os.environ.get("WFP_ROOT", "")
if not WFP:
    print("错误：请设置环境变量 WFP_ROOT 指向 wfp-toolkit 根目录。", file=sys.stderr)
    sys.exit(1)
WFP_SCRIPTS = os.path.join(WFP, "scripts")
EXTRACT = os.path.join(WFP_SCRIPTS, "extract_hard_metrics.py")
MERGE = os.path.join(WFP_SCRIPTS, "merge_fingerprint.py")
PERSONA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_persona_generic.py")
sys.path.insert(0, WFP_SCRIPTS)
try:
    # 与 validate/normalize/merge/extract --summary 共用同一口径与同一聚合实现
    from field_map import aggregate_baseline, DegenerateBaseline, FIELD_MAP_VERSION
    import genre as genre_mod
except ImportError:
    print("错误：$WFP_ROOT/scripts/field_map.py 缺少 aggregate_baseline / genre.py（wfp-toolkit 太旧，请更新到 field_map v4+）。",
          file=sys.stderr)
    sys.exit(1)

# extract 的 stderr 里这些是 jieba 加载噪音，不转发；其余（缺 jieba、空文本等）原样转发
_NOISE = re.compile(r"^(Building prefix dict|Loading model|Prefix dict has been built|Dumping model)")


def _forward_warnings(stderr: str, doc_id: str):
    for line in (stderr or "").splitlines():
        if line.strip() and not _NOISE.match(line):
            print(f"[extract:{doc_id}] {line}", file=sys.stderr)


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
                    if txt.strip():
                        items.append((str(it.get("id") or it.get("title") or fn), txt))
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
        else:
            print(f"[warn] 跳过空文本 {fn}", file=sys.stderr)
        if limit and len(items) >= limit:
            break
    return items[:limit] if limit else items


def _safe(doc_id) -> str:
    return re.sub(r"[^\w\u4e00-\u9fa5-]", "_", str(doc_id))[:60]


def extract_fp(text: str, doc_id: str, workdir: str):
    """单篇指纹：临时文件以 doc_id 命名（指纹 doc_id 即原文 id），并显式回填 doc_id。失败返回 None。"""
    tmp = os.path.join(workdir, f"{_safe(doc_id)}.txt")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        r = subprocess.run([sys.executable, EXTRACT, tmp, "--json"],
                           capture_output=True, text=True, encoding="utf-8")
    finally:
        os.remove(tmp)
    _forward_warnings(r.stderr, doc_id)
    if r.returncode != 0:
        print(f"[warn] 指纹提取失败 {doc_id}（退出码 {r.returncode}）", file=sys.stderr)
        return None
    fp = json.loads(r.stdout)
    fp["doc_id"] = str(doc_id)
    return fp


def extract_all(items, out_dir, name):
    """逐篇调 extract_hard_metrics.py 单文件模式（自带内容哈希缓存），指纹落盘到 fingerprints/。"""
    fp_dir = os.path.join(out_dir, "fingerprints")
    os.makedirs(fp_dir, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="wenbi_extract_") as td:
        for doc_id, text in items:
            fp = extract_fp(text, doc_id, td)
            if fp is None:
                continue
            json.dump(fp, open(os.path.join(fp_dir, f"{name}_{_safe(doc_id)}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
            rows.append(fp)
    if not rows:
        print("错误：无有效文本可提取指纹。", file=sys.stderr)
        sys.exit(1)
    return rows


def _input_hash(rows, min_docs) -> str:
    h = hashlib.sha256(f"fm{FIELD_MAP_VERSION}|min{min_docs}|".encode())
    for fp in sorted(rows, key=lambda r: str(r.get("doc_id"))):
        h.update(json.dumps(fp, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:20]


def build_baseline(rows, out_dir, fname, name, min_docs=5, meta=None, fatal=True):
    """用 field_map.aggregate_baseline 聚合；同输入（input_hash 相同）时复用已有基线文件。"""
    bl_path = os.path.join(out_dir, fname)
    ih = _input_hash(rows, min_docs)
    if os.path.exists(bl_path):
        try:
            old = json.load(open(bl_path, encoding="utf-8"))
            if old.get("input_hash") == ih and (meta or {}).items() <= old.items():
                print(f"[ok] 基线输入未变（input_hash {ih}），复用 {bl_path}")
                return bl_path
        except (OSError, ValueError):
            pass
    try:
        out = aggregate_baseline(rows, name=name, min_docs=min_docs, version="wenbi-replica")
    except DegenerateBaseline as e:
        msg = (f"错误：{e}。请提供更多（≥5 篇、内容有差异的）非空原文；--min-docs 只能放宽篇数门槛，"
               f"sd=0 的特征仍不可用。")
        if fatal:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg.replace("错误", "[warn] 跳过该体裁基线"), file=sys.stderr)
        return None
    out["note"] = "由文笔复刻 replicate.py 聚合生成（field_map.aggregate_baseline）"
    out["input_hash"] = ih
    out.update(meta or {})
    json.dump(out, open(bl_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[ok] 硬指标基线: {bl_path}（{out['n_docs']} 篇 / {len(out['baseline'])} 特征，field_map v{FIELD_MAP_VERSION}）")
    if out.get("missing_features"):
        print(f"[warn] 基线缺少 Delta 特征：{out['missing_features']}", file=sys.stderr)
    return bl_path


def detect_genres(items, use_llm=False):
    ctx = {}
    return {str(d): genre_mod.classify(t, use_llm=use_llm, _ctx=ctx) for d, t in items}


def run_wfp_hard(items, out_dir, name, min_docs=5, genre="auto", genre_llm=False):
    """→ (主基线路径, 闸门信息)。genre=auto 时按体裁分组建基线。"""
    os.makedirs(out_dir, exist_ok=True)
    rows = extract_all(items, out_dir, name)
    if genre == "off":
        return build_baseline(rows, out_dir, f"wfp_baseline_{name}.json", name, min_docs), None
    texts = dict((str(d), t) for d, t in items)
    labels = detect_genres([(r["doc_id"], texts.get(str(r["doc_id"]), "")) for r in rows], genre_llm)
    g = genre_mod.gate({d: v["genre"] for d, v in labels.items()}, min_docs=min_docs)
    g["per_doc"] = labels
    g["per_genre_baselines"] = {}
    for w in g["warnings"]:
        print(f"[warn] {w}", file=sys.stderr)
    by = {}
    for r in rows:
        by.setdefault(labels[str(r["doc_id"])]["genre"], []).append(r)
    for gn in g["usable_genres"]:
        p = build_baseline(by[gn], out_dir, f"wfp_baseline_{name}__{gn}.json", name, min_docs,
                           meta={"genre": gn}, fatal=False)
        if p:
            g["per_genre_baselines"][gn] = p
    dom = g["dominant"]
    if dom in g["per_genre_baselines"]:
        main_bl = build_baseline(by[dom], out_dir, f"wfp_baseline_{name}.json", name, min_docs, meta={"genre": dom})
    else:  # 没有可用体裁组：退回全部篇目，但标 analysis_only
        main_bl = build_baseline(rows, out_dir, f"wfp_baseline_{name}.json", name, min_docs,
                                 meta={"genre": "mixed"})
    g["analysis_only"] = g["status"] != "ok"
    g["main_genre"] = dom if dom in g["per_genre_baselines"] else "mixed"
    json.dump(g, open(os.path.join(out_dir, "genre_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    dist = "、".join(f"{genre_mod.GENRE_ZH.get(k, k)} {len(v)}" for k, v in sorted(g["groups"].items(), key=lambda kv: -len(kv[1])))
    print(f"[ok] 体裁分布：{dist}（闸门 {g['status']}，主体裁 {genre_mod.GENRE_ZH.get(g['main_genre'], g['main_genre'])}）")
    return main_bl, g


def run_persona(name, display, out_dir, gate_info=None, **kw):
    cmd = [sys.executable, PERSONA, "--name", name,
           "--out-dir", out_dir, "--wfp-baseline", kw.get("wfp_baseline")]
    if gate_info:
        mg = gate_info["main_genre"]
        cmd += ["--genre", mg, "--genre-zh", genre_mod.GENRE_ZH.get(mg, "混合")]
        if gate_info["analysis_only"]:
            cmd.append("--analysis-only")
        for w in gate_info["warnings"]:
            cmd += ["--warning", w]
    if display:
        cmd += ["--display-name", display]
    for opt, key in [("--spi-clusters", "spi_clusters"), ("--aot-profiles", "aot_profiles"),
                     ("--aot-person", "aot_person"), ("--l3-baseline", "l3_baseline"),
                     ("--people-baseline", "people_baseline"), ("--people-key", "people_key")]:
        if kw.get(key):
            cmd += [opt, str(kw[key])]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(r.stdout, end="")
    if r.stderr.strip():
        print(r.stderr, end="", file=sys.stderr)  # 人设卡的告警也要让用户看到
    if r.returncode != 0:
        sys.exit(1)


def pick_genre_baseline(text, baseline_path, use_llm=False):
    """回测/闭环：识别生成文体裁，优先用同目录的同体裁基线；体裁不符时告警。"""
    gg = genre_mod.classify(text, use_llm=use_llm)["genre"]
    try:
        bg = json.load(open(baseline_path, encoding="utf-8")).get("genre")
    except (OSError, ValueError):
        bg = None
    if bg in (None, gg):
        return baseline_path, gg
    stem = os.path.basename(baseline_path)[:-5].split("__")[0]
    alt = os.path.join(os.path.dirname(baseline_path), f"{stem}__{gg}.json")
    if os.path.exists(alt):
        print(f"[ok] 生成文体裁「{genre_mod.GENRE_ZH.get(gg, gg)}」→ 改用同体裁基线 {alt}")
        return alt, gg
    print(f"[warn] 生成文体裁「{genre_mod.GENRE_ZH.get(gg, gg)}」与基线体裁「{genre_mod.GENRE_ZH.get(bg, bg)}」不同，"
          f"且没有同体裁基线：Delta 跨体裁比较，不可靠", file=sys.stderr)
    return baseline_path, gg


def run_backtest(gen_file, baseline_path, out_dir, genre="auto", genre_llm=False):
    text = open(gen_file, encoding="utf-8").read()
    if not text.strip():
        print(f"错误：生成文 {gen_file} 是空文本，无法回测", file=sys.stderr)
        sys.exit(1)
    if genre != "off":
        baseline_path, _ = pick_genre_baseline(text, baseline_path, genre_llm)
    with tempfile.TemporaryDirectory(prefix="wenbi_bt_") as td:
        fp = extract_fp(text, os.path.splitext(os.path.basename(gen_file))[0], td)
    if fp is None:
        print("错误：生成文指纹提取失败", file=sys.stderr)
        sys.exit(1)
    fp_path = os.path.join(out_dir, "_backtest_fp.json")
    json.dump(fp, open(fp_path, "w", encoding="utf-8"), ensure_ascii=False)
    r2 = subprocess.run([sys.executable, MERGE, fp_path, "--baseline", baseline_path, "--json"],
                        capture_output=True, text=True, encoding="utf-8")
    if r2.returncode != 0:
        print(f"错误：Delta 计算失败: {r2.stderr.strip()[:300]}", file=sys.stderr)
        sys.exit(1)
    res = json.loads(r2.stdout)
    print(f"[ok] 回测完成（生成文 {os.path.basename(gen_file)}）")
    r0 = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else {})
    for k in ("delta", "n_features"):
        if k in r0:
            print(f"      {k}: {r0[k]}")
    sm = r0.get("summary") or {}
    if sm:
        print(f"      摘要: 句长 {sm.get('avg_sl')} | 问句 {sm.get('questions')} | 隐喻/千字 {sm.get('meta_per_k')} | 我:你 {sm.get('wo_ni')}")
    print(f"      完整结果: {fp_path} + merge_fingerprint.py --baseline {baseline_path}")


def main():
    ap = argparse.ArgumentParser(description="文笔复刻 一键管线")
    ap.add_argument("--name", required=True, help="对象标识（ASCII，如 alice）")
    ap.add_argument("--display-name", default="", help="人读名")
    ap.add_argument("--corpus-dir", help="原文目录或单个文本/语料 JSON")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 当前目录/data/results/<name>）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理篇数（0=全量）")
    ap.add_argument("--spi-clusters", help="已有 SPI 聚类画像 JSON")
    ap.add_argument("--aot-profiles", help="已有 AoT people_profiles.json")
    ap.add_argument("--aot-person", help="AoT 画像人名")
    ap.add_argument("--l3-baseline", help="已有 L3 软评分基线 JSON（只进人设卡软画像，不当 WFP 基线）")
    ap.add_argument("--wfp-baseline", help="已有 WFP 硬指标基线 JSON（不给 --corpus-dir 时必填）")
    ap.add_argument("--min-docs", type=int, default=5, help="建基线最少非空篇数（默认 5）")
    ap.add_argument("--people-baseline", help="已有块级七人基线 JSON")
    ap.add_argument("--people-key", help="块级基线对象 key")
    ap.add_argument("--backtest", help="生成文 .txt，回测 Delta")
    ap.add_argument("--genre", choices=["auto", "off"], default="auto",
                    help="体裁识别与按体裁分组基线（默认 auto；off=全部篇目一个基线）")
    ap.add_argument("--genre-llm", action="store_true", help="规则置信度 <0.7 的篇目再用 LLM 判体裁（需 key）")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join("data", "results", args.name)
    os.makedirs(out_dir, exist_ok=True)

    if args.corpus_dir:
        items = scan_corpus(args.corpus_dir, args.limit)
        if not items:
            print("错误：语料目录无可识别文本。", file=sys.stderr)
            sys.exit(1)
        print(f"[ok] 语料就绪：{len(items)} 篇（来源 {args.corpus_dir}）")
        if args.wfp_baseline:
            print("[warn] 同时给了 --corpus-dir 与 --wfp-baseline：使用语料新建的基线", file=sys.stderr)
        bl, gate_info = run_wfp_hard(items, out_dir, args.name, min_docs=args.min_docs,
                                     genre=args.genre, genre_llm=args.genre_llm)
    elif args.wfp_baseline:
        if not os.path.exists(args.wfp_baseline):
            print(f"错误：--wfp-baseline 文件不存在 {args.wfp_baseline}", file=sys.stderr)
            sys.exit(1)
        bl = args.wfp_baseline
        gate_info = None
    else:
        # 原实现把 --l3-baseline 当 WFP 基线传下去（错位）；现在要求显式 WFP 基线
        print("错误：需要 --corpus-dir（新建基线）或 --wfp-baseline（已有 WFP 基线）之一。", file=sys.stderr)
        sys.exit(1)

    kw = dict(spi_clusters=args.spi_clusters, aot_profiles=args.aot_profiles,
              aot_person=args.aot_person, l3_baseline=args.l3_baseline,
              people_baseline=args.people_baseline, people_key=args.people_key,
              wfp_baseline=bl)
    run_persona(args.name, args.display_name, out_dir, gate_info=gate_info, **kw)

    if args.backtest:
        run_backtest(args.backtest, bl, out_dir, genre=args.genre, genre_llm=args.genre_llm)

    print(f"\n完成。产物目录：{out_dir}")
    if not args.backtest:
        print("\n训练已完成。生成前请确定这次要写什么（用途/平台、字数、题目，可选读者与其他要求）：\n"
              "  预设：口播稿 / 公众号文章 / 朋友圈 / 小红书图文 / 知乎回答 / 演讲稿 / custom（python3 scripts/wenbi.py presets）\n"
              f"  python3 scripts/closed_loop.py --persona-md {out_dir}/三件套人设卡_{args.name}.md "
              f"--baseline {bl} --corpus-dir <原文目录> --purpose <用途> --topic <题目> --length <字数> --out-dir <输出目录>")


if __name__ == "__main__":
    main()
