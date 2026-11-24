"""结转领域规则：结转额、整批阻断、补录合并、幂等回放与待补标记。"""

import pytest

from app.business import DomainIssue
from app.carry.domain import (
    assert_issuable,
    classify,
    lines_from_run,
    merge_supplement,
    next_period,
)


def closed_run(run_id="r1", created="2026-11-24T08:00:00.000+00:00"):
    def measure(ledger, pool_cap=100, discount=100):
        return dict(
            value=sum(row["issued_cents"] for row in ledger),
            expected=discount,
            unit="分",
            evidence={row["record"]: row["issued_cents"] for row in ledger},
            flag=False,
            ledger=ledger,
            pool=dict(record="p", case=ledger[0]["case"], discount_cents=discount, cap_cents=pool_cap),
        )

    ledger_a = [
        dict(record="A1", case="C1", usage_units=1, cap_cents=40, issued_cents=34, carry_cents=6, basis="ledger:A1"),
        dict(record="A2", case="C1", usage_units=1, cap_cents=40, issued_cents=33, carry_cents=7, basis="ledger:A2"),
    ]
    return dict(
        id=run_id,
        status="APPROVED",
        revision=1,
        report=dict(
            manifest=dict(sha256="fp-src", created=created),
            cases=[dict(case="C1", status="READY", measure=measure(ledger_a))],
        ),
    )


def test_carry_amount_is_cap_minus_issued_and_basis_kept():
    lines, blocked = lines_from_run(closed_run())
    assert blocked == []
    assert [(line["record"], line["carry_cents"]) for line in lines] == [("A1", 6), ("A2", 7)]
    assert all(line["source_period"] == "2026-11" for line in lines)
    assert lines[0]["basis"] == ["ledger:A1"] and lines[0]["origins"] == ["r1"]


def test_next_period_rolls_over_year_end():
    assert next_period("2026-11-24T08:00:00.000+00:00") == "2026-12"
    assert next_period("2026-12-31T23:59:00.000+00:00") == "2027-01"


def test_over_cap_blocks_whole_batch_and_lists_record_keys():
    run = closed_run()
    run["report"]["cases"][0]["measure"]["ledger"].append(
        dict(record="A3", case="C1", usage_units=1, cap_cents=5, issued_cents=9, carry_cents=-4, basis="ledger:A3")
    )
    lines, blocked = lines_from_run(run)
    assert classify(blocked) == "BLOCKED"
    assert blocked == [dict(record="A3", case="C1", reason="OVER_CAP")]
    report = dict(status="BLOCKED", lines=lines, blocked=blocked, events=[])
    with pytest.raises(DomainIssue) as raised:
        assert_issuable(report)
    assert raised.value.code == "CARRY_BLOCKED"
    assert [item["record"] for item in raised.value.details] == ["A3"]


def test_missing_pool_blocks_case_with_record_key_none():
    run = closed_run()
    run["report"]["cases"][0]["measure"]["pool"] = None
    _, blocked = lines_from_run(run)
    assert blocked == [dict(record=None, case="C1", reason="POOL_MISSING")]


def test_duplicate_replay_keeps_single_line_and_marks_pending():
    lines, _ = lines_from_run(closed_run())
    report = dict(
        status="DRAFT", lines=lines, blocked=[], pending_supplement=False, events=[]
    )
    supplement = dict(
        cases=[
            dict(
                case="C1",
                ledger=[
                    dict(record="A1", cap_cents=40, issued_cents=34),
                    dict(record="A2", cap_cents=40, issued_cents=33),
                ],
            )
        ],
        isolation=[],
        fingerprint="fp-replay",
        period="2026-11",
    )
    merged = merge_supplement(report, supplement, "now")
    assert len(merged["lines"]) == 2
    assert merged["lines"][0]["carry_cents"] == 6
    assert merged["pending_supplement"] is True and merged["status"] == "DRAFT"
    assert merged["events"][-1]["detail"] == dict(
        fingerprint="fp-replay", added=0, updated=0, replays=2, isolated=0, replay_only=True
    )


def test_supplement_adds_new_account_and_appends_basis():
    lines, _ = lines_from_run(closed_run())
    report = dict(
        status="DRAFT", lines=lines, blocked=[], pending_supplement=False, events=[]
    )
    supplement = dict(
        cases=[
            dict(case="C2", ledger=[dict(record="B1", cap_cents=12, issued_cents=10)])
        ],
        isolation=[],
        fingerprint="fp-add",
        period="2026-11",
    )
    merged = merge_supplement(report, supplement, "now")
    new_line = next(line for line in merged["lines"] if line["record"] == "B1")
    assert new_line["carry_cents"] == 2
    assert new_line["basis"] == ["supplement:fp-add:B1"]
    assert merged["status"] == "DRAFT" and merged["pending_supplement"] is False


def test_supplement_only_changes_unissued_batch_never_origin_period():
    lines, _ = lines_from_run(closed_run())
    original = [dict(line) for line in lines]
    report = dict(
        status="DRAFT", lines=lines, blocked=[], pending_supplement=False, events=[]
    )
    supplement = dict(
        cases=[dict(case="C1", ledger=[dict(record="A1", cap_cents=44, issued_cents=30)])],
        isolation=[],
        fingerprint="fp-edit",
        period="2026-11",
    )
    merged = merge_supplement(report, supplement, "now")
    changed = next(line for line in merged["lines"] if line["record"] == "A1")
    assert changed["carry_cents"] == 14
    assert len(changed["basis"]) == 2 and changed["basis"][0] == "ledger:A1"
    # 原账期快照保持原样，未被补录覆盖。
    assert original[0]["carry_cents"] == 6 and original[0]["basis"] == ["ledger:A1"]


def test_issued_batch_rejects_supplement():
    report = dict(status="ISSUED", lines=[], blocked=[], pending_supplement=False, events=[])
    with pytest.raises(DomainIssue, match="CARRY_FINALIZED"):
        merge_supplement(report, dict(cases=[], isolation=[], fingerprint="x", period="2026-11"), "now")


def test_missing_cap_isolation_blocks_and_clears_when_completed():
    lines, _ = lines_from_run(closed_run())
    report = dict(
        status="DRAFT", lines=lines, blocked=[], pending_supplement=False, events=[]
    )
    missing = dict(
        cases=[dict(case="C7", ledger=[])],
        isolation=[dict(line=9, record="X1", case="C7", reason="MISSING_NUMBER")],
        fingerprint="fp-miss",
        period="2026-11",
    )
    blocked_report = merge_supplement(report, missing, "now")
    assert blocked_report["blocked"] == [dict(record="X1", case="C7", reason="CAP_MISSING")]
    assert blocked_report["status"] == "BLOCKED"
    completed = dict(
        cases=[dict(case="C7", ledger=[dict(record="X1", cap_cents=12, issued_cents=10)])],
        isolation=[],
        fingerprint="fp-fix",
        period="2026-11",
    )
    cleared = merge_supplement(blocked_report, completed, "later")
    assert cleared["blocked"] == [] and cleared["status"] == "DRAFT"
    fixed = next(line for line in cleared["lines"] if line["record"] == "X1")
    assert fixed["carry_cents"] == 2


def test_empty_batch_cannot_issue():
    report = dict(status="DRAFT", lines=[], blocked=[], events=[])
    with pytest.raises(DomainIssue, match="CARRY_EMPTY"):
        assert_issuable(report)


def test_pending_flag_clears_when_real_supplement_arrives():
    lines, _ = lines_from_run(closed_run())
    report = dict(
        status="DRAFT", lines=lines, blocked=[], pending_supplement=False, events=[]
    )
    replay = dict(
        cases=[
            dict(case="C1", ledger=[
                dict(record="A1", cap_cents=40, issued_cents=34),
                dict(record="A2", cap_cents=40, issued_cents=33),
            ])
        ],
        isolation=[],
        fingerprint="fp-replay",
        period="2026-11",
    )
    first = merge_supplement(report, replay, "t1")
    assert first["pending_supplement"] is True
    real = dict(
        cases=[dict(case="C2", ledger=[dict(record="B1", cap_cents=10, issued_cents=8)])],
        isolation=[],
        fingerprint="fp-real",
        period="2026-11",
    )
    second = merge_supplement(first, real, "t2")
    assert second["pending_supplement"] is False and len(second["lines"]) == 3
    third = merge_supplement(
        second,
        dict(cases=[dict(case="C2", ledger=[dict(record="B1", cap_cents=10, issued_cents=8)])],
             isolation=[], fingerprint="fp-replay-2", period="2026-11"),
        "t3",
    )
    assert third["pending_supplement"] is True
