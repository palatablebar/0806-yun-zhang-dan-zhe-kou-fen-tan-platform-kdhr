"""补录来源的解析：复用既有采信与计算管线，把新来源转成逐户台账。

补录只服务于尚未签发的下月批次；折扣池或账户额度缺失在此显式阻断。
"""

from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.calculate import compute
from app.modules.grouping import case_groups
from app.modules.prepare import prepare


def supplement_cases(data):
    """解析补录 CSV，返回 (cases, isolation)。

    cases 中每项带 case、pool_missing 与 ledger；隔离行带原始原因码与行号。
    """
    intake = inspect(data)
    cases = []
    for case_id, rows in case_groups(intake["rows"]):
        item = {"case": case_id, "pool_missing": False, "ledger": []}
        try:
            _, payload = prepare(rows)
            measure = compute(payload)
        except DomainIssue as error:
            if error.code == "EXPECTED_ONE_POOL":
                item["pool_missing"] = True
                # 无折扣池仍保留已采信的账户行，便于逐户定位额度。
                item["ledger"] = [
                    dict(
                        record=r["record"],
                        case=case_id,
                        cap_cents=r.get("cap_cents"),
                        issued_cents=0,
                    )
                    for r in rows
                    if r["kind"] == "usage"
                ]
                cases.append(item)
                continue
            if error.code == "NO_ELIGIBLE_USAGE":
                # 有效账户行均因缺测被隔离；逐户原因在 isolation 中以 CAP_MISSING 阻断。
                cases.append(item)
                continue
            raise
        item["ledger"] = measure["ledger"]
        item["pool"] = measure["pool"]
        cases.append(item)
    return cases, intake["isolation"]
