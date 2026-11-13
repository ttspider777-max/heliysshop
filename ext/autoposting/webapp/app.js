const tg = window.Telegram?.WebApp;
const initData = tg?.initData || '';
const $ = (sel, root = document) => root.querySelector(sel);
const view = $('#view');
const sheet = $('#sheet');
const sheetBody = $('#sheetBody');

const S = { tab: 'profile', me: null, accounts: [], mailings: [], pay: {}, wiz: {}, onClose: null };

const INTERVAL_LABEL = { 5: '5 минут', 10: '10 минут', 15: '15 минут', 30: '30 минут', 60: '1 час', 120: '2 часа', 240: '4 часа', 720: '12 часов', 1440: '24 часа' };
const KIND_ICON = { topup: 'wallet', ref: 'users', sub: 'crown', admin: 'gift' };

const ICON = {
  wallet: '<path d="M3 7a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v2"/><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2H5a2 2 0 0 1-2-2Z"/><circle cx="16.5" cy="13.5" r="1"/>',
  crown: '<path d="m3 8 4 4 5-7 5 7 4-4-2 11H5L3 8Z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.8a3.5 3.5 0 0 1 0 6.4M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/><path d="M9 11h.01M12.5 11h.01M16 11h.01"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h3l8 5V5L7 10H4a1 1 0 0 0-1 1Z"/><path d="M18.5 9a4.2 4.2 0 0 1 0 6"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  play: '<path d="M7 5v14l12-7L7 5Z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
  gift: '<rect x="3.5" y="8" width="17" height="4" rx="1"/><path d="M5 12v8h14v-8M12 8v12M12 8c-1.5-4-6-4-5-1 .6 1.6 5 1 5 1Zm0 0c1.5-4 6-4 5-1-.6 1.6-5 1-5 1Z"/>',
  arrow: '<path d="M9 6l6 6-6 6"/>',
};
const ic = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[name]}</svg>`;

const SNOWCAP = '<svg class="snowcap" viewBox="0 0 400 40" preserveAspectRatio="none"><path fill="#fff" d="M0 0h400v14c-14 10-26 2-38 8s-20 14-34 6-22-12-40-4-30 12-46 4-24-10-40-2-28 14-44 6-22-10-38-4-26 10-42 4-20-8-38-2-24 8-40 0V0z"/></svg>';
const FAQ = [
  ['Free и Pro — в чём разница?', 'Free бесплатный: все функции, до 5 аккаунтов и до 50 чатов в рассылке. Pro покупается по желанию за hlx: до 10 аккаунтов и до 100 чатов.'],
  ['Что такое hlx?', 'Это внутренняя валюта сервиса. Ей оплачивается Pro. Пополнить баланс можно звёздами Telegram, через CryptoBot или xRocket.'],
  ['Как сделать пост с фото и премиум-эмодзи?', 'Фото можно прикрепить прямо при создании рассылки. Для премиум-эмодзи и форматирования отправьте готовый пост боту в чат, затем при создании рассылки выберите «Пост из чата». Премиум-эмодзи отображаются, если у аккаунта рассылки есть Telegram Premium.'],
  ['Что такое автоподписка?', 'Если в чате бот-охранник требует подписаться на канал, чтобы писать, аккаунт сам вступит в этот канал — и следующее сообщение пройдёт. Включается в рассылке по желанию, не больше 20 вступлений в сутки на аккаунт.'],
  ['Как подключить аккаунт?', 'Откройте вкладку «Аккаунты», нажмите «Подключить по номеру», введите номер и код, который придёт в Telegram. Если включена двухэтапная защита — понадобится облачный пароль.'],
  ['Это безопасно?', 'Вход выполняется через официальный API Telegram. Сессия хранится в зашифрованном виде и видна у вас в Telegram → Настройки → Устройства — её можно завершить в любой момент.'],
  ['Как работает рассылка?', 'Вы выбираете аккаунт, чаты, пост и паузу (от 5 минут). Сообщение отправляется во все выбранные чаты по кругу с паузой 6 секунд между чатами, затем сервис отдыхает заданное время и начинает новый круг. В конец каждого сообщения добавляется подпись «Отправлено через» с юзернеймом бота.'],
  ['Почему чат пропал из рассылки?', 'Если в чате запретили писать или аккаунт исключили, сервис убирает этот чат из рассылки и не пытается отправлять туда снова.'],
  ['Сколько аккаунтов можно подключить?', 'На Free — до 5, на Pro — до 10.'],
  ['Как отключить аккаунт?', 'Нажмите на корзину рядом с аккаунтом. Сессия будет завершена, а рассылки с него удалены.'],
];

// ---------- утилиты ----------

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = n => String(n).padStart(2, '0');
const fmtDate = ts => { const d = new Date(ts * 1000); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const rub = n => `${n} <span class="rub">₽</span>`;
const haptic = (type = 'light') => { try { tg?.HapticFeedback?.impactOccurred(type); } catch {} };

async function api(path, body, method) {
  const res = await fetch('api/' + path, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { 'X-Init-Data': initData, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: 'Ошибка сети' }));
  if (!res.ok) {
    const e = new Error(data.error || 'Ошибка');
    e.data = data;
    throw e;
  }
  return data;
}

let toastTimer;
function toast(text, isError) {
  const el = $('#toast');
  el.textContent = text;
  el.className = 'toast show' + (isError ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 2600);
  try { tg?.HapticFeedback?.notificationOccurred(isError ? 'error' : 'success'); } catch {}
}

function openUrl(url) {
  try {
    if (/^https:\/\/t\.me\//.test(url)) tg.openTelegramLink(url);
    else tg.openLink(url);
  } catch { window.open(url, '_blank'); }
}

function openSheet(html, onClose) {
  S.onClose = onClose || null;
  sheetBody.innerHTML = html;
  sheetBody.scrollTop = 0;
  sheet.classList.add('open');
  $('#scrim').classList.add('open');
}

function closeSheet() {
  sheet.classList.remove('open');
  $('#scrim').classList.remove('open');
  const cb = S.onClose;
  S.onClose = null;
  cb?.();
}

// Кнопка блокируется на время запроса, ошибка показывается тостом
async function run(btn, fn) {
  btn?.classList.add('busy');
  try { await fn(); } catch (e) { toast(e.message, true); } finally { btn?.classList.remove('busy'); }
}

function confirmSheet(title, text, label, onYes) {
  S.confirm = onYes;
  openSheet(`<h2>${esc(title)}</h2><p class="lead">${esc(text)}</p>
    <div class="stack"><button class="btn danger wide" data-act="confirm-yes">${esc(label)}</button>
    <button class="btn ghost wide" data-act="close">Отмена</button></div>`);
}

// ---------- загрузка данных ----------

async function loadMe() { S.me = await api('me'); }
async function loadAccounts() { S.accounts = (await api('accounts')).accounts; }
async function loadMailings() { S.mailings = (await api('mailings')).mailings; }

function render() {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === S.tab));
  ({ profile: renderProfile, mailings: renderMailings, stats: renderStats, accounts: renderAccounts })[S.tab]();
}

async function loadStats() { S.stats = await api('stats'); }

async function switchTab(tab) {
  S.tab = tab;
  clearInterval(S.statsTimer);
  render();
  window.scrollTo(0, 0);
  try {
    if (tab === 'profile') await loadMe();
    else if (tab === 'stats') {
      await loadStats();
      // пока вкладка открыта, цифры и «следующий круг через…» обновляются сами
      S.statsTimer = setInterval(() => {
        if (S.tab !== 'stats' || document.hidden || sheet.classList.contains('open')) return;
        loadStats().then(() => { if (S.tab === 'stats') render(); }).catch(() => {});
      }, 20000);
    } else await Promise.all([loadAccounts(), loadMailings()]);
    if (S.tab === tab) render();
  } catch (e) { toast(e.message, true); }
}

// ---------- профиль ----------

function renderProfile() {
  const u = S.me.user;
  const tile = (act, icon, label, half) => `<button class="tile${half ? ' half' : ''}" data-act="${act}"><span class="tile-ic">${ic(icon)}</span>${label}</button>`;
  view.innerHTML = `
    <section class="hero">
      ${SNOWCAP}
      <div class="hello">привет, ${esc(u.name)} ❄</div>
      <div class="balance"><b>${u.balance}</b><span>hlx</span></div>
      <div class="pill ${u.sub_active ? 'on' : 'off'}"><i></i>${u.sub_active ? 'Pro до ' + fmtDate(u.sub_until) : 'Тариф Free'}</div>
      <div class="hero-actions">
        <button class="btn primary" data-act="topup">${ic('wallet')}Пополнить</button>
        <button class="btn ghost" data-act="sub">${ic('crown')}Pro</button>
      </div>
    </section>
    <section class="tiles">
      ${tile('invite', 'users', 'Пригласить друзей')}
      ${tile('support', 'chat', 'Поддержка')}
      ${tile('faq', 'list', 'Частые вопросы')}
      ${tile('history', 'clock', 'История операций', true)}
      ${tile('docs', 'file', 'Документы', true)}
    </section>`;
}

function topupSheet() {
  const { pkg, method } = S.pay;
  const packs = S.me.packages.map(p => `
    <button class="pack${p.id === pkg ? ' active' : ''}" data-act="pick-pack" data-id="${p.id}">
      ${p.id === 'p500' ? '<span class="tag">выгодно</span>' : ''}
      <b>${p.hlx}<small>hlx</small></b>
      <span class="price">${method === 'stars' ? p.stars + ' ⭐' : rub(p.rub)}</span>
    </button>`).join('');
  const methods = [['stars', '⭐ Звёзды'], ['cryptobot', 'CryptoBot'], ['xrocket', 'xRocket']]
    .map(([id, label]) => `<button class="chip${id === method ? ' active' : ''}" data-act="pick-method" data-id="${id}">${label}</button>`).join('');
  const cur = S.me.packages.find(p => p.id === pkg);
  const wait = S.pay.id ? `<p class="hint">Ожидаем оплату… баланс обновится автоматически.</p>
    <button class="btn ghost wide" data-act="pay-check" style="margin-top:10px">Проверить оплату</button>` : '';
  openSheet(`<h2>Пополнение</h2><p class="lead">Выберите пакет и способ оплаты.</p>
    <div class="packs">${packs}</div>
    <span class="label">Способ оплаты</span><div class="chips">${methods}</div>
    <div style="margin-top:18px"><button class="btn primary wide" data-act="pay">Оплатить ${method === 'stars' ? cur.stars + ' ⭐' : rub(cur.rub)}</button></div>
    ${wait}`, stopPayPolling);
}

function stopPayPolling() { clearInterval(S.pay.timer); S.pay.timer = null; S.pay.id = null; }

async function paid() {
  stopPayPolling();
  closeSheet();
  await loadMe();
  render();
  toast('Баланс пополнен');
}

async function checkPayment(manual) {
  if (!S.pay.id) return;
  const { status } = await api('pay/check', { payment_id: S.pay.id });
  if (status === 'paid') await paid();
  else if (manual) toast('Оплата пока не поступила', true);
}

function subSheet() {
  const L = S.me.limits;
  const plans = S.me.plans.map(p => `
    <div class="card plan">
      <span class="badge-ic">${ic('crown')}</span>
      <div class="row-main"><div class="row-title">Pro · ${esc(p.title)}</div><div class="row-sub">до ${L.sub} аккаунтов и ${L.pro_chats} чатов</div></div>
      <button class="btn gold sm" data-act="buy-sub" data-id="${p.id}"><span class="cost">${p.price}<small>hlx</small></span></button>
    </div>`).join('');
  const u = S.me.user;
  openSheet(`<h2>Тарифы</h2>
    <p class="lead">${u.sub_active ? 'У вас Pro до ' + fmtDate(u.sub_until) + '. Покупка продлит срок.' : 'Сейчас у вас Free — он бесплатный. Pro можно купить по желанию.'} На балансе: <b>${u.balance} hlx</b></p>
    <div class="plans-cmp">
      <div class="card"><b>Free</b><ul><li>Бесплатно</li><li>До ${L.free} аккаунтов</li><li>До ${L.free_chats} чатов</li><li>Фото, премиум-эмодзи</li><li>Круг от 5 минут</li></ul></div>
      <div class="card pro"><b>Pro 👑</b><ul><li>За hlx</li><li>До ${L.sub} аккаунтов</li><li>До ${L.pro_chats} чатов</li><li>Всё из Free</li></ul></div>
    </div>
    <div class="stack">${plans}</div>`);
}

function inviteSheet() {
  const r = S.me.ref;
  openSheet(`<h2>Пригласить друзей</h2>
    <p class="lead">За каждого, кто придёт по вашей ссылке — ${r.bonus} hlx. Дальше ${r.percent}% с каждого его пополнения.</p>
    <div class="linkbox"><span>${esc(r.link)}</span><button class="icon-btn" data-act="copy-ref">${ic('copy')}</button></div>
    <div class="stats" style="grid-template-columns:1fr 1fr;margin:14px 0">
      <div class="stat"><b>${r.count}</b><span>приглашено</span></div>
      <div class="stat"><b>${r.earned}</b><span>заработано hlx</span></div>
    </div>
    <button class="btn primary wide" data-act="share-ref">Поделиться ссылкой</button>`);
}

function faqSheet() {
  openSheet('<h2>Частые вопросы</h2>' + FAQ.map(([q, a]) => `<details class="faq"><summary>${q}</summary><p>${a}</p></details>`).join(''));
}

function docsSheet() {
  const link = (url, title) => `<button class="card row" data-act="open-url" data-url="${esc(url)}" style="width:100%;text-align:left">
    <span class="badge-ic">${ic('file')}</span><div class="row-main"><div class="row-title">${title}</div></div>${ic('arrow').replace('<svg', '<svg width="18" height="18" style="color:var(--mut)"')}</button>`;
  openSheet(`<h2>Документы</h2><p class="lead">Используя сервис, вы принимаете условия этих документов.</p>
    <div class="stack">${link(S.me.links.policy, 'Политика конфиденциальности')}${link(S.me.links.offer, 'Пользовательское соглашение')}</div>`);
}

// ---------- статистика (отдельная вкладка) ----------

function renderStats() {
  if (!S.stats) { view.innerHTML = '<div class="loader"><span class="spin"></span></div>'; return; }
  const { stats, mailings, now } = S.stats;
  const t = stats.today;
  const period = (title, d) => `<div class="card period-card"><span class="label">${title}</span><div class="stats four">
      <div class="stat"><b>${d.sent}</b><span>отправлено</span></div>
      <div class="stat"><b>${d.rounds}</b><span>кругов</span></div>
      <div class="stat"><b>${d.failed}</b><span>пропущено</span></div>
      <div class="stat"><b>${d.joined}</b><span>автоподписок</span></div></div></div>`;
  const active = mailings.filter(m => m.status === 'active').length;
  const mails = mailings.map(m => {
    const left = Math.max(0, m.next_run - now);
    const state = m.status !== 'active' ? 'остановлена' : left ? `следующий круг через ${Math.ceil(left / 60)} мин` : 'идёт круг';
    return `<div class="card">
      <div class="row"><span class="badge-ic">${ic('megaphone')}</span>
        <div class="row-main"><div class="row-title">${esc(m.account)}</div><div class="row-sub">${state}</div></div>
        <span class="status ${m.status === 'active' ? 'on' : 'off'}">${m.status === 'active' ? 'идёт' : 'стоп'}</span></div>
      <div class="stats four" style="margin-top:12px">
        <div class="stat"><b>${m.rounds}</b><span>кругов</span></div>
        <div class="stat"><b>${m.sent}</b><span>отправлено</span></div>
        <div class="stat"><b>${m.failed}</b><span>пропущено</span></div>
        <div class="stat"><b>${m.chats}</b><span>чатов${m.removed ? ` (−${m.removed})` : ''}</span></div>
      </div>
      <div class="row-sub" style="margin-top:10px">Пауза ${INTERVAL_LABEL[m.interval_min] || m.interval_min + ' мин'}${m.last_run ? ' · последний круг ' + fmtDate(m.last_run) : ''}${m.joined ? ' · автоподписок ' + m.joined : ''}</div>
    </div>`;
  }).join('');
  view.innerHTML = `
    <div class="page-head"><h1>Статистика</h1><span class="count">${active} идёт</span></div>
    <section class="card today-card">
      <span class="label">Сегодня отправлено</span>
      <div class="big-num">${t.sent}</div>
      <div class="row-sub">${t.rounds} кругов · ${t.failed} пропущено${t.joined ? ' · ' + t.joined + ' автоподписок' : ''}</div>
    </section>
    <div class="stack" style="margin-top:12px">
      ${period('Вчера', stats.yesterday)}${period('За 7 дней', stats.week)}${period('За всё время', stats.total)}
    </div>
    <div class="page-head" style="margin-top:20px"><h1 style="font-size:18px">По рассылкам</h1></div>
    <div class="stack">${mails || '<div class="card empty">Рассылок пока нет</div>'}</div>
    <p class="note">Обновляется автоматически каждые 20 секунд.</p>`;
}

async function historySheet() {
  openSheet('<h2>История операций</h2><div class="loader"><span class="spin"></span></div>');
  const { transactions } = await api('history');
  const tx = transactions.length ? transactions.map(t => `
    <div class="tx"><span class="badge-ic">${ic(KIND_ICON[t.kind] || 'wallet')}</span>
      <div class="row-main"><div class="row-title">${esc(t.note)}</div><div class="row-sub">${fmtDate(t.created_at)}</div></div>
      <span class="amt${t.amount > 0 ? ' plus' : ''}">${t.amount > 0 ? '+' : ''}${t.amount}</span></div>`).join('')
    : '<div class="empty">Операций пока нет</div>';
  sheetBody.innerHTML = `<h2>История операций</h2>
    <p class="lead">Пополнения, покупки Pro и бонусы. Статистика рассылок — во вкладке «Статистика».</p>${tx}`;
}

// ---------- рассылки ----------

const freeAccounts = () => S.accounts.filter(a => a.alive && !a.busy);

function renderMailings() {
  let hint = '';
  if (!S.accounts.length) hint = 'Сначала подключите аккаунт во вкладке «Аккаунты».';
  else if (!freeAccounts().length) hint = 'На всех аккаунтах уже идут рассылки.';
  const list = S.mailings.map(m => `
    <div class="card">
      <div class="row">
        <span class="badge-ic">${ic('megaphone')}</span>
        <div class="row-main"><div class="row-title">${esc(m.account)}</div><div class="row-sub">каждые ${INTERVAL_LABEL[m.interval_min] || m.interval_min + ' мин'}</div></div>
        <span class="status ${m.status === 'active' ? 'on' : 'off'}">${m.status === 'active' ? 'идёт' : 'остановлена'}</span>
      </div>
      <div class="mail-text">${esc(m.text) || '<i style="color:var(--mut)">только фото</i>'}</div>
      ${m.photo || m.formatted ? `<div class="tags" style="margin:-4px 0 10px">${m.photo ? '<span>📷 фото</span>' : ''}${m.formatted ? '<span>✨ оформление</span>' : ''}</div>` : ''}
      <div class="stats">
        <div class="stat"><b>${m.chats}</b><span>чатов</span></div>
        <div class="stat"><b>${m.rounds}</b><span>кругов</span></div>
        <div class="stat"><b>${m.sent}</b><span>отправлено</span></div>
      </div>
      <div class="mail-actions">
        <button class="mini-btn" data-act="mail-edit" data-id="${m.id}" style="flex-basis:calc(50% - 4px)">✏️ Изменить пост</button>
        <button class="mini-btn${m.autojoin ? ' on' : ''}" data-act="mail-aj" data-id="${m.id}" style="flex-basis:calc(50% - 4px)">Автоподписка: ${m.autojoin ? 'вкл' : 'выкл'}</button>
        ${m.status === 'active'
          ? `<button class="btn ghost sm" data-act="mail-stop" data-id="${m.id}">${ic('stop')}Остановить</button>`
          : `<button class="btn ghost sm" data-act="mail-start" data-id="${m.id}">${ic('play')}Запустить</button>`}
        <button class="btn danger sm" data-act="mail-del" data-id="${m.id}">${ic('trash')}Удалить</button>
      </div>
    </div>`).join('');
  view.innerHTML = `
    <div class="page-head"><h1>Рассылки</h1><span class="count">${S.mailings.length}</span></div>
    <div class="card start-card">
      <h2>Новая рассылка</h2>
      <p>Сервис найдёт чаты аккаунта — лишние можно будет убрать.</p>
      <button class="btn primary wide" data-act="wiz-start" ${hint ? 'disabled' : ''}>${ic('megaphone')}Начать рассылку</button>
      ${hint ? `<p class="hint">${hint}</p>` : ''}
    </div>
    <div class="stack" style="margin-top:14px">${list}</div>`;
}

function wizStart() {
  const free = freeAccounts();
  S.wiz = { interval: S.me.intervals[0], source: 'text', photo: null, photoUrl: null, autojoin: false, text: '' };
  if (free.length === 1) return wizScan(free[0].id);
  openSheet(`<h2>С какого аккаунта?</h2><p class="lead">Выберите аккаунт для рассылки.</p><div class="stack">${
    free.map(a => `<button class="card row" data-act="wiz-acc" data-id="${a.id}" style="width:100%;text-align:left">
      <span class="badge-ic">${esc(a.name[0] || '?')}</span>
      <div class="row-main"><div class="row-title">${esc(a.name)}</div><div class="row-sub">${esc(a.phone)}</div></div></button>`).join('')}</div>`);
}

async function wizScan(accountId) {
  S.wiz.account_id = accountId;
  openSheet('<div class="loader"><span class="spin"></span>Сканируем чаты аккаунта…</div>');
  try {
    S.wiz.chats = (await api(`accounts/${accountId}/chats`)).chats;
  } catch (e) { closeSheet(); return toast(e.message, true); }
  if (!S.wiz.chats.length) {
    return openSheet('<h2>Чатов не найдено</h2><p class="lead">На этом аккаунте нет групп, в которые можно писать.</p><button class="btn ghost wide" data-act="close">Понятно</button>');
  }
  const rows = S.wiz.chats.map(c => `
    <label class="chat"><input type="checkbox" checked value="${c.id}"><span class="box">${ic('check')}</span>
      <div class="row-main"><div class="row-title">${esc(c.title)}</div>${c.members ? `<div class="row-sub">${c.members} участников</div>` : ''}</div></label>`).join('');
  openSheet(`<h2>Чаты для рассылки</h2><p class="lead">Снимите галочки с чатов, куда отправлять не нужно.</p>
    <div class="list-head"><span id="chatCount"></span><button data-act="wiz-toggle">Снять все</button></div>
    <div id="chatList">${rows}</div>
    <div class="sheet-foot"><button class="btn primary wide" data-act="wiz-next">Далее</button></div>`);
  updateChatCount();
}

function updateChatCount() {
  const n = sheetBody.querySelectorAll('#chatList input:checked').length;
  const el = $('#chatCount');
  if (el) el.textContent = `Выбрано: ${n} из ${S.wiz.chats.length}`;
  const toggle = $('[data-act="wiz-toggle"]');
  if (toggle) toggle.textContent = n ? 'Снять все' : 'Выбрать все';
}

async function wizCompose() {
  const ids = [...sheetBody.querySelectorAll('#chatList input:checked')].map(i => Number(i.value));
  if (!ids.length) return toast('Выберите хотя бы один чат', true);
  if (ids.length > S.me.limits.chats) {
    return toast(`Не больше ${S.me.limits.chats} чатов` + (S.me.user.sub_active ? '' : ` (в Pro — до ${S.me.limits.pro_chats})`), true);
  }
  S.wiz.chat_ids = ids;
  try { S.wiz.draft = (await api('draft')).draft; } catch { S.wiz.draft = null; }
  renderCompose();
}

function renderCompose() {
  const w = S.wiz, L = S.me.limits;
  const keep = $('#mailText');
  if (keep) w.text = keep.value;   // не теряем текст при перерисовке
  const chips = S.me.intervals.map(i => `<button class="chip${i === w.interval ? ' active' : ''}" data-act="wiz-interval" data-id="${i}">${INTERVAL_LABEL[i] || i + ' мин'}</button>`).join('');
  const d = w.draft;
  let body;
  if (w.source === 'draft') {
    body = d ? `<div class="draft"><div class="row-title">Пост из чата с ботом</div>
        <div class="mail-text">${esc(d.text) || '<i style="color:var(--mut)">без текста</i>'}</div>
        <div class="tags">${d.photo ? '<span>📷 фото</span>' : ''}${d.emoji ? '<span>💎 премиум-эмодзи</span>' : ''}${d.formatted ? '<span>✨ оформление</span>' : ''}</div></div>
        <p class="hint" style="text-align:left">Хотите другой пост — просто отправьте его боту в чат и вернитесь сюда.${d.emoji ? ' Премиум-эмодзи отобразятся, если у аккаунта рассылки есть Telegram Premium.' : ''}</p>`
      : `<div class="draft"><div class="row-title">Поста пока нет</div>
        <p class="hint" style="text-align:left;margin-top:6px">Отправьте боту в чат готовый пост: фото с подписью или текст. Форматирование и премиум-эмодзи сохранятся. Потом вернитесь сюда.</p></div>
        <div style="margin-top:10px"><button class="btn ghost wide" data-act="wiz-draft-reload">Я отправил — обновить</button></div>`;
  } else {
    const hasPhoto = w.photo || w.keepPhoto;   // keepPhoto — фото, которое уже есть у редактируемой рассылки
    const max = hasPhoto ? L.caption : L.text;
    body = `<textarea class="field" id="mailText" maxlength="${max}" placeholder="${hasPhoto ? 'Подпись к фото (можно оставить пустой)' : 'Текст рассылки'}">${esc(w.text)}</textarea>
      <div class="photo-row">
        ${w.photoUrl ? `<img class="photo-thumb" src="${w.photoUrl}" alt="">` : w.keepPhoto ? '<div class="tags" style="margin:0"><span>📷 текущее фото</span></div>' : ''}
        <label class="btn ghost sm" style="cursor:pointer">${hasPhoto ? 'Заменить фото' : '📷 Прикрепить фото'}<input type="file" id="photoInput" accept="image/jpeg,image/png,image/webp"></label>
        ${hasPhoto ? '<button class="btn ghost sm" data-act="wiz-photo-del">Убрать</button>' : ''}
      </div>
      ${hasPhoto ? `<p class="hint" style="text-align:left">С фото подпись — до ${L.caption} символов.</p>` : ''}
      ${w.edit && w.wasFormatted ? '<p class="hint" style="text-align:left">У текущего поста есть оформление или премиум-эмодзи. Если сохранить текст отсюда, они пропадут. Чтобы их оставить, отправьте пост боту в чат и выберите «Пост из чата».</p>' : ''}`;
  }
  const head = w.edit
    ? `<h2>Изменить пост</h2><p class="lead">Чаты, пауза и статистика останутся. Новый пост уйдёт со следующего круга.</p>`
    : `<h2>Сообщение</h2><p class="lead">Чатов выбрано: ${w.chat_ids.length}. Первый круг начнётся сразу после запуска.</p>`;
  const settings = w.edit ? '' : `
    <span class="label">Пауза между кругами</span><div class="chips" id="intervals">${chips}</div>
    <label class="switch"><input type="checkbox" id="autojoin" ${w.autojoin ? 'checked' : ''}><span class="tr"></span>
      <div class="row-main"><div class="row-title">Автоподписка</div><div class="row-sub">Если чат требует подписаться на канал — аккаунт вступит сам (до ${L.autojoin_day} в сутки)</div></div></label>`;
  openSheet(`${head}
    <div class="seg"><button class="${w.source === 'text' ? 'active' : ''}" data-act="wiz-src" data-id="text">Написать</button>
      <button class="${w.source === 'draft' ? 'active' : ''}" data-act="wiz-src" data-id="draft">Пост из чата${d ? ' ✓' : ''}</button></div>
    ${body}
    <p class="hint" style="text-align:left">В конец каждого сообщения добавится «Отправлено через @${esc(S.me.bot_username)}».</p>
    ${settings}
    <div style="margin-top:18px"><button class="btn primary wide" data-act="${w.edit ? 'edit-save' : 'wiz-create'}">${w.edit ? 'Сохранить пост' : 'Запустить рассылку'}</button></div>`);
}

async function editPost(id) {
  openSheet('<div class="loader"><span class="spin"></span></div>');
  try {
    const [{ mailing: m }, { draft }] = await Promise.all([api(`mailings/${id}`), api('draft')]);
    S.wiz = { edit: id, source: 'text', text: m.text, photo: null, photoUrl: null, keepPhoto: m.photo,
              wasFormatted: m.formatted, draft, autojoin: false };
    renderCompose();
  } catch (e) { closeSheet(); toast(e.message, true); }
}

async function uploadPhoto(file) {
  if (file.size > S.me.limits.photo_mb * 1024 * 1024) throw new Error(`Фото больше ${S.me.limits.photo_mb} МБ`);
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('api/upload', { method: 'POST', headers: { 'X-Init-Data': initData }, body: fd });
  const data = await res.json().catch(() => ({ error: 'Ошибка сети' }));
  if (!res.ok) throw new Error(data.error || 'Не удалось загрузить фото');
  return data.file;
}

// ---------- аккаунты ----------

function renderAccounts() {
  const limit = S.me.user.acc_limit;
  const full = S.accounts.length >= limit;
  const list = S.accounts.length ? S.accounts.map(a => `
    <div class="card row">
      <span class="badge-ic">${esc(a.name[0] || '?')}</span>
      <div class="row-main"><div class="row-title">${esc(a.name)}</div><div class="row-sub">${esc(a.phone)}${a.username ? ' · @' + esc(a.username) : ''}</div></div>
      <span class="status ${!a.alive ? 'bad' : a.busy ? 'on' : 'off'}">${!a.alive ? 'отключён' : a.busy ? 'рассылка' : 'готов'}</span>
      <button class="icon-btn" data-act="acc-del" data-id="${a.id}" aria-label="Отключить">${ic('trash')}</button>
    </div>`).join('') : `<div class="card empty">${ic('phone')}<div>Пока нет подключённых аккаунтов</div></div>`;
  view.innerHTML = `
    <div class="page-head"><h1>Аккаунты</h1><span class="count">${S.accounts.length} / ${limit}</span></div>
    <div class="stack">${list}</div>
    <div style="margin-top:14px"><button class="btn primary wide" data-act="acc-add" ${full ? 'disabled' : ''}>${ic('phone')}Подключить по номеру</button></div>
    ${full && !S.me.user.sub_active ? `<p class="hint">Лимит на Free — ${S.me.limits.free}. На Pro — до ${S.me.limits.sub}.</p>` : ''}
    <p class="note">Подключенная сессия видна в Telegram → Настройки → Устройства — отозвать её можно там в любой момент.</p>`;
}

const cancelLogin = () => { api('accounts/cancel', {}).catch(() => {}); };

function accStep(step) {
  const steps = {
    phone: ['Подключение аккаунта', 'Введите номер телефона аккаунта в международном формате.',
      '<input class="field" id="accInput" type="tel" inputmode="tel" autocomplete="off" placeholder="+7 999 123 45 67">', 'acc-phone', 'Получить код'],
    code: ['Код подтверждения', 'Telegram отправил код в чат «Telegram» на этом аккаунте.',
      '<input class="field" id="accInput" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="12345">', 'acc-code', 'Подтвердить'],
    password: ['Облачный пароль', 'На аккаунте включена двухэтапная защита. Пароль используется только для входа и не сохраняется.',
      '<input class="field" id="accInput" type="password" autocomplete="off" placeholder="Пароль">', 'acc-pass', 'Войти'],
  };
  const [title, lead, input, act, label] = steps[step];
  openSheet(`<h2>${title}</h2><p class="lead">${lead}</p>${input}
    <div style="margin-top:14px"><button class="btn primary wide" data-act="${act}">${label}</button></div>`, cancelLogin);
  setTimeout(() => $('#accInput')?.focus(), 350);
}

async function accDone() {
  S.onClose = null;
  closeSheet();
  await Promise.all([loadAccounts(), loadMe()]);
  render();
  toast('Аккаунт подключён');
}

// ---------- действия ----------

const actions = {
  tab: el => { haptic(); switchTab(el.dataset.tab); },
  close: closeSheet,
  'confirm-yes': el => run(el, async () => { await S.confirm?.(); }),
  'open-url': el => openUrl(el.dataset.url),
  support: () => openUrl(S.me.links.support),
  invite: inviteSheet,
  faq: faqSheet,
  docs: docsSheet,
  history: () => historySheet().catch(e => toast(e.message, true)),
  sub: subSheet,
  topup: () => { S.pay = { pkg: 'p100', method: 'stars' }; topupSheet(); },

  'pick-pack': el => { S.pay.pkg = el.dataset.id; topupSheet(); },
  'pick-method': el => { S.pay.method = el.dataset.id; topupSheet(); },
  pay: el => run(el, async () => {
    const res = await api('pay/create', { package: S.pay.pkg, method: S.pay.method });
    if (res.method === 'stars') {
      try { tg.openInvoice(res.url, status => { if (status === 'paid') paid(); }); } catch { openUrl(res.url); }
      return;
    }
    clearInterval(S.pay.timer);
    S.pay.id = res.payment_id;
    S.pay.timer = setInterval(() => checkPayment().catch(() => {}), 4000);
    topupSheet();
    openUrl(res.url);
  }),
  'pay-check': el => run(el, () => checkPayment(true)),

  'buy-sub': el => run(el, async () => {
    const plan = S.me.plans.find(p => p.id === el.dataset.id);
    if (S.me.user.balance < plan.price) {
      toast('Недостаточно hlx — пополните баланс', true);
      return actions.topup();
    }
    await api('sub/buy', { plan: plan.id });
    await loadMe();
    closeSheet();
    render();
    toast('Pro активирован');
  }),

  'copy-ref': async () => {
    try { await navigator.clipboard.writeText(S.me.ref.link); toast('Ссылка скопирована'); }
    catch { toast('Не удалось скопировать', true); }
  },
  'share-ref': () => openUrl('https://t.me/share/url?url=' + encodeURIComponent(S.me.ref.link) + '&text=' + encodeURIComponent('Heliys AutoPosting — автопостинг в Telegram')),

  'wiz-start': wizStart,
  'wiz-acc': el => wizScan(Number(el.dataset.id)),
  'wiz-toggle': () => {
    const boxes = [...sheetBody.querySelectorAll('#chatList input')];
    const any = boxes.some(b => b.checked);
    boxes.forEach(b => { b.checked = !any; });
    updateChatCount();
  },
  'wiz-next': el => run(el, wizCompose),
  'wiz-interval': el => {
    S.wiz.interval = Number(el.dataset.id);
    sheetBody.querySelectorAll('#intervals .chip').forEach(c => c.classList.toggle('active', c === el));
  },
  'wiz-src': el => { S.wiz.autojoin = !!$('#autojoin')?.checked; S.wiz.source = el.dataset.id; renderCompose(); },
  'wiz-draft-reload': el => run(el, async () => {
    S.wiz.draft = (await api('draft')).draft;
    S.wiz.autojoin = !!$('#autojoin')?.checked;
    renderCompose();
    if (!S.wiz.draft) toast('Пост ещё не пришёл боту', true);
  }),
  'wiz-photo-del': () => {
    S.wiz.autojoin = !!$('#autojoin')?.checked;
    S.wiz.photo = null; S.wiz.photoUrl = null; S.wiz.keepPhoto = false; renderCompose();
  },
  'mail-edit': el => editPost(Number(el.dataset.id)),
  'edit-save': el => run(el, async () => {
    const w = S.wiz;
    let payload;
    if (w.source === 'draft') {
      if (!w.draft) throw new Error('Сначала отправьте пост боту в чат');
      payload = { source: 'draft' };
    } else {
      payload = { text: $('#mailText').value.trim(), photo: w.photo, keep_photo: !!w.keepPhoto };
      if (!payload.text && !w.photo && !w.keepPhoto) throw new Error('Введите текст или прикрепите фото');
    }
    await api(`mailings/${w.edit}/post`, payload);
    closeSheet();
    await loadMailings();
    render();
    toast('Пост обновлён — уйдёт со следующего круга');
  }),
  'mail-aj': el => run(el, async () => {
    const r = await api(`mailings/${el.dataset.id}/autojoin`, {});
    toast(r.autojoin ? 'Автоподписка включена' : 'Автоподписка выключена');
    await switchTab('mailings');
  }),
  'wiz-create': el => run(el, async () => {
    const w = S.wiz;
    const payload = { account_id: w.account_id, chat_ids: w.chat_ids, interval: w.interval, autojoin: !!$('#autojoin')?.checked };
    if (w.source === 'draft') {
      if (!w.draft) throw new Error('Сначала отправьте пост боту в чат');
      payload.source = 'draft';
    } else {
      payload.text = $('#mailText').value.trim();
      payload.photo = w.photo;
      if (!payload.text && !w.photo) throw new Error('Введите текст или прикрепите фото');
    }
    await api('mailings', payload);
    closeSheet();
    await Promise.all([loadAccounts(), loadMailings()]);
    render();
    toast('Рассылка запущена');
  }),

  'mail-stop': el => run(el, async () => { await api(`mailings/${el.dataset.id}/stop`, {}); await switchTab('mailings'); }),
  'mail-start': el => run(el, async () => { await api(`mailings/${el.dataset.id}/start`, {}); await switchTab('mailings'); }),
  'mail-del': el => confirmSheet('Удалить рассылку?', 'Рассылка остановится, статистика по ней будет удалена.', 'Удалить', async () => {
    await api(`mailings/${el.dataset.id}/delete`, {});
    closeSheet();
    await switchTab('mailings');
  }),

  'acc-add': () => accStep('phone'),
  'acc-phone': el => run(el, async () => {
    await api('accounts/send_code', { phone: $('#accInput').value });
    accStep('code');
  }),
  'acc-code': el => run(el, async () => {
    const res = await api('accounts/sign_in', { code: $('#accInput').value });
    if (res.need_password) return accStep('password');
    await accDone();
  }),
  'acc-pass': el => run(el, async () => {
    await api('accounts/password', { password: $('#accInput').value });
    await accDone();
  }),
  'acc-del': el => confirmSheet('Отключить аккаунт?', 'Сессия в Telegram будет завершена, рассылки с этого аккаунта удалятся.', 'Отключить', async () => {
    await api(`accounts/${el.dataset.id}/delete`, {});
    closeSheet();
    await switchTab('accounts');
  }),

  recheck: el => run(el, boot),
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (el && !el.disabled) actions[el.dataset.act]?.(el);
});
document.addEventListener('change', e => {
  if (e.target.closest('#chatList')) updateChatCount();
  if (e.target.id === 'photoInput' && e.target.files[0]) {
    const file = e.target.files[0];
    const label = e.target.closest('label');
    label?.classList.add('busy');
    uploadPhoto(file).then(name => {
      S.wiz.autojoin = !!$('#autojoin')?.checked;
      S.wiz.photo = name;
      S.wiz.photoUrl = URL.createObjectURL(file);
      renderCompose();
    }).catch(err => toast(err.message, true)).finally(() => label?.classList.remove('busy'));
  }
});

// ---------- новогоднее оформление ----------

function drawGarland() {
  const svg = $('#garland');
  const w = window.innerWidth;
  const n = Math.max(6, Math.round(w / 46));
  const step = w / n;
  const colors = ['#ff4f5e', '#f4d58d', '#45d483', '#a9dcff'];
  let path = 'M0 4';
  let bulbs = '';
  for (let i = 0; i < n; i++) {
    const x = i * step;
    path += ` Q${x + step / 2} 26 ${x + step} 4`;
    const c = colors[i % colors.length];
    bulbs += `<g class="bulb" style="animation-delay:${(i % 4) * .6}s"><circle cx="${x + step / 2}" cy="19" r="8" fill="${c}" opacity=".25"/><circle cx="${x + step / 2}" cy="19" r="3.6" fill="${c}"/></g>`;
  }
  svg.setAttribute('viewBox', `0 0 ${w} 34`);
  svg.innerHTML = `<path class="wire" d="${path}"/>${bulbs}`;
}

function startSnow() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const canvas = $('#snow');
  const ctx = canvas.getContext('2d');
  let w, h, flakes;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    flakes = Array.from({ length: Math.round(w / 9) }, () => ({
      x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.8 + .5,
      v: Math.random() * .5 + .2, drift: Math.random() * 2 * Math.PI, a: Math.random() * .5 + .2,
    }));
  };
  resize();
  window.addEventListener('resize', () => { resize(); drawGarland(); });
  (function frame() {
    ctx.clearRect(0, 0, w, h);
    for (const f of flakes) {
      f.y += f.v; f.drift += .01; f.x += Math.sin(f.drift) * .3;
      if (f.y > h + 4) { f.y = -4; f.x = Math.random() * w; }
      ctx.globalAlpha = f.a;
      ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, 6.283); ctx.fillStyle = '#fff'; ctx.fill();
    }
    if (!document.hidden) requestAnimationFrame(frame);
    else document.addEventListener('visibilitychange', function once() { document.removeEventListener('visibilitychange', once); requestAnimationFrame(frame); });
  })();
}

// ---------- запуск ----------

function screen(title, text, extra = '') {
  $('#tabbar').hidden = true;
  view.innerHTML = `<div class="screen"><h1>${title}</h1><p>${text}</p>${extra}</div>`;
}

async function boot() {
  try {
    await loadMe();
  } catch (e) {
    if (e.message === 'subscribe') {
      const links = e.data.channels.map(c => `<button class="btn ghost wide" data-act="open-url" data-url="${esc(c.url)}">${esc(c.title)}</button>`).join('');
      return screen('Подпишитесь на каналы', 'Чтобы пользоваться сервисом, нужна подписка на наши каналы.',
        `<div class="stack">${links}<button class="btn primary wide" data-act="recheck">Я подписался</button></div>`);
    }
    if (e.message === 'banned') return screen('Доступ закрыт', 'Ваш аккаунт заблокирован в сервисе. Если это ошибка — напишите в поддержку.');
    if (e.message === 'unauthorized') return screen('Откройте в Telegram', 'Это приложение работает только внутри Telegram — запустите его кнопкой в боте.');
    return screen('Не удалось загрузить', esc(e.message), '<button class="btn primary" data-act="recheck">Повторить</button>');
  }
  $('#tabbar').hidden = false;
  render();
  Promise.all([loadAccounts(), loadMailings()]).catch(() => {});
}

function init() {
  try {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#030305');
    tg.setBackgroundColor('#030305');
  } catch {}
  const user = tg?.initDataUnsafe?.user;
  const avatar = $('#avatar');
  if (user?.photo_url) avatar.innerHTML = `<img src="${esc(user.photo_url)}" alt="">`;
  else avatar.textContent = (user?.first_name || 'H')[0].toUpperCase();
  drawGarland();
  startSnow();
  boot();
}

init();
