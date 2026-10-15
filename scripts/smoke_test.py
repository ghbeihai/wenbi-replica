#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test：用仓库内小样例（tests/fixtures/smoke，合成语料）端到端跑通流水线，每次 push 前必跑。

覆盖：
 1. replicate.py：提取指纹 → 聚合基线（field_map v2 口径）→ 人设卡
 2. schema 校验（schemas.py + validate_schemas.py）
 3. 人设卡第四节 prompt 含关键数值约束（含隐喻根域 top3）
 4. merge_fingerprint / normalize_backtest / validate_discrimination 三者 Delta 一致（共用 field_map）
 5. validate_discrimination 手动模式 + 自动模式（--other-author）
 6. iterative_generate（人读标签）、build_l3_baseline（含失败分过滤、空目录报错）
 7. 边界：单篇/空文本/退化基线报错、无 jieba 告警被转发、--summary 与 replicate 基线逐项相同、
    手动两关、自动模式 seed 可复现 + 基线重叠剔除
 9. v3opt：体裁识别 + 语料闸门 + 同体裁回测；指纹/LLM/基线缓存命中；ruler extend/learn/score + 隐喻并入；
    validate_discrimination --weights；LLM 盲测尺（mock）；生成闭环 closed_loop（mock，≤3 轮、保留最佳）
 8. 离线 mock LLM（WENBI_MOCK_LLM=flaky，首个请求 429 → 退避重试）：L3 score_stylistics + --l3-baseline-out、
    score_metaphor、SPI spi-quant spi/profile + aggregate_spi_profiles、AoT prepare_corpus + score_dimensions +
    aggregate_profiles，最后三模块合成人设卡并全量 schema 校验（找不到 SPI/AoT 仓库时这两段跳过并提示）

路径全部可移植：WFP_ROOT 取环境变量，否则依次尝试 <repo>/../wfp-toolkit、<repo>/../toolkits/wfp-toolkit。
用法：
  python3 scripts/smoke_test.py [--keep]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
FIXTURE = REPO / "tests" / "fixtures" / "smoke"


def find_wfp_root() -> Path:
    cands = [os.environ.get("WFP_ROOT", ""), REPO.parent / "wfp-toolkit", REPO.parent / "toolkits" / "wfp-toolkit"]
    for c in cands:
        if c and (Path(c) / "scripts" / "field_map.py").exists():
            return Path(c).resolve()
    print("FAIL: 找不到 wfp-toolkit（请设置 WFP_ROOT），尝试过：" + ", ".join(map(str, cands[1:])), file=sys.stderr)
    sys.exit(1)


def find_root(var: str, name: str, flag: str):
    for c in [os.environ.get(var, ""), REPO.parent / name, REPO.parent / "toolkits" / name]:
        if c and (Path(c) / flag).exists():
            return Path(c).resolve()
    return None


WFP_ROOT = find_wfp_root()
SPI_ROOT = find_root("SPI_ROOT", "spi-toolkit", "src/spi_quant/cli.py")
AOT_ROOT = find_root("AOT_ROOT", "aot-toolkit", "scripts/score_dimensions.py")
WFP_SCRIPTS = WFP_ROOT / "scripts"
ENV = dict(os.environ, WFP_ROOT=str(WFP_ROOT))
ENV.pop("DEEPSEEK_API_KEY", None)  # smoke 永远不用真 key（LLM 段走 mock）
MOCK = dict(ENV, WENBI_MOCK_LLM="flaky", WENBI_LLM_BACKOFF="0.001", WENBI_ENV_FILE="/nonexistent")
N_OK = 0


def run(cmd: list, expect_rc: int = 0, env: dict | None = None, cwd=None) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                       env=env or ENV, cwd=cwd)
    if r.returncode != expect_rc:
        print(f"FAIL (rc={r.returncode}, 期望 {expect_rc}): {' '.join(map(str, cmd))}", file=sys.stderr)
        print(f"stdout: {r.stdout[-800:]}\nstderr: {r.stderr[-800:]}", file=sys.stderr)
        sys.exit(1)
    return r


def ok(msg: str):
    global N_OK
    N_OK += 1
    print(f"✓ {msg}")


def check(cond: bool, msg: str):
    if not cond:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)
    ok(msg)


def main():
    ap = argparse.ArgumentParser(description="wenbi-replica 端到端 smoke test（合成小语料，无需 API key）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    args = ap.parse_args()

    a_dir, b_dir = FIXTURE / "author_a", FIXTURE / "author_b"
    check(len(list(a_dir.glob("*.txt"))) >= 10 and len(list(b_dir.glob("*.txt"))) >= 2,
          f"fixture 就位（{a_dir}）")
    tmp = Path(tempfile.mkdtemp(prefix="wenbi_smoke_"))
    for e in (ENV, MOCK):  # 每次 smoke 用全新缓存目录（否则 mock 429 重试会被缓存命中跳过）
        e["WENBI_CACHE_DIR"] = str(tmp / "cache")
    print(f"=== Smoke Test（WFP_ROOT={WFP_ROOT}，临时目录 {tmp}）===")
    try:
        _run_all(tmp, a_dir, b_dir)
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n=== Smoke Test 全部通过（{N_OK} 项）===")


def _run_all(tmp: Path, a_dir: Path, b_dir: Path):
    sys.path.insert(0, str(SCRIPT_DIR))
    sys.path.insert(0, str(WFP_SCRIPTS))
    import field_map
    import schemas

    # 1. replicate：基线 + 人设卡
    out = tmp / "out"
    run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "smoke", "--display-name", "样例作者",
         "--corpus-dir", a_dir, "--out-dir", out, "--genre", "off"])
    bl_path = out / "wfp_baseline_smoke.json"
    bl = json.loads(bl_path.read_text(encoding="utf-8"))
    check(bl.get("field_map_version") == field_map.FIELD_MAP_VERSION, "基线 field_map_version 与 field_map 一致")
    feats = field_map.delta_features()
    missing = [k for k in feats if k not in bl["baseline"]]
    check(not missing, f"基线包含全部 {len(feats)} 个 Delta 特征（缺 {missing}）")
    check("L4_SUR_001_meta_domains_total" not in feats and "L2_DIS_001_paras" not in feats,
          "重复/篇幅字段不参与 Delta")
    schemas.validate_wfp_baseline(bl)
    run([sys.executable, SCRIPT_DIR / "validate_schemas.py", "--wfp", bl_path])
    ok("schema 校验通过")

    # 2. 人设卡 prompt
    md = next(out.glob("三件套人设卡_*.md")).read_text(encoding="utf-8")
    tpl = md.split("## 四、")[-1]
    for k in ["平均句长", "语气词/千字", "话语标记/千字", "问句/千字", "隐喻/千字", "隐喻根域偏好"]:
        check(k in tpl, f"第四节 prompt 含「{k}」")

    # 3. 单篇指纹 → 三个消费者 Delta 一致
    held, ctrl = sorted(a_dir.glob("*.txt"))[0], sorted(b_dir.glob("*.txt"))[0]
    fps = {}
    for tag, f in [("held", held), ("ctrl", ctrl)]:
        r = run([sys.executable, WFP_SCRIPTS / "extract_hard_metrics.py", f, "--json"])
        p = tmp / f"{tag}.fp.json"
        p.write_text(r.stdout, encoding="utf-8")
        fps[tag] = p
    m = json.loads(run([sys.executable, WFP_SCRIPTS / "merge_fingerprint.py", fps["held"], fps["ctrl"],
                        "--baseline", bl_path, "--json"]).stdout)
    n = json.loads(run([sys.executable, WFP_SCRIPTS / "normalize_backtest.py", fps["held"],
                        "--baseline", bl_path, "--json"]).stdout)
    v = json.loads(run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
                        "--held-out", held, "--control", ctrl, "--json"]).stdout)
    d_m, d_n, d_v = m[0]["delta"], n["delta"], v["delta_held"]
    check(abs(d_m - d_n) < 0.01 and abs(d_m - d_v) < 0.01 and m[0]["n_features"] == n["n_features"],
          f"merge/normalize/validate Delta 一致（{d_m} / {d_n} / {d_v}，n={n['n_features']}）")
    check(v["ratio"] > 1.0, f"异风格对照 Delta 更大（判别比 {v['ratio']}）")

    # 4. 自动模式 + 他人对照
    #    基线就是用 a_dir 建的 → 自动留出全是基线内文档，必须被重叠检查拦下
    r = run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
             "--corpus", a_dir, "--other-author", b_dir, "--rounds", "2"], expect_rc=1)
    check("基线语料" in r.stderr, "自动模式：留出文与基线 doc_ids 重叠时剔除并报错")
    auto = [sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
            "--corpus", a_dir, "--other-author", b_dir, "--rounds", "2", "--seed", "7", "--allow-overlap", "--json"]
    r1, r2 = json.loads(run(auto).stdout), json.loads(run(auto).stdout)
    check(r1 == r2 and r1.get("rounds") == 2, "自动模式（--other-author，--allow-overlap）跑通且同 seed 结果可复现")
    run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
         "--corpus", a_dir, "--rounds", "0"], expect_rc=2)
    ok("--rounds 0 被参数校验拦下（原 ZeroDivisionError）")
    #    手动两关
    v2 = json.loads(run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
                         "--held-out", held, "--control", ctrl, "--other-author", ctrl, "--json"]).stdout)
    check(v2.get("n_gates") == 2 and "passed_control" in v2 and "passed_other" in v2, "手动模式 --control + --other-author 两关都跑")

    # 5. iterative_generate
    prompt = tmp / "p.txt"
    prompt.write_text("原始 prompt", encoding="utf-8")
    it = json.loads(run([sys.executable, SCRIPT_DIR / "iterative_generate.py", "--baseline", bl_path,
                         "--gen-fp", fps["ctrl"], "--original-prompt", prompt, "--json"]).stdout)
    check(bool(it.get("top_deviations")), "iterative_generate 输出偏项")
    corr = it["corrected_prompt"].split("【本轮修正要求】")[-1]
    check("L1_" not in corr and "L2_" not in corr and "L4_" not in corr,
          "修正 prompt 只用人读标签（不含内部字段名）")

    # 6. build_l3_baseline：失败分过滤 + 空目录报错
    l3 = tmp / "l3"
    l3.mkdir()
    (l3 / "a.json").write_text(json.dumps({
        "d1::D01": {"dim": "D01", "dim_name": "互动", "score": 5.5},
        "d1::D02": {"dim": "D02", "dim_name": "幽默", "score": None, "failed": True},
        "d1::D03": {"dim": "D03", "dim_name": "抽象", "score": 0.0, "simulated": True},
    }, ensure_ascii=False), encoding="utf-8")
    run([sys.executable, WFP_SCRIPTS / "build_l3_baseline.py", l3, "--out", tmp / "l3bl.json"])
    l3bl = json.loads((tmp / "l3bl.json").read_text(encoding="utf-8"))
    check(list(l3bl["baseline"]) == ["D01"], "build_l3_baseline 过滤 failed/simulated 分")
    schemas.validate_l3_baseline(l3bl)
    empty = tmp / "l3_empty"
    empty.mkdir()
    run([sys.executable, WFP_SCRIPTS / "build_l3_baseline.py", empty, "--out", tmp / "x.json"], expect_rc=1)
    ok("build_l3_baseline 空目录报错退出")

    _edge_cases(tmp, a_dir, b_dir, bl_path, held)
    _mock_llm(tmp, a_dir, bl_path)
    _v3opt(tmp, a_dir, b_dir, bl_path)


def _edge_cases(tmp: Path, a_dir: Path, b_dir: Path, bl_path: Path, held: Path):
    ex = WFP_SCRIPTS / "extract_hard_metrics.py"
    # 单篇语料 → 拒绝建基线
    one = tmp / "one"
    one.mkdir()
    shutil.copy(held, one / held.name)
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "one", "--corpus-dir", one,
             "--out-dir", tmp / "out_one"], expect_rc=1)
    check("无法建可信基线" in r.stderr, "单篇语料：replicate 报错退出（不再产出 sd=0 基线）")
    # 空文本
    empty = tmp / "empty.txt"
    empty.write_text("  \n\t ", encoding="utf-8")
    run([sys.executable, ex, empty, "--json"], expect_rc=1)
    ok("空文本：extract 报错退出")
    run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
         "--held-out", empty, "--control", held], expect_rc=1)
    ok("空文本：validate_discrimination 报错退出")
    run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "smoke", "--wfp-baseline", bl_path,
         "--out-dir", tmp / "out_bt", "--backtest", empty], expect_rc=1)
    ok("空生成文：replicate --backtest 报错退出")
    # 退化基线（1 篇手工基线）→ 下游都报错
    fp1 = tmp / "fp1.json"
    fp1.write_text(run([sys.executable, ex, held, "--json"]).stdout, encoding="utf-8")
    deg = tmp / "deg.json"
    one_bl = json.loads(bl_path.read_text(encoding="utf-8"))
    one_bl["n_docs"] = 1
    one_bl["baseline"] = {k: dict(v, sd=0.0, n=1) for k, v in one_bl["baseline"].items()}
    deg.write_text(json.dumps(one_bl, ensure_ascii=False), encoding="utf-8")
    for cmd in ([WFP_SCRIPTS / "merge_fingerprint.py", fp1, "--baseline", deg],
                [WFP_SCRIPTS / "normalize_backtest.py", fp1, "--baseline", deg],
                [WFP_SCRIPTS / "validate_discrimination.py", "--baseline", deg, "--held-out", held, "--control", held],
                [SCRIPT_DIR / "validate_schemas.py", "--wfp", deg]):
        run([sys.executable, *cmd], expect_rc=1)
    ok("退化基线（1 篇 / sd=0）：merge / normalize / validate / validate_schemas 全部报错（不再 999/判别比 1.0）")
    # 没装 jieba：告警必须穿透 replicate
    fake = tmp / "nojieba"
    fake.mkdir()
    (fake / "jieba.py").write_text('raise ImportError("smoke: 模拟未安装 jieba")\n', encoding="utf-8")
    env_nj = dict(ENV, PYTHONPATH=str(fake))
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "nj", "--corpus-dir", a_dir,
             "--out-dir", tmp / "out_nj"], env=env_nj)
    check("未安装 jieba" in r.stderr, "无 jieba：extract 的告警经 replicate 转发给用户")
    # --summary 与 replicate 基线逐项相同（同一 aggregate_baseline 实现）
    fpd = tmp / "fps"
    fpd.mkdir()
    for f in sorted(a_dir.glob("*.txt")):
        (fpd / f"{f.stem}.json").write_text(run([sys.executable, ex, f, "--json"]).stdout, encoding="utf-8")
    summ = json.loads(run([sys.executable, ex, "--summary", *sorted(fpd.glob("*.json")), "--name", "smoke"]).stdout)
    rep = json.loads(bl_path.read_text(encoding="utf-8"))
    check(summ["baseline"] == rep["baseline"] and summ["doc_ids"] == rep["doc_ids"]
          and rep["doc_ids"][0] == sorted(a_dir.glob("*.txt"))[0].stem,
          f"extract --summary 与 replicate 基线逐项相同，doc_ids 为真实文件名（{rep['doc_ids'][:2]}…）")
    # 无语料也无 WFP 基线 → 报错（原来会把 L3 基线当 WFP 基线）
    run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "x", "--l3-baseline", bl_path,
         "--out-dir", tmp / "out_x"], expect_rc=1)
    ok("replicate 无 --corpus-dir 且无 --wfp-baseline：报错（不再把 L3 基线当 WFP 基线）")
    # -h 不崩
    for p in sorted(WFP_SCRIPTS.glob("*.py")) + sorted(SCRIPT_DIR.glob("*.py")):
        if p.name in ("field_map.py", "llm_common.py", "data_sources.py", "schemas.py", "smoke_test.py"):
            continue
        run([sys.executable, p, "-h"])
    ok("WFP 与 replica 全部 CLI -h 正常")


def _mock_llm(tmp: Path, a_dir: Path, bl_path: Path):
    """离线 mock LLM：不需要 key、不花钱；flaky 模式每个请求首次 429，验证退避重试。"""
    # 无 key 时打分脚本必须退出 1（不能静默/模拟）
    nokey = dict(ENV, WENBI_ENV_FILE="/nonexistent")
    run([sys.executable, WFP_SCRIPTS / "score_stylistics.py", "--corpus-dir", a_dir, "--dims", "1",
         "--out-dir", tmp / "l3x"], expect_rc=1, env=nokey)
    ok("无 DEEPSEEK_API_KEY：score_stylistics 退出 1")
    l3dir, l3bl = tmp / "l3_mock", tmp / "l3_mock_bl.json"
    r = run([sys.executable, WFP_SCRIPTS / "score_stylistics.py", "--corpus-dir", a_dir, "--dims", "3",
             "--out-dir", l3dir, "--l3-baseline-out", l3bl], env=MOCK)
    check("[retry]" in r.stderr, "mock 429 → llm_common 指数退避重试")
    l3 = json.loads(l3bl.read_text(encoding="utf-8"))
    check(l3["n_docs"] == len(list(a_dir.glob("*.txt"))) and l3["n_dims"] == 3,
          f"score_stylistics --l3-baseline-out 产出 L3 基线（{l3['n_docs']} 篇 × {l3['n_dims']} 维）")
    run([sys.executable, SCRIPT_DIR / "validate_schemas.py", "--l3", l3bl])
    ok("validate_schemas --l3 通过")
    long_txt = tmp / "long.txt"
    long_txt.write_text("我们走在一条漫长的路上。" * 400 + "\n" + "生活就是一场战斗" * 300, encoding="utf-8")
    met = json.loads(run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", long_txt, "--json"], env=MOCK).stdout)
    check(met["n_chunks"] >= 3 and met["failed_chunks"] == [],
          f"score_metaphor：单段超长按句切块（{met['n_chunks']} 块）+ mock 识别")

    spi_bl, aot_bl, aot_person = None, None, None
    if SPI_ROOT:
        envs = dict(MOCK, PYTHONPATH=str(SPI_ROOT / "src"))
        prof = tmp / "spi_prof"
        prof.mkdir()
        for f in sorted(a_dir.glob("*.txt"))[:2]:
            run([sys.executable, "-m", "spi_quant.cli", "profile", "--file", f, "--out", prof / f"{f.stem}.json",
                 "--rounds", "1"], env=envs, cwd=SPI_ROOT)
        long_spi = json.loads(run([sys.executable, "-m", "spi_quant.cli", "spi", "--file", long_txt],
                                  env=envs, cwd=SPI_ROOT).stdout)
        check(long_spi.get("truncated") is True and long_spi.get("failed") is False,
              "SPI map_text：超长截断带 truncated 标记 + 退避重试成功")
        run([sys.executable, "-m", "spi_quant.cli", "profile", "-h"], env=envs, cwd=SPI_ROOT)
        ok("spi-quant profile -h 不再崩溃（%% 转义）")
        spi_bl = tmp / "spi_cluster_all.json"
        run([sys.executable, SPI_ROOT / "scripts" / "aggregate_spi_profiles.py", prof, "--out", spi_bl])
        s = json.loads(spi_bl.read_text(encoding="utf-8"))
        check(s["n_docs"] == 2 and all(c["n_top5"] <= 2 for c in s["cluster_summary"]),
              "aggregate_spi_profiles 汇总（每篇最多计 top5）")
    else:
        print("  - 跳过 SPI mock 段（找不到 spi-toolkit，设 SPI_ROOT）")
    if AOT_ROOT:
        corpus = tmp / "aot_corpus"
        run([sys.executable, AOT_ROOT / "scripts" / "prepare_corpus.py", a_dir, "--person", "smoke",
             "--name", "样例作者", "--out-dir", corpus])
        scores = tmp / "aot_scores"
        run([sys.executable, AOT_ROOT / "scripts" / "score_dimensions.py", "--corpus-dir", corpus,
             "--out-dir", scores, "--pilot", "1", "2"], env=MOCK)
        aot_bl = tmp / "people_profiles.json"
        run([sys.executable, AOT_ROOT / "scripts" / "aggregate_profiles.py", scores, "--names", "smoke=样例作者",
             "--out", aot_bl])
        aot_person = "样例作者"
        run([sys.executable, AOT_ROOT / "scripts" / "score_dimensions.py", "--full", "--dry-run",
             "--corpus-dir", tmp / "nope"], expect_rc=1)
        ok("AoT：prepare_corpus → score_dimensions(mock) → aggregate_profiles；缺语料目录明确报错")
    else:
        print("  - 跳过 AoT mock 段（找不到 aot-toolkit，设 AOT_ROOT）")

    cmd = [sys.executable, SCRIPT_DIR / "replicate.py", "--name", "full", "--display-name", "样例作者",
           "--wfp-baseline", bl_path, "--l3-baseline", l3bl, "--out-dir", tmp / "out_full"]
    if spi_bl:
        cmd += ["--spi-clusters", spi_bl]
    if aot_bl:
        cmd += ["--aot-profiles", aot_bl, "--aot-person", aot_person]
    run(cmd)
    persona = json.loads((tmp / "out_full" / "persona_full.json").read_text(encoding="utf-8"))
    check(bool(persona["wfp_style"]["l3"]) and (not spi_bl or persona["spi_personality"])
          and (not aot_bl or persona["aot_thinking"]),
          f"三模块合成人设卡（source={persona['source']}）")
    vcmd = [sys.executable, SCRIPT_DIR / "validate_schemas.py", "--wfp", bl_path, "--l3", l3bl]
    if spi_bl:
        vcmd += ["--spi", spi_bl]
    if aot_bl:
        vcmd += ["--aot", aot_bl]
    run(vcmd)
    ok("validate_schemas 全模块通过")


def _v3opt(tmp: Path, a_dir: Path, b_dir: Path, bl_path: Path):
    import field_map
    ex = WFP_SCRIPTS / "extract_hard_metrics.py"
    gdir = tmp / "genre"
    gdir.mkdir()
    samples = {
        "poetry": "春风又绿江南岸\n明月何时照我还\n\n独在异乡为异客\n每逢佳节倍思亲\n\n山重水复疑无路\n柳暗花明又一村\n",
        "dialogue": "甲：你今天去哪儿了？\n乙：我去图书馆了。\n甲：借了什么书？\n乙：一本小说。\n甲：好看吗？\n乙：还行吧。\n",
        "news": "新华社北京10月15日电 记者从有关部门获悉，截至9月底，全国已建成5G基站300万个。据介绍，"
                "相关负责人表示，下一步将继续推进网络建设。据统计，同比增长12%。\n",
    }
    for k, t in samples.items():
        (gdir / f"{k}.txt").write_text(t, encoding="utf-8")
    gj = json.loads(run([sys.executable, WFP_SCRIPTS / "genre.py", "--dir", gdir, "--json"]).stdout)
    got = {d: v["genre"] for d, v in gj["docs"].items()}
    check(all(got.get(k) == k for k in samples), f"genre.py 规则识别 诗歌/对话/新闻（{got}）")
    gl = json.loads(run([sys.executable, WFP_SCRIPTS / "genre.py", gdir / "poetry.txt", "--llm", "--json"],
                        env=MOCK).stdout)
    check(bool(gl), "genre.py --llm（mock）跑通")
    # 体裁闸门：混合语料（a 10 篇 + 3 篇异体裁）→ 主体裁基线 + 告警
    mix = tmp / "mix"
    shutil.copytree(a_dir, mix)
    for k in samples:
        shutil.copy(gdir / f"{k}.txt", mix / f"z_{k}.txt")
    og = tmp / "out_genre"
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "g", "--corpus-dir", mix, "--out-dir", og,
             "--backtest", gdir / "news.txt"])
    rep = json.loads((og / "genre_report.json").read_text(encoding="utf-8"))
    main_bl = json.loads((og / "wfp_baseline_g.json").read_text(encoding="utf-8"))
    check(sum(len(v) for v in rep["groups"].values()) == 13 and "体裁" in r.stderr and rep["warnings"],
          f"replicate 体裁分组 + 小组告警（{ {k: len(v) for k, v in rep['groups'].items()} }）")
    check(main_bl.get("genre") == rep["main_genre"] and main_bl["n_docs"] == len(rep["groups"][rep["main_genre"]]),
          f"主基线只用主体裁篇目（{rep['main_genre']} {main_bl['n_docs']} 篇）")
    check("跨体裁" in r.stderr, "回测：生成文体裁与基线不同且无同体裁基线 → 显式告警")
    persona = json.loads((og / "persona_g.json").read_text(encoding="utf-8"))
    check(persona.get("genre", {}).get("genre") == rep["main_genre"] and persona["analysis_only"] == rep["analysis_only"],
          "人设卡记录体裁与 analysis_only")
    # 闸门：太小（3 篇三种体裁）→ analysis_only
    tiny = tmp / "tiny"
    tiny.mkdir()
    for f in sorted(a_dir.glob("*.txt"))[:3]:
        shutil.copy(f, tiny / f.name)
    for k in samples:
        shutil.copy(gdir / f"{k}.txt", tiny / f"z_{k}.txt")
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "t", "--corpus-dir", tiny, "--out-dir",
             tmp / "out_tiny", "--min-docs", "4"])
    pt = json.loads((tmp / "out_tiny" / "persona_t.json").read_text(encoding="utf-8"))
    mdt = (tmp / "out_tiny" / "三件套人设卡_t.md").read_text(encoding="utf-8")
    check(pt["analysis_only"] and "analysis_only" in mdt and "analysis_only" in r.stderr,
          "体裁组过小/混杂 → 人设卡 analysis_only + 显式告警")
    # 基线缓存：同输入复用
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "g", "--corpus-dir", mix, "--out-dir", og])
    check("复用" in r.stdout, "基线 input_hash 未变 → 复用")
    # 指纹缓存
    f0 = sorted(a_dir.glob("*.txt"))[0]
    o1 = run([sys.executable, ex, f0, "--json"]).stdout
    o2 = run([sys.executable, ex, f0, "--json", "--no-cache"]).stdout
    check(json.loads(o1) == json.loads(o2) and any((tmp / "cache" / "fp").rglob("*.json")),
          "指纹缓存：命中结果与 --no-cache 重算一致")
    # LLM 缓存：同请求第二次不再 429 重试
    c2 = dict(MOCK, WENBI_CACHE_DIR=str(tmp / "cache_llm"))
    r1 = run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", f0, "--json"], env=c2)
    r2 = run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", f0, "--json"], env=c2)
    check("[retry]" in r1.stderr and "[retry]" not in r2.stderr and json.loads(r1.stdout) == json.loads(r2.stdout),
          "LLM 内容哈希缓存：第二次命中（无重试、结果一致）")
    r3 = run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", f0, "--json"], env=dict(c2, WENBI_NO_CACHE="1"))
    check("[retry]" in r3.stderr, "WENBI_NO_CACHE=1 关闭缓存")
    # ruler：隐喻 extend + learn + score
    fpa, fpb, md = tmp / "r_fpa", tmp / "r_fpb", tmp / "r_meta"
    for d in (fpa, fpb, md):
        d.mkdir()
    for f in sorted(a_dir.glob("*.txt")):
        (fpa / f"{f.stem}.json").write_text(run([sys.executable, ex, f, "--json"]).stdout, encoding="utf-8")
        run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", f, "--out", md / f"{f.stem}.json"], env=MOCK)
    for f in sorted(b_dir.glob("*.txt")):
        (fpb / f"{f.stem}.json").write_text(run([sys.executable, ex, f, "--json"]).stdout, encoding="utf-8")
        run([sys.executable, WFP_SCRIPTS / "score_metaphor.py", f, "--out", md / f"{f.stem}.json"], env=MOCK)
    rul = WFP_SCRIPTS / "ruler.py"
    ebl = tmp / "bl_ext.json"
    run([sys.executable, rul, "extend", "--baseline", bl_path, "--metaphor-dir", md, "--out", ebl])
    check("L4_LLM_meta_per_k" in json.loads(ebl.read_text(encoding="utf-8")).get("extra", {}),
          "ruler extend：LLM 隐喻密度并入基线（metaphor 进 Delta）")
    wj = tmp / "w.json"
    run([sys.executable, rul, "learn", "--baseline", ebl, "--pos", fpa, "--neg", fpb, "--length-fps", fpa,
         "--metaphor-dir", md, "--out", wj])
    w = json.loads(wj.read_text(encoding="utf-8"))
    pri = sum(field_map.weight(k) for k in w["features"] if not k.startswith("L3::") and k != "L4_LLM_meta_per_k")
    check(w["layers"] and all(v["weight"] > 0 for v in w["features"].values()) and pri > 0,
          f"ruler learn：分层权重（{ {k: v['weight_share'] for k, v in w['layers'].items()} }），只降权不删特征")
    sc = json.loads(run([sys.executable, rul, "score", fpb, "--baseline", ebl, "--weights", wj,
                         "--metaphor-dir", md, "--json"]).stdout)
    check(sc and sc[0]["composite"] is not None and "L4" in sc[0]["layers"] and "L1_SYN" in sc[0]["layers"],
          "ruler score：综合分 + 分层分（含 L4 隐喻）")
    held, ctrl = sorted(a_dir.glob("*.txt"))[0], sorted(b_dir.glob("*.txt"))[0]
    vw = json.loads(run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
                         "--held-out", held, "--control", ctrl, "--weights", wj, "--json"]).stdout)
    check(vw.get("ratio") is not None, f"validate_discrimination --weights（学习权重综合分，判别比 {vw.get('ratio')}）")
    # 盲测尺
    bt = json.loads(run([sys.executable, WFP_SCRIPTS / "blind_test.py", "--reference", a_dir, "--real", held,
                         "--fake", ctrl, "--json"], env=MOCK).stdout)
    p0 = bt["pairs"][0]
    check(bt["n_ok"] == 1 and len(p0["picks"]) == 2 and held.stem not in p0["refs"],
          f"LLM 盲测尺（mock）：正反两序 + 参考片段排除被测真文（P(识破)={bt['mean_p_real']}）")
    # 闭环
    lo = tmp / "loop"
    persona_md = next((tmp / "out").glob("三件套人设卡_*.md"))
    r = run([sys.executable, SCRIPT_DIR / "closed_loop.py", "--persona-md", persona_md, "--baseline", bl_path,
             "--task", "写一篇谈读书的短文", "--out-dir", lo, "--rounds", "5", "--weights", wj,
             "--blind-reference", a_dir], env=MOCK)
    lr = json.loads((lo / "loop_report.json").read_text(encoding="utf-8"))
    comps = [h["composite"] for h in lr["rounds"]]
    check(len(lr["rounds"]) == 3 and "上限" in r.stderr, f"closed_loop：--rounds 5 截到 3 轮（逐轮综合分 {comps}）")
    check(lr["best_composite"] == min(comps) and (lo / "best.txt").read_text(encoding="utf-8")
          == (lo / f"round_{lr['best_round']}.txt").read_text(encoding="utf-8"), "closed_loop：保留最佳轮")
    p2 = (lo / "round_2_prompt.txt").read_text(encoding="utf-8")
    check("偏离最大的层" in p2 and "原作者约" in p2 and "L1_" not in p2.split("【上一稿文风偏差")[-1],
          "closed_loop：分层偏差以中文标签回灌 prompt")
    check(all(h["layers"] for h in lr["rounds"]) and lr.get("blind_test", {}).get("mean_p_detect") is not None
          and (lo / "loop_report.md").exists(), "closed_loop：逐轮分层分数报告 + 盲测独立信号")


if __name__ == "__main__":
    main()
