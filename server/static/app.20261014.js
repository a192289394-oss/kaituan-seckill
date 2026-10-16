'use strict';
const $ = s => document.querySelector(s);
const base = new URL('api/', location.href).href;
const states = {
  queued: ['等待开始', '这张任务尚未开始核对。执行端接收后会更新进度，请稍后查看。', 'neutral'],
  running: ['正在处理', '酒店、商品与权限正在核对。处理期间请等待结果，需要确认时会在这里提醒。', ''],
  waiting_review: ['结果待确认', '这次操作的最终结果尚未确认。请等待平台结果核对完成，再决定是否继续。', 'warn'],
  waiting_device: ['执行暂时中断', '执行端暂时无法继续，这张任务还未完成。请恢复设备连接后，在这里查看进度。', 'warn'],
  needs_input: ['需要你确认', '继续处理前需要补充信息或确认设置。请打开「查看并处理」，核对后再继续。', 'warn'],
  succeeded: ['已核验', '这张任务的核验已完成。请查看核验方式与活动设置，确认是否符合本次需求。', 'ok'],
  failed: ['未完成', '本次任务未能完成，开团或授权结果还不能确认。请检查计划与活动设置，联系管理员确认继续方式。', 'bad'],
  cancelled: ['已停止', '这张任务已停止处理。需要重新处理相同计划或账号时，请联系管理员确认继续方式。', 'neutral'],
  expired: ['已过期', '这张任务已超过可执行时间。需要继续时，请获取新的有效计划链接，或联系管理员处理。', 'neutral'],
  cancel_requested: ['正在停止', '停止请求已收到，当前操作仍需结束核对。请稍候查看最终状态。', 'warn']
};
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'expired']);
const errorMessages = {
  stale_revision: '任务已更新，本次操作未完成。请刷新任务后重新确认。',
  preview_changed: '活动设置已发生变化，本次确认未完成。请刷新后重新核对商品、价格与时间。',
  task_expired: '任务已超过可执行时间，本次确认未完成。请获取新的有效计划链接，或联系管理员处理。',
  not_waiting_input: '这张任务已进入其他处理阶段。请刷新查看最新进度后再操作。',
  approval_unavailable: '这张计划暂时不能授权执行。请刷新查看最新核验结果后再处理。',
  schedule_unavailable: '这张任务暂时不能修改活动时间。请刷新查看最新结果后再处理。',
  cancelled: '这张任务已停止，无法直接继续处理。需要重办相同任务时，请联系管理员确认继续方式。',
  request_conflict: '本次填写的信息与之前提交的任务不同。请检查内容后重新提交。',
  plan_id: '暂时无法识别这条计划。请粘贴完整的来客计划链接或计划编号后重试。',
  accounts: '抖音号格式不正确，任务尚未提交。请填写 1 至 40 个账号，使用字母、数字、点、下划线或短横线。',
  hotel: '酒店名称尚未填写完整，任务尚未提交。请填写酒店全称与分店后重试。',
  schedule_time: '活动时间不正确，本次确认未完成。请填写未来的开始时间，结束时间须晚于开始时间。',
  forbidden_origin: '登录状态或页面来源无法验证，本次操作未完成。请返回工作台重新打开。'
};
let tasks = [], filter = 'all', loading = false, pendingRequest = null, authenticated = false, hasLoaded = false, fieldCounter = 0;
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function safeName(v) {
  if (typeof v !== 'string') return '';
  const s = v.trim();
  if (!s || s.length > 200 || /(?:[0-9a-f]{24,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{15,}|\b(?:fingerprint|request_id|worker_id|plan_id|expected_revision|read_only|lease_token|traceback|HTTP)\b|[{}\[\]\n])/i.test(s) || /^\d{18,}$/.test(s)) return '';
  return s;
}
function hotelName(t) { return safeName(t.result?.hotel) || safeName(t.details?.hotel) || safeName(t.payload?.hotel) || ''; }
function taskTitle(t) { const kind = t.kind === 'authorization' ? '秒杀账号' : t.kind === 'inspect' ? '计划核验' : '直播开团'; return kind + ' · ' + (hotelName(t) || '酒店待核对'); }
function when(n) { return Number.isFinite(Number(n)) && Number(n) > 0 ? new Date(Number(n) * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未开始'; }
function taskStatus(t) {
  const status = states[t.status] || ['进度待确认', '暂时无法确定这张任务的进度。请刷新后查看，仍未更新时联系管理员。', 'warn'];
  if (t.status === 'succeeded' && t.kind === 'inspect') return ['已核验', '计划信息已核对，本次仅查看信息。请核对酒店与商品，需要执行时提交开团任务。', 'ok'];
  if (t.status === 'succeeded' && !t.payload?.allow_write && !t.committed) return ['已核验', '计划或账号信息已核对，本次任务仅核对信息。需要继续执行时，请核对活动设置并联系管理员确认继续方式。', 'ok'];
  return status;
}
function setSubmitAvailability() { $('#submit').disabled = !authenticated; $('#submit').title = authenticated ? '' : '连接任务入口后即可提交'; }
class UserError extends Error { constructor(message, technical) { super(message); this.technical = technical; } }
async function api(path, body) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', signal: controller.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await r.json().catch(() => null);
    if (r.status === 401 || r.redirected && r.url.includes('/site/login')) {
      authenticated = false; setSubmitAvailability(); $('#login').hidden = false;
      throw new UserError('访问验证已失效，暂时无法读取或提交任务。请重新连接任务入口后继续。', { status: r.status, response: data });
    }
    if (!r.ok || !data) throw new UserError(errorMessages[data?.error] || '暂时无法完成这次操作，最新结果尚未确认。请刷新后重试，仍有问题时联系管理员。', { status: r.status, response: data });
    return data;
  } catch (e) {
    if (e instanceof UserError) throw e;
    throw new UserError('连接暂时中断，最新结果尚未确认。请检查网络后刷新任务，确认最新进度再继续。', { message: e.name === 'AbortError' ? 'Request timeout' : String(e) });
  } finally { clearTimeout(timer); }
}
function technicalDetails(value) { const d = el('details'), s = el('summary', '技术详情'); d.append(s, el('pre', JSON.stringify(value, null, 2))); return d; }
function error(e, target = $('#error')) {
  target.hidden = false; target.replaceChildren(el('span', e instanceof UserError ? e.message : '操作暂时未完成。请检查填写的信息后重试。'));
  if (e.technical) target.append(technicalDetails(e.technical));
}
function empty(title, text, clear = false) {
  const box = el('div', undefined, 'empty');
  box.append(el('h3', title), el('p', text));
  if (clear) { const b = el('button', '查看全部任务', 'secondary'); b.type = 'button'; b.onclick = () => { filter = 'all'; $('#task-search').value = ''; updateFilters(); render(); }; box.append(b); }
  return box;
}
function confirmAction(title, description, accept = '确认继续', danger = false) {
  return new Promise(resolve => {
    const dialog = $('#confirm-dialog'); $('#confirm-title').textContent = title; $('#confirm-description').textContent = description;
    $('#confirm-accept').textContent = accept; $('#confirm-accept').className = danger ? 'danger' : '';
    dialog.returnValue = ''; dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true }); dialog.showModal(); dialog.querySelector('button[value="cancel"]').focus();
  });
}
function updateFilters() { for (const b of document.querySelectorAll('[data-filter]')) { const selected = b.dataset.filter === filter; b.classList.toggle('selected', selected); b.setAttribute('aria-pressed', String(selected)); } }
function render() {
  const list = $('#tasks'), focused = document.activeElement;
  const kept = new Map([...list.querySelectorAll('.task')].map(n => [n.dataset.taskId, { form: n.querySelector('.resume'), revision: n.dataset.revision, expanded: !!n.querySelector(':scope > details[open]') }]));
  list.replaceChildren();
  const attention = tasks.filter(t => ['needs_input', 'failed', 'waiting_device', 'waiting_review'].includes(t.status));
  const active = tasks.filter(t => !terminal.has(t.status));
  $('#queue-summary').textContent = tasks.length ? `最近 ${tasks.length} 张任务 · ${active.length} 张进行中 · ${attention.length} 张需要处理` : '暂无任务。提交后可在这里查看结果。';
  const query = $('#task-search').value.trim().toLocaleLowerCase();
  const shown = tasks.filter(t => (filter === 'all' || filter === 'attention' && attention.includes(t) || filter === 'active' && active.includes(t) || filter === t.status) && (!query || `${taskTitle(t)} ${(t.payload?.accounts || []).join(' ')}`.toLocaleLowerCase().includes(query)));
  if (!shown.length) { list.append(tasks.length ? empty('没有找到匹配的任务', '当前筛选或搜索下没有任务。调整条件后继续查看。', true) : empty('从一张任务开始', '粘贴开团计划链接，或填写酒店与抖音号。提交核验后，进度与需要确认的设置会显示在这里。')); return; }
  for (const t of shown) {
    const item = el('article', undefined, 'task'); item.dataset.taskId = t.id; item.dataset.revision = t.revision;
    const [status, summary, tone] = taskStatus(t), head = el('div', undefined, 'task-head'); head.append(el('h3', taskTitle(t)), el('span', status, 'badge ' + tone));
    item.append(head, el('p', summary, 'task-summary'));
    const facts = el('div', undefined, 'task-facts'), p = t.payload || {};
    const mode = t.committed ? (t.status === 'succeeded' ? '核验方式：执行后核对结果' : '核验方式：确认执行结果') : p.allow_write && !t.read_only ? '处理方式：核对后执行' : '处理方式：仅核对信息';
    facts.append(el('span', mode));
    if (t.kind === 'authorization' && Array.isArray(p.accounts)) facts.append(el('span', '抖音号：' + p.accounts.join('、')));
    item.append(facts, el('div', '更新于 ' + when(t.updated), 'meta'));
    const actions = el('div', undefined, 'task-actions');
    if (t.status === 'needs_input' && !t.cancel_requested) { const b = el('button', '查看并处理'); b.type = 'button'; b.onclick = () => showResume(item, t, b); actions.append(b); }
    if (['waiting_device', 'waiting_review'].includes(t.status) && !t.cancel_requested) {
      const b = el('button', '重新核对进度', 'secondary'); b.type = 'button';
      b.onclick = async () => { if (!await confirmAction('重新核对这张任务？', '将重新查看这张任务的进度。若执行端仍未恢复，结果可能还需要等待。', '确认核对')) return; b.disabled = true; try { await api('tasks/' + t.id + '/retry', { expected_revision: t.revision }); await refresh(); } catch (e) { error(e); b.disabled = false; } }; actions.append(b);
    }
    if (!terminal.has(t.status) && !t.cancel_requested) {
      const b = el('button', '停止处理', 'secondary'); b.type = 'button';
      b.onclick = async () => { if (!await confirmAction('停止这张任务？', t.committed ? '任务已进入执行阶段。停止后将确认已有操作的结果，已经提交的平台操作无法撤回。' : '停止后，这张任务将不再继续执行。已经进行中的核对可能需要稍后才能结束。', '确认停止', true)) return; b.disabled = true; try { await api('tasks/' + t.id + '/cancel', { expected_revision: t.revision }); await refresh(); } catch (e) { error(e); b.disabled = false; } }; actions.append(b);
    }
    if (actions.children.length) item.append(actions);
    const d = technicalDetails({ id: t.id, status: t.status, result: t.result, details: t.details, payload: p, revision: t.revision, committed: t.committed, read_only: t.read_only });
    const old = kept.get(t.id); d.open = old?.expanded || false; item.append(d);
    if (old?.form && t.status === 'needs_input' && old.revision === String(t.revision)) { item.append(old.form); const b = actions.querySelector('button'); if (b?.textContent === '查看并处理') b.disabled = true; }
    list.append(item);
  }
  if (focused?.closest('.resume') && focused.isConnected) focused.focus({ preventScroll: true });
}
function addPreview(parent, preview) {
  const box = el('div', undefined, 'preview'); box.append(el('h4', '本次沿用的商品设置'));
  if (Array.isArray(preview.products) && preview.products.length) {
    const scroll = el('div', undefined, 'table-scroll'), table = el('table'), head = el('thead'), tr = el('tr');
    for (const text of ['商品', '秒杀价', '每达人库存']) tr.append(el('th', text)); head.append(tr); table.append(head);
    const body = el('tbody'); for (const [index, p] of preview.products.entries()) { const row = el('tr'); const cents = Number(p.price_cents), stock = Number(p.stock_per_creator); row.append(el('td', safeName(p.name) || `商品 ${index + 1}（名称待核对）`), el('td', p.price_cents != null && Number.isFinite(cents) ? '¥' + (cents / 100).toFixed(2) : '待确认'), el('td', p.stock_per_creator != null && Number.isFinite(stock) ? String(stock) : '待确认')); body.append(row); }
    table.append(body); scroll.append(table); box.append(scroll);
  } else box.append(el('p', '暂时没有可展示的商品设置。请核对原活动内容后再确认。', 'hint'));
  if (Array.isArray(preview.accounts) && preview.accounts.length) box.append(el('p', '抖音号：' + preview.accounts.join('、'), 'meta'));
  if (preview.end_time_old) box.append(el('p', '原活动结束时间：' + when(preview.end_time_old), 'hint')); parent.append(box);
}
function inputField(labelText, type, required = true) {
  const label = el('label', labelText), input = el(type === 'textarea' ? 'textarea' : 'input'); input.id = 'resume-field-' + ++fieldCounter; label.htmlFor = input.id;
  if (type !== 'textarea') input.type = type; input.required = required; return { label, input };
}
function showResume(item, t, button) {
  if (item.querySelector('.resume')) return;
  button.disabled = true; const f = el('form', undefined, 'resume'), localError = el('div', undefined, 'notice error'); localError.hidden = true; localError.setAttribute('role', 'alert');
  const candidates = t.details?.preview ? [t.details.preview] : (t.details?.candidates || []).filter(x => x.template_id && x.fingerprint); let selected = candidates[0];
  if (t.kind === 'authorization' && selected && !t.details?.blocked && !selected.blocked) {
    f.append(el('p', '原活动已结束。核对以下商品、秒杀价与每达人库存，填写新时间后，即可为本任务指定的抖音号创建授权。'));
    const previewHost = el('div');
    if (candidates.length > 1) { const label = el('label', '选择要沿用的活动'), select = el('select'); select.id = 'resume-field-' + ++fieldCounter; label.htmlFor = select.id;
      for (const [index, p] of candidates.entries()) { const o = el('option', `活动 ${index + 1} · 结束于 ${when(p.end_time_old)}`); o.value = String(index); select.append(o); }
      select.onchange = () => { selected = candidates[Number(select.value)]; previewHost.replaceChildren(); addPreview(previewHost, selected); }; f.append(label, select);
    }
    addPreview(previewHost, selected); f.append(previewHost);
    const start = inputField('新开始时间（北京时间）', 'datetime-local'), end = inputField('新结束时间（北京时间）', 'datetime-local'); f.append(start.label, start.input);
    const soon = el('button', '设为约 2 分钟后开始', 'secondary'); soon.type = 'button'; soon.onclick = () => { start.input.value = new Date(Math.ceil((Date.now() + 120000) / 60000) * 60000 + 8 * 3600000).toISOString().slice(0, 16); localError.hidden = true; }; f.append(soon, end.label, end.input);
    const consent = el('label', undefined, 'permission'), check = el('input'); check.type = 'checkbox'; check.required = true; consent.append(check, el('span', '已核对商品、价格、每达人库存与活动时间')); const b = el('button', '确认设置并继续'); b.type = 'submit'; f.append(consent, b);
    f.onsubmit = async e => {
      e.preventDefault(); const start_time = Date.parse(start.input.value + ':00+08:00') / 1000, end_time = Date.parse(end.input.value + ':00+08:00') / 1000;
      if (!Number.isFinite(start_time) || !Number.isFinite(end_time) || start_time <= Date.now() / 1000 || end_time <= start_time) { error(new UserError(errorMessages.schedule_time), localError); return; }
      if (!await confirmAction('按这些设置创建秒杀授权？', `${hotelName(t) || '本任务酒店'}\n抖音号：${(t.payload?.accounts || []).join('、')}\n开始：${when(start_time)}\n结束：${when(end_time)}\n将沿用上方商品、价格与每达人库存。`, '确认授权')) return;
      b.disabled = true; try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { template_id: selected.template_id, fingerprint: selected.fingerprint, start_time, end_time, confirmed: true } }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; }
    };
  } else if (t.kind === 'plan' && t.read_only && !t.committed && !t.cancel_requested) {
    f.append(el('p', '本计划的信息已进入确认步骤。继续后将重新核对酒店、商品、计划条款与权限，核对一致后同意计划。'));
    if (Array.isArray(t.details?.preview?.products)) addPreview(f, t.details.preview);
    const b = el('button', '确认并同意计划'); b.type = 'submit'; f.append(b);
    f.onsubmit = async e => { e.preventDefault(); if (!await confirmAction('同意这条开团计划？', `${hotelName(t) || '本任务酒店'}\n确认后，将重新核对酒店、商品与计划条款，核对一致后执行同意计划。请先确认这正是你要处理的计划。`, '确认同意')) return; b.disabled = true; try { const params = { confirmed: true, action: 'approve_plan' }; if (t.details?.preview?.fingerprint) params.fingerprint = t.details.preview.fingerprint; await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
  } else {
    if (selected) addPreview(f, selected);
    f.append(el('p', '当前信息还不足以继续执行。补充需要核对的情况，随后可重新查看本任务的结果。'));
    const note = inputField('补充说明', 'textarea', false); note.input.placeholder = '例如：已恢复登录，或已有新的生效活动'; const b = el('button', '保存说明并继续核对'); b.type = 'submit'; f.append(note.label, note.input, b);
    f.onsubmit = async e => { e.preventDefault(); b.disabled = true; try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { note: note.input.value.trim() } }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
  }
  const close = el('button', '收起', 'secondary resume-close'); close.type = 'button'; close.onclick = () => { f.remove(); button.disabled = false; button.focus(); }; f.append(close, localError); item.append(f); f.querySelector('input,textarea,select,button')?.focus();
}
function renderConnection(s) {
  const worker = s.worker || {}, seen = Number(worker.last_heartbeat || 0), online = worker.online === true;
  $('#connection').textContent = online ? '已连接' : '暂未连接'; $('#connection').className = 'badge ' + (online ? 'ok' : 'warn'); $('#connection-dot').className = 'status-dot ' + (online ? 'ok' : 'warn');
  $('#connection-heading').textContent = online ? '执行端已连接' : '执行端暂未连接';
  $('#connection-detail').textContent = online ? '执行端可接收任务，具体处理结果以每张任务为准。提交后，请在任务进展里查看结果。' : '新任务暂时无法开始处理。请确认执行设备已开启并连网，恢复后刷新查看进度。';
  $('#last-updated').textContent = '读取于 ' + when(Date.now() / 1000) + (seen ? ' · 最近连接于 ' + when(seen) : '');
}
async function refresh() {
  if (loading) return; loading = true; $('#refresh').disabled = true; $('#refresh span').textContent = '读取中'; $('#tasks').setAttribute('aria-busy', 'true');
  try {
    const [q, s] = await Promise.all([api('tasks'), api('status')]); if (!Array.isArray(q.tasks) || typeof s.worker?.online !== 'boolean') throw new UserError('最新进度尚未完整读取，当前结果还不能确认。请刷新后再查看任务。', { response: { tasks: q, status: s } }); tasks = q.tasks; hasLoaded = true; authenticated = true; $('#login').hidden = true; $('#error').hidden = true; renderConnection(s); render();
  } catch (e) {
    error(e); $('#connection-heading').textContent = '最新进度暂时无法读取'; $('#connection').textContent = '待更新'; $('#connection').className = 'badge warn'; $('#connection-dot').className = 'status-dot warn'; $('#connection-detail').textContent = '当前连接暂时不可用，页面中的进度可能已经变化。请恢复连接后刷新，再确认是否继续。';
    if (!hasLoaded) { $('#queue-summary').textContent = '最新任务暂时无法读取。请连接后刷新。'; $('#tasks').replaceChildren(empty('暂时无法读取任务', '最新进度尚未确认。请检查网络或连接任务入口，然后点击刷新。')); }
  } finally { loading = false; $('#refresh').disabled = false; $('#refresh span').textContent = '刷新'; $('#tasks').setAttribute('aria-busy', 'false'); setSubmitAvailability(); }
}
function renderTheme() { const light = document.documentElement.dataset.theme === 'light'; $('#theme-toggle').setAttribute('aria-label', light ? '切换到深色模式' : '切换到浅色模式'); $('#theme-toggle span').textContent = light ? '深色模式' : '浅色模式'; }
$('#theme-toggle').onclick = () => { const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'; document.documentElement.dataset.theme = theme; try { localStorage.setItem('zkn-theme', theme); } catch (_) {} renderTheme(); };
addEventListener('storage', e => { if (e.key === 'zkn-theme') { document.documentElement.dataset.theme = e.newValue === 'light' ? 'light' : 'dark'; renderTheme(); } });
$('#login-form').onsubmit = async e => { e.preventDefault(); const b = e.target.querySelector('button'); b.disabled = true; $('#login-result').textContent = '正在连接，请稍候。'; try { await api('login', { token: new FormData(e.target).get('token') }); e.target.reset(); $('#login-result').textContent = ''; await refresh(); } catch (err) { error(err, $('#login-result')); } finally { b.disabled = false; } };
for (const b of document.querySelectorAll('[data-filter]')) b.onclick = () => { filter = b.dataset.filter; updateFilters(); if (hasLoaded) render(); };
$('#task-search').addEventListener('input', () => { if (hasLoaded) render(); });
for (const radio of document.querySelectorAll('[name=kind]')) radio.onchange = () => { const isPlan = radio.value === 'plan'; $('#plan-fields').hidden = !isPlan; $('#authorization-fields').hidden = isPlan; $('#link').required = isPlan; $('#hotel').required = !isPlan; $('#accounts').required = !isPlan; pendingRequest = null; $('#form-result').replaceChildren(); updatePermission(); };
function updatePermission() { $('#submit').firstChild.textContent = $('#allow-write').checked ? '提交并授权执行' : '提交核验任务'; $('#permission-note').textContent = $('#allow-write').checked ? '核对无误后将执行，提交前会再次请你确认。' : '当前只核对信息。需要执行时，你可以在任务里确认。'; }
$('#task-form').addEventListener('input', () => { pendingRequest = null; updatePermission(); });
$('#task-form').onsubmit = async e => {
  e.preventDefault(); const b = $('#submit'); b.disabled = true; $('#form-result').className = ''; $('#form-result').replaceChildren();
  try {
    const kind = document.querySelector('[name=kind]:checked').value; const payload = { kind, allow_write: $('#allow-write').checked };
    if (kind === 'plan') { const v = $('#link').value.trim(), matches = v.match(/(?:task_id|plan_id|id)=([0-9]{18,20})(?:[^0-9]|$)/g); const ids = [...new Set((matches || []).map(m => m.match(/=([0-9]+)/)[1]))]; if (/^[0-9]{18,20}$/.test(v)) ids.push(v); if (ids.length !== 1) throw new UserError('暂时无法识别唯一的计划，任务尚未提交。请粘贴完整的来客计划链接或计划编号后重试。'); payload.plan_id = ids[0]; }
    else { payload.hotel = $('#hotel').value.trim(); payload.accounts = [...new Set($('#accounts').value.trim().split(/[\s,，、;；]+/).filter(Boolean))]; if (!payload.hotel) throw new UserError(errorMessages.hotel); if (!payload.accounts.length || payload.accounts.length > 40 || payload.accounts.some(a => !/^[A-Za-z0-9_.-]{1,64}$/.test(a))) throw new UserError(errorMessages.accounts); }
    if (payload.allow_write && !await confirmAction('提交并授权执行？', kind === 'plan' ? '核对酒店、商品、条款与权限一致后，将同意这条来客开团计划。请确认计划链接正确。' : `${payload.hotel}\n抖音号：${payload.accounts.join('、')}\n核对活动商品、价格、库存与时间一致后，将为这些账号补充授权。`, '确认提交并授权')) return;
    $('#form-result').textContent = '正在提交，任务进度将在右侧显示。'; pendingRequest = pendingRequest || crypto.randomUUID();
    const response = await api('tasks', { request_id: pendingRequest, ...payload }); $('#form-result').className = 'success'; $('#form-result').textContent = response.duplicate ? '这项任务已存在。请在任务进展里查看当前状态，再决定是否继续。' : '任务已提交，处理结果仍需核验。请在任务进展里查看进度与下一步。';
    filter = 'all'; $('#task-search').value = ''; updateFilters(); await refresh();
  } catch (err) { $('#form-result').className = 'error'; error(err, $('#form-result')); } finally { setSubmitAvailability(); }
};
$('#refresh').onclick = refresh; renderTheme(); setSubmitAvailability(); refresh(); setInterval(() => { if (!document.hidden && !$('#tasks .resume') && !$('#confirm-dialog').open) refresh(); }, 10000);
