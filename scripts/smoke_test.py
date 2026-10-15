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
 9. v3opt：体裁识别 + --genre-force + 语料闸门 + 同体裁回测；指纹/LLM/基线缓存命中；ruler extend/learn/score + 隐喻并入；
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
    # --genre-force：用户声明整份语料同一体裁，跳过自动识别
    of = tmp / "out_force"
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "f", "--corpus-dir", a_dir, "--out-dir", of,
             "--genre-force", "lecture", "--genre-force-note", "用户声明：全部是在线讲课稿"])
    gf = json.loads((of / "genre_report.json").read_text(encoding="utf-8"))
    bf = json.loads((of / "wfp_baseline_f.json").read_text(encoding="utf-8"))
    check(gf.get("forced") and gf["force_genre"] == "lecture" and gf["main_genre"] == "lecture"
          and bf.get("genre") == "lecture" and bf["n_docs"] == len(list(a_dir.glob("*.txt")))
          and "用户声明" in r.stderr and "讲座" in (of / "三件套人设卡_f.md").read_text(encoding="utf-8"),
          f"replicate --genre-force lecture：全部 {bf['n_docs']} 篇进主基线，genre_report.forced=true")
    # --genre-force：用户声明整份语料同一体裁，跳过自动识别
    of = tmp / "out_force"
    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "f", "--corpus-dir", a_dir, "--out-dir", of,
             "--genre-force", "lecture", "--genre-force-note", "用户声明：全部是在线讲课稿"])
    gf = json.loads((of / "genre_report.json").read_text(encoding="utf-8"))
    bf = json.loads((of / "wfp_baseline_f.json").read_text(encoding="utf-8"))
    check(gf.get("forced") and gf["force_genre"] == "lecture" and gf["main_genre"] == "lecture"
          and bf.get("genre") == "lecture" and bf["n_docs"] == len(list(a_dir.glob("*.txt")))
          and "用户声明" in r.stderr and "讲座" in (of / "三件套人设卡_f.md").read_text(encoding="utf-8"),
          f"replicate --genre-force lecture：全部 {bf['n_docs']} 篇进主基线，genre_report.forced=true")
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
    # 体裁偏离：目标基线是讲稿，mock 生成的是随笔 → 仍按目标基线打分（各轮同一把尺子），并回灌"改回体裁"
    lg = tmp / "loop_genre"
    gbl = og / "wfp_baseline_g.json"
    run([sys.executable, SCRIPT_DIR / "closed_loop.py", "--persona-md", persona_md, "--baseline", gbl,
         "--task", "写一篇谈读书的短文", "--out-dir", lg, "--rounds", "3"], env=MOCK)
    lgr = json.loads((lg / "loop_report.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(WFP_SCRIPTS))
    import ruler
    gb = json.loads(gbl.read_text(encoding="utf-8"))
    same_ruler = all(h["composite"] == ruler.score(ruler.vector(json.loads(
        (lg / f"round_{h['round']}_fp.json").read_text(encoding="utf-8"))), gb)["composite"] for h in lgr["rounds"])
    mm = [h["round"] for h in lgr["rounds"] if h["genre_mismatch"] and h["round"] < 3]
    check(same_ruler and mm and "体裁偏离" in (lg / f"round_{mm[0] + 1}_prompt.txt").read_text(encoding="utf-8"),
          "closed_loop：体裁偏离时仍用目标基线打分（逐轮可比）并回灌体裁修正")
    _gen_config(tmp, a_dir, bl_path, persona_md)


def _gen_config(tmp: Path, a_dir: Path, bl_path: Path, persona_md: Path):
    sys.path.insert(0, str(WFP_SCRIPTS))
    import genre as genre_mod
    # 1. 优先级：预设 < 配置文件 < 命令行；可选格式默认不加
    gc = tmp / "gen.yaml"
    gc.write_text("purpose: 小红书图文\nlength: 900\ntone: 配置里的语气\n", encoding="utf-8")
    t = run([sys.executable, SCRIPT_DIR / "gen_spec.py", "--gen-config", gc, "--topic", "维生素怎么吃",
             "--tone", "命令行的语气", "--extra", "不要提品牌"]).stdout
    check("约 900 字" in t and "命令行的语气" in t and "配置里的语气" not in t and "不要提品牌" in t
          and "小红书图文" in t and "话题标签" not in t, "生成配置：预设 < 配置文件 < 命令行，可选格式默认不加")
    t2 = run([sys.executable, SCRIPT_DIR / "gen_spec.py", "--purpose", "小红书图文", "--topic", "x",
              "--with-optional-format"]).stdout
    check("话题标签" in t2 and "约 600 字" in t2, "生成配置：--with-optional-format 才加 emoji/话题标签；预设默认字数")
    run([sys.executable, SCRIPT_DIR / "gen_spec.py", "--purpose", "不存在的平台", "--topic", "x"], expect_rc=1)
    run([sys.executable, SCRIPT_DIR / "closed_loop.py", "--persona-md", persona_md, "--baseline", bl_path,
         "--out-dir", tmp / "x_loop"], expect_rc=1, env=MOCK)
    ok("生成配置：未知预设、没给题目 → 报错提示先定用途/字数/题目")
    p = run([sys.executable, SCRIPT_DIR / "wenbi.py", "presets"]).stdout
    check(all(k in p for k in ("口播稿", "公众号文章", "朋友圈", "小红书图文", "知乎回答", "演讲稿")), "wenbi.py presets 列出用途预设")
    # 2. 闭环：公众号 + L3 回灌 + relax + few-shot 体裁优先
    l3bl = tmp / "l3_mock_bl.json"
    lp = tmp / "loop_purpose"
    run([sys.executable, SCRIPT_DIR / "closed_loop.py", "--persona-md", persona_md, "--baseline", bl_path,
         "--corpus-dir", a_dir, "--purpose", "公众号文章", "--topic", "谈读书", "--length", "800",
         "--l3-baseline", l3bl, "--out-dir", lp], env=MOCK)
    rep = json.loads((lp / "loop_report.json").read_text(encoding="utf-8"))
    check(rep["spec"]["purpose"] == "公众号文章" and "公众号文章" in (lp / "round_1_prompt.txt").read_text(encoding="utf-8"),
          "closed_loop：写作要求（用途/题目/字数）进 prompt 与报告")
    check(all(h["l3_scored"] and "L3" in h["layers"] for h in rep["rounds"]), "closed_loop：每轮 L3 软评分进分层打分")
    l3fb = any(f["feature"].startswith("L3::") for h in rep["rounds"] for f in h["feedback"])
    check(l3fb or all(h["layers"]["L3"]["score"] < 1.0 for h in rep["rounds"]),
          "closed_loop：L3 偏差进回灌（有显著偏差时）")
    leaked = []
    for h in rep["rounds"][:-1]:
        raw = (lp / f"round_{h['round'] + 1}_prompt.txt").read_text(encoding="utf-8")
        # 只检查「表层文风」回灌段（思维依从段不应含 WFP 特征名）
        nxt = raw.split("【上一稿表层文风")[-1] if "【上一稿表层文风" in raw else raw.split("【上一稿文风偏差")[-1]
        # 放松特征的修正措辞不该出现；「仅报告」可以在报告里
        leaked += [f["label"] for f in h["feedback"] if f.get("relaxed") and (f["label"]+"：") in nxt and "不强制修正" not in nxt.split(f["label"]+"：",1)[-1][:40]]
    n_rel = sum(len(h["relaxed_deviations"]) for h in rep["rounds"])
    md = (lp / "loop_report.md").read_text(encoding="utf-8")
    check(not leaked and set(rep["relaxed_features"]) >= {"L1_SYN_003_punct_per_k_total"}
          and (n_rel == 0 or "只报告不强制修正" in md),
          f"closed_loop：与平台冲突的偏差只报告不回灌（本次 {n_rel} 条，泄漏 {leaked}）")
    gs = [genre_mod.classify_rule((a_dir / f"{d}.txt").read_text(encoding="utf-8"))["genre"] for d in rep["fewshot"]]
    check(len(rep["fewshot"]) == 3 and gs[:2] == ["essay", "essay"],
          f"few-shot 取自作者原文且优先用途体裁（{list(zip(rep['fewshot'], gs))}）")
    # 3. doctor：缺 key → ✗ + 退出 1；有 key 不显示内容；训练完成后提示问用途
    nok = dict(ENV, WENBI_ENV_FILE="/nonexistent")
    r = run([sys.executable, SCRIPT_DIR / "doctor.py"], expect_rc=1, env=nok)
    check("✗ DEEPSEEK_API_KEY" in r.stdout and "platform.deepseek.com" in r.stdout and "请提供要复刻" in r.stdout,
          "doctor：缺 key / 缺语料时中文提醒（怎么设 key、原文格式与数量）")
    fake = "sk-smoke-NOT-A-REAL-KEY-123"
    r = subprocess.run([sys.executable, SCRIPT_DIR / "doctor.py", "--corpus-dir", a_dir, "--out-dir", tmp / "out",
                        "--json"], capture_output=True, text=True, env=dict(nok, DEEPSEEK_API_KEY=fake))
    d = json.loads(r.stdout)
    key = [i for i in d["items"] if i["item"] == "DEEPSEEK_API_KEY"][0]
    check(key["level"] == "ok" and fake not in r.stdout and d["stage"] == "ready_to_generate"
          and "用途/平台" in d["next"] and "字数" in d["next"], "doctor：key 不回显；训练完成后提示先问用途/平台、字数、题目")
    one = tmp / "doc_few"
    one.mkdir()
    shutil.copy(sorted(a_dir.glob("*.txt"))[0], one)
    r = run([sys.executable, SCRIPT_DIR / "wenbi.py", "doctor", "--corpus-dir", one, "--json"], expect_rc=1,
            env=dict(nok, DEEPSEEK_API_KEY=fake))
    check(json.loads(r.stdout)["stage"] == "need_corpus", "doctor：语料不足 5 篇 → 阻塞并提示补原文")
    # SPI+AoT 先导：大纲进 prompt；依从主尺；选最佳看依从
    pj = tmp / "out_full" / "persona_full.json"
    if not pj.exists():
        # 最小 persona（仅 SPI/AoT 字段）供大纲
        pj = tmp / "persona_min.json"
        pj.write_text(json.dumps({
            "name": "smoke", "display_name": "样例",
            "spi_personality": [{"label": "Analytical Cognition", "n_first": 2, "n_top5": 3, "avg_relevance": 5}],
            "aot_thinking": [{"dim_name": "抽象-具体转换", "mean": 5.5, "evidence": ["先讲清楚再举例"]}],
            "wfp_style": {"hard": {}, "l3": {}},
        }, ensure_ascii=False), encoding="utf-8")
    lo2 = tmp / "loop_spi_first"
    run([sys.executable, SCRIPT_DIR / "closed_loop.py", "--persona-md", persona_md, "--persona-json", pj,
         "--baseline", bl_path, "--purpose", "口播稿", "--topic", "维生素怎么吃", "--length", "600",
         "--corpus-dir", a_dir, "--out-dir", lo2, "--rounds", "2"], env=MOCK)
    r2 = json.loads((lo2 / "loop_report.json").read_text(encoding="utf-8"))
    p1 = (lo2 / "round_1_prompt.txt").read_text(encoding="utf-8")
    ol = json.loads((lo2 / "outline.json").read_text(encoding="utf-8"))
    check((lo2 / "outline.json").exists() and ("篇章框架" in p1 or "思维大纲" in p1)
          and (p1.find("篇章框架") if "篇章框架" in p1 else p1.find("思维大纲")) < p1.find("【写作要求】"),
          "SPI+AoT 先导：先产出篇章框架，且框架块在写作要求之前")
    check(ol.get("stance") and (ol.get("sections") or ol.get("thesis_arc") or ol.get("outline_text")),
          "框架含立场 + 结构/弧线（非空条目堆）")
    check((lo2 / "edge_profile.json").exists() or ol.get("edge"),
          "棱角画像写入 edge_profile.json 或 outline.edge")
    check("棱角" in p1, "生成 prompt 含棱角画像硬约束")
    check(r2.get("best_adherence") is not None and "adherence" in r2["rounds"][0]
          and r2.get("best_edge") is not None
          and ("棱角" in (lo2 / "loop_report.md").read_text(encoding="utf-8")
               or "SPI+AoT" in (lo2 / "loop_report.md").read_text(encoding="utf-8")),
          f"闭环主尺=依从+棱角+结构（依从 {r2.get('best_adherence')}｜棱角 {r2.get('best_edge')}）")
    check(float(r2.get("temperature") or 0) >= 1.0, f"棱角模式默认抬高温度（实际 {r2.get('temperature')}）")
    if (lo2 / "round_2_prompt.txt").exists():
        p2 = (lo2 / "round_2_prompt.txt").read_text(encoding="utf-8")
        check(("思维依从" in p2 or "棱角" in p2) and p2.find("表层文风") > 0
              and min(i for i in (p2.find("思维依从"), p2.find("棱角")) if i >= 0) < p2.find("表层文风"),
              "回灌：依从/棱角块在表层文风之前")
    # 人设卡第四节顺序：SPI/AoT 在 WFP 数值前
    md_full = (tmp / "out_full" / "三件套人设卡_full.md")
    if md_full.exists():
        md = md_full.read_text(encoding="utf-8")
        sec = md.split("## 四、")[-1]
        check(sec.find("人格底色") < sec.find("表层说法") or sec.find("SPI") < sec.find("WFP")
              or "生成顺序" in sec,
              "人设卡第四节：SPI/AoT 先导说明在 WFP 表层之前")


    # —— 棱角保留单元检查（通用，不绑定具体作者）——
    sys.path.insert(0, str(SCRIPT_DIR))
    import edge_profile, gen_spec, topic_outline, llm_common
    ep = edge_profile.build({
        "name": "t",
        "spi_personality": [{"label": "A", "avg_relevance": 0.9, "n_first": 10},
                            {"label": "B", "avg_relevance": 0.1, "n_first": 1}],
        "aot_thinking": [{"dim_name": "高维", "mean": 6.0, "evidence": ["这个东西一定有问题。"]},
                         {"dim_name": "低维", "mean": 2.0, "evidence": ["也许"]}],
    })
    check(ep["enabled"] and ep["high_spi"][0]["label"] == "A" and any("低维" in b for b in ep["hard_bans"])
          and ep["sharp_evidence"] and "棱角画像" in edge_profile.block(ep),
          "edge_profile：高偏置 SPI/AoT + 尖锐证据 + 低维硬禁")
    check(edge_profile.load_cfg().get("enabled") is True
          and float(edge_profile.load_cfg().get("generation_temperature", 0)) >= 1.0,
          "edge_preserve.yaml 默认开启且温度≥1.0")
    efs = tmp / "edge_fs"; efs.mkdir(exist_ok=True)
    (efs / "a.txt").write_text(("今天天气不错我们来聊聊日常饮食习惯和一些可能的建议也许对你有帮助。") * 3, encoding="utf-8")
    (efs / "b.txt").write_text(("没那回事！你说对不对？这个东西一定有问题，别指望神药，必须先讲清楚。") * 3, encoding="utf-8")
    shots = gen_spec.pick_fewshot(str(efs), {"topic": "营养", "genre_pref": ""}, n=1, prefer_edge=True)
    check(shots and shots[0]["doc_id"] == "b", "few-shot 优先棱角段")
    hist = [
        {"adherence": {"score": 4, "structure_score": 4}, "edge": {"score": 4}, "composite": 1.0},
        {"adherence": {"score": 7, "structure_score": 7}, "edge": {"score": 7}, "composite": 3.0},
    ]
    def _rank(h):
        ad, eg, st = (h.get("adherence") or {}).get("score"), (h.get("edge") or {}).get("score"), (h.get("adherence") or {}).get("structure_score")
        primary = sum(v for v in (ad, eg, st) if v is not None) / 3
        return (-primary, h["composite"])
    check(min(hist, key=_rank)["composite"] == 3.0, "选最佳：主尺棱角/依从优先于更低 WFP")
    role_txt = gen_spec.task_text({"role": "某领域专业营养师", "topic": "测", "purpose": "口播稿", "name": "口播"})
    check("作者身份/职业" in role_txt and "专业营养师" in role_txt, "生成配置 --role 进写作要求")
    plain = gen_spec.task_text({"plain_oral": True, "topic": "测", "purpose": "口播稿", "name": "口播"})
    check("大众口语" in plain and "剂量" in plain, "生成配置 --plain-oral 进写作要求")
    class _A:
        audience, plain_oral, purpose, topic, length, tone, format_notes, extra = "大众听众", None, "口播稿", "测", None, None, None, None
        relax, with_optional_format, fewshot, corpus_dir, role, gen_config, presets = None, False, None, None, None, None, None
    check(gen_spec.resolve(_A()).get("plain_oral") is True, "audience 含大众 → 自动 plain_oral")



    r = run([sys.executable, SCRIPT_DIR / "replicate.py", "--name", "nx", "--corpus-dir", a_dir, "--out-dir", tmp / "out_nx",
             "--genre", "off"])
    check("生成前请确定" in r.stdout and "--purpose" in r.stdout, "replicate 训练完成后提示用户确定用途/字数/题目")


if __name__ == "__main__":
    main()
