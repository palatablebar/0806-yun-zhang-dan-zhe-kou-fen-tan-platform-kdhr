"""结转服务与持久化：关账守卫、幂等、补录边界与原子签发。"""

import pytest

from app.business import DomainIssue
from app.carry.service import add_supplement, carry_id, create_carry, issue_carry


def close_clean(runs, clean):
    from app.review.service import execute, review

    run = execute(runs, clean)
    return review(
        runs, run["id"], dict(revision=0, status="APPROVED", note="关账复核通过")
    )


def test_carry_requires_closed_run(store, clean):
    from app.review.service import execute

    run = execute(store, clean)
    from app.carry.store import CarryStore

    carries = CarryStore(store.path)
    with pytest.raises(DomainIssue, match="RUN_NOT_CLOSED"):
        create_carry(store, carries, run["id"])


def test_carry_lines_match_cap_minus_issued(store, carries, clean):
    run = close_clean(store, clean)
    carry = create_carry(store, carries, run["id"])
    report = carry["report"]
    assert report["status"] == "DRAFT" and report["target_period"] == "2026-12"
    expected = {
        "000102": (40, 34, 6),
        "000103": (40, 33, 7),
        "000104": (40, 33, 7),
        "000202": (6, 6, 0),
        "000203": (5, 3, 2),
    }
    for line in report["lines"]:
        assert (line["cap_cents"], line["issued_cents"], line["carry_cents"]) == expected[line["record"]]
        assert line["basis"][0] == f"ledger:{line['record']}"


def test_repeated_carry_replay_returns_same_batch(store, carries, clean):
    run = close_clean(store, clean)
    first = create_carry(store, carries, run["id"])
    second = create_carry(store, carries, run["id"])
    assert first["id"] == second["id"] == carry_id(run["id"])
    assert len(carries.list()) == 1


def test_issue_is_atomic_and_final(store, carries, clean):
    run = close_clean(store, clean)
    cid = create_carry(store, carries, run["id"])["id"]
    issued = issue_carry(carries, cid)
    assert issued["status"] == "ISSUED" and issued["revision"] == 1 and issued["issued"]
    with pytest.raises(DomainIssue, match="CARRY_FINALIZED"):
        issue_carry(carries, cid)


def test_supplement_blocked_issue_leaves_batch_unchanged(store, carries, clean):
    run = close_clean(store, clean)
    cid = create_carry(store, carries, run["id"])["id"]
    over = [
        ["000601", "0006", "pool", "0", "50", "50", "池"],
        ["000602", "0006", "usage", "1", "0", "10", "超额账户"],
    ]
    from conftest import csv_data

    add_supplement(store, carries, run["id"], csv_data(over))
    blocked = carries.load(cid)
    assert blocked["report"]["status"] == "BLOCKED"
    with pytest.raises(DomainIssue, match="CARRY_BLOCKED") as raised:
        issue_carry(carries, cid)
    assert [item["record"] for item in raised.value.details] == ["000602"]
    still = carries.load(cid)
    # 原子性：失败签发后批次状态与修订号原样保留，不产生半批。
    assert still["status"] == "BLOCKED" and still["revision"] == blocked["revision"]


def test_supplement_cannot_touch_issued_batch(store, carries, clean):
    run = close_clean(store, clean)
    cid = create_carry(store, carries, run["id"])["id"]
    issue_carry(carries, cid)
    with pytest.raises(DomainIssue, match="CARRY_FINALIZED"):
        add_supplement(store, carries, run["id"], clean)


def test_supplement_preserves_closed_period_history(store, carries, clean):
    run = close_clean(store, clean)
    create_carry(store, carries, run["id"])
    before = store.load(run["id"])
    add_supplement(store, carries, run["id"], clean)  # replay-only
    after = store.load(run["id"])
    assert after["report"] == before["report"] and after["status"] == "APPROVED"
    carry = carries.load(carry_id(run["id"]))
    assert carry["report"]["pending_supplement"] is True
    assert [event["type"] for event in carry["report"]["events"]] == ["CREATED", "SUPPLEMENT"]


def test_missing_pool_supplement_blocks(store, carries, clean):
    run = close_clean(store, clean)
    create_carry(store, carries, run["id"])
    from conftest import csv_data

    no_pool = csv_data([["000802", "0008", "usage", "1", "0", "10", "无池"]])
    carry = add_supplement(store, carries, run["id"], no_pool)
    assert carry["report"]["blocked"] == [dict(record=None, case="0008", reason="POOL_MISSING")]
