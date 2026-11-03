/* Новогодняя тема мини-приложений (конструктор /c/app и магазины из него).
   Подключается сервером только когда тема включена в /admin бота-конструктора (см. web.with_ny).
   Ничего не меняет в логике приложения: только украшения поверх — заставка с котом, снег, гирлянда,
   кот над карточкой со счётчиком до Нового года, сугроб на нижнем меню. */
(() => {
  "use strict";
  if (window.__heliysNY) return;
  window.__heliysNY = true;

  const RM = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const tg = window.Telegram && window.Telegram.WebApp;
  const haptic = (k) => { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} };
  let uid = 0;

  /* ---------- дата: «С наступающим 2027!» в ноябре–декабре, «С Новым 2027 годом!» в январе–феврале ---------- */
  function when() {
    const now = new Date(), m = now.getMonth(), y = now.getFullYear();
    if (m >= 10) {
      const ny = new Date(y + 1, 0, 1), ms = ny - now;
      const d = Math.floor(ms / 864e5), h = Math.floor(ms / 36e5) % 24;
      return { year: y + 1, before: true, title: `С наступающим ${y + 1}!`, d, h,
        sub: d > 0 ? `До Нового года ${d} ${plural(d, "день", "дня", "дней")} ${h} ч` : `До Нового года ${h} ч — уже совсем скоро` };
    }
    return { year: y, before: false, title: `С Новым ${y} годом!`, sub: "Пусть этот год будет волшебным" };
  }
  function plural(n, a, b, c) { n = Math.abs(n) % 100; const k = n % 10; return n > 10 && n < 20 ? c : k > 1 && k < 5 ? b : k === 1 ? a : c; }

  /* ---------- кот (тот же силуэт, что на аватарке Heliys) в шапке Деда Мороза и шарфе ----------
     part: "all" — целиком, "body" — без лапок, "paws" — только лапки (чтобы лапки лежали поверх карточки) */
  function cat(part = "all") {
    const i = ++uid, body = part !== "paws", paws = part !== "body";
    const defs = `<defs>
      <radialGradient id="nyF${i}" cx="50%" cy="30%" r="75%"><stop offset="0" stop-color="#2a2a34"/><stop offset=".55" stop-color="#101016"/><stop offset="1" stop-color="#040406"/></radialGradient>
      <linearGradient id="nyH${i}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff5a5f"/><stop offset=".55" stop-color="#e3172b"/><stop offset="1" stop-color="#9c0d1d"/></linearGradient>
      <linearGradient id="nyW${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d6e4f5"/></linearGradient>
      <pattern id="nyS${i}" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(-35)"><rect width="16" height="16" fill="#e3172b"/><rect width="5" height="16" fill="#fff"/></pattern>
      <filter id="nyG${i}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>
    </defs>`;
    const B = "M34 98C29 80 30 52 38 26c2-6 8-7 12-3l34 33c11-3 21-3 32 0l34-33c4-4 10-3 12 3 8 26 9 54 4 72 12 20 16 44 14 94H20c-2-50 2-74 14-94z";
    const out = [];
    if (body) out.push(`
      <path d="${B}" fill="none" stroke="#fff" stroke-width="7" opacity=".45" filter="url(#nyG${i})"/>
      <path d="${B}" fill="url(#nyF${i})" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>
      <path d="M44 34l26 25-22 6zM156 34l-26 25 22 6z" fill="#23232c"/>
      <g class="ny-eyes"><ellipse cx="76" cy="128" rx="9.5" ry="14.5" fill="#fff"/><ellipse cx="124" cy="128" rx="9.5" ry="14.5" fill="#fff"/></g>
      <ellipse cx="60" cy="150" rx="10" ry="5" fill="#ff6b8a" opacity=".38"/><ellipse cx="140" cy="150" rx="10" ry="5" fill="#ff6b8a" opacity=".38"/>
      <path d="M22 162c50 14 106 14 156 0l3 20c-52 15-110 15-162 0z" fill="url(#nyS${i})" stroke="#fff" stroke-width="1.5" opacity=".97"/>
      <path d="M46 170l-9 22 17 2 6-21z" fill="url(#nyS${i})" stroke="#fff" stroke-width="1.5"/>
      <g class="ny-hat"><g transform="rotate(-9 100 64)">
        <path d="M60 68C64 32 90 8 118 9c22 1 38 16 42 36l-9 4c-4-11-13-18-25-17 7 10 12 22 15 36z" fill="url(#nyH${i})"/>
        <path d="M118 9c22 1 38 16 42 36l-9 4c-4-11-13-18-25-17-4-6-9-12-14-16z" fill="#000" opacity=".14"/>
        <g class="ny-pom"><circle cx="157" cy="52" r="11" fill="url(#nyW${i})"/><circle cx="153" cy="48" r="4" fill="#fff"/></g>
        <rect x="48" y="58" width="104" height="22" rx="11" fill="url(#nyW${i})"/>
        <g fill="#fff"><circle cx="58" cy="60" r="5"/><circle cx="74" cy="58" r="5.5"/><circle cx="92" cy="57" r="5.5"/><circle cx="110" cy="57" r="5.5"/><circle cx="128" cy="58" r="5.5"/><circle cx="143" cy="60" r="5"/></g>
      </g></g>`);
    if (paws) out.push(`<g class="ny-pw">
      <path d="M44 194c0-14 10-22 22-22s22 8 22 22z" fill="url(#nyF${i})" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>
      <path d="M112 194c0-14 10-22 22-22s22 8 22 22z" fill="url(#nyF${i})" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>
      <path d="M59 184v8M73 184v8M127 184v8M141 184v8" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/></g>`);
    return `<svg class="ny-cat ny-${part}" viewBox="0 0 200 196" aria-hidden="true">${defs}${out.join("")}</svg>`;
  }

  const SPARK = `<svg viewBox="0 0 24 24"><path d="M12 0c.6 6.3 5.7 11.4 12 12-6.3.6-11.4 5.7-12 12-.6-6.3-5.7-11.4-12-12C6.3 11.4 11.4 6.3 12 0z" fill="currentColor"/></svg>`;
  const GIFT = (c1, c2) => `<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="6" y="24" width="52" height="36" rx="5" fill="${c1}"/><rect x="2" y="16" width="60" height="12" rx="4" fill="${c1}" style="filter:brightness(1.15)"/><rect x="27" y="16" width="10" height="44" fill="${c2}"/><path d="M32 16c-6-12-20-12-18-3 1 5 11 4 18 3zm0 0c6-12 20-12 18-3-1 5-11 4-18 3z" fill="none" stroke="${c2}" stroke-width="4.5" stroke-linejoin="round"/></svg>`;
  const TREE = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l4 6h-2l4 6h-2.5l4.5 6H4l4.5-6H6l4-6H8z" fill="#3ddc84"/><rect x="10.5" y="20" width="3" height="3" rx="1" fill="#a0652f"/><circle cx="12" cy="2.4" r="1.6" fill="#ffd34d"/><circle cx="10" cy="11" r="1" fill="#ff4d5e"/><circle cx="14" cy="16" r="1" fill="#ffd34d"/><circle cx="9" cy="17" r="1" fill="#4fc3ff"/></svg>`;

  /* ---------- стили ---------- */
  const css = `
  body.ny { --ny-gold: #ffd36b; --ny-red: #ff3b4e; --ny-snow: #fff; }
  :root:not([data-theme="light"]) body.ny { background:
      radial-gradient(130% 55% at 50% -12%, rgba(52, 96, 210, .32), transparent 62%),
      radial-gradient(70% 40% at 105% 8%, rgba(150, 70, 230, .16), transparent 70%),
      radial-gradient(70% 40% at -5% 30%, rgba(30, 190, 160, .10), transparent 70%), var(--bg); background-attachment: fixed; }
  :root[data-theme="light"] body.ny { --ny-snow: #9cc4ea; }
  body.ny .wrap { padding-top: 40px; }
  .ny-garland { position: absolute; z-index: 16; left: 0; right: 0; top: 0; height: 40px; pointer-events: none; overflow: hidden; }
  .ny-garland svg { width: 100%; height: 100%; display: block; }
  .ny-garland .b { animation: ny-bulb 2.4s ease-in-out infinite; }
  .ny-garland .b.k1 { animation-delay: -.8s; } .ny-garland .b.k2 { animation-delay: -1.6s; }
  @keyframes ny-bulb { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
  #ny-snow { position: fixed; inset: 0; z-index: 15; pointer-events: none; width: 100%; height: 100%; }

  /* кот над карточкой */
  .ny-perch { position: relative; height: 86px; margin: 2px 0 0; display: flex; align-items: center; padding: 0 118px 18px 4px; }
  body.ny .hero { z-index: 1; }
  .ny-perch .ny-hi { min-width: 0; }
  .ny-perch .ny-t { font: 700 16px/1.2 var(--display, sans-serif); letter-spacing: -.01em; background: linear-gradient(100deg, #fff6d8 0%, var(--ny-gold) 35%, #ff9f6b 60%, #fff6d8 100%); background-size: 220% 100%;
    -webkit-background-clip: text; background-clip: text; color: transparent; animation: ny-shine 5s linear infinite; }
  :root[data-theme="light"] .ny-perch .ny-t { background-image: linear-gradient(100deg, #b4282f 0%, #e3172b 40%, #c7891a 70%, #b4282f 100%); }
  .ny-perch .ny-s { margin-top: 4px; font-size: 12.5px; font-weight: 600; color: var(--muted, #8e8e96); display: flex; align-items: center; gap: 6px; }
  .ny-perch .ny-s svg { width: 15px; height: 15px; flex: none; }
  @keyframes ny-shine { to { background-position: -220% 0; } }
  .ny-pc { position: absolute; right: 14px; bottom: -8px; width: 98px; height: 96px; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .ny-pc .ny-cat { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .ny-pc .ny-body { z-index: 0; transform-origin: 50% 100%; animation: ny-breathe 4s ease-in-out infinite; }
  .ny-pc .ny-paws { z-index: 2; }
  .ny-pc.jump .ny-body { animation: ny-jump .6s cubic-bezier(.3, 1.6, .5, 1); }
  @keyframes ny-breathe { 0%, 100% { transform: scale(1, 1); } 50% { transform: scale(1.015, .985); } }
  @keyframes ny-jump { 0% { transform: translateY(0); } 40% { transform: translateY(-14px) rotate(-3deg); } 100% { transform: none; } }
  .ny-cat .ny-eyes { transform-box: fill-box; transform-origin: center; animation: ny-blink 5.5s infinite; }
  @keyframes ny-blink { 0%, 93%, 100% { transform: scaleY(1); } 95.5% { transform: scaleY(.1); } }
  .ny-cat .ny-pom { transform-box: view-box; transform-origin: 140px 30px; animation: ny-pom 3.2s ease-in-out infinite; }
  @keyframes ny-pom { 0%, 100% { transform: rotate(0); } 50% { transform: rotate(7deg); } }
  .ny-burst { position: absolute; z-index: 3; width: 12px; height: 12px; color: var(--ny-gold); pointer-events: none; animation: ny-burst .9s ease-out forwards; }
  .ny-burst svg { width: 100%; height: 100%; display: block; }
  @keyframes ny-burst { from { transform: translate(0, 0) scale(.4); opacity: 1; } to { transform: translate(var(--dx), var(--dy)) scale(1.1) rotate(90deg); opacity: 0; } }

  /* снег на карточке и сугроб на меню */
  .ny-cap { position: absolute; z-index: 3; left: -2px; right: -2px; top: -3px; height: 12px; pointer-events: none; }
  .ny-cap svg, .ny-drift svg { width: 100%; height: 100%; display: block; }
  body.ny .nav { overflow: visible; }
  .ny-drift { position: absolute; left: 0; right: 0; top: -10px; height: 12px; pointer-events: none; }

  /* заставка при входе */
  .ny-splash { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; overflow: hidden; color: #fff; cursor: pointer; -webkit-user-select: none; user-select: none;
    background: radial-gradient(120% 75% at 50% 0%, #1d3270 0%, #0b1433 46%, #03050d 100%); transition: opacity .55s ease, transform .55s ease; }
  .ny-splash.out { opacity: 0; transform: scale(1.06); pointer-events: none; }
  .ny-aur { position: absolute; width: 90vmax; height: 40vmax; border-radius: 50%; filter: blur(60px); opacity: .45; animation: ny-aur 9s ease-in-out infinite alternate; }
  .ny-aur.a1 { top: -16vmax; left: -30vmax; background: radial-gradient(closest-side, #2ee6a8, transparent); }
  .ny-aur.a2 { top: -10vmax; right: -34vmax; background: radial-gradient(closest-side, #7b5cff, transparent); animation-delay: -4s; }
  @keyframes ny-aur { to { transform: translate(8vmax, 4vmax) rotate(8deg); } }
  .ny-star { position: absolute; width: 2px; height: 2px; border-radius: 50%; background: #fff; animation: ny-tw 3s ease-in-out infinite; }
  @keyframes ny-tw { 0%, 100% { opacity: .15; } 50% { opacity: 1; } }
  .ny-sp { position: absolute; width: 18px; color: #fff; filter: drop-shadow(0 0 6px #fff); animation: ny-tw 2.6s ease-in-out infinite; }
  .ny-sp svg { display: block; width: 100%; }
  .ny-scene { position: relative; z-index: 2; width: min(78vw, 340px); display: flex; flex-direction: column; align-items: center; text-align: center; }
  .ny-stage { position: relative; width: 100%; aspect-ratio: 1 / .78; }
  .ny-stage .ny-cat { position: absolute; left: 50%; bottom: 24%; width: 66%; transform: translateX(-50%); overflow: visible; animation: ny-pop 1s cubic-bezier(.2, 1.4, .4, 1) both; filter: drop-shadow(0 0 24px rgba(160, 200, 255, .35)); }
  @keyframes ny-pop { from { transform: translate(-50%, 40%) scale(.7); opacity: 0; } to { transform: translate(-50%, 0) scale(1); opacity: 1; } }
  .ny-mound { position: absolute; left: -6%; right: -6%; bottom: 0; height: 34%; }
  .ny-mound svg { width: 100%; height: 100%; display: block; }
  .ny-gift { position: absolute; bottom: 10%; width: 17%; animation: ny-pop2 .9s .35s cubic-bezier(.2, 1.4, .4, 1) both; }
  .ny-gift.g1 { left: 6%; } .ny-gift.g2 { right: 7%; width: 14%; animation-delay: .5s; }
  .ny-gift svg { width: 100%; display: block; filter: drop-shadow(0 6px 10px rgba(0, 0, 0, .45)); }
  @keyframes ny-pop2 { from { transform: translateY(30px) scale(.6); opacity: 0; } to { transform: none; opacity: 1; } }
  .ny-title { margin-top: 18px; font: 700 clamp(24px, 7.4vw, 34px)/1.12 var(--display, "Unbounded", sans-serif); letter-spacing: -.02em;
    background: linear-gradient(100deg, #fff6d8 0%, #ffd36b 30%, #ff9f6b 55%, #fff6d8 100%); background-size: 220% 100%; -webkit-background-clip: text; background-clip: text; color: transparent;
    animation: ny-up .8s .45s ease-out both, ny-shine 4s 1.2s linear infinite; }
  .ny-sub { margin-top: 10px; font-size: 14.5px; font-weight: 600; color: rgba(255, 255, 255, .78); animation: ny-up .8s .6s ease-out both; }
  .ny-tap { position: absolute; z-index: 2; bottom: calc(26px + env(safe-area-inset-bottom, 0px)); left: 0; right: 0; text-align: center; font-size: 12.5px; font-weight: 600; color: rgba(255, 255, 255, .5); animation: ny-up .8s 1.2s ease-out both; }
  .ny-bar { position: absolute; z-index: 2; left: 50%; bottom: calc(14px + env(safe-area-inset-bottom, 0px)); width: 84px; height: 3px; margin-left: -42px; border-radius: 3px; background: rgba(255, 255, 255, .14); overflow: hidden; }
  .ny-bar i { display: block; height: 100%; background: linear-gradient(90deg, #ffd36b, #ff3b4e); transform-origin: left; animation: ny-prog var(--t) linear both; }
  @keyframes ny-prog { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  @keyframes ny-up { from { transform: translateY(14px); opacity: 0; } to { transform: none; opacity: 1; } }
  .ny-splash canvas { position: absolute; inset: 0; z-index: 1; width: 100%; height: 100%; }

  @media (prefers-reduced-motion: reduce) {
    .ny-splash *, .ny-perch *, .ny-garland * { animation: none !important; }
  }`;
  const st = document.createElement("style");
  st.textContent = css;
  document.head.appendChild(st);

  /* ---------- снег (canvas) ---------- */
  function snow(canvas, count, opts = {}) {
    const ctx = canvas.getContext("2d");
    let w = 0, h = 0, dpr = Math.min(window.devicePixelRatio || 1, 2), flakes = [], raf = 0, alive = true;
    const color = () => getComputedStyle(document.body).getPropertyValue("--ny-snow").trim() || "#fff";
    let col = color();
    function size() {
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function flake(top) {
      const r = Math.random() * (opts.big ? 3 : 2.2) + .7;
      return { x: Math.random() * w, y: top ? -10 : Math.random() * h, r, v: r * .32 + .25, a: Math.random() * 6.28, s: Math.random() * .02 + .006, o: Math.random() * .5 + .45 };
    }
    size();
    for (let i = 0; i < count; i++) flakes.push(flake(false));
    function draw() {
      if (!alive) return;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = col;
      for (const f of flakes) {
        f.a += f.s; f.y += f.v; f.x += Math.sin(f.a) * .45;
        if (f.y > h + 6 || f.x < -8 || f.x > w + 8) Object.assign(f, flake(true));
        ctx.globalAlpha = f.o; ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, 6.283); ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    }
    if (RM) { draw(); cancelAnimationFrame(raf); } else draw();
    const onResize = () => { size(); col = color(); };
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", () => {
      if (RM) return;
      cancelAnimationFrame(raf);
      if (!document.hidden && alive) raf = requestAnimationFrame(draw);
    });
    // тема Telegram могла смениться (светлая / тёмная) — подстраиваем цвет снега
    new MutationObserver(() => { col = color(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { alive = false; cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }

  /* ---------- гирлянда вверху страницы ---------- */
  const BULBS = ["#ff4d5e", "#ffd34d", "#3ddc84", "#4fc3ff", "#ff7ad9"];
  function garland() {
    let g = document.querySelector(".ny-garland");
    if (!g) { g = document.createElement("div"); g.className = "ny-garland"; document.body.prepend(g); }
    const W = Math.max(320, document.documentElement.clientWidth), seg = W < 480 ? 4 : 6, sw = W / seg;
    let wire = "M0 6", bulbs = "", n = 0;
    for (let s = 0; s < seg; s++) {
      const x0 = s * sw;
      wire += ` Q${x0 + sw / 2} 30 ${x0 + sw} 6`;
      for (let k = 1; k <= 4; k++) {
        const t = k / 5, x = x0 + sw * t, y = (1 - t) * (1 - t) * 6 + 2 * (1 - t) * t * 30 + t * t * 6;
        const c = BULBS[n % BULBS.length], cls = "k" + (n % 3);
        bulbs += `<g class="b ${cls}"><circle cx="${x}" cy="${y + 9}" r="7" fill="${c}" opacity=".28"/><rect x="${x - 2.2}" y="${y}" width="4.4" height="4" rx="1" fill="#55606e"/><ellipse cx="${x}" cy="${y + 9}" rx="3.6" ry="5.2" fill="${c}"/><ellipse cx="${x - 1.1}" cy="${y + 7.5}" rx="1" ry="1.8" fill="#fff" opacity=".7"/></g>`;
        n++;
      }
    }
    g.innerHTML = `<svg viewBox="0 0 ${W} 40" preserveAspectRatio="none"><path d="${wire}" fill="none" stroke="#3a4656" stroke-width="1.6"/>${bulbs}</svg>`;
  }

  /* ---------- сугробы ---------- */
  const CAP = `<svg viewBox="0 0 200 16" preserveAspectRatio="none" aria-hidden="true"><path d="M0 0h200v5c-6 0-8 7-15 7s-8-5-15-5-9 9-17 9-8-7-16-7-7 4-14 4-9-6-16-6-8 8-15 8-7-5-14-5-9 7-16 7-8-6-15-6-6 4-12 4-7-5-12-5-5 3-10 3L0 9z" fill="#fff"/><path d="M0 9c5 0 5-3 10-3s5 5 12 5 6-4 12-4 8 6 15 6 7-7 14-7 8 5 15 5 9-8 16-8 8 6 14 6 8-4 16-4 8 7 16 7 10-9 17-9 8 5 15 5 9-7 15-7" fill="none" stroke="#bcd6f2" stroke-width="1.2" opacity=".8"/></svg>`;
  const DRIFT = `<svg viewBox="0 0 400 12" preserveAspectRatio="none" aria-hidden="true"><path d="M0 12V8c18-6 34-7 52-3s30 3 48-2 36-4 54 1 30 5 50 0 38-6 58-1 30 6 52 2 34-6 52-3 24 4 34 4v6z" fill="#fff" opacity=".95"/></svg>`;

  function decorate() {
    // карточка на главной (не превью в мастере создания)
    document.querySelectorAll(".screen .hero").forEach((hero) => {
      if (hero.closest(".preview")) return;
      if (!hero.querySelector(".ny-cap")) {
        const c = document.createElement("div"); c.className = "ny-cap"; c.innerHTML = CAP; hero.appendChild(c);
      }
      const prev = hero.previousElementSibling;
      if (!prev || !prev.classList.contains("ny-perch")) hero.before(perch());
    });
    const nav = document.querySelector(".nav");
    if (nav && !nav.querySelector(".ny-drift")) {
      const d = document.createElement("div"); d.className = "ny-drift"; d.innerHTML = DRIFT; nav.prepend(d);
    }
  }
  function perch() {
    const w = when();
    const el = document.createElement("div");
    el.className = "ny-perch";
    el.innerHTML = `<div class="ny-hi"><div class="ny-t">${w.title}</div><div class="ny-s">${TREE}<span>${w.sub}</span></div></div>
      <div class="ny-pc" role="img" aria-label="Новогодний кот">${cat("body")}${cat("paws")}</div>`;
    const pc = el.querySelector(".ny-pc");
    pc.addEventListener("click", (e) => {
      e.stopPropagation();
      haptic("medium");
      pc.classList.remove("jump"); void pc.offsetWidth; pc.classList.add("jump");
      for (let i = 0; i < 8; i++) {
        const s = document.createElement("span"), a = (i / 8) * 6.283;
        s.className = "ny-burst"; s.innerHTML = SPARK;
        s.style.cssText = `left:${pc.offsetLeft + 44}px;top:${pc.offsetTop + 20}px;--dx:${Math.cos(a) * 46}px;--dy:${Math.sin(a) * 40 - 10}px;color:${BULBS[i % BULBS.length]}`;
        el.appendChild(s); setTimeout(() => s.remove(), 950);
      }
    });
    return el;
  }

  /* ---------- заставка при входе ---------- */
  function splash() {
    let shown = false;
    try { shown = sessionStorage.getItem("ny-splash") === "1"; sessionStorage.setItem("ny-splash", "1"); } catch (e) {}
    if (shown) return;
    const w = when(), T = RM ? 2200 : 3400;
    const rnd = (a, b) => a + Math.random() * (b - a);
    const stars = Array.from({ length: 36 }, () => `<i class="ny-star" style="left:${rnd(0, 100)}%;top:${rnd(0, 62)}%;animation-delay:${-rnd(0, 3)}s;opacity:${rnd(.2, 1)}"></i>`).join("");
    const sparks = [[12, 18, 22], [84, 14, 18], [20, 52, 14], [80, 46, 20], [62, 8, 12]].map(([x, y, s], i) =>
      `<span class="ny-sp" style="left:${x}%;top:${y}%;width:${s}px;animation-delay:${-i * .5}s">${SPARK}</span>`).join("");
    const el = document.createElement("div");
    el.className = "ny-splash";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", w.title);
    el.innerHTML = `<i class="ny-aur a1"></i><i class="ny-aur a2"></i>${stars}${sparks}<canvas></canvas>
      <div class="ny-scene">
        <div class="ny-stage">
          ${cat("all")}
          <div class="ny-mound"><svg viewBox="0 0 300 100" preserveAspectRatio="none"><defs><linearGradient id="nyM" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#9fbde6"/></linearGradient></defs><path d="M0 100C14 70 44 50 84 44c28-4 42 4 68 0s52-12 82-6c34 7 54 30 66 62z" fill="url(#nyM)"/><path d="M48 62c20-8 38-11 58-8M176 42c22 0 42 7 60 18" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".8" fill="none"/></svg></div>
          <div class="ny-gift g1">${GIFT("#e3172b", "#ffd36b")}</div>
          <div class="ny-gift g2">${GIFT("#1fa463", "#ff4d5e")}</div>
        </div>
        <div class="ny-title">${w.title}</div>
        <div class="ny-sub">${w.sub}</div>
      </div>
      <div class="ny-tap">Нажмите, чтобы войти</div>
      <div class="ny-bar"><i style="--t:${T}ms"></i></div>`;
    document.body.appendChild(el);
    const stop = snow(el.querySelector("canvas"), 70, { big: true });
    let done = false;
    const close = () => {
      if (done) return;
      done = true; haptic("light");
      el.classList.add("out");
      setTimeout(() => { stop(); el.remove(); }, 600);
    };
    el.addEventListener("click", close);
    setTimeout(close, T);
  }

  /* ---------- запуск ---------- */
  function start() {
    document.body.classList.add("ny");
    splash();
    garland();
    const cv = document.createElement("canvas");
    cv.id = "ny-snow";
    document.body.appendChild(cv);
    snow(cv, window.innerWidth < 500 ? 38 : 60);
    decorate();
    // приложение перерисовывает экраны через innerHTML — украшаем заново
    let t = 0;
    new MutationObserver(() => { clearTimeout(t); t = setTimeout(decorate, 30); })
      .observe(document.body, { childList: true, subtree: true });
    let rt = 0;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(garland, 150); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
