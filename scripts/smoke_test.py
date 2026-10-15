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
 6. iterative_generate、build_l3_baseline（含失败分过滤、空目录报错）

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


WFP_ROOT = find_wfp_root()
WFP_SCRIPTS = WFP_ROOT / "scripts"
ENV = dict(os.environ, WFP_ROOT=str(WFP_ROOT))
N_OK = 0


def run(cmd: list, expect_rc: int = 0) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", env=ENV)
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
         "--corpus-dir", a_dir, "--out-dir", out])
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
    r = run([sys.executable, WFP_SCRIPTS / "validate_discrimination.py", "--baseline", bl_path,
             "--corpus", a_dir, "--other-author", b_dir, "--rounds", "2"])
    check("判别比" in r.stdout, "validate_discrimination 自动模式（--other-author）跑通")

    # 5. iterative_generate
    prompt = tmp / "p.txt"
    prompt.write_text("原始 prompt", encoding="utf-8")
    it = json.loads(run([sys.executable, SCRIPT_DIR / "iterative_generate.py", "--baseline", bl_path,
                         "--gen-fp", fps["ctrl"], "--original-prompt", prompt, "--json"]).stdout)
    check(bool(it.get("top_deviations")), "iterative_generate 输出偏项")

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


if __name__ == "__main__":
    main()
