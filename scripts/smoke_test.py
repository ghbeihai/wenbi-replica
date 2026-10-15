#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test：用小样例跑通整个流水线，每次 push 前必跑。

跑通以下环节：
1. 生成小样例语料（3 篇短文）
2. 提取硬指标指纹
3. 生成基线
4. schema 校验基线
5. 跑判别力自检（手动模式）

跑不过禁止发版。

用法：
  python3 scripts/smoke_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WFP_ROOT = os.environ.get("WFP_ROOT", "/home/user/Documents/opensource/wfp-toolkit")
SCRIPT_DIR = Path(__file__).parent
WFP_SCRIPTS = Path(WFP_ROOT) / "scripts"


def run(cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
    """运行命令，失败直接退出"""
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, encoding="utf-8")
    if r.returncode != 0:
        print(f"FAIL: {' '.join(cmd)}", file=sys.stderr)
        print(f"stderr: {r.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return r


def main():
    print("=== Smoke Test 开始 ===")

    # 1. 建临时目录
    tmp = tempfile.mkdtemp(prefix="wenbi_smoke_")
    print(f"临时目录: {tmp}")

    # 2. 生成 3 篇小样例语料
    sample1 = """今天天气很好。我去公园散步，看到很多人在锻炼身体。有的在跑步，有的在打太极。
我觉得坚持运动很重要，身体是革命的本钱。每天坚持半小时，一年下来会有很大变化。
很多人说没时间，但时间就像海绵里的水，只要愿挤，总还是有的。"""

    sample2 = """学习是一件长期的事情。不能急功近利，要循序渐进。
我当年学英语的时候，每天背 50 个单词，坚持了一年。后来词汇量突破了 15000。
所以说，坚持比天赋更重要。只要方向对了，慢一点也没关系。"""

    sample3 = """健康管理的核心是自律。不是说要完全戒掉美食，而是要懂得节制。
我平时喜欢吃甜食，但每天只吃一小块。这样既满足了口腹之欲，又不会过量。
很多人减肥失败，就是因为太极端了，一下子什么都不吃，最后反而反弹。"""

    files = []
    for i, text in enumerate([sample1, sample2, sample3]):
        f = Path(tmp) / f"sample_{i}.txt"
        f.write_text(text, encoding="utf-8")
        files.append(str(f))
    print(f"✓ 生成 {len(files)} 篇小样例")

    # 3. 提取硬指标指纹（每篇）
    fps = []
    for f in files:
        r = run([sys.executable, str(WFP_SCRIPTS / "extract_hard_metrics.py"), f, "--json"])
        fp = json.loads(r.stdout)
        fps.append(fp)
    print(f"✓ 提取 {len(fps)} 篇指纹")

    # 4. 生成基线（手动模拟 replicate.py 的聚合）
    baseline = {
        "n_docs": len(fps),
        "avg_chars": sum(fp.get("chars", 0) for fp in fps) // len(fps),
        "baseline": {},
    }
    # 简单聚合：取平均值
    for k in fps[0]:
        v = fps[0][k]
        if isinstance(v, (int, float)):
            vals = [fp[k] for fp in fps if isinstance(fp.get(k), (int, float))]
            if vals:
                baseline["baseline"][k] = {
                    "mean": sum(vals) / len(vals),
                    "sd": 1.0,  # smoke test 不精确，随便给个非零值
                    "n": len(vals),
                }

    baseline_path = Path(tmp) / "baseline.json"
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 生成基线（{len(baseline['baseline'])} 个特征）")

    # 5. schema 校验基线
    sys.path.insert(0, str(SCRIPT_DIR))
    import schemas
    schemas.validate_wfp_baseline(baseline)
    print(f"✓ schema 校验通过")

    # 6. 跑判别力自检（手动模式）
    held_file = str(Path(tmp) / "held.txt")
    control_file = str(Path(tmp) / "control.txt")
    Path(held_file).write_text(sample1, encoding="utf-8")
    Path(control_file).write_text(sample2, encoding="utf-8")

    r = run([
        sys.executable, str(WFP_SCRIPTS / "validate_discrimination.py"),
        "--baseline", str(baseline_path),
        "--held-out", held_file,
        "--control", control_file,
        "--json",
    ])
    result = json.loads(r.stdout)
    print(f"✓ 判别力自检跑完（比值 {result['ratio']}）")

    print("\n=== Smoke Test 全部通过 ===")
    print(f"临时目录: {tmp}（可以删掉）")


if __name__ == "__main__":
    main()
