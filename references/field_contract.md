# 字段命名规范（接口契约）

所有脚本的输入输出必须遵守此规范，避免同一个字段在不同脚本里叫不同名字。

## 1. 命名规则

- **内部字段**：统一用带编号的字段名，如 `L1_LEX_004_yqci_per_k`
- **人读字段**：只有在最终人设卡（.md）里才翻译成中文名，如"语气词/千字"
- **不允许**：脚本内部出现中文名键，或同一个字段在不同脚本里叫不同名字

## 2. 字段分层

| 前缀 | 层级 | 含义 |
|---|---|---|
| L1_SYN_xxx | 句法层 | 句长、问句、句长波动 |
| L1_LEX_xxx | 词汇层 | 词汇多样性、语气词、衔接词、人称代词、情感词 |
| L2_DIS_xxx | 语篇层 | 段落、论证结构 |
| L2_SUR_xxx | 语篇修辞 | 句群、详略 |
| L3_xxx | 软评分 | 叙事修辞 14 维（1-7 分） |
| L4_xxx | 深层 | 隐喻、正负面情绪 |

## 3. 归一化后缀

| 后缀 | 含义 | 说明 |
|---|---|---|
| `_per_k` | 每千字密度 | 频次类指标统一用这个 |
| `_total` | 字典展开后的总和 | 基线聚合时从字典字段生成 |
| `_ratio` | 比率 | 如我:你比例 |
| `_avg_sl` | 平均句长 | |
| `_per_doc` | 每篇（已废弃） | 不要用，统一改成 _per_k |

## 4. 中间文件格式

### wfp_baseline.json
```json
{
  "n_docs": 42,
  "avg_chars": 342,
  "baseline": {
    "L1_SYN_001_avg_sl": {"mean": 25.1, "sd": 8.2, "n": 42},
    "L1_LEX_004_yqci_per_k_total": {"mean": 5.7, "sd": 2.1, "n": 42}
  }
}
```

### spi_cluster_all.json
```json
{
  "cluster_summary": [
    {"cluster": "C1", "label": "情感温暖", "n_first": 5, "n_top5": 12, "avg_relevance": 0.85}
  ]
}
```

### people_profiles.json
```json
{
  "person_id": {
    "name": "中文名",
    "n_dims": 25,
    "top5": [
      {"dim": "dim1", "dim_name": "中文维度名", "mean": 5.5, "evidence": ["原文片段"]}
    ]
  }
}
```

## 5. 错误处理原则

- **传了参数但内容为空** → 报错退出，不要静默跳过
- **没传参数** → 跳过（最小闭环模式）
- **字段格式不对** → 报错退出，列出具体缺哪个字段
- **单篇语料解析失败** → 警告并跳过该篇，但最后要统计成功/失败数量

## field_map v3（wfp-toolkit field_map.py，FIELD_MAP_VERSION = 3）

`validate_discrimination` / `normalize_backtest` / `merge_fingerprint` / `replicate`（基线）/
`iterative_generate` 全部调用 `field_map.flatten()` + `field_map.delta()`，不再各自维护口径。

| 指纹原字段 | Delta / 基线字段 | 说明 |
|---|---|---|
| `L1_SYN_004_question_sents`（按篇） | `L1_SYN_004_question_per_k` | ×1000/chars |
| `L1_SYN_004_rhet_sents`（按篇） | `L1_SYN_004_rhet_per_k` | ×1000/chars |
| `L1_LEX_005_dm`（字典，原始计数） | `L1_LEX_005_dm_per_k_total` | 求和后 ×1000/chars |
| 其他 `*_per_k` 字典 | `*_per_k_total` | 求和 |
| `L2_DIS_001_paras` | —（排除） | 篇幅量 |
| `L4_SUR_001_meta_domains(_total)` | —（重复） | 与 `L4_SUR_001_meta_per_k` 相等 |

| `L1_LEX_002_ttr_word` | —（v3 排除） | 原始 TTR 随篇长单调下降；词汇多样性用 `L1_LEX_001_sttr100` |
| `L1_LEX_006_wo_ni_ratio`、`L4_SUR_003_pos_neg_ratio` | 同名（v3 口径） | (a+1)/(b+1) 平滑，分母为 0 不再爆炸；v<3 旧基线自动跳过这两项 |
| 句长簇 6 项（avg/sd/med/short/long/burstiness） | 同名 | 共享权重 3.0（每项 0.5），避免同一信号重复计票 |

- 基线聚合唯一实现：`field_map.aggregate_baseline()`（`replicate.py` 与 `extract_hard_metrics.py --summary` 共用，逐项相同）；
  sd 为样本标准差（n-1）；输出含 `doc_ids`（文件名 stem）、`missing_features`、`field_map_version`。
- 退化检查 `check_baseline()`：篇数 <5 或 sd>0 的可用特征 <10 → `DegenerateBaseline`，所有 Delta 消费者报错退出；
  空文本 → `EmptyText` 报错（不再 per_k=0）。
- 迭代修正 prompt 用 `field_map.FEATURE_LABELS` 的中文标签。
- 旧基线（无 `field_map_version`）由 `baseline_stat()` 用 `avg_chars` 近似换算，建议重建基线。
