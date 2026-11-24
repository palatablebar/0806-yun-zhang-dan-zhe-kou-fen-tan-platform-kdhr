import {request} from './client.js';

const createBtn = document.querySelector('#carry-create');
const supplementBtn = document.querySelector('#carry-supplement');
const issueBtn = document.querySelector('#carry-issue');
const carryFile = document.querySelector('#carry-file');
const carryStatus = document.querySelector('#carry-status');
const carryEvidence = document.querySelector('#carry-evidence');

let runId = null;
let active = null;

function setStatus(text, failure = false) {
  carryStatus.textContent = text;
  carryStatus.dataset.failure = String(failure);
}

function render(carry) {
  active = carry;
  const report = carry.report;
  const blocked = report.blocked.length;
  const pending = report.pending_supplement ? ' · 待补来源' : '';
  setStatus(`${carry.target_period} · ${report.status} · ${report.lines.length} 户 · 阻断 ${blocked}${pending}`);
  carryEvidence.hidden = false;
  carryEvidence.href = `/api/carries/${carry.id}/evidence`;
  const finalized = report.status === 'ISSUED';
  supplementBtn.disabled = finalized;
  issueBtn.disabled = finalized || blocked > 0;
}

export function resetCarry() {
  runId = null;
  active = null;
  carryEvidence.hidden = true;
  setStatus('');
  [createBtn, supplementBtn, issueBtn].forEach(button => { button.disabled = true; });
}

export function bindCarry(currentRun) {
  runId = currentRun?.id || null;
  const closed = currentRun?.status === 'APPROVED';
  if (!closed) { resetCarry(); return; }
  createBtn.disabled = false;
  // 关账后尝试载入既有下月批次（重复回放直接返回同一条）。
  request(`/api/carries/from-run/${runId}`, {method: 'POST'})
    .then(render)
    .catch(error => setStatus(error.message, true));
}

createBtn.addEventListener('click', () => {
  if (!runId) return;
  request(`/api/carries/from-run/${runId}`, {method: 'POST'})
    .then(carry => { render(carry); setStatus('已生成下月结转批次'); })
    .catch(error => setStatus(error.message, true));
});

supplementBtn.addEventListener('click', () => carryFile.click());
carryFile.addEventListener('change', async () => {
  if (!runId || !carryFile.files.length) return;
  const data = new FormData();
  data.append('file', carryFile.files[0]);
  try {
    const carry = await request(`/api/carries/from-run/${runId}/supplement`, {method: 'POST', body: data});
    render(carry);
    setStatus('补录已并入未签发批次，已关账账期未改写');
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    carryFile.value = '';
  }
});

issueBtn.addEventListener('click', () => {
  if (!active) return;
  request(`/api/carries/${active.id}/issue`, {method: 'POST'})
    .then(carry => {
      active = carry;
      render(carry);
      setStatus('下月批次已完整签发');
    })
    .catch(error => {
      const blocked = error.blocked ? `：${error.blocked.map(item => item.record || item.case).join('、')}` : '';
      setStatus(`${error.message}${blocked}`, true);
    });
});
