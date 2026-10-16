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
let writeEnvironmentReady = false, writeEnvironmentReason = '正在读取写入环境。';
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
function publicBusinessText(value) {
  if (typeof value !== 'string') return '';
  const text = value.trim();
  if (!text || text.length > 2000 || /^[a-z][a-z0-9_]{2,}$/i.test(text) || /(?:traceback|stack trace|lease_token|request_id|worker_id)/i.test(text)) return '';
  return text;
}
function taskSummary(t, fallback) { return publicBusinessText(t.result?.text) || publicBusinessText(typeof t.result === 'string' ? t.result : '') || publicBusinessText(t.details?.reason) || fallback; }
function hotelSuggestions(t) {
  const values = [], add = value => { const name = safeName(value); if (name && !values.includes(name)) values.push(name); };
  add(t.result?.evidence?.hotel_resolution?.resolved_hotel); add(t.details?.hotel_resolution?.resolved_hotel); add(t.details?.suggested_hotel); add(t.details?.resolved_hotel);
  for (const candidate of Array.isArray(t.details?.candidates) ? t.details.candidates : []) add(candidate?.name);
  return values;
}
function resolvedHotel(t) { return safeName(t.result?.evidence?.hotel_resolution?.resolved_hotel) || safeName(t.details?.hotel_resolution?.resolved_hotel) || ''; }
function renderHotelGuidance(parent, t) {
  if (t.kind !== 'authorization') return;
  const resolved = resolvedHotel(t), suggestions = hotelSuggestions(t); if (!resolved && !suggestions.length) return;
  const box = el('div', undefined, 'hotel-guidance');
  if (resolved) box.append(el('strong', '已解析精确门店：' + resolved), el('p', '系统按精确目录身份继续核对，不会用相似酒店代替。'));
  else if (suggestions.length === 1) box.append(el('strong', '建议核对精确门店：' + suggestions[0]), el('p', '建议仅供审阅；原任务的门店与账号不会被补充说明改写。'));
  else box.append(el('strong', `目录返回 ${suggestions.length} 个候选门店`), el('p', '请在新建任务中填写完整分店名；原任务不会自动选择相似门店。'), el('p', suggestions.slice(0, 5).join('、'), 'meta'));
  parent.append(box);
}
function carryAuthorizationToComposer(t, hotel) {
  const radio = document.querySelector('[name=kind][value=authorization]'); radio.checked = true; radio.dispatchEvent(new Event('change'));
  $('#hotel').value = hotel; $('#accounts').value = Array.isArray(t.payload?.accounts) ? t.payload.accounts.join('\n') : ''; $('#allow-write').checked = false; pendingRequest = null; updatePermission();
  $('.composer').scrollIntoView({ behavior: 'smooth', block: 'start' }); $('#hotel').focus({ preventScroll: true });
}
function setSubmitAvailability() {
  $('#submit').disabled = !authenticated; $('#submit').title = authenticated ? '' : '连接任务入口后即可提交';
  $('#allow-write').disabled = !authenticated || !writeEnvironmentReady;
}
class UserError extends Error { constructor(message, technical) { super(message); this.technical = technical; } }
async function api(path, body) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', signal: controller.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await r.json().catch(() => null);
    if (r.status === 401 || r.redirected && r.url.includes('/site/login')) {
      authenticated = false; setSubmitAvailability(); updatePermission(); $('#login').hidden = false;
      throw new UserError('访问验证已失效，暂时无法读取或提交任务。请重新连接任务入口后继续。', { status: r.status, response: data });
    }
    if (!r.ok || !data) throw new UserError(errorMessages[data?.error] || '暂时无法完成这次操作，最新结果尚未确认。请刷新后重试，仍有问题时联系管理员。', { status: r.status, response: data });
    return data;
  } catch (e) {
    if (e instanceof UserError) throw e;
    throw new UserError('连接暂时中断，最新结果尚未确认。请检查网络后刷新任务，确认最新进度再继续。', { message: e.name === 'AbortError' ? 'Request timeout' : String(e) });
  } finally { clearTimeout(timer); }
}
async function submitTask(payload) {
  pendingRequest = pendingRequest || crypto.randomUUID();
  const response = await api('tasks', { request_id: pendingRequest, ...payload });
  pendingRequest = null;
  return response;
}
function parsePlanId(input) {
  const message = '暂时无法识别唯一的计划，任务尚未提交。请粘贴完整的来客计划链接或计划编号后重试。';
  const reject = () => { throw new UserError(message); };
  const PLAN_ID = /^[0-9]{18,20}$/;
  const uniqueId = ids => {
    const valid = ids.filter(id => PLAN_ID.test(id));
    return valid.length && new Set(valid).size === 1 ? valid[0] : null;
  };
  const scanIds = text => uniqueId([...(String(text).matchAll(/(?:task_id|plan_id|id)=([0-9]{18,20})/gi))].map(m => m[1]));
  if (typeof input !== 'string' || input.length > 16384) return reject();
  // Chat shares often prefix "@商家名" or other labels before the real URL.
  const raw = input.trim().replace(/[\u200b\u200c\u200d\ufeff\u00ad]/g, '');
  if (PLAN_ID.test(raw)) return raw;
  let value = raw.replace(/\s/g, '');
  const embedded = value.match(/https:\/\/life\.douyin\.com\/[^\s"'<>]*|snssdk299467:\/\/[^\s"'<>]*/i);
  if (embedded) value = embedded[0].replace(/[，。；;）)\]】>]+$/g, '');
  const early = scanIds(value);
  for (let layer = 0; layer < 8; layer++) {
    for (let encoding = 0; !/^[a-z][a-z0-9+.-]*:\/\//i.test(value) && encoding < 8; encoding++) {
      let decoded;
      try { decoded = decodeURIComponent(value); } catch (_) { return early || reject(); }
      if (decoded === value) return early || reject();
      value = decoded;
    }
    if (/%(?![0-9a-f]{2})/i.test(value)) return early || reject();
    let url;
    try { url = new URL(value); } catch (_) { return early || reject(); }
    if (url.username || url.password) return early || reject();
    if (url.port && url.port !== '443' && url.port !== '80') return early || reject();
    if (url.hash) url.hash = '';
    const nested = key => {
      const values = url.searchParams.getAll(key);
      if (values.length !== 1 || !values[0]) return null;
      return values[0];
    };
    if (url.protocol === 'https:' && url.hostname === 'life.douyin.com') {
      const path = url.pathname.replace(/\/+$/, '') || '/';
      if (path === '/h5/download') {
        const next = nested('redirect_url');
        if (!next) return early || reject();
        value = next;
        continue;
      }
      const ids = ['task_id', 'plan_id', 'id'].flatMap(key => url.searchParams.getAll(key));
      const planId = uniqueId(ids) || scanIds(value);
      if (planId && (path === '/h5/alliance/merchant/plan/oriented/info' || path.includes('/plan/') || early)) return planId;
      if (planId) return planId;
      return early || reject();
    }
    if (url.protocol === 'snssdk299467:' && (url.hostname === 'webview' || url.pathname.replace(/\/+$/, '') === '/webview')) {
      const next = nested('url');
      if (!next) return early || reject();
      value = next;
      continue;
    }
    return early || reject();
  }
  return early || scanIds(value) || reject();
}
function money(cents) {
  const valid = typeof cents === 'number' && Number.isInteger(cents) || typeof cents === 'string' && /^\d+$/.test(cents);
  return valid ? new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(Number(cents) / 100) : '未返回';
}
function tableRegion(table, label) { const box = el('div', undefined, 'table-scroll'); box.tabIndex = 0; box.setAttribute('role', 'region'); box.setAttribute('aria-label', label); box.append(table); return box; }
function productKey(product) { return String(product?.id) + '\u0000' + String(product?.sku_id); }
function productRelation(oldProductKeys, candidate) { return oldProductKeys.has(productKey(candidate)) ? '旧模板精确命中' : '当前候选 · 未授权'; }
function productState(product) {
  if (!product.candidate_returned) return ['未返回 · 状态未知', 'neutral'];
  if (product.status === 'verified') return ['精确命中', 'ok'];
  if (product.status === 'blocked') return ['已返回 · 条件未通过', 'bad'];
  return ['已返回 · 仍有未知项', 'warn'];
}
function productReason(product) {
  if (!product.candidate_returned) return '当前完整候选列表未返回这个精确商品，无法据此判断停售或库存。';
  const reasons = (product.reasons || []).map(value => String(value).replaceAll('可售库存', '可售量'));
  if (reasons.length) return reasons.join('；');
  return product.status === 'verified' ? '商品、规格、销售和使用时段已按当前接口核对。' : '当前接口已返回，但仍有条件未确认。';
}
function renderProductCheck(parent, check) {
  if (!check || typeof check !== 'object') return;
  const section = el('section', undefined, 'product-check'); section.setAttribute('aria-label', '当前档期商品核对'); section.append(el('h4', '当前档期商品核对'));
  if (check.status === 'unavailable' || !Array.isArray(check.products)) {
    section.append(el('p', '当前商品接口暂未完成核对，所有商品状态保持未知。本单只会继续读取结果，不会重复发送保存请求。', 'product-check-lead')); parent.append(section); return;
  }
  const products = check.products, returned = products.filter(product => product.candidate_returned).length, missing = products.length - returned;
  section.append(el('p', `旧模板 ${products.length} 个商品：当前接口精确返回 ${returned} 个；未返回 ${missing} 个。未返回只表示状态未知，不能据此判断停售或库存。`, 'product-check-lead'));
  const oldTable = el('table'); oldTable.className = 'product-table old-products'; const oldCaption = el('caption', '旧模板商品核对明细', 'sr-only'), oldHead = el('thead'), oldHeadRow = el('tr');
  for (const text of ['旧模板商品', '当前核对结果', '说明']) oldHeadRow.append(el('th', text)); oldHead.append(oldHeadRow); oldTable.append(oldCaption, oldHead); const oldBody = el('tbody');
  for (const [index, product] of products.entries()) {
    const row = el('tr'), identityCell = el('td'), name = safeName(product.name) || `旧模板商品 ${index + 1}`; identityCell.append(el('div', name, 'product-name'), el('div', `商品 ${product.id || '未返回'} · 规格 ${product.sku_id || '未返回'}`, 'meta'));
    const [label, tone] = productState(product), stateCell = el('td'); stateCell.append(el('span', label, 'badge ' + tone)); row.append(identityCell, stateCell, el('td', productReason(product))); oldBody.append(row);
  }
  oldTable.append(oldBody); section.append(tableRegion(oldTable, '旧模板商品核对明细，可横向滚动'));
  const candidates = Array.isArray(check.current_candidates) ? check.current_candidates : [], seen = new Set(), rows = candidates.filter(candidate => { const key = productKey(candidate); if (seen.has(key)) return false; seen.add(key); return true; });
  if (rows.length) {
    const oldProductKeys = new Set(products.map(productKey)), candidateProducts = new Set(rows.map(candidate => String(candidate.id))); section.append(el('h5', `当前接口候选 · ${candidateProducts.size} 个商品`)); section.append(el('p', '商品售价来自当前商品接口；平台建议秒杀价仅供审阅，尚未确认使用。这里不会替换旧模板商品，也不会触发新建。', 'hint'));
    const table = el('table'); table.className = 'product-table current-products'; const caption = el('caption', '当前接口候选商品与价格', 'sr-only'), head = el('thead'), headRow = el('tr');
    for (const text of ['当前商品', '与旧模板关系', '商品售价', '平台建议秒杀价（未确认）', '平台状态']) headRow.append(el('th', text)); head.append(headRow); table.append(caption, head); const body = el('tbody');
    for (const [index, candidate] of rows.entries()) {
      const row = el('tr'), identityCell = el('td'); identityCell.append(el('div', safeName(candidate.name) || `当前候选商品 ${index + 1}`, 'product-name'), el('div', `商品 ${candidate.id || '未返回'} · 规格 ${candidate.sku_id || '未返回'}`, 'meta'));
      const relation = productRelation(oldProductKeys, candidate); let platform = '禁选状态未返回';
      if (candidate.is_deny === true || candidate.deny_reason) platform = candidate.deny_reason || '平台明确禁选'; else if (candidate.is_deny === false) platform = '平台未标记禁选';
      row.append(identityCell, el('td', relation), el('td', money(candidate.price_cents)), el('td', money(candidate.suggested_price_cents)), el('td', platform)); body.append(row);
    }
    table.append(body); section.append(tableRegion(table, '当前候选商品与价格，可横向滚动'));
  }
  parent.append(section);
}
function technicalDetails(value) { const d = el('details'), s = el('summary', '技术详情'); d.append(s, el('pre', JSON.stringify(value, (key, item) => key === 'current_product_check' ? undefined : item, 2))); return d; }
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
    const [status, fallbackSummary, tone] = taskStatus(t), summary = taskSummary(t, fallbackSummary), head = el('div', undefined, 'task-head'); head.append(el('h3', taskTitle(t)), el('span', status, 'badge ' + tone));
    item.append(head, el('p', summary, 'task-summary'));
    const facts = el('div', undefined, 'task-facts'), p = t.payload || {};
    const mode = t.committed ? (t.status === 'succeeded' ? '核验方式：执行后核对结果' : '核验方式：确认执行结果') : p.allow_write && !t.read_only ? '处理方式：核对后执行' : '处理方式：仅核对信息';
    facts.append(el('span', mode));
    if (t.kind === 'authorization' && Array.isArray(p.accounts)) facts.append(el('span', '抖音号：' + p.accounts.join('、')));
    item.append(facts, el('div', '更新于 ' + when(t.updated), 'meta'));
    renderHotelGuidance(item, t);
    renderProductCheck(item, t.details?.current_product_check);
    const actions = el('div', undefined, 'task-actions');
    if (t.status === 'needs_input' && !t.cancel_requested) { const b = el('button', '查看并处理'); b.type = 'button'; b.onclick = () => showResume(item, t, b); actions.append(b); }
    const suggestedHotels = hotelSuggestions(t), preferredHotel = resolvedHotel(t) || (suggestedHotels.length === 1 ? suggestedHotels[0] : '');
    if (t.status === 'needs_input' && t.kind === 'authorization' && preferredHotel && preferredHotel !== safeName(t.payload?.hotel) && !t.details?.preview) { const b = el('button', '用此门店新建任务', 'secondary'); b.type = 'button'; b.onclick = () => carryAuthorizationToComposer(t, preferredHotel); actions.append(b); }
    if (['waiting_device', 'waiting_review'].includes(t.status) && !t.cancel_requested) {
      const b = el('button', '立即只读复核', 'secondary'); b.type = 'button';
      b.onclick = async () => { if (!await confirmAction('立即只读复核这张任务？', '只重新读取平台当前状态，不会再次发送保存、同意或创建请求。若执行端仍未恢复，结果可能还需要等待。', '确认只读复核')) return; b.disabled = true; b.textContent = '正在只读复核'; try { await api('tasks/' + t.id + '/retry', { expected_revision: t.revision }); await refresh(); } catch (e) { error(e); b.disabled = false; b.textContent = '立即只读复核'; } }; actions.append(b);
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
  if (t.kind === 'authorization' && selected?.mode === 'authorize_existing' && !t.details?.blocked && !selected.blocked) {
    f.append(el('p', '当前活动仍在生效，但下列抖音号缺少完整授权。确认后，系统会重新读取同一活动、商品、价格、库存与已有达人；全部与本预览一致时，才补充缺失账号。'));
    addPreview(f, selected);
    const missing = Array.isArray(selected.missing_accounts) ? selected.missing_accounts : (t.payload?.accounts || []);
    if (missing.length) f.append(el('p', '本次只补充：' + missing.join('、'), 'meta'));
    if (selected.end_time) f.append(el('p', '当前活动结束时间：' + when(selected.end_time), 'hint'));
    const consent = el('label', undefined, 'permission'), check = el('input'); check.type = 'checkbox'; check.required = true;
    consent.append(check, el('span', '已核对当前活动、商品、价格、每达人库存与待补充账号'));
    const b = el('button', writeEnvironmentReady ? '确认补充授权' : '执行环境未就绪'); b.type = 'submit'; b.disabled = !writeEnvironmentReady;
    if (!writeEnvironmentReady) f.append(el('p', writeEnvironmentReason + ' 刷新状态后再确认。', 'notice warn'));
    f.append(consent, b);
    f.onsubmit = async e => {
      e.preventDefault();
      if (!writeEnvironmentReady) { error(new UserError(writeEnvironmentReason), localError); return; }
      if (!await confirmAction('把缺失账号补充到当前秒杀活动？', `${hotelName(t) || '本任务酒店'}\n只补充：${missing.join('、')}\n系统会在执行前重新核对活动、商品、价格、库存与已有达人；任何变化都会停止，不会覆盖原授权。`, '确认补充授权')) return;
      b.disabled = true;
      try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { action: 'authorize_existing', confirmed: true, activity_id: selected.activity_id, fingerprint: selected.fingerprint } }); f.remove(); await refresh(); }
      catch (e) { error(e, localError); b.disabled = false; }
    };
  } else if (t.kind === 'authorization' && selected && !t.details?.blocked && !selected.blocked) {
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
    if (t.kind === 'authorization' && !selected) {
      f.append(el('p', taskSummary(t, '当前门店或账号信息还不足以继续核对。'), 'resume-reason'));
      f.append(el('p', '这张原任务的门店与抖音号已经锁定。下方备注只会留作复核线索，不会修改门店、账号、商品或价格；门店名称有误时，请回到“新建任务”重新提交精确分店名。'));
      const suggestions = hotelSuggestions(t), preferred = resolvedHotel(t) || (suggestions.length === 1 ? suggestions[0] : '');
      if (preferred && preferred !== safeName(t.payload?.hotel)) { const use = el('button', '把建议门店带回新建任务', 'secondary'); use.type = 'button'; use.onclick = () => carryAuthorizationToComposer(t, preferred); f.append(use); }
    } else f.append(el('p', '当前信息还不足以继续执行。补充需要核对的情况，随后可重新查看本任务的结果。'));
    const note = inputField(t.kind === 'authorization' && !selected ? '复核备注（不会更改门店或账号）' : '补充说明', 'textarea', false); note.input.placeholder = t.kind === 'authorization' && !selected ? '例如：已核对目录名称，等待重新只读核验' : '例如：已恢复登录，或已有新的生效活动'; const b = el('button', t.kind === 'authorization' && !selected ? '保存备注并只读复核' : '保存说明并继续核对'); b.type = 'submit'; f.append(note.label, note.input, b);
    f.onsubmit = async e => { e.preventDefault(); b.disabled = true; try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { note: note.input.value.trim() } }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
  }
  const close = el('button', '收起', 'secondary resume-close'); close.type = 'button'; close.onclick = () => { f.remove(); button.disabled = false; button.focus(); }; f.append(close, localError); item.append(f); f.querySelector('input,textarea,select,button')?.focus();
}
function runtimeState(kind, value = {}) {
  const status = value.status, reason = value.reason;
  if (kind === 'business_app') {
    if (status === 'running') return ['运行中', 'ok'];
    if (status === 'stopped') return ['未启动', 'bad'];
    return ['未确认', reason === 'metadata_probe_skipped' ? 'neutral' : 'warn'];
  }
  if (kind === 'native_interface') {
    if (status === 'available') return ['可用', 'ok'];
    if (status === 'unavailable') return ['不可执行', 'bad'];
    if (reason === 'processes_present_attach_not_probed') return ['任务执行前复核', 'warn'];
    return ['未确认', reason === 'metadata_probe_skipped' ? 'neutral' : 'warn'];
  }
  if (status === 'available') return [kind === 'root' ? '已确认' : '可连接', 'ok'];
  if (status === 'unavailable') return [kind === 'root' ? '未就绪' : '不可用', 'bad'];
  return ['未确认', reason === 'metadata_probe_skipped' ? 'neutral' : 'warn'];
}
function renderRuntimeHealth(runtime = {}) {
  const list = $('#runtime-health'), rows = [['android_device', 'Android'], ['root', 'root'], ['business_app', '来客 App'], ['native_interface', '原生接口']]; list.replaceChildren();
  for (const [key, name] of rows) { const item = el('li'), state = runtimeState(key, runtime[key]); item.append(el('span', name), el('strong', state[0], 'badge ' + state[1])); list.append(item); }
}
function writeReadiness(worker, runtime) {
  if (worker.gateway_online !== true) return [false, 'Mac 收单离线，暂不接受新的写入任务。'];
  if (runtime?.android_device?.status !== 'available') return [false, 'Android 尚未确认可连接，暂不接受新的写入任务。'];
  if (runtime?.root?.status !== 'available') return [false, 'root 尚未确认就绪，暂不接受新的写入任务。'];
  if (runtime?.business_app?.status !== 'running') return [false, '来客 App 尚未确认运行，暂不接受新的写入任务。'];
  const native = runtime?.native_interface || {}, safeUnknown = native.status === 'unknown' && native.reason === 'processes_present_attach_not_probed';
  if (native.status !== 'available' && !safeUnknown) return [false, native.status === 'unavailable' ? '原生接口当前不可执行，暂不接受新的写入任务。' : '原生接口状态尚未确认，暂不接受新的写入任务。'];
  return [true, 'Android、root 与来客 App 已通过只读探测；原生接口会在每张任务执行前复核。'];
}
function setWriteEnvironment(ready, reason) {
  writeEnvironmentReady = ready; writeEnvironmentReason = reason;
  if (!ready && $('#allow-write').checked) { $('#allow-write').checked = false; pendingRequest = null; }
  $('.permission').classList.toggle('is-disabled', !ready); setSubmitAvailability(); updatePermission();
}
function renderConnection(s) {
  const worker = s.worker || {}, seen = Number(worker.last_heartbeat || 0), gateway = worker.gateway_online === true, runtime = worker.health?.runtime || {};
  $('#connection').textContent = gateway ? '收单在线' : '收单离线'; $('#connection').className = 'badge ' + (gateway ? 'ok' : 'bad'); $('#connection-dot').className = 'status-dot ' + (gateway ? 'ok' : 'bad');
  $('#connection-heading').textContent = gateway ? 'Mac 收单在线' : 'Mac 收单离线';
  $('#connection-detail').textContent = gateway ? '服务器可以把任务交给 Mac。收单在线不代表 Android、App 或原生接口已经可执行，请分别查看下方状态。' : '服务器暂时联系不到 Mac。任务仍会保留；可提交只读核验，写入任务需等待收单恢复。';
  renderRuntimeHealth(runtime); const readiness = writeReadiness(worker, runtime); setWriteEnvironment(readiness[0], readiness[1]);
  const checked = Number(runtime.checked_at || 0); $('#last-updated').textContent = '读取于 ' + when(Date.now() / 1000) + (seen ? ' · 最近收单于 ' + when(seen) : '') + (checked ? ' · 环境核对于 ' + when(checked) : '');
}
async function refresh() {
  if (loading) return; loading = true; $('#refresh').disabled = true; $('#refresh span').textContent = '读取中'; $('#tasks').setAttribute('aria-busy', 'true');
  try {
    const [q, s] = await Promise.all([api('tasks'), api('status')]); if (!Array.isArray(q.tasks) || typeof s.worker?.online !== 'boolean') throw new UserError('最新进度尚未完整读取，当前结果还不能确认。请刷新后再查看任务。', { response: { tasks: q, status: s } }); tasks = q.tasks; hasLoaded = true; authenticated = true; $('#login').hidden = true; $('#error').hidden = true; renderConnection(s); render();
  } catch (e) {
    error(e); $('#connection-heading').textContent = '最新收单与环境状态无法读取'; $('#connection').textContent = '待更新'; $('#connection').className = 'badge warn'; $('#connection-dot').className = 'status-dot warn'; $('#connection-detail').textContent = '当前状态可能已经变化。只读任务仍可保存，新的写入任务会保持关闭，恢复连接后请刷新。'; renderRuntimeHealth({}); setWriteEnvironment(false, '运行环境状态无法读取，暂不接受新的写入任务。');
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
function updatePermission() {
  const checked = $('#allow-write').checked; $('#submit').firstChild.textContent = checked ? '提交并授权执行' : '提交核验任务';
  if (!authenticated) $('#permission-note').textContent = '连接任务入口后可提交；写入选项还需运行环境核验。';
  else if (!writeEnvironmentReady) $('#permission-note').textContent = writeEnvironmentReason + ' 仍可提交只读核验。';
  else $('#permission-note').textContent = checked ? '执行前会重新核对环境、酒店、商品与权限，提交前会再次请你确认。' : writeEnvironmentReason + ' 当前只提交只读核验。';
}
$('#task-form').addEventListener('input', () => { pendingRequest = null; updatePermission(); });
$('#task-form').onsubmit = async e => {
  e.preventDefault(); const b = $('#submit'); b.disabled = true; $('#form-result').className = ''; $('#form-result').replaceChildren();
  try {
    const kind = document.querySelector('[name=kind]:checked').value; const payload = { kind, allow_write: $('#allow-write').checked };
    if (kind === 'plan') payload.plan_id = parsePlanId($('#link').value);
    else { payload.hotel = $('#hotel').value.trim(); payload.accounts = [...new Set($('#accounts').value.trim().split(/[\s,，、;；]+/).filter(Boolean))]; if (!payload.hotel) throw new UserError(errorMessages.hotel); if (!payload.accounts.length || payload.accounts.length > 40 || payload.accounts.some(a => !/^[A-Za-z0-9_.-]{1,64}$/.test(a))) throw new UserError(errorMessages.accounts); }
    if (payload.allow_write && !writeEnvironmentReady) throw new UserError(writeEnvironmentReason + ' 当前只能提交只读核验。');
    if (payload.allow_write && !await confirmAction('提交并授权执行？', kind === 'plan' ? '核对酒店、商品、条款与权限一致后，将同意这条来客开团计划。请确认计划链接正确。' : `${payload.hotel}\n抖音号：${payload.accounts.join('、')}\n核对活动商品、价格、库存与时间一致后，将为这些账号补充授权。`, '确认提交并授权')) return;
    $('#form-result').textContent = '正在提交，任务进度将在右侧显示。';
    const response = await submitTask(payload); $('#form-result').className = 'success'; $('#form-result').textContent = response.duplicate ? '这项任务已存在。请在任务进展里查看当前状态，再决定是否继续。' : '任务已提交，处理结果仍需核验。请在任务进展里查看进度与下一步。';
    filter = 'all'; $('#task-search').value = ''; updateFilters(); await refresh();
  } catch (err) { $('#form-result').className = 'error'; error(err, $('#form-result')); } finally { setSubmitAvailability(); }
};
$('#refresh').onclick = refresh; renderTheme(); setSubmitAvailability(); updatePermission(); refresh(); setInterval(() => { if (!document.hidden && !$('#tasks .resume') && !$('#confirm-dialog').open) refresh(); }, 10000);
