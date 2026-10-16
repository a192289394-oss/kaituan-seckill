'use strict';
const $ = s => document.querySelector(s);
const base = new URL('api/', location.href).href;
const states = {
  queued: ['排队中', '已收到，还在排队，请稍候。', 'neutral'],
  running: ['处理中', '正在处理，请稍候。需要你点一下时会在这里提醒。', 'info'],
  waiting_review: ['处理中', '正在确认结果，请稍候。', 'info'],
  waiting_device: ['处理中', '暂时连不上执行端，恢复后会继续，请稍候。', 'warn'],
  needs_input: ['需要你选一下', '点「去处理」按提示确认具体事项后再继续。', 'warn'],
  succeeded: ['已完成', '已经做完。请看下方经营信息是否符合本次需求。', 'ok'],
  failed: ['没做成', '这次没有做成。请看原因后决定是否重新提交。', 'bad'],
  cancelled: ['没做成', '这张任务已停止。需要再办时请重新提交。', 'neutral'],
  expired: ['没做成', '这张任务已过期。请用新的计划链接或重新提交。', 'neutral'],
  cancel_requested: ['处理中', '正在停止，请稍候看最终结果。', 'warn']
};
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'expired']);
const operatorFailReasons = {
  cancelled: '已停止处理',
  expired: '已超过可执行时间',
  failed: '处理失败'
};
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
const readFailureLabels = {
  timeout: '读取超时',
  bridge_unavailable: '原生桥接不可用',
  identity_changed: '登录身份已变化',
  context_not_ready: '来客上下文未就绪',
  identity_invalid: '登录身份无效',
  sync_unavailable: '同步接口不可用',
  invalid_response: '接口返回无效',
  api_rejected: '接口拒绝读取',
  unknown: '原因未知'
};
function readFailureCopy(t) {
  const code = typeof t.details?.read_failure_code === 'string' ? t.details.read_failure_code : (typeof t.result?.read_failure_code === 'string' ? t.result.read_failure_code : '');
  const label = readFailureLabels[code] || '';
  const message = publicBusinessText(t.details?.message) || publicBusinessText(t.result?.message) || '';
  if (!label && !message) return '';
  const head = label ? ('暂时读不到最新结果：' + label) : '暂时读不到最新结果';
  const body = message ? (' ' + message) : '';
  return head + body + '。正在重试确认，不会再次提交。';
}
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
function taskTitle(t) { const kind = t.kind === 'authorization' ? '秒杀添加' : t.kind === 'inspect' ? '计划核验' : '直播开团'; return kind + ' · ' + (hotelName(t) || '酒店待核对'); }
function when(n) { return Number.isFinite(Number(n)) && Number(n) > 0 ? new Date(Number(n) * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未开始'; }
function isReadbackWaiting(t) {
  if (t.committed) return true;
  const text = [t.result?.text, t.details?.reason, t.details?.message, t.details?.verify_mismatch]
    .filter(v => typeof v === 'string').join(' ');
  return /回读|只回读|勿重发|确认结果|已提交/.test(text);
}
function isHumanChoiceWaiting(t) {
  if (t.status === 'needs_input') return true;
  if (t.status !== 'waiting_review') return false;
  if (isReadbackWaiting(t)) return false;
  const list = Array.isArray(t.details?.candidates) ? t.details.candidates : [];
  if (list.some(x => x && (x.mode === 'authorize_existing' || x.mode === 'create_new' || x.activity_id || x.template_id))) return true;
  if (t.details?.preview && !t.details?.blocked) return true;
  const text = [t.result?.text, t.details?.reason, t.details?.message]
    .filter(v => typeof v === 'string').join(' ');
  return /选活动|选择活动|确认时间|新建秒杀|没有生效中的秒杀|自行创建|补参|请确认|需要你|加到当前秒杀/.test(text);
}
function failReasonText(t) {
  const business = publicBusinessText(t.result?.text) || publicBusinessText(typeof t.result === 'string' ? t.result : '') || publicBusinessText(t.details?.reason) || publicBusinessText(t.details?.message);
  if (business) return business;
  return operatorFailReasons[t.status] || '这次没有做成，请刷新或重新提交。';
}
function needsInputDetail(t) {
  const live = Array.isArray(t.details?.candidates)
    ? t.details.candidates.filter(x => x && x.mode === 'authorize_existing' && x.activity_id && x.fingerprint && !x.blocked)
    : [];
  if (live.length > 1) return '请选择本店秒杀活动';
  if (live.length === 1) return '确认加到当前秒杀活动';
  const refuseCopy = '本店没有生效中的秒杀，请先去抖音来客创建活动后再来加号';
  const reasonBlobEarly = [t.details?.reason, t.details?.message, t.result?.text, t.details?.candidate_kind].filter(v => typeof v === 'string').join(' ');
  if (t.details?.candidate_kind === 'none' || /no_live_activity_refuse_create|没有生效中的秒杀|自行创建秒杀/.test(reasonBlobEarly)) {
    return refuseCopy;
  }
  const expired = Array.isArray(t.details?.candidates)
    ? t.details.candidates.filter(x => x && x.template_id && x.fingerprint && x.mode !== 'authorize_existing' && !x.blocked)
    : [];
  if (expired.length || (t.details?.preview && t.details.preview.mode !== 'authorize_existing' && !t.details?.blocked)) {
    return refuseCopy;
  }
  if (!live.length && (t.details?.blocked || t.details?.match === 'none')) {
    return refuseCopy;
  }
  const hotel = hotelName(t) || safeName(t.payload?.hotel);
  const accounts = Array.isArray(t.payload?.accounts) ? t.payload.accounts : [];
  const reasonBlob = [t.details?.reason, t.details?.message, t.result?.text].filter(v => typeof v === 'string').join(' ');
  if (!hotel) return '请填写或确认酒店全称';
  if (!accounts.length) return '请填写或确认要授权的抖音号';
  if (/酒店|门店/.test(reasonBlob) && /未|缺|不全|找不到|无法识别|未能|有误/.test(reasonBlob)) return '请填写或确认酒店全称';
  if (/账号|抖音号|达人/.test(reasonBlob) && /未|缺|不全|空|有误/.test(reasonBlob)) return '请填写或确认要授权的抖音号';
  const reason = publicBusinessText(t.details?.reason) || publicBusinessText(t.details?.message) || publicBusinessText(t.result?.text);
  if (reason) return reason;
  return states.needs_input[1];
}
function taskStatus(t) {
  const fallback = states[t.status] || ['处理中', '进度还在更新，请稍候刷新。', 'warn'];
  if (t.status === 'succeeded') {
    if (t.kind === 'inspect') return ['已完成', '计划信息已看过。需要开团时，请提交开团任务。', 'ok'];
    if (!t.payload?.allow_write && !t.committed) return ['已完成', '信息已核对。需要继续执行时，请重新提交。', 'ok'];
    return ['已完成', fallback[1], 'ok'];
  }
  if (['failed', 'cancelled', 'expired'].includes(t.status)) {
    return ['没做成', failReasonText(t), t.status === 'failed' ? 'bad' : 'neutral'];
  }
  if (t.status === 'queued') return ['排队中', fallback[1], 'neutral'];
  if (isHumanChoiceWaiting(t)) {
    return [needsInputDetail(t), states.needs_input[1], 'warn'];
  }
  if (t.status === 'waiting_review' || (t.committed && ['waiting_review', 'waiting_device', 'running'].includes(t.status))) {
    const mismatch = publicBusinessText(t.result?.text) || publicBusinessText(t.details?.reason) || publicBusinessText(t.details?.verify_mismatch);
    if (t.committed && mismatch) return ['处理中', '正在确认结果。读到的结果和预期不太一样：' + mismatch + ' 请人工核对，不要再次提交。', 'warn'];
    const fail = readFailureCopy(t);
    if (fail) return ['处理中', '正在确认结果。' + fail, 'warn'];
    return ['处理中', '正在确认结果，请稍候。', 'info'];
  }
  if (t.status === 'waiting_device') {
    const fail = readFailureCopy(t);
    return ['处理中', fail || fallback[1], 'warn'];
  }
  if (t.status === 'running' || t.status === 'cancel_requested') return [fallback[0], fallback[1], fallback[2]];
  return fallback;
}
function elapsedText(fromTs) {
  const start = Number(fromTs);
  if (!Number.isFinite(start) || start <= 0) return '';
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - start));
  if (sec < 60) return '不到 1 分钟';
  if (sec < 3600) return Math.floor(sec / 60) + ' 分钟';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return m ? (h + ' 小时 ' + m + ' 分钟') : (h + ' 小时');
}
function formatDurationSeconds(sec) {
  const n = Math.max(0, Math.floor(Number(sec) || 0));
  if (n < 60) return '不到 1 分钟';
  if (n < 3600) return Math.floor(n / 60) + ' 分钟';
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60);
  return m ? (h + ' 小时 ' + m + ' 分钟') : (h + ' 小时');
}
function formatTaskTimeline(t) {
  const created = Number(t.created || t.created_at || 0);
  const updated = Number(t.updated || t.updated_at || 0);
  const completed = Number(t.completed || t.completed_at || 0) || (terminal.has(t.status) ? updated : 0);
  const parts = [];
  if (created > 0) parts.push('提交时间：' + when(created));
  if (terminal.has(t.status)) {
    if (completed > 0) parts.push('完成时间：' + when(completed));
    if (created > 0 && completed > created) parts.push('共用时 ' + formatDurationSeconds(completed - created));
  } else if (updated > 0) {
    parts.push('当前状态：' + when(updated) + ' 起 · 已 ' + (elapsedText(updated) || '片刻'));
  } else if (created > 0) {
    parts.push('已处理 ' + (elapsedText(created) || '片刻'));
  }
  return parts;
}
function publicBusinessText(value) {
  if (typeof value !== 'string') return '';
  const text = value.trim();
  if (!text || text.length > 2000 || /^[a-z][a-z0-9_]{2,}$/i.test(text) || /(?:traceback|stack trace|lease_token|request_id|worker_id)/i.test(text)) return '';
  return text;
}
function taskSummary(t, fallback) { return publicBusinessText(t.result?.text) || publicBusinessText(typeof t.result === 'string' ? t.result : '') || publicBusinessText(t.details?.reason) || fallback; }
function isActivityCandidate(c) {
  return !!(c && (c.activity_id || c.mode === 'authorize_existing' || c.mode === 'create_new' || c.fingerprint));
}
function hotelSuggestions(t) {
  const values = [], add = value => { const name = safeName(value); if (name && !values.includes(name)) values.push(name); };
  add(t.result?.evidence?.hotel_resolution?.resolved_hotel); add(t.details?.hotel_resolution?.resolved_hotel); add(t.details?.suggested_hotel); add(t.details?.resolved_hotel);
  for (const candidate of Array.isArray(t.details?.candidates) ? t.details.candidates : []) {
    if (isActivityCandidate(candidate)) continue;
    add(candidate?.name || candidate?.hotel || candidate?.store_name);
  }
  const hotels = t.details?.hotel_resolution?.candidates || t.details?.hotel_candidates || [];
  for (const candidate of Array.isArray(hotels) ? hotels : []) add(candidate?.name || candidate?.hotel || candidate);
  return values;
}
function resolvedHotel(t) { return safeName(t.result?.evidence?.hotel_resolution?.resolved_hotel) || safeName(t.details?.hotel_resolution?.resolved_hotel) || ''; }
function hasLiveActivityPicker(t) {
  const list = Array.isArray(t.details?.candidates) ? t.details.candidates : [];
  return list.some(x => x && x.mode === 'authorize_existing' && x.activity_id && x.fingerprint && !x.blocked);
}
function renderHotelGuidance(parent, t) {
  if (t.kind !== 'authorization') return;
  if (hasLiveActivityPicker(t)) return;
  const resolved = resolvedHotel(t), suggestions = hotelSuggestions(t); if (!resolved && !suggestions.length) return;
  const box = el('div', undefined, 'hotel-guidance');
  if (resolved) box.append(el('strong', '已解析精确门店：' + resolved), el('p', '系统按精确目录身份继续核对，不会用相似酒店代替。'));
  else if (suggestions.length === 1) box.append(el('strong', '建议核对精确门店：' + suggestions[0]), el('p', '建议仅供审阅；原任务的门店与账号不会被补充说明改写。'));
  else box.append(el('strong', `门店未能唯一匹配（${suggestions.length} 个候选）`), el('p', '请核对分店全称后新建任务；不会自动选相似门店。'), el('p', suggestions.slice(0, 5).join('、'), 'meta'));
  parent.append(box);
}
function carryAuthorizationToComposer(t, hotel) {
  const radio = document.querySelector('[name=kind][value=authorization]'); radio.checked = true; radio.dispatchEvent(new Event('change'));
  $('#hotel').value = hotel; $('#accounts').value = Array.isArray(t.payload?.accounts) ? t.payload.accounts.join('\n') : ''; $('#allow-write').checked = false; pendingRequest = null; updatePermission();
  $('.composer').scrollIntoView({ behavior: 'smooth', block: 'start' }); $('#hotel').focus({ preventScroll: true });
}
function extractAccounts(raw) {
  const text = String(raw || '');
  const found = [];
  const seen = new Set();
  // Prefer long digit/letter runs typical of Douyin IDs, then general account tokens.
  const patterns = [/[A-Za-z0-9][A-Za-z0-9_.-]{3,63}/g];
  for (const re of patterns) {
    for (const match of text.matchAll(re)) {
      const token = match[0].replace(/^[_.-]+|[_.-]+$/g, '');
      if (!/^[A-Za-z0-9_.-]{1,64}$/.test(token)) continue;
      // drop obvious Chinese-adjacent noise already filtered by charset
      if (/^(https?|www|com|http)$/i.test(token)) continue;
      if (seen.has(token)) continue;
      seen.add(token); found.push(token);
      if (found.length >= 40) return found;
    }
  }
  return found;
}
function cleanAccountsField(showHint = true) {
  const input = $('#accounts'); if (!input) return [];
  const accounts = extractAccounts(input.value);
  const next = accounts.join('\n');
  if (input.value !== next) input.value = next;
  const hint = $('#accounts-clean-hint');
  if (hint && showHint) hint.textContent = accounts.length ? ('已抽出 ' + accounts.length + ' 个账号：' + accounts.join('、')) : '粘贴后会自动清洗：只保留数字/字母账号。多个用空格或换行分开。';
  return accounts;
}
function hotelCatalog() {
  return Array.isArray(window.KAITUAN_HOTELS) ? window.KAITUAN_HOTELS : [];
}
function fillHotelDatalist() {
  const list = $('#hotel-datalist'); if (!list) return;
  list.replaceChildren();
  for (const name of hotelCatalog().slice(0, 500)) {
    const opt = el('option'); opt.value = name; list.append(opt);
  }
}
function renderHotelPicker(query) {
  const box = $('#hotel-list'); if (!box) return;
  const q = String(query || '').trim().toLocaleLowerCase();
  if (!q) { box.hidden = true; box.replaceChildren(); return; }
  const hits = hotelCatalog().filter(name => name.toLocaleLowerCase().includes(q)).slice(0, 12);
  box.replaceChildren();
  if (!hits.length) {
    const empty = el('p', '没有匹配的商家，请换个关键字，或直接填写全称。', 'hint');
    box.append(empty); box.hidden = false; return;
  }
  for (const name of hits) {
    const btn = el('button', name, 'hotel-list-item secondary'); btn.type = 'button'; btn.setAttribute('role', 'option');
    btn.onclick = () => { $('#hotel').value = name; box.hidden = true; box.replaceChildren(); $('#accounts').focus(); };
    box.append(btn);
  }
  box.hidden = false;
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
    const row = el('tr'), identityCell = el('td'), name = safeName(product.name) || `旧模板商品 ${index + 1}`; identityCell.append(el('div', name, 'product-name'));
    const [label, tone] = productState(product), stateCell = el('td'); stateCell.append(el('span', label, 'badge ' + tone)); row.append(identityCell, stateCell, el('td', productReason(product))); oldBody.append(row);
  }
  oldTable.append(oldBody); section.append(tableRegion(oldTable, '旧模板商品核对明细，可横向滚动'));
  const candidates = Array.isArray(check.current_candidates) ? check.current_candidates : [], seen = new Set(), rows = candidates.filter(candidate => { const key = productKey(candidate); if (seen.has(key)) return false; seen.add(key); return true; });
  if (rows.length) {
    const oldProductKeys = new Set(products.map(productKey)), candidateProducts = new Set(rows.map(candidate => String(candidate.id))); section.append(el('h5', `当前接口候选 · ${candidateProducts.size} 个商品`)); section.append(el('p', '商品售价来自当前商品接口；平台建议秒杀价仅供审阅，尚未确认使用。这里不会替换旧模板商品，也不会触发新建。', 'hint'));
    const table = el('table'); table.className = 'product-table current-products'; const caption = el('caption', '当前接口候选商品与价格', 'sr-only'), head = el('thead'), headRow = el('tr');
    for (const text of ['当前商品', '与旧模板关系', '商品售价', '平台建议秒杀价（未确认）', '平台状态']) headRow.append(el('th', text)); head.append(headRow); table.append(caption, head); const body = el('tbody');
    for (const [index, candidate] of rows.entries()) {
      const row = el('tr'), identityCell = el('td'); identityCell.append(el('div', safeName(candidate.name) || `当前候选商品 ${index + 1}`, 'product-name'));
      const relation = productRelation(oldProductKeys, candidate); let platform = '禁选状态未返回';
      if (candidate.is_deny === true || candidate.deny_reason) platform = candidate.deny_reason || '平台明确禁选'; else if (candidate.is_deny === false) platform = '平台未标记禁选';
      row.append(identityCell, el('td', relation), el('td', money(candidate.price_cents)), el('td', money(candidate.suggested_price_cents)), el('td', platform)); body.append(row);
    }
    table.append(body); section.append(tableRegion(table, '当前候选商品与价格，可横向滚动'));
  }
  parent.append(section);
}
function formatCommission(rate) {
  if (rate == null || rate === '') return '未知';
  const n = Number(rate);
  if (!Number.isFinite(n) || n < 0) return '未知';
  // Contract: fraction 0–1. Legacy/raw 来客万分比 (500 → 5%) still accepted for old cards.
  let fraction = n;
  if (n > 1) fraction = n / 10000;
  if (fraction > 1) return '未知';
  const pct = fraction * 100;
  return pct.toFixed(pct % 1 === 0 ? 0 : 2) + '%';
}
function formatStock(value) {
  if (value == null || value === '') return '未知';
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : '未知';
}
function resultCard(t) {
  const card = t.details?.card;
  return card && typeof card === 'object' ? card : null;
}
function renderResultCard(parent, t) {
  const card = resultCard(t);
  if (!card) return false;
  const box = el('div', undefined, 'result-card');
  if (card.kind === 'plan') {
    box.append(el('p', t.status === 'succeeded' ? '开团已成功' : '开团结果', 'result-card-title'));
    if (card.plan_id) box.append(el('p', '计划编号：' + String(card.plan_id), 'meta'));
    const products = Array.isArray(card.products) ? card.products : [];
    if (products.length) {
      const scroll = el('div', undefined, 'table-scroll'), table = el('table'), head = el('thead'), tr = el('tr');
      for (const text of ['商品', '佣金率']) tr.append(el('th', text)); head.append(tr); table.append(head);
      const body = el('tbody');
      for (const [index, product] of products.entries()) {
        const row = el('tr');
        row.append(el('td', safeName(product.name) || ('商品 ' + (index + 1))), el('td', formatCommission(product.commission_rate)));
        body.append(row);
      }
      table.append(body); scroll.append(table); box.append(scroll);
    } else box.append(el('p', '暂无商品佣金信息。', 'hint'));
  } else if (card.kind === 'seckill') {
    const activityName = safeName(card.activity_name) || safeName(card.name);
    box.append(el('p', t.status === 'succeeded' ? '秒杀授权已成功' : '秒杀结果', 'result-card-title'));
    if (activityName) box.append(el('p', '活动：' + activityName, 'result-card-activity'));
    else box.append(el('p', '活动名：未知（需补全后才算验收通过）', 'notice warn'));
    if (Array.isArray(card.accounts) && card.accounts.length) box.append(el('p', '抖音号：' + card.accounts.join('、'), 'meta'));
    const bits = [];
    if (card.end_time) bits.push('有效至 ' + when(card.end_time));
    bits.push('库存最低 ' + formatStock(card.min_stock));
    if (bits.length) box.append(el('p', bits.join(' · '), 'hint'));
  } else return false;
  parent.append(box);
  return true;
}
function technicalDetails(value) {
  // 内测默认不对操作员展示；仅供调试时手动调用。
  const d = el('details'), s = el('summary', '给技术看');
  const slim = {};
  if (value && typeof value === 'object') {
    for (const key of ['id', 'revision', 'status', 'committed', 'read_only']) {
      if (value[key] !== undefined) slim[key] = value[key];
    }
    if (value.result && typeof value.result === 'object') {
      slim.result = { text: value.result.text };
    } else if (typeof value.result === 'string') slim.result = value.result;
    if (value.details && typeof value.details === 'object') {
      const keep = {};
      for (const key of ['reason', 'read_failure_code', 'message', 'card']) {
        if (value.details[key] !== undefined) keep[key] = value.details[key];
      }
      if (Array.isArray(value.details.candidates)) keep.candidates_count = value.details.candidates.length;
      slim.details = keep;
    }
    if (value.payload && typeof value.payload === 'object') {
      slim.payload = { kind: value.payload.kind, hotel: value.payload.hotel, accounts: value.payload.accounts, allow_write: value.payload.allow_write };
    }
    if (value.status !== undefined && slim.status === undefined) slim.status = value.status;
  }
  d.append(s, el('pre', JSON.stringify(Object.keys(slim).length ? slim : value, null, 2)));
  return d;
}

function error(e, target = $('#error')) {
  target.hidden = false; target.replaceChildren(el('span', e instanceof UserError ? e.message : '操作暂时未完成。请检查填写的信息后重试。'));
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
  const kept = new Map([...list.querySelectorAll('.task')].map(n => [n.dataset.taskId, { form: n.querySelector('.resume'), revision: n.dataset.revision }]));
  list.replaceChildren();
  const attention = tasks.filter(t => {
    const [label] = taskStatus(t);
    return isHumanChoiceWaiting(t) || label === '没做成';
  });
  const active = tasks.filter(t => !terminal.has(t.status));
  const needYou = attention.filter(t => isHumanChoiceWaiting(t)).length;
  $('#queue-summary').textContent = tasks.length ? `最近 ${tasks.length} 张 · ${active.length} 张进行中 · ${needYou} 张需要处理` : '暂无任务。提交后可在这里查看结果。';
  const query = $('#task-search').value.trim().toLocaleLowerCase();
  const shown = tasks.filter(t => {
    const [label] = taskStatus(t);
    const matchFilter = filter === 'all'
      || (filter === 'attention' && attention.includes(t))
      || (filter === 'active' && active.includes(t))
      || (filter === 'succeeded' && label === '已完成')
      || filter === t.status;
    return matchFilter && (!query || `${taskTitle(t)} ${(t.payload?.accounts || []).join(' ')}`.toLocaleLowerCase().includes(query));
  });
  if (!shown.length) { list.append(tasks.length ? empty('没有找到匹配的任务', '当前筛选或搜索下没有任务。调整条件后继续查看。', true) : empty('从一张任务开始', '粘贴开团计划链接，或填写酒店与抖音号。提交后，进度与需要你点一下的步骤会显示在这里。')); return; }
  const attentionRank = t => {
    const [label] = taskStatus(t);
    if (isHumanChoiceWaiting(t)) return 0;
    if (label === '没做成') return 1;
    return 2;
  };
  shown.sort((a, b) => attentionRank(a) - attentionRank(b));
  let lastGroup = null;
  for (const t of shown) {
    const [status, fallbackSummary, tone] = taskStatus(t);
    const needsYou = isHumanChoiceWaiting(t);
    const group = (needsYou || status === '没做成') ? 'attention' : 'rest';
    if (filter === 'all' && group !== lastGroup) {
      list.append(el('h3', group === 'attention' ? '要你处理' : '其余任务', 'task-group-label'));
      lastGroup = group;
    }
    const item = el('article', undefined, 'task' + (needsYou ? ' needs-you' : ''));
    item.dataset.taskId = t.id; item.dataset.revision = t.revision;
    const card = resultCard(t);
    let summary = taskSummary(t, fallbackSummary);
    if (card?.kind === 'plan' && t.status === 'succeeded') summary = '开团已成功，商品与佣金见下方。';
    if (card?.kind === 'seckill' && t.status === 'succeeded') summary = '秒杀已加好，活动信息见下方。';
    if (needsYou) summary = fallbackSummary;
    const head = el('div', undefined, 'task-head'); head.append(el('h3', taskTitle(t)), el('span', status, 'badge ' + (tone || 'info')));
    item.append(head, el('p', summary, 'task-summary'));
    renderResultCard(item, t);
    const facts = el('div', undefined, 'task-facts'), p = t.payload || {};
    for (const bit of formatTaskTimeline(t)) facts.append(el('span', bit));
    if (t.kind === 'authorization' && Array.isArray(p.accounts) && p.accounts.length) facts.append(el('span', '抖音号：' + p.accounts.join('、')));
    item.append(facts);
    renderHotelGuidance(item, t);
    const detailHost = el('div');
    renderProductCheck(detailHost, t.details?.current_product_check);
    if (detailHost.childNodes.length) {
      const fold = el('details', undefined, 'task-detail');
      fold.append(el('summary', '详情 · 商品核对'));
      while (detailHost.firstChild) fold.append(detailHost.firstChild);
      item.append(fold);
    }
    const actions = el('div', undefined, 'task-actions');
    const canResume = (t.status === 'needs_input' || (t.status === 'waiting_review' && isHumanChoiceWaiting(t))) && !t.cancel_requested;
    if (canResume) { const b = el('button', '去处理'); b.type = 'button'; b.onclick = () => showResume(item, t, b); actions.append(b); }
    const suggestedHotels = hotelSuggestions(t), preferredHotel = resolvedHotel(t) || (suggestedHotels.length === 1 ? suggestedHotels[0] : '');
    if (canResume && t.kind === 'authorization' && preferredHotel && preferredHotel !== safeName(t.payload?.hotel) && !t.details?.preview && !hasLiveActivityPicker(t)) { const b = el('button', '用此门店新建任务', 'secondary'); b.type = 'button'; b.onclick = () => carryAuthorizationToComposer(t, preferredHotel); actions.append(b); }
    if (['waiting_device', 'waiting_review'].includes(t.status) && !isHumanChoiceWaiting(t) && !t.cancel_requested) {
      const b = el('button', '再确认一下结果', 'secondary'); b.type = 'button';
      b.onclick = async () => { if (!await confirmAction('再确认一下结果？', '只会重新读取平台当前状态，不会再次提交。若暂时连不上，可能还要再等一会儿。', '确认')) return; b.disabled = true; b.textContent = '正在确认'; try { await api('tasks/' + t.id + '/retry', { expected_revision: t.revision }); await refresh(); } catch (e) { error(e); b.disabled = false; b.textContent = '再确认一下结果'; } }; actions.append(b);
    }
    if (!terminal.has(t.status) && !t.cancel_requested) {
      const b = el('button', '停止处理', 'secondary'); b.type = 'button';
      b.onclick = async () => { if (!await confirmAction('停止这张任务？', t.committed ? '已经提交过了。停止后只会确认已有结果，不能撤回已经发生的操作。' : '停止后这张任务不再继续。需要再办时请重新提交。', '确认停止', true)) return; b.disabled = true; try { await api('tasks/' + t.id + '/cancel', { expected_revision: t.revision }); await refresh(); } catch (e) { error(e); b.disabled = false; } }; actions.append(b);
    }
    if (actions.children.length) item.append(actions);
    const old = kept.get(t.id);
    if (old?.form && canResume && old.revision === String(t.revision)) { item.append(old.form); const b = actions.querySelector('button'); if (b?.textContent === '去处理') b.disabled = true; }
    list.append(item);
  }
  if (focused?.closest('.resume') && focused.isConnected) focused.focus({ preventScroll: true });
}
function addPreview(parent, preview) {
  const box = el('div', undefined, 'preview');
  const activityName = safeName(preview.activity_name) || safeName(preview.name);
  if (activityName) box.append(el('p', '活动：' + activityName, 'result-card-activity'));
  if (Array.isArray(preview.accounts) && preview.accounts.length) box.append(el('p', '抖音号：' + preview.accounts.join('、'), 'meta'));
  if (preview.end_time_old) box.append(el('p', '原活动结束时间：' + when(preview.end_time_old), 'hint'));
  const fold = el('details', undefined, 'product-fold');
  const summary = el('summary', '本次沿用的商品设置');
  fold.append(summary);
  if (Array.isArray(preview.products) && preview.products.length) {
    summary.textContent = '本次沿用的商品设置（' + preview.products.length + ' 个，点击展开）';
    const scroll = el('div', undefined, 'table-scroll'), table = el('table'), head = el('thead'), tr = el('tr');
    for (const text of ['商品', '秒杀价', '每达人库存']) tr.append(el('th', text)); head.append(tr); table.append(head);
    const body = el('tbody'); for (const [index, p] of preview.products.entries()) { const row = el('tr'); const cents = Number(p.price_cents), stock = Number(p.stock_per_creator); row.append(el('td', safeName(p.name) || `商品 ${index + 1}（名称待核对）`), el('td', p.price_cents != null && Number.isFinite(cents) ? '¥' + (cents / 100).toFixed(2) : '未知'), el('td', p.stock_per_creator != null && Number.isFinite(stock) ? String(stock) : '未知')); body.append(row); }
    table.append(body); scroll.append(table); fold.append(scroll);
  } else fold.append(el('p', '暂时没有可展示的商品设置。请核对原活动内容后再确认。', 'hint'));
  box.append(fold);
  parent.append(box);
}
function inputField(labelText, type, required = true) {
  const label = el('label', labelText), input = el(type === 'textarea' ? 'textarea' : 'input'); input.id = 'resume-field-' + ++fieldCounter; label.htmlFor = input.id;
  if (type !== 'textarea') input.type = type; input.required = required; return { label, input };
}

function existingSeckillHeadcount(p) {
  if (!p || typeof p !== 'object') return null;
  for (const key of ['anchor_count', 'authorized_count', 'existing_account_count', 'existing_author_count', 'talent_count', 'author_count']) {
    const n = Number(p[key]);
    if (Number.isFinite(n) && n >= 0) return n;
  }
  for (const key of ['authorized_accounts', 'existing_accounts', 'anchor_info_list', 'anchors']) {
    if (Array.isArray(p[key])) return p[key].length;
  }
  return null;
}
function showResume(item, t, button) {
  if (item.querySelector('.resume')) return;
  button.disabled = true; const f = el('form', undefined, 'resume'), localError = el('div', undefined, 'notice error'); localError.hidden = true; localError.setAttribute('role', 'alert');
  const rawCandidates = Array.isArray(t.details?.candidates) ? t.details.candidates : [];
  const liveCandidates = rawCandidates.filter(x => x && x.mode === 'authorize_existing' && x.activity_id && x.fingerprint && !x.blocked);
  const expiredCandidates = rawCandidates.filter(x => x && x.template_id && x.fingerprint && x.mode !== 'authorize_existing' && !x.blocked);
  const preview = t.details?.preview && !t.details?.blocked ? t.details.preview : null;
  const liveList = liveCandidates.length ? liveCandidates : (preview?.mode === 'authorize_existing' && preview.activity_id && preview.fingerprint && !preview.blocked ? [preview] : []);
  const expiredList = expiredCandidates.length ? expiredCandidates : (preview && preview.mode !== 'authorize_existing' && preview.template_id && preview.fingerprint && !preview.blocked ? [preview] : []);
  let selected = null;

  function candidateLabel(p, index, kind) {
    const title = safeName(p.activity_name) || safeName(p.name) || ('活动 ' + (index + 1));
    if (kind === 'live') {
      const end = p.end_time ? (' · 结束于 ' + when(p.end_time)) : '';
      const n = existingSeckillHeadcount(p);
      const head = n == null ? '' : (' · 已有 ' + n + ' 人');
      return title + end + head;
    }
    return title + ' · 结束于 ' + when(p.end_time_old);
  }

  function bindExplicitSelect(list, kind, previewHost, onPick) {
    const groupId = 'activity-pick-' + ++fieldCounter;
    const banner = el('div', undefined, 'activity-pick-banner notice warn');
    banner.append(
      el('strong', kind === 'live' ? '请选择本店秒杀活动' : '请选择要沿用的参考活动'),
      el('p', kind === 'live' ? ('店里有 ' + list.length + ' 个生效秒杀。未选出前不能提交，点选后再核对确认。') : ('有 ' + list.length + ' 个参考活动。未选出前不能提交，点选后再填时间。'))
    );
    const fieldset = el('fieldset', undefined, 'activity-pick');
    const legend = el('legend', kind === 'live' ? '请选择本店秒杀活动' : '请选择参考活动');
    fieldset.append(legend);
    for (const [index, p] of list.entries()) {
      const title = safeName(p.activity_name) || safeName(p.name) || ('活动 ' + (index + 1));
      const end = kind === 'live' ? (p.end_time ? when(p.end_time) : '结束时间未知') : when(p.end_time_old);
      const card = el('label', undefined, 'activity-pick-card');
      const radio = el('input'); radio.type = 'radio'; radio.name = groupId; radio.value = String(index); radio.required = true;
      const body = el('span', undefined, 'activity-pick-body');
      body.append(el('strong', title));
      body.append(el('span', (kind === 'live' ? '有效至 ' : '原结束于 ') + end, 'meta'));
      if (kind === 'live') {
        const n = existingSeckillHeadcount(p);
        if (n != null) body.append(el('span', '秒杀已有 ' + n + ' 人', 'meta seckill-headcount'));
      }
      if (kind === 'expired') body.append(el('span', '参考、非当前有效', 'badge warn'));
      card.append(radio, body);
      radio.onchange = () => {
        selected = list[Number(radio.value)] || null;
        previewHost.replaceChildren();
        if (selected) {
          if (kind === 'expired') previewHost.append(el('p', '参考、非当前有效', 'badge warn reference-badge'));
          addPreview(previewHost, selected);
        }
        onPick(!!selected);
      };
      fieldset.append(card);
    }
    f.append(banner, fieldset);
    return fieldset;
  }

  if (t.kind === 'authorization' && liveList.length && !t.details?.blocked) {
    f.append(el('p', liveList.length > 1
      ? ('请选择本店秒杀活动（共 ' + liveList.length + ' 个）。选好后会再核对该活动的商品、价格、库存与已有达人，一致才把缺失账号加上。')
      : '确认加到当前秒杀活动。核对商品、价格、库存与已有达人无误后，再把缺失账号加上。'));
    const previewHost = el('div');
    const consent = el('label', undefined, 'permission'), check = el('input'); check.type = 'checkbox'; check.required = true;
    consent.append(check, el('span', '已核对当前活动、商品、价格、每达人库存与待补充账号'));
    const b = el('button', writeEnvironmentReady ? '确认补充授权' : '执行环境未就绪'); b.type = 'submit'; b.disabled = true;
    const syncSubmit = ready => { b.disabled = !(ready && writeEnvironmentReady && check.checked); };
    check.onchange = () => syncSubmit(!!selected);
    if (liveList.length === 1) {
      selected = liveList[0];
      addPreview(previewHost, selected);
      const missing = Array.isArray(selected.missing_accounts) ? selected.missing_accounts : (t.payload?.accounts || []);
      if (missing.length) f.append(el('p', '本次只补充：' + missing.join('、'), 'meta'));
      if (selected.end_time) f.append(el('p', '当前活动结束时间：' + when(selected.end_time), 'hint'));
      f.append(previewHost);
      syncSubmit(true);
    } else {
      bindExplicitSelect(liveList, 'live', previewHost, ready => {
        const missing = selected && Array.isArray(selected.missing_accounts) ? selected.missing_accounts : (t.payload?.accounts || []);
        const extra = el('div');
        if (selected && missing.length) extra.append(el('p', '本次只补充：' + missing.join('、'), 'meta'));
        if (selected?.end_time) extra.append(el('p', '当前活动结束时间：' + when(selected.end_time), 'hint'));
        previewHost.append(extra);
        syncSubmit(ready);
      });
      f.append(previewHost);
    }
    if (!writeEnvironmentReady) f.append(el('p', writeEnvironmentReason + ' 刷新状态后再确认。', 'notice warn'));
    f.append(consent, b);
    f.onsubmit = async e => {
      e.preventDefault();
      if (!selected?.activity_id || !selected?.fingerprint) { error(new UserError('请先选择目标活动，未选不能提交。'), localError); return; }
      if (!writeEnvironmentReady) { error(new UserError(writeEnvironmentReason), localError); return; }
      const missing = Array.isArray(selected.missing_accounts) ? selected.missing_accounts : (t.payload?.accounts || []);
      if (!await confirmAction('确认加到这个秒杀活动？', `${hotelName(t) || '本任务酒店'}\n只补充：${missing.join('、')}\n会再核对一遍活动、商品、价格、库存与已有达人；有变化就停，不会改掉原来的授权。`, '确认加上')) return;
      b.disabled = true;
      try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { action: 'authorize_existing', confirmed: true, activity_id: selected.activity_id, fingerprint: selected.fingerprint } }); f.remove(); await refresh(); }
      catch (e) { error(e, localError); b.disabled = false; }
    };
  } else if (t.kind === 'authorization' && !liveList.length && expiredList.length && !t.details?.blocked) {
    // 仅失效参考候选、无生效活动：只拒建说明 + 收起，绝不弹出参考活动/填时间/创建
    f.append(el('p', '本店没有生效中的秒杀，请先去抖音来客创建活动后再来加号', 'resume-reason'));
    f.append(el('p', '这里只往已有生效活动加号，不会参考旧活动新建。请先到抖音来客建好活动，再回来用「秒杀添加」。', 'hint'));
  } else if (t.kind === 'plan' && t.read_only && !t.committed && !t.cancel_requested) {
    f.append(el('p', '本计划的信息已进入确认步骤。继续后将重新核对酒店、商品、计划条款与权限，核对一致后同意计划。'));
    if (Array.isArray(t.details?.preview?.products)) addPreview(f, t.details.preview);
    const b = el('button', '确认并同意计划'); b.type = 'submit'; f.append(b);
    f.onsubmit = async e => { e.preventDefault(); if (!await confirmAction('同意这条开团计划？', `${hotelName(t) || '本任务酒店'}\n确认后，将重新核对酒店、商品与计划条款，核对一致后执行同意计划。请先确认这正是你要处理的计划。`, '确认同意')) return; b.disabled = true; try { const params = { confirmed: true, action: 'approve_plan' }; if (t.details?.preview?.fingerprint) params.fingerprint = t.details.preview.fingerprint; await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
  } else {
    if (preview) addPreview(f, preview);
    if (t.kind === 'authorization' && !liveList.length) {
      const refuse = expiredList.length
        || /no_live_activity_refuse_create|没有生效中的秒杀|自行创建秒杀/.test([t.details?.reason, t.details?.message, t.result?.text, t.details?.candidate_kind].filter(v => typeof v === 'string').join(' '))
        || t.details?.candidate_kind === 'none'
        || (t.details?.blocked && t.details?.match === 'none');
      if (refuse) {
        f.append(el('p', '本店没有生效中的秒杀，请先去抖音来客创建活动后再来加号', 'resume-reason'));
        f.append(el('p', '这里只往已有生效活动加号，不会参考旧活动新建。请先到抖音来客建好活动，再回来用「秒杀添加」。', 'hint'));
      } else {
        f.append(el('p', taskSummary(t, '当前门店或账号信息还不足以继续核对。'), 'resume-reason'));
        f.append(el('p', '这张原任务的门店与抖音号已经锁定。下方备注只会留作复核线索，不会修改门店、账号、商品或价格；门店名称有误时，请回到“新建任务”重新提交精确分店名。'));
        const suggestions = hotelSuggestions(t), preferred = resolvedHotel(t) || (suggestions.length === 1 ? suggestions[0] : '');
        if (preferred && preferred !== safeName(t.payload?.hotel)) { const use = el('button', '把建议门店带回新建任务', 'secondary'); use.type = 'button'; use.onclick = () => carryAuthorizationToComposer(t, preferred); f.append(use); }
        const note = inputField('复核备注（不会更改门店或账号）', 'textarea', false); note.input.placeholder = '例如：已核对目录名称，等待重新只读核验'; const b = el('button', '保存备注并只读复核'); b.type = 'submit'; f.append(note.label, note.input, b);
        f.onsubmit = async e => { e.preventDefault(); b.disabled = true; try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { note: note.input.value.trim() } }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
      }
    } else {
      f.append(el('p', '当前信息还不足以继续执行。补充需要核对的情况，随后可重新查看本任务的结果。'));
      const note = inputField('补充说明', 'textarea', false); note.input.placeholder = '例如：已恢复登录，或已有新的生效活动'; const b = el('button', '保存说明并继续核对'); b.type = 'submit'; f.append(note.label, note.input, b);
      f.onsubmit = async e => { e.preventDefault(); b.disabled = true; try { await api('tasks/' + t.id + '/resume', { expected_revision: t.revision, params: { note: note.input.value.trim() } }); f.remove(); await refresh(); } catch (e) { error(e, localError); b.disabled = false; } };
    }
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
  const residency = worker?.health?.residency;
  if (typeof residency?.write_ready === 'boolean') {
    if (worker.gateway_online !== true) return [false, 'Mac 收单离线，已暂停写入'];
    const human = typeof residency.human_reason === 'string' ? residency.human_reason.trim() : '';
    return [residency.write_ready, human || (residency.write_ready ? '执行环境正常，可以开团/加秒杀' : '执行端未就绪，已暂停写入')];
  }
  if (worker.gateway_online !== true) return [false, 'Mac 收单离线，已暂停写入'];
  if (runtime?.android_device?.status !== 'available') return [false, '模拟器未连上，已暂停写入'];
  if (runtime?.root?.status !== 'available') return [false, 'root 未就绪，已暂停写入'];
  if (runtime?.business_app?.status !== 'running') return [false, '抖音来客未就绪，已暂停写入'];
  const native = runtime?.native_interface || {}, safeUnknown = native.status === 'unknown' && native.reason === 'processes_present_attach_not_probed';
  if (native.status !== 'available' && !safeUnknown) return [false, native.status === 'unavailable' ? '原生接口不可执行，已暂停写入' : '原生接口未确认，已暂停写入'];
  return [true, '执行环境正常，可以开团/加秒杀'];
}
function setWriteEnvironment(ready, reason) {
  writeEnvironmentReady = ready; writeEnvironmentReason = reason;
  if (!ready && $('#allow-write').checked) { $('#allow-write').checked = false; pendingRequest = null; }
  $('.permission').classList.toggle('is-disabled', !ready); setSubmitAvailability(); updatePermission();
}
function renderConnection(s) {
  const worker = s.worker || {}, seen = Number(worker.last_heartbeat || 0), gateway = worker.gateway_online === true, runtime = worker.health?.runtime || {};
  renderRuntimeHealth(runtime);
  const readiness = writeReadiness(worker, runtime), ready = readiness[0], reason = readiness[1];
  let badgeText = '已暂停写入', badgeClass = 'bad';
  if (!gateway) { badgeText = '收单离线'; badgeClass = 'bad'; }
  else if (ready) { badgeText = '可写入'; badgeClass = /不在前台/.test(reason) ? 'warn' : 'ok'; }
  $('#connection-heading').textContent = reason;
  $('#connection').textContent = badgeText; $('#connection').className = 'badge ' + badgeClass; $('#connection-dot').className = 'status-dot ' + badgeClass;
  $('#connection-detail').textContent = gateway
    ? (ready ? '写入闸已放行。Android、root、来客与原生接口细项见下方四格；原生接口仍会在任务执行前复核。' : '写入闸已暂停。细项见下方四格；仍可提交只读核验。')
    : '服务器暂时联系不到 Mac。任务仍会保留；可提交只读核验，写入任务需等待收单恢复。';
  setWriteEnvironment(ready, reason);
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
addEventListener('storage', e => { if (e.key === 'zkn-theme') { document.documentElement.dataset.theme = e.newValue === 'dark' ? 'dark' : 'light'; renderTheme(); } });
$('#login-form').onsubmit = async e => { e.preventDefault(); const b = e.target.querySelector('button'); b.disabled = true; $('#login-result').textContent = '正在连接，请稍候。'; try { await api('login', { token: new FormData(e.target).get('token') }); e.target.reset(); $('#login-result').textContent = ''; await refresh(); } catch (err) { error(err, $('#login-result')); } finally { b.disabled = false; } };
for (const b of document.querySelectorAll('[data-filter]')) b.onclick = () => { filter = b.dataset.filter; updateFilters(); if (hasLoaded) render(); };
$('#task-search').addEventListener('input', () => { if (hasLoaded) render(); });
for (const radio of document.querySelectorAll('[name=kind]')) radio.onchange = () => { const isPlan = radio.value === 'plan'; $('#plan-fields').hidden = !isPlan; $('#authorization-fields').hidden = isPlan; $('#link').required = isPlan; $('#hotel').required = !isPlan; $('#accounts').required = !isPlan; const perm = document.querySelector('label.permission'); if (perm) perm.hidden = isPlan; const pnote = $('#permission-note'); if (pnote) pnote.hidden = isPlan; if (isPlan) $('#allow-write').checked = false; pendingRequest = null; $('#form-result').replaceChildren(); updatePermission(); };
function updatePermission() {
  const isPlan = document.querySelector('[name=kind]:checked')?.value === 'plan';
  const small = $('#permission-small');
  if (small) small.textContent = isPlan ? '' : '需要真正加号时再勾选；未勾选只做只读核验';
  if (isPlan) {
    $('#submit').firstChild.textContent = '提交开团';
    if ($('#permission-note')) $('#permission-note').textContent = '粘贴链接后直接提交，系统自动排队执行，不再二次确认。';
    return;
  }
  const checked = $('#allow-write').checked; $('#submit').firstChild.textContent = checked ? '提交并授权执行' : '提交核验任务';
  if (!authenticated) $('#permission-note').textContent = '连接任务入口后可提交；写入选项还需运行环境核验。';
  else if (!writeEnvironmentReady) $('#permission-note').textContent = writeEnvironmentReason + ' 仍可提交只读核验。';
  else $('#permission-note').textContent = checked ? '已勾选：将为这些抖音号补充秒杀授权；执行前会再核对环境、酒店、商品与权限。' : writeEnvironmentReason + ' 当前只提交只读核验；需要真正加号时再勾选。';
}
$('#task-form').addEventListener('input', () => { pendingRequest = null; updatePermission(); });
$('#task-form').onsubmit = async e => {
  e.preventDefault(); const b = $('#submit'); b.disabled = true; $('#form-result').className = ''; $('#form-result').replaceChildren();
  try {
    const kind = document.querySelector('[name=kind]:checked').value;
    // 开团：提交即执行，不走勾选/确认弹层；秒杀仍保留授权勾选与确认。
    const payload = { kind, allow_write: kind === 'plan' ? true : $('#allow-write').checked };
    if (kind === 'plan') payload.plan_id = parsePlanId($('#link').value);
    else { payload.hotel = $('#hotel').value.trim(); payload.accounts = cleanAccountsField(true); if (!payload.hotel) throw new UserError(errorMessages.hotel); if (!payload.accounts.length) throw new UserError('未识别到账号，请粘贴含数字/字母的抖音号后再提交。'); if (payload.accounts.length > 40 || payload.accounts.some(a => !/^[A-Za-z0-9_.-]{1,64}$/.test(a))) throw new UserError(errorMessages.accounts); }
    if (kind !== 'plan' && payload.allow_write && !writeEnvironmentReady) throw new UserError(writeEnvironmentReason + ' 当前只能提交只读核验。');
    if (kind !== 'plan' && payload.allow_write && !await confirmAction('提交并授权执行？', `${payload.hotel}\n抖音号：${payload.accounts.join('、')}\n核对活动商品、价格、库存与时间一致后，将为这些账号补充授权。`, '确认提交并授权')) return;
    $('#form-result').textContent = kind === 'plan' ? '正在提交开团，任务会自动排队执行。' : '正在提交，任务进度将在右侧显示。';
    const response = await submitTask(payload); $('#form-result').className = 'success'; $('#form-result').textContent = response.duplicate ? '这项任务已存在。请在任务进展里查看当前状态，再决定是否继续。' : (kind === 'plan' ? '开团已提交，正在排队执行。请在任务进展里查看结果。' : '任务已提交，处理结果仍需核验。请在任务进展里查看进度与下一步。');
    filter = 'all'; $('#task-search').value = ''; updateFilters(); await refresh();
    const qh = $('#queue-heading'); const queue = document.querySelector('.queue');
    if (qh) { qh.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    if (queue) { queue.classList.remove('queue-flash'); void queue.offsetWidth; queue.classList.add('queue-flash'); setTimeout(() => queue.classList.remove('queue-flash'), 1600); }
  } catch (err) { $('#form-result').className = 'error'; error(err, $('#form-result')); } finally { setSubmitAvailability(); }
};
$('#refresh').onclick = refresh; renderTheme(); setSubmitAvailability(); updatePermission(); fillHotelDatalist();
const hotelInput = $('#hotel');
if (hotelInput) {
  hotelInput.addEventListener('input', () => renderHotelPicker(hotelInput.value));
  hotelInput.addEventListener('focus', () => renderHotelPicker(hotelInput.value));
  hotelInput.addEventListener('keydown', e => { if (e.key === 'Escape') { $('#hotel-list').hidden = true; } });
}
const accountsInput = $('#accounts');
if (accountsInput) {
  accountsInput.addEventListener('paste', () => setTimeout(() => cleanAccountsField(true), 0));
  accountsInput.addEventListener('blur', () => cleanAccountsField(true));
}
document.addEventListener('click', e => { const box = $('#hotel-list'); if (box && !box.hidden && !e.target.closest('#hotel') && !e.target.closest('#hotel-list')) box.hidden = true; });
refresh(); setInterval(() => { if (!document.hidden && !$('#tasks .resume') && !$('#confirm-dialog').open) refresh(); }, 10000);

function openGuidePanel() {
  const panel = $('#guide-panel');
  if (!panel) { location.href = 'guide.html'; return; }
  panel.hidden = false; panel.setAttribute('aria-hidden', 'false');
  panel.querySelector('.guide-close')?.focus();
}
function closeGuidePanel() {
  const panel = $('#guide-panel'); if (!panel) return;
  panel.hidden = true; panel.setAttribute('aria-hidden', 'true');
  $('#guide-open')?.focus();
}
const guideOpen = $('#guide-open');
if (guideOpen) guideOpen.onclick = openGuidePanel;
const guideClose = $('#guide-close');
if (guideClose) guideClose.onclick = closeGuidePanel;
const guideBackdrop = $('#guide-panel');
if (guideBackdrop) guideBackdrop.addEventListener('click', e => { if (e.target === guideBackdrop) closeGuidePanel(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('#guide-panel') && !$('#guide-panel').hidden) closeGuidePanel(); });
