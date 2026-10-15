#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻 · 环境与进度自检（wenbi doctor）
检查：DeepSeek API Key、三个 toolkit、Python 依赖、SPI 数据、原文语料（篇数/字数/体裁）、训练产物，
并告诉你下一步该做什么。不打印 key 本身，不调用 LLM，不花钱。

用法：
  python3 scripts/doctor.py [--corpus-dir 原文目录] [--out-dir 训练输出目录] [--json]
  python3 scripts/wenbi.py doctor ...（同上）
退出码：0 = 可以进入下一步；1 = 有阻塞项（缺 key / 缺 toolkit / 缺依赖 / 缺语料）
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIN_DOCS, REC_DOCS, REC_CHARS = 5, 20, 300

KEY_HELP = ("文笔复刻的 SPI 人格 / AoT 思维 / L3 软评分 / L4 隐喻 / 生成闭环都需要 DeepSeek API Key。\n"
            "    获取：https://platform.deepseek.com/ → API Keys → 创建\n"
            "    设置（任选其一）：export DEEPSEEK_API_KEY=sk-...  或在 wenbi-replica/.env 写一行 DEEPSEEK_API_KEY=sk-...\n"
            "    没有 key 时只能跑 WFP L1/L2 纯规则硬指标（最小闭环）。")
CORPUS_HELP = ("请提供要复刻的那个人的原文：\n"
               "    格式：.txt / .md（一篇一个文件，文件名即篇目 id），或语料 JSON（{\"items\":[{\"id\",\"text\"}]} 或 {id: 文本}）\n"
               f"    数量：至少 {MIN_DOCS} 篇才能建基线；建议 ≥{REC_DOCS} 篇、每篇 ≥{REC_CHARS} 字（越多越稳）\n"
               "    体裁：尽量同一种体裁（全是讲稿，或全是文章）；混杂时会按体裁分组，篇数少的体裁只做分析")
ASK_SPEC = ("训练已完成。生成前请告诉我这次要写什么：\n"
            "    1) 用途/平台：口播稿 / 公众号文章 / 朋友圈 / 小红书图文 / 知乎回答 / 演讲稿 / 其他（自己描述）\n"
            "    2) 字数（约多少字）\n"
            "    3) 题目或主题\n"
            "    4) 读者是谁（可选）\n"
            "    5) 语气、格式或其他要求（可选，例如要不要小标题、要不要 emoji/话题标签）\n"
            "    预设只是可编辑模板（config/purpose_presets.yaml），你写的要求优先。")


def check(corpus_dir=None, out_dir=None) -> dict:
    items, block = [], False

    def add(level, name, msg, help_=None):
        nonlocal block
        items.append({"level": level, "item": name, "msg": msg, "help": help_})
        block |= level == "missing"

    wfp = os.environ.get("WFP_ROOT", "")
    roots = {"WFP_ROOT": ("wfp-toolkit", "scripts/field_map.py"), "SPI_ROOT": ("spi-toolkit", "src/spi_quant/cli.py"),
             "AOT_ROOT": ("aot-toolkit", "scripts/score_dimensions.py")}
    for var, (name, flag) in roots.items():
        v = os.environ.get(var, "")
        if v and (Path(v) / flag).exists():
            add("ok", var, f"{name}：{v}")
        else:
            add("missing", var, f"未设置或路径不对（{name}）",
                "先 bash scripts/install.sh 再 source wenbi.env；或 export " + var + "=<" + name + " 根目录>")
    # key
    if wfp and (Path(wfp) / "scripts/llm_common.py").exists():
        sys.path.insert(0, os.path.join(wfp, "scripts"))
        import llm_common
        k, src = llm_common.load_key(REPO)
        if k:
            add("ok", "DEEPSEEK_API_KEY", f"已找到（来源 {src.split(':')[0] if src.startswith('env') else src}；不显示内容）")
        else:
            add("missing", "DEEPSEEK_API_KEY", "没有找到 DeepSeek API Key", KEY_HELP)
    elif os.environ.get("DEEPSEEK_API_KEY"):
        add("ok", "DEEPSEEK_API_KEY", "环境变量已设置（不显示内容）")
    else:
        add("missing", "DEEPSEEK_API_KEY", "没有找到 DeepSeek API Key", KEY_HELP)
    # deps
    bad = [m for m in ("jieba", "yaml", "numpy", "openai", "dotenv", "spi_quant") if importlib.util.find_spec(m) is None]
    if bad:
        add("missing", "Python 依赖", f"缺少：{', '.join(bad)}", "bash scripts/install.sh")
    else:
        add("ok", "Python 依赖", "jieba / pyyaml / numpy / openai / python-dotenv / spi_quant 均可导入")
    spi = os.environ.get("SPI_ROOT", "")
    if spi:
        atlas = Path(spi) / "assets/survey/results/spi_table.json"
        if atlas.exists():
            add("ok", "SPI Personality Atlas", str(atlas))
        else:
            add("missing", "SPI Personality Atlas", "缺少 SPI 人格数据（约 1.1GB）",
                "cd $SPI_ROOT/assets && git clone https://github.com/Wildertrek/survey.git（或 bash scripts/install.sh）")
    # corpus
    stage = "need_corpus"
    if corpus_dir:
        p = Path(corpus_dir)
        if not p.exists():
            add("missing", "原文语料", f"目录不存在：{corpus_dir}", CORPUS_HELP)
        else:
            files = [p] if p.is_file() else sorted(f for f in p.iterdir() if f.suffix.lower() in (".txt", ".md", ".json"))
            texts = {}
            for f in files:
                if f.suffix.lower() == ".json":
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except ValueError:
                        continue
                    its = d.get("items", []) if isinstance(d, dict) and "items" in d else (
                        [{"id": k, "text": v} for k, v in d.items()] if isinstance(d, dict) else [])
                    for it in its:
                        t = it.get("text") if isinstance(it, dict) else None
                        if isinstance(t, list):
                            t = " ".join(t)
                        if t and str(t).strip():
                            texts[str(it.get("id"))] = str(t)
                else:
                    t = f.read_text(encoding="utf-8", errors="ignore")
                    if t.strip():
                        texts[f.stem] = t
            n = len(texts)
            short = sum(len(t.strip()) < REC_CHARS for t in texts.values())
            msg = f"{n} 篇非空原文，共 {sum(len(t) for t in texts.values())} 字；短于 {REC_CHARS} 字的 {short} 篇"
            if n < MIN_DOCS:
                add("missing", "原文语料", msg + f"（不足 {MIN_DOCS} 篇，无法建基线）", CORPUS_HELP)
            else:
                add("warn" if n < REC_DOCS or short > n / 3 else "ok", "原文语料",
                    msg + ("" if n >= REC_DOCS else f"（建议 ≥{REC_DOCS} 篇）"))
                stage = "need_train"
                if wfp:
                    try:
                        import genre as genre_mod
                        g = genre_mod.gate({d: genre_mod.classify_rule(t)["genre"] for d, t in texts.items()})
                        dist = "、".join(f"{genre_mod.GENRE_ZH.get(k, k)} {len(v)}" for k, v in
                                        sorted(g["groups"].items(), key=lambda kv: -len(kv[1])))
                        add("ok" if g["status"] == "ok" else "warn", "体裁", f"{dist}（闸门 {g['status']}）",
                            "；".join(g["warnings"]) or None)
                    except Exception as e:  # noqa: BLE001
                        add("warn", "体裁", f"体裁检查失败：{e}")
    else:
        add("todo", "原文语料", "还没提供原文目录（--corpus-dir）", CORPUS_HELP)
    # training outputs
    if out_dir and Path(out_dir).exists():
        od = Path(out_dir)
        bl = sorted(od.glob("wfp_baseline_*.json"))
        pc = sorted(od.glob("三件套人设卡_*.md"))
        if bl and pc:
            stage = "ready_to_generate"
            pj = sorted(od.glob("persona_*.json"))
            ao = False
            if pj:
                try:
                    ao = json.loads(pj[0].read_text(encoding="utf-8")).get("analysis_only")
                except ValueError:
                    pass
            add("warn" if ao else "ok", "训练产物", f"基线 {len(bl)} 份、人设卡 {pc[0].name}"
                + ("；人设卡标注 analysis_only（语料不足或体裁混杂，生成结果仅供参考）" if ao else ""))
        else:
            add("todo", "训练产物", f"{out_dir} 里还没有基线/人设卡")
    nxt = {
        "need_corpus": CORPUS_HELP,
        "need_train": ("下一步：训练（建基线 + 人设卡）：\n"
                       "    python3 scripts/replicate.py --name <对象名> --corpus-dir <原文目录> --out-dir <输出目录>\n"
                       "    完整版先按 SKILL.md ② 跑 SPI/AoT/L3/L4，再把画像传给 replicate 合成"),
        "ready_to_generate": ASK_SPEC + "\n    然后：python3 scripts/closed_loop.py --persona-md <人设卡.md> --baseline <基线.json> "
                             "--corpus-dir <原文目录> --purpose <用途> --topic <题目> --length <字数> --out-dir <输出>"}[stage]
    if block:
        nxt = "先补齐上面标 ✗ 的项。\n    " + nxt
    return {"blocking": block, "stage": stage, "items": items, "next": nxt}


def main():
    ap = argparse.ArgumentParser(description="文笔复刻 环境与进度自检（不调用 LLM、不显示 key）")
    ap.add_argument("--corpus-dir", help="原文目录/文件")
    ap.add_argument("--out-dir", help="replicate 的输出目录（检查是否已训练）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = check(a.corpus_dir, a.out_dir)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        mark = {"ok": "✓", "warn": "!", "missing": "✗", "todo": "·"}
        print("=== 文笔复刻 自检 ===")
        for it in r["items"]:
            print(f" {mark[it['level']]} {it['item']}：{it['msg']}")
            if it["help"] and it["level"] != "ok":
                print("    " + it["help"])
        print("\n" + r["next"])
    sys.exit(1 if r["blocking"] else 0)


if __name__ == "__main__":
    main()
