# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。

## 结转接口（关账后）

仅 `APPROVED`（已关账）运行可结转。结转额 = 账户额度 − 已签发分摊，逐户生成下月批次，原账期报告冻结不改写。

- `POST /api/carries/from-run/<run_id>`：基于关账运行生成下月可签发批次。同一运行重复调用幂等，返回同一条。
- `POST /api/carries/from-run/<run_id>/supplement`：`multipart/form-data` 上传补录 CSV，只并入尚未签发的下月批次；已签发批次返回 409。完全相同的逐户记录按已核对重复回放保留一条并标记待补。
- `GET /api/carries`：最近 50 个结转批次。
- `GET /api/carries/<id>`：批次详情，含逐户结转线、阻断记录键与事件链。
- `POST /api/carries/<id>/issue`：整批原子签发。任一账户超额或额度缺失时返回 422 `CARRY_BLOCKED`，响应体 `blocked` 列出记录键，批次保持原样不产生半批。
- `GET /api/carries/<id>/evidence`：下载结转证据 JSON（`carry-evidence/1`），含逐户依据、阻断键与完整事件链。

阻断原因码：`OVER_CAP`（已签发分摊超过账户额度）、`CAP_MISSING`（账户额度缺失）、`POOL_MISSING`（折扣池缺失）。守卫码：`RUN_NOT_CLOSED`(409)、`CARRY_FINALIZED`(409)、`CARRY_NOT_FOUND`(404)、`CARRY_EMPTY`(422)。
