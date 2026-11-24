"""关账后折扣额度结转的领域规则。

结转额以账户额度减去已签发分摊为准；任一账户超额则整批阻断并列出记录键。
本模块只处理纯数据结构，不读写数据库或 HTTP，便于逐户断言。
"""

from app.business import DomainIssue

# 补录隔离原因到结转阻断原因的映射：缺数字即额度缺失，其余结构性问题原样保留。
CAP_REASONS = {"MISSING_NUMBER"}


def next_period(created):
    """关账运行创建时间所在账期的下一账期，格式 YYYY-MM。"""
    year, month = int(created[:4]), int(created[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year:04d}-{month + 1:02d}"


def _line_from_ledger(entry, source):
    """依据冻结台账生成一条结转线，保留原账期依据键。"""
    cap = entry.get("cap_cents")
    issued = entry.get("issued_cents")
    line = dict(
        record=entry["record"],
        case=entry["case"],
        source_period=source["period"],
        cap_cents=cap,
        issued_cents=issued,
        carry_cents=None if cap is None or issued is None else cap - issued,
        basis=[entry.get("basis") or f"ledger:{entry['record']}"],
        origins=[source["run_id"]],
    )
    return line


def _blocked_for(line):
    if line["cap_cents"] is None:
        return "CAP_MISSING"
    if line["issued_cents"] is None:
        return "CAP_MISSING"
    if line["carry_cents"] < 0:
        return "OVER_CAP"
    return None


def lines_from_run(run):
    """从已关账运行的冻结报告抽取逐户结转线与阻断记录。"""
    report = run["report"]
    source = dict(
        run_id=run["id"],
        period=report["manifest"]["created"][:7],
        fingerprint=report["manifest"]["sha256"],
    )
    lines, blocked = [], []
    for case in report["cases"]:
        measure = case.get("measure")
        if measure is None:
            continue
        pool = measure.get("pool")
        if not pool or pool.get("discount_cents") is None:
            blocked.append(
                dict(record=None, case=case["case"], reason="POOL_MISSING")
            )
            continue
        for entry in measure.get("ledger", []):
            line = _line_from_ledger(entry, source)
            lines.append(line)
            reason = _blocked_for(line)
            if reason:
                blocked.append(
                    dict(record=line["record"], case=line["case"], reason=reason)
                )
    return lines, sorted(blocked, key=lambda b: (b["case"] or "", b["record"] or ""))


def classify(blocked):
    return "BLOCKED" if blocked else "DRAFT"


def _supplement_blocked(isolation, cases):
    blocked = []
    for row in isolation:
        reason = row.get("reason")
        code = "CAP_MISSING" if reason in CAP_REASONS else reason
        blocked.append(
            dict(record=row.get("record"), case=row.get("case"), reason=code)
        )
    for case in cases:
        if case.get("pool_missing"):
            blocked.append(dict(record=None, case=case["case"], reason="POOL_MISSING"))
        for entry in case.get("ledger", []):
            if entry.get("cap_cents") is None:
                blocked.append(
                    dict(record=entry["record"], case=case["case"], reason="CAP_MISSING")
                )
    return blocked


def merge_supplement(report, supplement, at):
    """把补录来源合并进尚未签发的下月批次。

    已关账账期不被改写：这里只在 DRAFT 批次的副本上更新结转线，并追加依据与事件。
    完全相同的逐户记录视为已核对重复回放，只保留一条且不改变金额。
    """
    if report["status"] == "ISSUED":
        raise DomainIssue("CARRY_FINALIZED")
    lines = [dict(line, basis=list(line["basis"]), origins=list(line["origins"]))
             for line in report["lines"]]
    index = {(line["case"], line["record"]): line for line in lines}
    # 本次补录覆盖到的账户键：补全后其历史 CAP_MISSING 阻断随之解除。
    touched = set()
    added = updated = replays = 0
    incoming_blocked = _supplement_blocked(
        supplement.get("isolation", []), supplement["cases"]
    )
    for case in supplement["cases"]:
        for entry in case.get("ledger", []):
            key = (case["case"], entry["record"])
            touched.add(key)
            cap, issued = entry.get("cap_cents"), entry.get("issued_cents")
            current = index.get(key)
            if current is None:
                line = dict(
                    record=entry["record"],
                    case=case["case"],
                    source_period=supplement["period"],
                    cap_cents=cap,
                    issued_cents=issued,
                    carry_cents=None if cap is None or issued is None else cap - issued,
                    basis=[f"supplement:{supplement['fingerprint'][:12]}:{entry['record']}"],
                    origins=[supplement["fingerprint"]],
                )
                lines.append(line)
                index[key] = line
                added += 1
                continue
            identical = (
                current["cap_cents"] == cap and current["issued_cents"] == issued
            )
            if identical:
                # 已核对重复回放：保留唯一一条，仅登记来源指纹。
                if supplement["fingerprint"] not in current["origins"]:
                    current["origins"].append(supplement["fingerprint"])
                replays += 1
                continue
            current["cap_cents"] = cap
            current["issued_cents"] = issued
            current["carry_cents"] = None if cap is None or issued is None else cap - issued
            current["basis"].append(
                f"supplement:{supplement['fingerprint'][:12]}:{entry['record']}"
            )
            current["origins"].append(supplement["fingerprint"])
            updated += 1
    blocked = [
        dict(record=line["record"], case=line["case"], reason=reason)
        for line in lines
        if (reason := _blocked_for(line))
    ]
    # 仍未解决的隔离/缺池阻断保留；已被本次补录覆盖的账户不再算缺失。
    pool_resolved = {c["case"] for c in supplement["cases"] if c.get("pool")}
    blocked.extend(
        item
        for item in incoming_blocked
        if (item["case"], item["record"]) not in touched
        and not (item["reason"] == "POOL_MISSING" and item["case"] in pool_resolved)
    )
    blocked = sorted(blocked, key=lambda b: (b["case"] or "", b["record"] or ""))
    replay_only = added == 0 and updated == 0 and replays > 0 and not incoming_blocked
    report["lines"] = sorted(lines, key=lambda line: (line["case"], line["record"]))
    report["blocked"] = blocked
    report["pending_supplement"] = replay_only or (
        report.get("pending_supplement", False) and not added and not updated
    )
    report["status"] = classify(blocked)
    report["events"].append(
        dict(
            seq=len(report["events"]),
            at=at,
            type="SUPPLEMENT",
            detail=dict(
                fingerprint=supplement["fingerprint"],
                added=added,
                updated=updated,
                replays=replays,
                isolated=len(incoming_blocked),
                replay_only=replay_only,
            ),
        )
    )
    return report


def assert_issuable(report):
    """签发前整批校验：存在任一阻断记录则整批阻断，附带记录键清单。"""
    if report["status"] == "ISSUED":
        raise DomainIssue("CARRY_FINALIZED")
    if report["blocked"]:
        raise DomainIssue("CARRY_BLOCKED", details=report["blocked"])
    if not report["lines"]:
        raise DomainIssue("CARRY_EMPTY")
