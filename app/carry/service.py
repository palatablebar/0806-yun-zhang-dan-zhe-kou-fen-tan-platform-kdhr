"""关账与结转的应用服务：在关账运行之上生成、补录并原子签发下月批次。"""

from hashlib import sha256

from app.business import DomainIssue
from app.carry.domain import (
    assert_issuable,
    classify,
    lines_from_run,
    merge_supplement,
    next_period,
)
from app.carry.intake import supplement_cases
from app.config import RULE_VERSION
from app.review.service import now


def carry_id(source_run_id):
    return sha256(f"carry:{RULE_VERSION}:{source_run_id}".encode()).hexdigest()


def _closed_run(runs, run_id):
    run = runs.load(run_id)
    if run["status"] != "APPROVED":
        raise DomainIssue("RUN_NOT_CLOSED")
    return run


def build_report(run, at):
    lines, blocked = lines_from_run(run)
    target = next_period(run["report"]["manifest"]["created"])
    status = classify(blocked)
    return dict(
        schema="carry-batch/1",
        source_run_id=run["id"],
        source_period=run["report"]["manifest"]["created"][:7],
        target_period=target,
        status=status,
        lines=lines,
        blocked=blocked,
        pending_supplement=False,
        events=[
            dict(
                seq=0,
                at=at,
                type="CREATED",
                detail=dict(
                    source_fingerprint=run["report"]["manifest"]["sha256"],
                    lines=len(lines),
                    blocked=len(blocked),
                ),
            )
        ],
    )


def create_carry(runs, carries, run_id):
    """对已关账运行生成下月可签发批次；重复回放返回同一批次。"""
    run = _closed_run(runs, run_id)
    cid = carry_id(run_id)
    try:
        return carries.load(cid)
    except DomainIssue as error:
        if error.code != "CARRY_NOT_FOUND":
            raise
    report = build_report(run, now())
    report["created"] = now()
    return carries.register(cid, report)


def add_supplement(runs, carries, run_id, data):
    """补录来源只改写未签发的下月批次；已关账账期保持原样。"""
    run = _closed_run(runs, run_id)
    cid = carry_id(run_id)
    carry = carries.load(cid)
    if carry["report"]["status"] == "ISSUED":
        raise DomainIssue("CARRY_FINALIZED")
    fingerprint = sha256(data).hexdigest()
    cases, isolation = supplement_cases(data)
    supplement = dict(
        cases=cases,
        isolation=isolation,
        fingerprint=fingerprint,
        period=now()[:7],
    )
    report = merge_supplement(carry["report"], supplement, now())
    carry["report"] = report
    carry["revision"] += 1
    return carries.save(carry)


def issue_carry(carries, carry_id):
    """整批原子签发：先做全量阻断校验，再单语句切换状态，避免半批结果。"""
    carry = carries.load(carry_id)
    assert_issuable(carry["report"])
    issued_at = now()
    carry["report"]["status"] = "ISSUED"
    carry["report"]["events"].append(
        dict(seq=len(carry["report"]["events"]), at=issued_at, type="ISSUED", detail={})
    )
    return carries.issue(carry_id, carry["report"], issued_at)
