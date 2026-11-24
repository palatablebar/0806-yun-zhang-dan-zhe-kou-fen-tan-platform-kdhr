# 云账单折扣分摊台规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 用量归集 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 折扣分摊 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 额度复核 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 关账结转 | 生成下月结转批次与逐户依据 | `POST /api/carries/from-run/<id>` | `app/carry/domain.py`、`app/carry/service.py` | `tests/test_carry_domain.py`、`tests/test_carry_service.py` |
| M9 补录与原子签发 | 补录并入未签发批次并整批签发 | `POST .../supplement、POST /api/carries/<id>/issue` | `app/carry/store.py`、`app/carry/intake.py` | `tests/test_carry_http.py`、`tests/test_carry_concurrency.py` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

金额以分为最小单位。归集正用量，以最大余额法补齐尾分。同余数时按记录键排序。账户额度不足退回复核。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`。

## 关账结转规则

- 结转额 `carry_cents = cap_cents - issued_cents`，依据在执行批次时冻结于 `measure.ledger`，关账后不被任何补录改写。
- 仅 `APPROVED` 运行可结转（`RUN_NOT_CLOSED`）。同一关账运行的结转批次 ID 由规则版本与运行 ID 派生，重复回放只保留一条。
- 补录来源只改写未签发的下月批次；已签发批次拒绝补录（`CARRY_FINALIZED`），已关账账期报告保持原样可追溯。
- 完全相同的逐户补录视为已核对重复回放：金额不变、来源指纹登记到 `origins`，批次标记 `pending_supplement`（待补）。
- 任一账户超额（`OVER_CAP`）、账户额度缺失（`CAP_MISSING`）或折扣池缺失（`POOL_MISSING`）即整批 `BLOCKED`，阻断清单列出记录键；签发时整批阻断，批次状态与修订号原样保留。
- 签发走单条条件 UPDATE（`status != 'ISSUED'`），报告与状态同事务写入，要么完整生效要么保持原样，避免半批结果。
- 每个批次保留 `events` 事件链（CREATED/SUPPLEMENT/ISSUED）与来源指纹，证据见 `app/carry/evidence.py`。
