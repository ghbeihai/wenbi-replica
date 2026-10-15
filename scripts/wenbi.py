#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文笔复刻 统一入口：
  wenbi.py doctor   [--corpus-dir D] [--out-dir O]   环境/语料/进度自检 + 下一步提示
  wenbi.py train    <replicate.py 参数>               建基线 + 人设卡（训练）
  wenbi.py generate <closed_loop.py 参数>             按用途/平台生成（闭环）
  wenbi.py presets                                    列出用途预设
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CMDS = {"doctor": "doctor.py", "train": "replicate.py", "generate": "closed_loop.py", "presets": "gen_spec.py"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") else 2)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "presets":
        rest = ["--list"] + rest
    sys.exit(subprocess.call([sys.executable, os.path.join(HERE, CMDS[cmd])] + rest))


if __name__ == "__main__":
    main()
