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

  /* ---------- кот: настоящий кот с аватарки Heliys (webapp/ny/cat.webp, вырезан без надписи и фона)
     + шапка Деда Мороза поверх: бархат с текстурой ткани и складками, объёмный мех (шум + освещение),
     снег на лапках и веки, которые моргают поверх настоящих глаз.
     Ничего с фильтрами не анимируется постоянно — на телефонах это дорого. ---------- */
  const BASE = new URL(".", (document.currentScript && document.currentScript.src) || location.href).href;
  const CAT_IMG = BASE + "ny/cat.webp";
  function cat() {
    const i = ++uid, f = (n) => `ny${n}${i}`;
    return `<svg class="ny-cat" viewBox="0 0 1100 740" aria-hidden="true"><defs>
      <linearGradient id="${f("v")}" x1="0" y1="0" x2="1" y2=".35">
        <stop offset="0" stop-color="#4a0510"/><stop offset=".1" stop-color="#7d0a18"/><stop offset=".22" stop-color="#b3101f"/>
        <stop offset=".34" stop-color="#e01f33"/><stop offset=".42" stop-color="#ff4256"/><stop offset=".5" stop-color="#e8273b"/>
        <stop offset=".62" stop-color="#c0142a"/><stop offset=".74" stop-color="#9a0d20"/><stop offset=".86" stop-color="#730917"/><stop offset="1" stop-color="#4d0510"/></linearGradient>
      <linearGradient id="${f("w")}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#ffffff"/><stop offset=".45" stop-color="#f4f7fb"/><stop offset=".8" stop-color="#d3dfec"/><stop offset="1" stop-color="#a9bdd3"/></linearGradient>
      <radialGradient id="${f("p")}" cx="38%" cy="32%" r="70%">
        <stop offset="0" stop-color="#ffffff"/><stop offset=".55" stop-color="#eef3f9"/><stop offset=".85" stop-color="#c6d5e6"/><stop offset="1" stop-color="#93abc6"/></radialGradient>
      <radialGradient id="${f("s")}" cx="50%" cy="20%" r="80%">
        <stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#e9f1fa"/><stop offset="1" stop-color="#a8c3e0"/></radialGradient>
      <filter id="${f("fur")}" x="-25%" y="-40%" width="150%" height="180%" color-interpolation-filters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency=".032" numOctaves="4" seed="${3 + i}" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="40" xChannelSelector="R" yChannelSelector="G" result="d"/>
        <feTurbulence type="fractalNoise" baseFrequency=".13 .07" numOctaves="4" seed="${9 + i}" result="fine"/>
        <feDiffuseLighting in="fine" surfaceScale="1.4" diffuseConstant="1.3" lighting-color="#fff" result="lit"><feDistantLight azimuth="235" elevation="64"/></feDiffuseLighting>
        <feGaussianBlur in="lit" stdDeviation=".8" result="soft"/>
        <feComposite in="soft" in2="d" operator="in" result="tex"/>
        <feBlend in="tex" in2="d" mode="multiply" result="m"/>
        <feGaussianBlur in="m" stdDeviation=".6" result="mb"/>
        <feDropShadow in="mb" dx="0" dy="12" stdDeviation="12" flood-color="#000" flood-opacity=".5"/></filter>
      <filter id="${f("vel")}" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency=".7" numOctaves="2" seed="${5 + i}" result="n"/>
        <feColorMatrix in="n" type="matrix" values=".33 .33 .33 0 0  .33 .33 .33 0 0  .33 .33 .33 0 0  0 0 0 0 1" result="g"/>
        <feComponentTransfer in="g" result="gt"><feFuncR type="linear" slope=".3" intercept=".78"/><feFuncG type="linear" slope=".3" intercept=".78"/><feFuncB type="linear" slope=".3" intercept=".78"/></feComponentTransfer>
        <feBlend in="SourceGraphic" in2="gt" mode="multiply" result="b"/>
        <feComposite in="b" in2="SourceGraphic" operator="in"/></filter>
      <filter id="${f("bl")}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="14"/></filter>
      <filter id="${f("bs")}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="5"/></filter>
      <clipPath id="${f("c")}"><path d="M375 120C380 20 430-120 560-175c120-50 270 25 345 135l20 35c-45-35-105-85-165-90-25 55-20 145-15 215z"/></clipPath>
      <clipPath id="${f("el")}"><ellipse cx="332" cy="370" rx="47" ry="72" transform="rotate(-4 332 370)"/></clipPath>
      <clipPath id="${f("er")}"><ellipse cx="697" cy="395" rx="44" ry="67" transform="rotate(4 697 395)"/></clipPath>
    </defs>
    <g transform="translate(20 245)">
      <image href="${CAT_IMG}" x="0" y="0" width="1058" height="492"/>
      <g class="ny-lid"><rect x="270" y="280" width="130" height="170" fill="#030303" clip-path="url(#${f("el")})"/><rect x="640" y="310" width="120" height="160" fill="#030303" clip-path="url(#${f("er")})"/></g>
      <g transform="rotate(8 555 150)">
        <ellipse cx="560" cy="165" rx="230" ry="38" fill="#000" opacity=".55" filter="url(#${f("bl")})"/>
        <g clip-path="url(#${f("c")})">
          <rect x="360" y="-240" width="600" height="380" fill="url(#${f("v")})" filter="url(#${f("vel")})"/>
          <path d="M760-95c60 5 120 55 165 90-50-20-110-45-160-45z" fill="#3a030b" opacity=".75" filter="url(#${f("bs")})"/>
          <path d="M760-95c-25 55-20 145-15 215l-60 0c10-70 20-150 75-215z" fill="#3a030b" opacity=".45" filter="url(#${f("bl")})"/>
          <path d="M430 60c10-80 50-170 120-215" stroke="#ff8a96" stroke-width="26" stroke-linecap="round" fill="none" opacity=".35" filter="url(#${f("bl")})"/>
          <path d="M520 110c15-90 60-170 150-230M610 110c20-70 70-130 140-170" stroke="#4a0510" stroke-width="10" stroke-linecap="round" fill="none" opacity=".45" filter="url(#${f("bs")})"/>
          <path d="M600-180c90-20 190 30 280 120" stroke="#ff9aa5" stroke-width="12" stroke-linecap="round" fill="none" opacity=".4" filter="url(#${f("bs")})"/>
        </g>
        <path d="M378 110C383 20 432-118 560-173c118-48 262 22 340 128" stroke="#dbe9ff" stroke-width="5" fill="none" stroke-linecap="round" opacity=".55" filter="url(#${f("bs")})"/>
        <rect x="325" y="92" width="465" height="112" rx="56" fill="url(#${f("w")})" filter="url(#${f("fur")})"/>
        <circle cx="930" cy="10" r="64" fill="url(#${f("p")})" filter="url(#${f("fur")})"/>
      </g>
      <path d="M48 440c6-34 44-52 96-52s100 14 112 50z" fill="url(#${f("s")})" filter="url(#${f("fur")})"/>
      <path d="M818 462c6-32 42-48 92-48s96 14 108 48z" fill="url(#${f("s")})" filter="url(#${f("fur")})"/>
    </g></svg>`;
  }

  const SPARK = `<svg viewBox="0 0 24 24"><path d="M12 0c.6 6.3 5.7 11.4 12 12-6.3.6-11.4 5.7-12 12-.6-6.3-5.7-11.4-12-12C6.3 11.4 11.4 6.3 12 0z" fill="currentColor"/></svg>`;
  const GIFT = (c1, c2) => { const g = "nyg" + (++uid); return `<svg viewBox="0 0 64 64" aria-hidden="true"><defs>
    <linearGradient id="${g}a" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".38"/></linearGradient>
    <linearGradient id="${g}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".35"/><stop offset=".3" stop-color="#000" stop-opacity="0"/></linearGradient></defs>
    <rect x="6" y="24" width="52" height="36" rx="4" fill="${c1}"/><rect x="6" y="24" width="52" height="36" rx="4" fill="url(#${g}a)"/><rect x="6" y="24" width="52" height="36" rx="4" fill="url(#${g}b)"/>
    <rect x="27" y="24" width="10" height="36" fill="${c2}"/><rect x="27" y="24" width="10" height="36" fill="url(#${g}a)"/>
    <rect x="2" y="15" width="60" height="12" rx="3" fill="${c1}" style="filter:brightness(1.12)"/><rect x="2" y="15" width="60" height="12" rx="3" fill="url(#${g}a)"/>
    <rect x="27" y="15" width="10" height="12" fill="${c2}" style="filter:brightness(1.1)"/>
    <path d="M32 15c-6-12-20-12-18-3 1 5 11 4 18 3zm0 0c6-12 20-12 18-3-1 5-11 4-18 3z" fill="none" stroke="${c2}" stroke-width="4.5" stroke-linejoin="round"/>
    <path d="M4 16h56" stroke="#fff" stroke-opacity=".35" stroke-width="1.2"/>
    <path d="M3 15c4-5 12-6 20-4M41 11c8-2 16-1 20 4" stroke="#fff" stroke-width="3.5" stroke-linecap="round" fill="none" opacity=".9"/></svg>`; };
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
  .ny-perch { position: relative; height: 92px; display: flex; align-items: center; padding: 0 142px 22px 4px; }
  body.ny .hero { z-index: 1; }
  .ny-perch .ny-hi { min-width: 0; }
  .ny-perch .ny-t { font: 700 16px/1.2 var(--display, sans-serif); letter-spacing: -.01em; background: linear-gradient(100deg, #fff6d8 0%, var(--ny-gold) 35%, #ff9f6b 60%, #fff6d8 100%); background-size: 220% 100%;
    -webkit-background-clip: text; background-clip: text; color: transparent; animation: ny-shine 5s linear infinite; }
  :root[data-theme="light"] .ny-perch .ny-t { background-image: linear-gradient(100deg, #b4282f 0%, #e3172b 40%, #c7891a 70%, #b4282f 100%); }
  .ny-perch .ny-s { margin-top: 4px; font-size: 12.5px; font-weight: 600; color: var(--muted, #8e8e96); display: flex; align-items: center; gap: 6px; }
  .ny-perch .ny-s svg { width: 15px; height: 15px; flex: none; }
  @keyframes ny-shine { to { background-position: -220% 0; } }
  .ny-pc { position: absolute; z-index: 2; right: 6px; bottom: -3px; width: 140px; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .ny-pc .ny-cat { display: block; width: 100%; height: auto; overflow: visible; transform-origin: 50% 100%; filter: drop-shadow(0 -2px 14px rgba(170, 205, 255, .22)); }
  .ny-pc.jump .ny-cat { animation: ny-jump .7s cubic-bezier(.16, 1, .3, 1); }
  @keyframes ny-jump { 0% { transform: none; } 35% { transform: translateY(-10px) rotate(-2deg); } 100% { transform: none; } }
  .ny-cat .ny-lid rect { transform-box: fill-box; transform-origin: 50% 0; transform: scaleY(0); animation: ny-blink 6s infinite; }
  @keyframes ny-blink { 0%, 94%, 100% { transform: scaleY(0); } 96.5% { transform: scaleY(1); } }
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
  .ny-stage { position: relative; width: 100%; aspect-ratio: 1 / .86; }
  .ny-stage .ny-cat { position: absolute; left: 50%; bottom: 19%; width: 96%; transform: translateX(-50%); overflow: visible; animation: ny-pop 1.1s cubic-bezier(.16, 1, .3, 1) both; filter: drop-shadow(0 0 28px rgba(160, 200, 255, .28)); }
  @keyframes ny-pop { from { transform: translate(-50%, 34%); opacity: 0; } to { transform: translate(-50%, 0); opacity: 1; } }
  .ny-mound { position: absolute; left: -6%; right: -6%; bottom: 0; height: 34%; }
  .ny-mound svg { width: 100%; height: 100%; display: block; }
  .ny-gift { position: absolute; bottom: 10%; width: 17%; animation: ny-pop2 .9s .35s cubic-bezier(.16, 1, .3, 1) both; }
  .ny-gift.g1 { left: -3%; width: 15%; } .ny-gift.g2 { right: -2%; width: 12%; animation-delay: .5s; }
  .ny-gift svg { width: 100%; display: block; filter: drop-shadow(0 6px 10px rgba(0, 0, 0, .45)); }
  @keyframes ny-pop2 { from { transform: translateY(24px); opacity: 0; } to { transform: none; opacity: 1; } }
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
      <div class="ny-pc" role="img" aria-label="Новогодний кот">${cat()}</div>`;
    const pc = el.querySelector(".ny-pc");
    pc.addEventListener("click", (e) => {
      e.stopPropagation();
      haptic("medium");
      pc.classList.remove("jump"); void pc.offsetWidth; pc.classList.add("jump");
      for (let i = 0; i < 8; i++) {
        const s = document.createElement("span"), a = (i / 8) * 6.283;
        s.className = "ny-burst"; s.innerHTML = SPARK;
        s.style.cssText = `left:${pc.offsetLeft + 64}px;top:${pc.offsetTop + 12}px;--dx:${Math.cos(a) * 46}px;--dy:${Math.sin(a) * 40 - 10}px;color:${BULBS[i % BULBS.length]}`;
        el.appendChild(s); setTimeout(() => s.remove(), 950);
      }
    });
    return el;
  }

  /* ---------- заставка при входе ---------- */
  const catReady = new Promise((res) => { const im = new Image(); im.onload = im.onerror = res; im.src = CAT_IMG; setTimeout(res, 700); });
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
          ${cat()}
          <div class="ny-mound"><svg viewBox="0 0 300 100" preserveAspectRatio="none"><defs><linearGradient id="nyM" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#9fbde6"/></linearGradient></defs><path d="M0 100C14 70 44 50 84 44c28-4 42 4 68 0s52-12 82-6c34 7 54 30 66 62z" fill="url(#nyM)"/><path d="M48 62c20-8 38-11 58-8M176 42c22 0 42 7 60 18" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".8" fill="none"/></svg></div>
          <div class="ny-gift g1">${GIFT("#e3172b", "#ffd36b")}</div>
          <div class="ny-gift g2">${GIFT("#1fa463", "#ff4d5e")}</div>
        </div>
        <div class="ny-title">${w.title}</div>
        <div class="ny-sub">${w.sub}</div>
      </div>
      <div class="ny-tap">Нажмите, чтобы войти</div>
      <div class="ny-bar"><i style="--t:${T}ms"></i></div>`;
    // пока грузится картинка кота (до 0,7 с) — просто тёмный фон, чтобы анимация появления не прошла впустую
    const cover = document.createElement("div");
    cover.className = "ny-splash";
    document.body.appendChild(cover);
    catReady.then(() => {
      document.body.appendChild(el);
      cover.remove();
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
    });
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
  window.__heliysNY = { cat };  // для отладки: window.__heliysNY.cat()
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
