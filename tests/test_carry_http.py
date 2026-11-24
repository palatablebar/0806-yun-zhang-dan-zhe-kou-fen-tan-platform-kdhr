"""结转 HTTP 接口：创建、补录、签发、证据与错误码。"""

import io

import pytest


def close_batch(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    response = client.patch(
        f"/api/runs/{run['id']}",
        json=dict(revision=0, status="APPROVED", note="关账复核通过"),
    )
    assert response.status_code == 200
    return run["id"]


def test_create_carry_and_list(client):
    run_id = close_batch(client)
    created = client.post(f"/api/carries/from-run/{run_id}")
    assert created.status_code == 200
    body = created.json
    assert body["report"]["status"] == "DRAFT"
    assert body["report"]["target_period"] == "2026-12"
    assert len(body["report"]["lines"]) == 5
    listing = client.get("/api/carries").json["items"]
    assert len(listing) == 1 and listing[0]["id"] == body["id"]


def test_carry_creation_is_idempotent_over_http(client):
    run_id = close_batch(client)
    first = client.post(f"/api/carries/from-run/{run_id}").json
    second = client.post(f"/api/carries/from-run/{run_id}").json
    assert first["id"] == second["id"]
    assert len(client.get("/api/carries").json["items"]) == 1


def test_unclosed_run_rejected(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    response = client.post(f"/api/carries/from-run/{run['id']}")
    assert response.status_code == 409 and response.json["code"] == "RUN_NOT_CLOSED"


def test_supplement_then_issue_flow_and_evidence(client):
    from pathlib import Path

    run_id = close_batch(client)
    cid = client.post(f"/api/carries/from-run/{run_id}").json["id"]
    supplement = (
        Path(__file__).resolve().parents[1] / "sample_data" / "supplement.csv"
    ).read_bytes()
    updated = client.post(
        f"/api/carries/from-run/{run_id}/supplement",
        data={"file": (io.BytesIO(supplement), "supplement.csv")},
    )
    assert updated.status_code == 200
    assert len(updated.json["report"]["lines"]) == 7
    issued = client.post(f"/api/carries/{cid}/issue")
    assert issued.status_code == 200 and issued.json["status"] == "ISSUED"
    evidence = client.get(f"/api/carries/{cid}/evidence")
    assert evidence.status_code == 200
    packet = evidence.json
    assert packet["schema"] == "carry-evidence/1"
    assert [event["type"] for event in packet["events"]] == ["CREATED", "SUPPLEMENT", "ISSUED"]
    assert "attachment" in evidence.headers["Content-Disposition"]


def test_blocked_batch_returns_record_keys_and_does_not_issue(client):
    run_id = close_batch(client)
    cid = client.post(f"/api/carries/from-run/{run_id}").json["id"]
    from conftest import csv_data

    over = csv_data(
        [
            ["000601", "0006", "pool", "0", "50", "50", "池"],
            ["000602", "0006", "usage", "1", "0", "10", "超额"],
        ]
    )
    client.post(
        f"/api/carries/from-run/{run_id}/supplement",
        data={"file": (io.BytesIO(over), "over.csv")},
    )
    response = client.post(f"/api/carries/{cid}/issue")
    assert response.status_code == 422
    payload = response.json
    assert payload["code"] == "CARRY_BLOCKED"
    assert payload["blocked"] == [dict(record="000602", case="0006", reason="OVER_CAP")]
    # 原子性：失败后批次保持阻断原样，未被签发。
    assert client.get(f"/api/carries/{cid}").json["status"] == "BLOCKED"


def test_unknown_carry_is_404(client):
    assert client.get("/api/carries/nope").status_code == 404
    assert client.post("/api/carries/nope/issue").status_code == 404


def test_evidence_404(client):
    assert client.get("/api/carries/nope/evidence").status_code == 404
