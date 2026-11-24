"""结转并发：重复创建只落一行，并发签发只有一个赢家，不产生半批。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.business import DomainIssue
from app.carry.service import create_carry, issue_carry


def _close(runs, clean):
    from app.review.service import execute, review

    run = execute(runs, clean)
    return review(runs, run["id"], dict(revision=0, status="APPROVED", note="关账复核通过"))


def test_parallel_carry_creation_commits_single_row(store, carries, clean):
    run = _close(store, clean)
    barrier = Barrier(4)

    def load():
        barrier.wait(3)
        return create_carry(store, carries, run["id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: load(), range(4)))
    assert all(item["id"] == results[0]["id"] for item in results)
    assert len(carries.list()) == 1


def test_parallel_issue_has_single_winner(store, carries, clean):
    run = _close(store, clean)
    cid = create_carry(store, carries, run["id"])["id"]
    barrier = Barrier(2)

    def attempt():
        barrier.wait(3)
        try:
            return issue_carry(carries, cid)["status"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["CARRY_FINALIZED", "ISSUED"]
    final = carries.load(cid)
    assert final["status"] == "ISSUED" and final["revision"] == 1
