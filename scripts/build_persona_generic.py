#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文笔复刻 · 三件套人设卡合成（通用版）
SPI（他是谁）+ AoT（他怎么想）+ WFP（他怎么说）→ 标准化"人设卡"

所有输入参数均可选：传了哪些画像，人设卡就合成哪些部分；全都不传则只产出骨架并提示。
设计目标：换对象只需换输入画像路径，不改脚本。

用法示例：
  python3 scripts/build_persona_generic.py \
    --name <key> --display-name "<人读名>" \
    --spi-clusters <SPI_ROOT>/data/results/<key>_profiles/spi_cluster_all.json \
    --aot-profiles <AoT_ROOT>/data/results/profiles_full/people_profiles.json --aot-person <人名> \
    --wfp-baseline <WFP_ROOT>/data/results/wfp_baseline_<key>.json \
    --l3-baseline  <WFP_ROOT>/data/results/l3_baseline.json \
    --out-dir <输出目录>

输出：
  <out-dir>/persona_<name>.json      —— 结构化人设卡（可程序消费）
  <out-dir>/三件套人设卡_<name>.md   —— 人读版人设卡 + 可直接投喂的生成指令模板
"""
import argparse
import json
import os
import sys

WFP = os.environ.get("WFP_ROOT", "")
L3_CONFIG_DEFAULT = os.path.join(WFP, "config/l3_dimensions.yaml") if WFP else ""


import schemas

def load_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"[warn] 读取 {path} 失败: {e}", file=sys.stderr)
        return None


# SPI 聚类名 → 生成端友好表述（可经 --spi-label-map 扩展）
# 仅作用于生成指令模板；persona JSON 保留原始 cluster label（与旧版产物一致）
SPI_LABEL_FIX = {
    "Dark Manipulation 黑暗操纵": "识破操纵（拆解话术陷阱）",
}


def load_spi(spi_clusters):
    """SPI 聚类画像：取命中前 6 语义簇（保留原始 label）"""
    if not spi_clusters:
        print("[警告] SPI 画像文件为空，将跳过人格底色段。请检查 aggregate_spi_profiles.py 是否跑通。", file=sys.stderr)
        return None
    if "cluster_summary" not in spi_clusters:
        print("[警告] SPI 画像文件缺 cluster_summary 字段，将跳过人格底色段。请检查输入格式。", file=sys.stderr)
        return None
    cs = spi_clusters["cluster_summary"]
    if not cs:
        print("[警告] SPI cluster_summary 为空，将跳过人格底色段。", file=sys.stderr)
        return None
    cs = sorted(cs, key=lambda c: -c.get("n_first", 0))
    return [{"cluster": c["cluster"], "label": c.get("label", ""),
             "n_first": c.get("n_first", 0), "n_top5": c.get("n_top5", 0),
             "avg_relevance": c.get("avg_relevance", 0)} for c in cs[:6]]


def spi_label_display(label, label_map=None):
    fix = dict(SPI_LABEL_FIX)
    if label_map:
        fix.update(label_map)
    return fix.get(label, label)


def load_aot(aot_profiles, person):
    """AoT 思维画像：按人名取 top5 维度（含证据）"""
    if not aot_profiles:
        print("[警告] AoT 画像文件为空，将跳过思维模式段。请检查 aggregate_profiles.py 是否跑通。", file=sys.stderr)
        return None
    target = None
    for k, v in aot_profiles.items():
        if v.get("name") == person or k == person:
            target = v
            break
    if not target:
        print(f"[警告] AoT 画像中未找到人名 '{person}'，将跳过思维模式段。可用人名：{list(aot_profiles.keys())}", file=sys.stderr)
        return None
    top = [{"dim": t.get("dim", ""), "dim_name": t.get("dim_name", ""),
            "mean": t.get("mean", 0), "evidence": (t.get("evidence") or [])[:2]}
           for t in target.get("top5", [])]
    return top if top else None


def load_wfp(wfp_baseline, l3_baseline, people_baseline, people_key, l3_config):
    """WFP 硬指标数值约束 + L3 软画像。"""
    hard = {}
    bl = (wfp_baseline or {}).get("baseline", {})
    avg_chars = (wfp_baseline or {}).get("avg_chars", 0) or 0

    def pick(feat, fmt=None):
        try:
            v = bl[feat]["mean"]
            if v is None:
                return None
            return v if fmt is None else fmt(v)
        except (KeyError, TypeError):
            return None

    def pick_people(feat, fmt=None):
        try:
            v = people_baseline["people"][people_key]["hard"][feat]
            if v is None:
                return None
            return v if fmt is None else fmt(v)
        except (KeyError, TypeError):
            return None

    v = pick("L1_SYN_001_avg_sl", round1)
    if v is not None:
        hard["平均句长"] = v
    for feat, name, fmt in [
        ("L1_SYN_002_short_lt10", "短句<10字占比", round3),
        ("L1_SYN_002_long_gt40", "长句>40字占比", round3),
        ("L1_LEX_006_wo_ni_ratio", "我:你", None),
        ("L1_LEX_007_pos_per_k", "正情/千字", round1),
        ("L1_LEX_007_neg_per_k", "负情/千字", round2),
        ("L1_SYN_006_fourchar_per_k", "四字格/千字", round2),
        ("L1_LEX_001_sttr100", "STTR100", round3),
    ]:
        val = pick(feat, fmt)
        if val is not None:
            hard[name] = val

    # 问句/修辞反问：按篇 → 每千字（避免篇幅陷阱）
    if avg_chars > 0:
        for feat, name in [("L1_SYN_004_question_sents", "问句/千字"),
                           ("L1_SYN_004_rhet_sents", "修辞反问/千字")]:
            v = pick(feat)
            if v is not None:
                hard[name] = round(v * 1000 / avg_chars, 2)

    # 字典字段展开后的总和（语气词/人称代词/衔接词）
    for feat, name in [
        ("L1_LEX_004_yqci_per_k_total", "语气词/千字"),
        ("L1_LEX_006_pron_per_k_total", "人称代词/千字"),
        ("L1_LEX_005_dm_total", "话语标记/千字"),
    ]:
        v = pick(feat)
        if v is not None:
            hard[name] = round(v, 2)

    # 其他字典字段（认知词/标点/隐喻根域/连接词）的 *_total
    for feat, name in [
        ("L1_LEX_008_cog_per_k_total", "认知词/千字"),
        ("L1_SYN_003_punct_per_k_total", "标点/千字"),
        ("L2_DIS_002_conn_per_k_total", "连接词/千字"),
        ("L4_SUR_001_meta_domains_total", "隐喻根域总数/千字"),
    ]:
        v = pick(feat)
        if v is not None:
            hard[name] = round(v, 2)

    # 其他重要标量字段
    for feat, name in [
        ("L1_SYN_005_ba_per_k", "把字句/千字"),
        ("L1_SYN_005_bei_per_k", "被字句/千字"),
        ("L1_SYN_005_shi_de_per_k", "是...的/千字"),
        ("L4_SUR_002_value_per_k", "价值词/千字"),
        ("L4_SUR_003_pos_neg_ratio", "正负情感比"),
    ]:
        v = pick(feat)
        if v is not None:
            hard[name] = round(v, 2)

    l3 = {}
    dims = (l3_baseline or {}).get("baseline", {})
    names = {}
    try:
        import yaml
        names = {d["id"]: d.get("name", d["id"]) for d in yaml.safe_load(open(l3_config, encoding="utf-8"))["dimensions"]}
    except Exception:
        pass
    for k, v in dims.items():
        mean = v.get("mean") if isinstance(v, dict) else v
        if mean is not None:
            l3[names.get(k, k)] = round(float(mean), 2)

    # 隐喻根域：从基线里读各根域密度，排名后输出
    meta_domains = {}
    for k, v in bl.items():
        if k.startswith("L4_SUR_001_meta_domains__"):
            domain = k.split("__")[1]
            mean = v.get("mean", 0) if isinstance(v, dict) else v
            if mean > 0:
                meta_domains[domain] = mean
    if meta_domains:
        top_domains = sorted(meta_domains.items(), key=lambda x: -x[1])[:3]
        hard["隐喻根域top3"] = "、".join(f"{d}({v}/千字)" for d, v in top_domains)

    return hard, l3


def round1(x): return round(x, 1)
def round2(x): return round(x, 2)
def round3(x): return round(x, 3)


def build_prompt(persona, hard, l3, aot, spi, label_map=None):
    """动态生成可直接投喂的生成指令模板：数值缺失的约束自动省略。"""
    parts = []

    if hard:
        segs = []
        v = hard.get("平均句长")
        if v is not None:
            s = f"平均句长{v-5:.0f}-{v+5:.0f}字（目标 {v} 字）"
            if hard.get("短句<10字占比") is not None:
                s += f"（短句<10字约占{round(hard['短句<10字占比'] * 100, 1)}%）"
            if hard.get("长句>40字占比") is not None:
                s += f"，长句>40字约占{round(hard['长句>40字占比'] * 100, 1)}%"
            segs.append(s)
        for feat in ["我:你", "语气词/千字", "人称代词/千字", "话语标记/千字", "认知词/千字",
                     "标点/千字", "连接词/千字", "隐喻根域总数/千字",
                     "正情/千字", "负情/千字", "四字格/千字", "问句/千字", "修辞反问/千字",
                     "把字句/千字", "被字句/千字", "是...的/千字", "价值词/千字"]:
            if hard.get(feat) is not None:
                if feat == "我:你":
                    segs.append(f"我:你比例{max(0.5, hard[feat]-1):.1f}-{hard[feat]+1:.1f}（目标 {hard[feat]}）")
                else:
                    segs.append(f"{feat}≈{hard[feat]}")
        parts.append("【数值约束】" + "；".join(segs) + "。")

    if l3:
        sorted_l3_desc = sorted(l3.items(), key=lambda x: -x[1])
        sorted_l3_asc = sorted(l3.items(), key=lambda x: x[1])
        top6 = sorted_l3_desc[:6]
        low_dims = [(k, v) for k, v in sorted_l3_asc if v < 4.0][:5]
        segs = [f"{k} {v}" for k, v in top6]
        if low_dims:
            low_segs = [f"{k} ≤{v+0.5:.1f}分（少用，不超过上限）" for k, v in low_dims]
            parts.append("【软画像】高分：" + "、".join(segs) + "；低分：" + "、".join(low_segs) + "（1–7 分）。")
        else:
            parts.append("【软画像】" + "（" + "、".join(segs) + "，1–7 分，按目标值对齐，避免顶格）。")

    if aot:
        segs = [f"{t['dim_name']}（{t['mean']}）" for t in aot]
        parts.append("【思维底色】" + "；".join(segs) + "（按分数对齐：高维多用、低维少用）。")

    if spi:
        labels = [spi_label_display(c["label"], label_map) for c in spi if c.get("label")]
        if labels:
            parts.append("【人格底色】" + "（" + "、".join(labels[:6]) + "）。")

    parts.append("【人称提示】多用'我'讲自己的经历和感受，少用'你'直接喊话或说教。目标我:你比例见上方数值约束。")
    parts.append("【few-shot 示例】（请从原作者语料里挑 2-3 段最有代表性的原文贴在这里，优先选第一人称叙述多的段落，比纯数值约束更有效）：")
    parts.append("【禁止】不书面化（不用'综上所述'等）；不堆隐喻；不顶格宣泄；不列一二三。")
    return "\n".join(parts)


def render_md(persona, hard, l3, aot, spi, prompt):
    A = []
    add = A.append
    add(f"# 三件套人设卡 · {persona['display_name']}")
    add("")
    add("> 合成：SPI（他是谁）+ AoT（他怎么想）+ WFP（他怎么说）→ 人设 prompt。文笔复刻。")
    add("")
    if spi:
        add("## 一、人格底色（SPI：他是谁）")
        add("")
        add("| 语义簇 | 首命中 | 前5 | 相关度 |")
        add("|---|---|---|---|")
        for c in spi:
            add(f"| {c['label']} | {c['n_first']} | {c['n_top5']} | {c['avg_relevance']} |")
        add("")
    if aot:
        add("## 二、思维模式（AoT：他怎么想）")
        add("")
        for t in aot:
            ev = t["evidence"][0][:40] if t.get("evidence") else ""
            add(f"- **{t['dim_name']}**（{t['mean']}/7）：如「{ev}」")
        add("")
    if hard or l3:
        add("## 三、文风指纹（WFP：他怎么说）")
        add("")
    if hard:
        add("### 硬指标数值约束（L1/L2/L4）")
        add("")
        add("| 特征 | 目标值 | 特征 | 目标值 |")
        add("|---|---|---|---|")
        keys = list(hard.keys())
        half = (len(keys) + 1) // 2
        for i in range(half):
            k1, k2 = keys[i], keys[i + half] if i + half < len(keys) else ""
            add(f"| {k1} | {hard[k1]} | {k2} | {hard[k2]} |" if k2 else f"| {k1} | {hard[k1]} | | |")
        add("")
    if l3:
        add("### L3 软画像（1–7）")
        add("")
        top6 = sorted(l3.items(), key=lambda x: -x[1])[:6]
        add("、" .join(f"{k} {v}" for k, v in top6) + "（其余维见 L3 基线 JSON）")
        add("")
    add("## 四、生成指令模板（可直接投喂）")
    add("")
    add('"""')
    add(prompt)
    add('"""')
    return "\n".join(A)


def main():
    ap = argparse.ArgumentParser(description="三件套人设卡合成（通用版）")
    ap.add_argument("--name", required=True, help="对象标识（ASCII，用于文件名，如 alice）")
    ap.add_argument("--display-name", default="", help="人读名（如 某老师）")
    ap.add_argument("--spi-clusters", help="SPI 聚类 JSON（含 cluster_summary）")
    ap.add_argument("--aot-profiles", help="AoT people_profiles.json")
    ap.add_argument("--aot-person", help="AoT 画像中的人名（与 --aot-profiles 搭配）")
    ap.add_argument("--wfp-baseline", help="WFP 硬指标基线 JSON（篇章级）")
    ap.add_argument("--l3-baseline", help="WFP L3 软评分基线 JSON")
    ap.add_argument("--people-baseline", help="WFP 块级七人基线 JSON（可选，补块级特征）")
    ap.add_argument("--people-key", help="块级基线中的对象 key")
    ap.add_argument("--spi-label-map", help="SPI 聚类名→生成端表述 映射 JSON（可选，叠加在默认修正表上）")
    ap.add_argument("--l3-config", default=L3_CONFIG_DEFAULT, help="L3 维度名映射 yaml")
    ap.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    args = ap.parse_args()

    label_map = load_json(args.spi_label_map)

    # 加载并校验 SPI
    spi_data = load_json(args.spi_clusters)
    if spi_data is not None:
        schemas.validate_spi_clusters(spi_data)
    spi = load_spi(spi_data)

    # 加载并校验 AoT
    aot_data = load_json(args.aot_profiles)
    if aot_data is not None:
        schemas.validate_aot_profiles(aot_data)
    aot = load_aot(aot_data, args.aot_person)

    # 加载并校验 WFP
    wfp_data = load_json(args.wfp_baseline)
    if wfp_data is not None:
        schemas.validate_wfp_baseline(wfp_data)
    l3_data = load_json(args.l3_baseline)
    if l3_data is not None:
        schemas.validate_l3_baseline(l3_data)
    hard, l3 = load_wfp(wfp_data, l3_data,
                        load_json(args.people_baseline), args.people_key, args.l3_config)

    if not (spi or aot or hard or l3):
        print("错误：未提供任何画像输入，无法合成人设卡。", file=sys.stderr)
        sys.exit(1)

    display = args.display_name or args.name
    prompt = build_prompt(None, hard, l3, aot, spi, label_map)
    persona = {
        "name": args.name,
        "display_name": display,
        "source": {
            "SPI": "32因子→15语义簇" if spi else None,
            "AoT": "270构念→25维" if aot else None,
            "WFP": "硬指标+17软维度" if (hard or l3) else None,
        },
        "spi_personality": spi,
        "aot_thinking": aot,
        "wfp_style": {"hard": hard, "l3": l3},
    }
    os.makedirs(args.out_dir, exist_ok=True)
    persona_path = os.path.join(args.out_dir, f"persona_{args.name}.json")
    md_path = os.path.join(args.out_dir, f"三件套人设卡_{args.name}.md")
    json.dump(persona, open(persona_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(md_path, "w", encoding="utf-8").write(render_md(persona, hard, l3, aot, spi, prompt))
    print(f"人设卡已生成：{persona_path}")
    print(f"人读版：{md_path}")
    got = [k for k, v in [("SPI", spi), ("AoT", aot), ("WFP", hard or l3)] if v]
    print(f"已合成模块：{' + '.join(got)}")


if __name__ == "__main__":
    main()
