from flask import jsonify

LABELS = {
    "FILE_TOO_LARGE": "文件超过 256 KiB",
    "FILE_EMPTY": "文件没有内容",
    "FILE_BLANK": "文件只有空白",
    "HEADER_ONLY": "文件只有标题行",
    "HEADER_MISMATCH": "列名与字段字典不一致",
    "ENCODING_INVALID": "请使用 UTF-8 CSV",
    "CSV_MALFORMED": "CSV 引号或行格式异常",
    "ROW_LIMIT": "文件超过 2000 行",
    "FILE_REQUIRED": "请选择 CSV 文件",
    "RUN_NOT_FOUND": "批次不存在",
    "REVIEW_FIELDS": "请填写 3 至 200 字复核意见",
    "STALE_REVIEW": "批次已更新，请刷新",
    "RUN_FINALIZED": "批次已签发",
    "UNRESOLVED_ISSUES": "存在待处理差异",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "处理阶段不存在",
    "RUN_NOT_CLOSED": "账期未关账，不能结转",
    "CARRY_NOT_FOUND": "结转批次不存在",
    "CARRY_FINALIZED": "下月批次已签发，不能改写",
    "CARRY_BLOCKED": "存在超额或额度缺失，整批阻断",
    "CARRY_EMPTY": "没有可结转的账户行",
    "OVER_CAP": "账户已签发分摊超过账户额度",
    "CAP_MISSING": "账户额度缺失",
    "POOL_MISSING": "折扣池缺失",
}


def response(error):
    code = error.code
    status = (
        404
        if code in {"RUN_NOT_FOUND", "SAMPLE_UNKNOWN", "STAGE_UNKNOWN", "CARRY_NOT_FOUND"}
        else (
            409
            if code
            in {
                "STALE_REVIEW",
                "RUN_FINALIZED",
                "UNRESOLVED_ISSUES",
                "RUN_NOT_CLOSED",
                "CARRY_FINALIZED",
            }
            else (
                413
                if code == "FILE_TOO_LARGE"
                else 422
            )
        )
    )
    payload = {"code": code, "message": LABELS.get(code, code)}
    if getattr(error, "details", None):
        payload["blocked"] = error.details
    return jsonify(payload), status
