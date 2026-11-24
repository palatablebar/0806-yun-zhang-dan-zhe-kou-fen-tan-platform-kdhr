from app.business import measured


def compute(data):
    pool, accounts = data
    total = sum(r["usage_units"] for r in accounts)
    shares = [
        (r, *divmod(pool["discount_cents"] * r["usage_units"], total)) for r in accounts
    ]
    extra = pool["discount_cents"] - sum(q for _, q, _ in shares)
    amounts = [
        (r, q + (i < extra))
        for i, (r, q, _) in enumerate(
            sorted(shares, key=lambda x: (-x[2], x[0]["record"]))
        )
    ]
    evidence = {r["record"]: a for r, a in amounts}
    # 逐户台账在执行批次时冻结，关账后作为结转依据的原始快照，不随后续补录改写。
    ledger = [
        dict(
            record=r["record"],
            case=r["case"],
            usage_units=r["usage_units"],
            cap_cents=r["cap_cents"],
            issued_cents=amount,
            carry_cents=r["cap_cents"] - amount,
            basis="ledger:" + r["record"],
        )
        for r, amount in amounts
    ]
    result = measured(
        sum(a for _, a in amounts),
        pool["discount_cents"],
        "分",
        evidence,
        any(a > r["cap_cents"] for r, a in amounts),
    )
    result["ledger"] = ledger
    result["pool"] = dict(
        record=pool["record"],
        case=pool["case"],
        discount_cents=pool["discount_cents"],
        cap_cents=pool["cap_cents"],
    )
    return result
