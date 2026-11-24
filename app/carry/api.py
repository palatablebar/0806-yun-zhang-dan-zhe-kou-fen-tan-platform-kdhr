from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.carry.evidence import carry_artifact
from app.carry.service import add_supplement, create_carry, issue_carry
from app.inputs import read_input

carry_api = Blueprint("carry", __name__, url_prefix="/api/carries")


def stores():
    return current_app.extensions["runs"], current_app.extensions["carries"]


@carry_api.post("/from-run/<run_id>")
def create(run_id):
    runs, carries = stores()
    return jsonify(create_carry(runs, carries, run_id))


@carry_api.post("/from-run/<run_id>/supplement")
def supplement(run_id):
    runs, carries = stores()
    data = read_input(required=True)
    return jsonify(add_supplement(runs, carries, run_id, data))


@carry_api.get("")
def listing():
    _, carries = stores()
    return jsonify(items=carries.list())


@carry_api.get("/<carry_id>")
def detail(carry_id):
    _, carries = stores()
    return jsonify(carries.load(carry_id))


@carry_api.post("/<carry_id>/issue")
def issue(carry_id):
    _, carries = stores()
    return jsonify(issue_carry(carries, carry_id))


@carry_api.get("/<carry_id>/evidence")
def evidence(carry_id):
    _, carries = stores()
    carry = carries.load(carry_id)
    return Response(
        carry_artifact(carry),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="carry-{carry["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )
