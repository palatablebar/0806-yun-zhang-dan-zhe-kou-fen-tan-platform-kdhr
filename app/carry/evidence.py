import json


def carry_artifact(carry):
    """结转批次证据：逐户结转依据、阻断键与完整事件链，原账期引用不被改写。"""
    report = carry["report"]
    packet = {
        "schema": "carry-evidence/1",
        "id": carry["id"],
        "source_run_id": carry["source_run_id"],
        "source_period": report["source_period"],
        "target_period": carry["target_period"],
        "status": carry["status"],
        "revision": carry["revision"],
        "created": carry["created"],
        "issued": carry["issued"],
        "pending_supplement": report["pending_supplement"],
        "lines": report["lines"],
        "blocked": report["blocked"],
        "events": report["events"],
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
