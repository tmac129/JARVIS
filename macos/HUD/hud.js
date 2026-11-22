/* J.A.R.V.I.S. HUD: Canvas 2D holographic core + panels. Native bridge via webkit.messageHandlers.jarvis */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.jarvis;
  const post = (m) => { if (native) native.postMessage(m); else Demo.handle(m); };

  // ---------------------------------------------------------------- state
  const S = {
    state: "standby",
    level: 0, levelTarget: 0,          // audio level 0..1
    visible: true,
    turns: 0, cost: 0,
    started: Date.now(),
  };
  const COLORS = {
    standby: [0, 229, 255], speaking: [0, 229, 255], listening: [56, 189, 248],
    thinking: [255, 184, 0], alert: [255, 42, 42],
  };
  const SPEED = { standby: 1, listening: 1.5, thinking: 3.4, speaking: 1.7, alert: 0.7 };
  const STATUS = {
    standby: "SYSTEM ONLINE // STANDBY", listening: "ASCOLTO ATTIVO // AUDIO INPUT",
    thinking: "ELABORAZIONE // PROTOCOLLO ATTIVO", speaking: "RISPOSTA VOCALE // OUTPUT",
    alert: "ATTENZIONE // CONFERMA RICHIESTA",
  };
  const MODULES = {
    MAIL_PROTOCOL: "POSTA // APPLE MAIL", CALENDAR_SYNC: "CALENDARIO // EVENTKIT", REMINDERS: "PROMEMORIA // EVENTKIT",
    CLOCK: "SVEGLIE E TIMER // LAUNCHD", FILE_SYSTEM: "FINDER // FILE SYSTEM", CONTACTS: "RUBRICA // CONTATTI",
    CONFIRM: "PROTOCOLLO DI SICUREZZA", NEURAL_LINK: "NUCLEO AI // ELABORAZIONE",
    AUDIO_INPUT: "MICROFONO // RICONOSCIMENTO VOCALE",
  };

  function setState(st, module) {
    const prev = S.state;
    S.state = st;
    document.body.className = st + (S.native ? " native" : "");
    $("status-text").textContent = STATUS[st] || st.toUpperCase();
    if (module) setModule(module);
    else if (st === "standby") setModule(null);
    if (st === "thinking") Chat.pending(true);
    else if (st === "standby" && prev !== "standby") Chat.pending(false);
  }
  function setModule(m) {
    $("module-name").textContent = m ? m : "STANDBY";
    $("module-sub").textContent = m ? (MODULES[m] || "MODULO ATTIVO") : "IN ATTESA DI ISTRUZIONI";
  }

  // ---------------------------------------------------------------- core renderer
  const cv = $("core"), ctx = cv.getContext("2d");
  let W = 0, H = 0, dpr = 1;
  function resize() {
    const r = cv.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  window.addEventListener("resize", resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(cv);

  const N = 460, pts = [];
  const GA = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (2 * (i + 0.5)) / N, r = Math.sqrt(1 - y * y), th = i * GA;
    pts.push([Math.cos(th) * r, y, Math.sin(th) * r, Math.random()]);
  }
  // segmented arc rings: [radius, width, speed, segments [start,len] in turns, alpha]
  const RINGS = [
    [1.30, 1.2, 0.10, [[0, .22], [.27, .08], [.40, .30], [.75, .17]], .55],
    [1.20, 3.0, -0.22, [[0, .12], [.20, .12], [.45, .05], [.55, .25], [.85, .08]], .8],
    [1.11, 1.0, 0.35, [[0, .48], [.52, .44]], .35],
    [0.98, 6.0, -0.06, [[.02, .06], [.27, .06], [.52, .06], [.77, .06]], .5],
  ];
  const RING_TEXT = "J.A.R.V.I.S. // NEURAL INTERFACE // ONLINE // ";
  const col = COLORS.standby.slice();
  const NB = 8, BUCK = Array.from({ length: NB }, () => []);
  const COS = [], SIN = [];
  for (let i = 0; i < 120; i++) { COS.push(Math.cos(i / 120 * Math.PI * 2)); SIN.push(Math.sin(i / 120 * Math.PI * 2)); }

  // offscreen sprites for the parts that only rotate: rebuilt when size or (rounded) color changes
  let SP = null;
  function coreSprites(R) {
    const key = [Math.round(R), dpr, col[0] >> 3, col[1] >> 3, col[2] >> 3].join(",");
    if (SP && SP.key === key) return SP;
    const make = (half, draw) => {
      const c = document.createElement("canvas"), px = Math.ceil(half * 2 * dpr);
      c.width = c.height = px; c._half = half;
      const x = c.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.translate(half, half); draw(x);
      return c;
    };
    const ticks = make(R * 1.42 + 34, (x) => {
      for (const major of [false, true]) {
        x.beginPath();
        for (let i = 0; i < 144; i++) {
          const isMaj = i % 12 === 0; if (isMaj !== major) continue;
          const a = (i / 144) * Math.PI * 2, r1 = R * 1.42, r2 = r1 + (isMaj ? 12 : i % 4 === 0 ? 6 : 3);
          x.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); x.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
        }
        x.strokeStyle = rgba(major ? 0.75 : 0.32); x.lineWidth = major ? 1.4 : 0.8; x.stroke();
      }
      x.fillStyle = rgba(0.55); x.font = "8px SF Mono, Menlo, monospace"; x.textAlign = "center";
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2, r = R * 1.42 + 22;
        x.save(); x.translate(Math.cos(a) * r, Math.sin(a) * r); x.rotate(a + Math.PI / 2);
        x.fillText(String(i * 30).padStart(3, "0"), 0, 0); x.restore();
      }
    });
    const text = make(R * 1.04 + 10, (x) => {
      x.fillStyle = rgba(0.38); x.font = "7px SF Mono, Menlo, monospace"; x.textAlign = "center";
      const txt = RING_TEXT + RING_TEXT, step = (Math.PI * 2) / txt.length;
      for (let i = 0; i < txt.length; i++) { x.save(); x.rotate(i * step); x.translate(0, -R * 1.04); x.fillText(txt[i], 0, 0); x.restore(); }
    });
    const circles = make(R * 1.36 + 2, (x) => {
      x.strokeStyle = rgba(0.18); x.lineWidth = 1; x.beginPath();
      for (const rr of [1.36, 1.25, 0.9]) { x.moveTo(R * rr, 0); x.arc(0, 0, R * rr, 0, Math.PI * 2); }
      x.stroke();
    });
    SP = { key, ticks, text, circles };
    return SP;
  }
  let speed = 1, phase = 0, last = performance.now(), t0 = last;
  const rgba = (a) => `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${a})`;
  const noise = (i, t) => (Math.sin(i * 1.7 + t * 3.1) + Math.sin(i * 0.37 + t * 5.3) + Math.sin(i * 3.1 - t * 2.2)) / 3;

  function frame(now) {
    if (!S.visible) { requestAnimationFrame(frame); last = now; return; }
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    const t = (now - t0) / 1000;
    const tc = COLORS[S.state] || COLORS.standby;
    for (let k = 0; k < 3; k++) col[k] += (tc[k] - col[k]) * Math.min(1, dt * 4);
    speed += ((SPEED[S.state] || 1) - speed) * Math.min(1, dt * 2.5);
    phase += dt * speed;
    if (S.state === "thinking") S.levelTarget = 0.35 + 0.25 * Math.abs(noise(1, t));
    else if (S.state === "standby" || S.state === "alert") S.levelTarget = 0;
    else S.levelTarget = Math.max(0, S.levelTarget - dt * 1.6);
    S.level += (S.levelTarget - S.level) * Math.min(1, dt * 12);

    if (window.Globe) window.Globe.draw(t, dt, col, S.state);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2 - 14;
    const R = Math.max(20, Math.min(W * 0.28, (H - 60) * 0.29));
    ctx.translate(cx, cy);
    ctx.globalCompositeOperation = "lighter";

    // ambient glow
    let g = ctx.createRadialGradient(0, 0, R * 0.2, 0, 0, R * 1.9);
    g.addColorStop(0, rgba(0.16)); g.addColorStop(0.5, rgba(0.05)); g.addColorStop(1, rgba(0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, R * 1.9, 0, Math.PI * 2); ctx.fill();

    // static rings (ticks, degree labels, text band, thin circles) come from cached sprites
    const sp = coreSprites(R);
    const blit = (img, rot) => { ctx.save(); ctx.rotate(rot); ctx.drawImage(img, -img._half, -img._half, img._half * 2, img._half * 2); ctx.restore(); };
    blit(sp.ticks, -phase * 0.04);
    blit(sp.text, phase * 0.05);
    ctx.drawImage(sp.circles, -sp.circles._half, -sp.circles._half, sp.circles._half * 2, sp.circles._half * 2);

    // orange accent brackets (counter-rotating), JARVIS style
    {
      const r0 = phase * 0.07;
      ctx.strokeStyle = "rgba(255,138,31,0.75)"; ctx.lineWidth = 2.2; ctx.beginPath();
      for (const s of [0.1, 0.6]) {
        const a0 = r0 + s * Math.PI * 2;
        ctx.moveTo(Math.cos(a0) * R * 1.53, Math.sin(a0) * R * 1.53);
        ctx.arc(0, 0, R * 1.53, a0, a0 + 0.05 * Math.PI * 2);
      }
      ctx.stroke();
    }

    // segmented rotating arcs (one path per ring)
    ctx.lineCap = "butt";
    for (const [rr, w, sp2, segs, al] of RINGS) {
      const rot = phase * sp2 * Math.PI, r = R * rr;
      ctx.strokeStyle = rgba(al); ctx.lineWidth = w; ctx.beginPath();
      for (const [s0, l] of segs) {
        const a0 = rot + s0 * Math.PI * 2;
        ctx.moveTo(Math.cos(a0) * r, Math.sin(a0) * r);
        ctx.arc(0, 0, r, a0, a0 + l * Math.PI * 2);
      }
      ctx.stroke();
    }

    // tilted orbital rings with travelling nodes
    ctx.strokeStyle = rgba(0.22 + (S.state === "thinking" ? 0.2 : 0)); ctx.lineWidth = 0.9;
    const nodes = [];
    ctx.beginPath();
    for (let k = 0; k < 3; k++) {
      const tilt = 0.28 + k * 0.1, rot = phase * (0.12 + k * 0.05) * (k % 2 ? -1 : 1) + k * 2.1;
      const rx = R * (1.16 + k * 0.05), ry = rx * tilt;
      ctx.moveTo(rx * Math.cos(rot), rx * Math.sin(rot));
      ctx.ellipse(0, 0, rx, ry, rot, 0, Math.PI * 2);
      const na = phase * (1.1 + k * 0.4) + k;
      const nx = Math.cos(na) * rx, ny = Math.sin(na) * ry;
      nodes.push([nx * Math.cos(rot) - ny * Math.sin(rot), nx * Math.sin(rot) + ny * Math.cos(rot)]);
    }
    ctx.stroke();
    ctx.fillStyle = rgba(0.25); ctx.beginPath();
    for (const [px, py] of nodes) { ctx.moveTo(px + 7, py); ctx.arc(px, py, 7, 0, Math.PI * 2); }
    ctx.fill();
    ctx.fillStyle = rgba(0.95); ctx.beginPath();
    for (const [px, py] of nodes) { ctx.moveTo(px + 2.4, py); ctx.arc(px, py, 2.4, 0, Math.PI * 2); }
    ctx.fill();

    // radial waveform (voice / processing): one path
    const bars = 120, base = R * 0.92;
    ctx.lineWidth = 1.6; ctx.strokeStyle = rgba(0.25 + S.level * 0.6); ctx.beginPath();
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2, c = COS[i], s = SIN[i];
      const amp = 2 + S.level * R * 0.32 * (0.5 + 0.5 * noise(i * 0.6, t * (1 + S.level * 2)));
      ctx.moveTo(c * base, s * base); ctx.lineTo(c * (base + amp), s * (base + amp));
    }
    ctx.stroke();

    // radar sweep
    ctx.save(); ctx.rotate(phase * 0.9);
    g = ctx.createLinearGradient(0, 0, R * 0.9, 0);
    g.addColorStop(0, rgba(0)); g.addColorStop(1, rgba(0.35));
    ctx.strokeStyle = g; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(R * 0.9, 0); ctx.stroke();
    ctx.restore();

    // particle sphere: points bucketed by brightness, one fill per bucket
    const ay = phase * 0.35, ax = 0.35 + Math.sin(t * 0.3) * 0.15;
    const cya = Math.cos(ay), sya = Math.sin(ay), cxa = Math.cos(ax), sxa = Math.sin(ax);
    const sr = R * (0.72 + S.level * 0.05);
    for (let b = 0; b < NB; b++) BUCK[b].length = 0;
    for (let i = 0; i < N; i++) {
      const q = pts[i], x = q[0], y = q[1], z = q[2];
      const x1 = x * cya + z * sya, z1 = -x * sya + z * cya;
      const y1 = y * cxa - z1 * sxa, z2 = y * sxa + z1 * cxa;
      const p = 1.6 / (1.6 - z2 * 0.5);
      const depth = (z2 + 1) / 2;
      const tw = 0.6 + 0.4 * Math.sin(t * 2 + q[3] * 20);
      const a = (0.12 + depth * 0.75) * tw;
      const s = 0.6 + depth * 1.6;
      BUCK[Math.min(NB - 1, (a * NB / 0.87) | 0)].push(x1 * sr * p - s / 2, y1 * sr * p - s / 2, s);
    }
    for (let b = 0; b < NB; b++) {
      const L = BUCK[b]; if (!L.length) continue;
      ctx.fillStyle = rgba(((b + 0.5) / NB) * 0.87); ctx.beginPath();
      for (let j = 0; j < L.length; j += 3) ctx.rect(L[j], L[j + 1], L[j + 2], L[j + 2]);
      ctx.fill();
    }

    // meridians
    ctx.strokeStyle = rgba(0.12); ctx.lineWidth = 0.8; ctx.beginPath();
    for (let k = 0; k < 4; k++) {
      const a = ay + (k * Math.PI) / 4, rx = Math.abs(Math.cos(a)) * sr + 0.1;
      ctx.moveTo(rx, 0); ctx.ellipse(0, 0, rx, sr, 0, 0, Math.PI * 2);
    }
    ctx.stroke();

    // core
    const breath = 0.5 + 0.5 * Math.sin(t * (S.state === "standby" ? 1.3 : 3.2));
    const cr = R * (0.22 + breath * 0.025 + S.level * 0.12);
    g = ctx.createRadialGradient(0, 0, 0, 0, 0, cr * 2.4);
    g.addColorStop(0, "rgba(255,255,255,0.95)");
    g.addColorStop(0.18, rgba(0.9)); g.addColorStop(0.45, rgba(0.28)); g.addColorStop(1, rgba(0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, cr * 2.4, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = rgba(0.8); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(0, 0, cr * 1.15, 0, Math.PI * 2); ctx.stroke();
    // inner segmented core ring (arc-reactor style)
    {
      const r0 = -phase * 0.8, r = cr * 1.45;
      ctx.lineWidth = 3; ctx.strokeStyle = rgba(0.6); ctx.beginPath();
      for (let i = 0; i < 10; i++) {
        const a = r0 + (i / 10) * Math.PI * 2;
        ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r); ctx.arc(0, 0, r, a, a + Math.PI * 0.13);
      }
      ctx.stroke();
    }

    ctx.globalCompositeOperation = "source-over";
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- telemetry
  const series = { cpu: [], netIn: [], netOut: [] };
  function spark(id, arrays, max) {
    const c = $(id), x = c.getContext("2d");
    const w = c.clientWidth, h = c.clientHeight, d = Math.min(window.devicePixelRatio || 1, 2);
    if (!w || !h) return;
    if (c.width !== Math.round(w * d)) { c.width = Math.round(w * d); c.height = Math.round(h * d); }
    x.setTransform(d, 0, 0, d, 0, 0); x.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.body).getPropertyValue("--c-rgb").trim();
    x.strokeStyle = `rgba(${css},0.08)`; x.lineWidth = 1;
    for (let gx = 0; gx < w; gx += w / 12) { x.beginPath(); x.moveTo(gx, 0); x.lineTo(gx, h); x.stroke(); }
    arrays.forEach((arr, k) => {
      const m = max || Math.max(1, ...arr);
      x.beginPath();
      arr.forEach((v, i) => { const px = (i / 59) * w, py = h - 1 - (v / m) * (h - 3); i ? x.lineTo(px, py) : x.moveTo(px, py); });
      x.strokeStyle = `rgba(${css},${k ? 0.45 : 0.95})`; x.lineWidth = 1; x.stroke();
      if (!k) { x.lineTo(w, h); x.lineTo(0, h); x.closePath(); x.fillStyle = `rgba(${css},0.1)`; x.fill(); }
    });
  }
  const push = (arr, v) => { arr.push(v); if (arr.length > 60) arr.shift(); };
  const fmtRate = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB/s" : (b / 1024).toFixed(0) + " KB/s";
  const fmtUp = (s) => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "g " : "") + h + "h " + m + "m"; };
  const GC = 2 * Math.PI * 25;
  function gauge(id, pct, hot) {
    const el = $(id); if (!el) return;
    const p = Math.max(0, Math.min(100, pct || 0));
    el.querySelector(".g-val").style.strokeDashoffset = (GC * (1 - p / 100)).toFixed(2);
    el.classList.toggle("hot", !!hot);
  }

  function telemetry(m) {
    if (m.os) $("telem-title").textContent = "TELEMETRIA // " + String(m.os).toUpperCase();
    $("cpu-val").textContent = m.cpu.toFixed(0) + "%"; gauge("g-cpu", m.cpu, m.cpu > 80);
    const ramPct = m.ramUsed / m.ramTotal * 100;
    $("ram-pct").textContent = ramPct.toFixed(0) + "%";
    $("ram-val").textContent = `${m.ramUsed.toFixed(1)}/${m.ramTotal.toFixed(0)} GB`;
    gauge("g-ram", ramPct, ramPct > 88);
    if (m.batt >= 0) {
      $("batt-val").textContent = m.batt + "%";
      $("batt-lbl").textContent = m.charging ? "IN CARICA" : m.ac ? "RETE" : "BATTERIA";
      gauge("g-batt", m.batt, m.batt < 20 && !m.charging);
    } else { $("batt-val").textContent = "N/D"; $("batt-lbl").textContent = "BATTERIA"; }
    $("net-val").textContent = `↓${fmtRate(m.netIn)} ↑${fmtRate(m.netOut)}`;
    $("thermal-val").textContent = m.thermal; $("uptime-val").textContent = fmtUp(m.uptime);
    $("diag-val").textContent = String(m.thermal || "NOMINALE").toUpperCase();
    push(series.cpu, m.cpu); push(series.netIn, m.netIn); push(series.netOut, m.netOut);
    $("cpu-peak").textContent = "PICCO " + Math.max(...series.cpu).toFixed(0) + "%";
    spark("cpu-spark", [series.cpu], 100); spark("net-spark", [series.netIn, series.netOut]);
  }

  // two-click "armed" buttons: first click arms, second (within 3s) runs
  function armed(btn, run) {
    let timer = null; const label = btn.textContent;
    btn.addEventListener("click", () => {
      if (!btn.classList.contains("armed")) {
        btn.classList.add("armed"); btn.textContent = "SICURO?";
        timer = setTimeout(() => { btn.classList.remove("armed"); btn.textContent = label; }, 3000);
        return;
      }
      clearTimeout(timer); btn.classList.remove("armed"); btn.textContent = label;
      run();
    });
  }

  // ---------------------------------------------------------------- action feed
  const fmtWhen = (d) => {
    const hm = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    const today = new Date().toDateString() === d.toDateString();
    return today ? hm : d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }) + " " + hm;
  };
  function feedCount() {
    $("feed-count").textContent = $("feed").querySelectorAll("li:not(.empty)").length;
  }
  function feedEmpty() { $("feed").innerHTML = '<li class="empty">NESSUNA AZIONE REGISTRATA</li>'; feedCount(); }
  function feed(item, fresh = true) {
    const ul = $("feed");
    const empty = ul.querySelector(".empty"); if (empty) empty.remove();
    ul.querySelectorAll("li.fresh").forEach((li) => li.classList.remove("fresh"));
    const li = document.createElement("li");
    if (fresh) li.className = "fresh";
    const d = item.ts ? new Date(item.ts) : new Date();
    li.innerHTML = `<div class="meta"><span></span><span class="tag"></span></div><div class="txt"></div>`;
    li.querySelector(".meta span").textContent = fmtWhen(d);
    li.querySelector(".tag").textContent = item.module || "SYS";
    li.querySelector(".txt").textContent = item.text;
    li.title = d.toLocaleString("it-IT");
    ul.prepend(li);
    if (fresh && ul.scrollTop < 60) ul.scrollTop = 0;
    while (ul.children.length > 300) ul.lastChild.remove();
    feedCount();
  }
  armed($("btn-clear-feed"), () => {
    const items = $("feed").querySelectorAll("li:not(.empty)");
    if (!items.length) return;
    items.forEach((li, i) => { li.style.animationDelay = Math.min(i, 12) * 25 + "ms"; li.classList.add("out"); });
    setTimeout(feedEmpty, 380 + Math.min(items.length, 12) * 25);
    post({ type: "clearFeed" });
  });

  // ---------------------------------------------------------------- chat (scrollable history, persisted locally)
  const Chat = (() => {
    const log = $("chat"), KEY = "jarvis.chat.v1", MAX = 160;
    let items = [];               // persisted entries { k, text, ts }
    let openUser = null;          // last user bubble still waiting for a reply (voice partials update it)
    let pendingEl = null, typing = null, saveT = null;
    try { items = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { items = []; }
    const save = () => { clearTimeout(saveT); saveT = setTimeout(() => { try { localStorage.setItem(KEY, JSON.stringify(items.slice(-MAX))); } catch (e) {} }, 300); };
    const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    const toBottom = (smooth) => log.scrollTo({ top: log.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    const hm = (ts) => new Date(ts).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

    function el(k, text, ts) {
      const d = document.createElement("div");
      d.className = "msg " + k;
      if (k === "tool" || k === "sys") d.textContent = text;
      else {
        d.innerHTML = '<div class="who"></div><div class="body"></div>';
        d.querySelector(".who").textContent = (k === "user" ? "TU" : "J.A.R.V.I.S.") + " // " + hm(ts);
        d.querySelector(".body").textContent = text;
      }
      return d;
    }
    function insert(node) {
      if (pendingEl && pendingEl.parentNode === log) log.insertBefore(node, pendingEl); else log.appendChild(node);
      while (log.children.length > MAX + 5) log.firstChild.remove();
    }
    function record(k, text, ts) { const e = { k, text, ts }; items.push(e); if (items.length > MAX) items.splice(0, items.length - MAX); save(); return e; }
    function finishTyping() { if (typing) { typing.body.textContent = typing.text; typing.node.classList.remove("typing"); typing = null; } }

    return {
      restore() {
        const frag = document.createDocumentFragment();
        items.forEach((e) => frag.appendChild(el(e.k, e.text, e.ts)));
        log.appendChild(frag);
        const now = Date.now();
        const sep = "SESSIONE // " + new Date(now).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
        if (items.length && items[items.length - 1].k === "sys") { items.pop(); log.lastChild.remove(); }
        if (items.length) { record("sys", sep, now); insert(el("sys", sep, now)); }
        else this.reply(greeting(), { animate: false, save: false });
        toBottom(false);
      },
      user(text, local) {
        finishTyping();
        const stick = nearBottom() || local;
        if (openUser) {
          openUser.node.querySelector(".body").textContent = text; openUser.entry.text = text; save();
        } else {
          const ts = Date.now(), node = el("user", text, ts);
          insert(node);
          openUser = { node, entry: record("user", text, ts) };
          node.addEventListener("dblclick", () => { $("cmd").value = node.querySelector(".body").textContent; $("cmd").focus(); });
        }
        if (stick) toBottom(true);
      },
      tool(text) {
        const stick = nearBottom();
        openUser = null;
        insert(el("tool", text, Date.now())); record("tool", text, Date.now());
        if (stick) toBottom(true);
      },
      pending(on) {
        if (on && !pendingEl) {
          const stick = nearBottom();
          pendingEl = document.createElement("div");
          pendingEl.className = "msg jarvis pending";
          pendingEl.innerHTML = '<div class="who">J.A.R.V.I.S.</div><div class="body">ELABORAZIONE<span class="dots"><i></i><i></i><i></i></span></div>';
          log.appendChild(pendingEl);
          if (stick) toBottom(true);
        } else if (!on && pendingEl) { pendingEl.remove(); pendingEl = null; }
      },
      reply(text, opt = {}) {
        finishTyping();
        this.pending(false);
        openUser = null;
        const stick = nearBottom();
        const ts = Date.now(), node = el("jarvis", text, ts), body = node.querySelector(".body");
        log.appendChild(node);
        if (opt.save !== false) record("jarvis", text, ts);
        // keep the beginning of long replies in view; short ones scroll to the bottom
        const anchor = log.scrollTop + node.getBoundingClientRect().top - log.getBoundingClientRect().top - 6;
        const follow = () => {
          if (stick) log.scrollTop = Math.min(anchor, log.scrollHeight - log.clientHeight);
          $("btn-jump").hidden = nearBottom();
        };
        if (opt.animate === false || text.length < 2) { follow(); return; }
        body.textContent = ""; node.classList.add("typing");
        typing = { node, body, text };
        const dur = Math.min(1400, 220 + text.length * 9), start = performance.now(), me = typing;
        const step = (now) => {
          if (typing !== me) return;
          const n = Math.ceil(text.length * Math.min(1, (now - start) / dur));
          body.textContent = text.slice(0, n);
          follow();
          if (n < text.length) requestAnimationFrame(step); else finishTyping();
        };
        requestAnimationFrame(step);
      },
      clear() {
        finishTyping(); items = []; openUser = null; save();
        log.innerHTML = ""; if (pendingEl) log.appendChild(pendingEl);
        this.reply("Cronologia ripulita, signore.", { save: false });
      },
      nearBottom, toBottom,
    };
  })();
  function greeting() {
    const h = new Date().getHours();
    return (h < 6 ? "Buonanotte" : h < 13 ? "Buongiorno" : h < 18 ? "Buon pomeriggio" : "Buonasera") + ", signore. Tutti i sistemi sono operativi.";
  }
  $("chat").addEventListener("scroll", () => { $("btn-jump").hidden = Chat.nearBottom(); });
  $("btn-jump").addEventListener("click", () => Chat.toBottom(true));
  armed($("btn-clear-chat"), () => Chat.clear());

  function showAlert(text) {
    $("alert-text").textContent = text;
    $("alert").hidden = false;
    setState("alert", "CONFIRM");
  }
  function hideAlert() { $("alert").hidden = true; }

  // ---------------------------------------------------------------- input
  const history = []; let hIdx = -1;
  $("cmd-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("cmd").value.trim();
    if (!v) return;
    history.unshift(v); hIdx = -1;
    $("cmd").value = "";
    Chat.user(v, true);
    post({ type: "command", text: v });
  });
  document.addEventListener("keydown", (e) => {
    const alertOn = !$("alert").hidden;
    if (e.key === "Escape") {
      e.preventDefault();
      if (alertOn) post({ type: "cancel" }); else post({ type: "hide" });
    } else if (e.key === "Enter" && alertOn && document.activeElement !== $("cmd")) {
      post({ type: "confirm" });
    } else if (e.key === "ArrowUp" && document.activeElement === $("cmd") && history.length) {
      hIdx = Math.min(hIdx + 1, history.length - 1); $("cmd").value = history[hIdx]; e.preventDefault();
    } else if (e.key === "ArrowDown" && document.activeElement === $("cmd")) {
      hIdx = Math.max(hIdx - 1, -1); $("cmd").value = hIdx >= 0 ? history[hIdx] : ""; e.preventDefault();
    } else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey &&
               !/INPUT|TEXTAREA/.test(document.activeElement.tagName) && !window.getSelection().toString()) {
      $("cmd").focus();              // typing anywhere goes to the command line
    }
  });
  $("btn-confirm").addEventListener("click", () => post({ type: "confirm" }));
  $("btn-cancel").addEventListener("click", () => post({ type: "cancel" }));
  $("btn-mic").addEventListener("click", () => post({ type: "mic" }));

  // ---------------------------------------------------------------- clock
  function clock() {
    const d = new Date();
    $("clock-time").textContent = d.toLocaleTimeString("it-IT");
    $("clock-date").textContent = d.toLocaleDateString("it-IT", { weekday: "long", day: "2-digit", month: "long", year: "numeric" }).toUpperCase();
    const s = Math.floor((Date.now() - S.started) / 1000);
    $("sess-val").textContent = [s / 3600, (s % 3600) / 60, s % 60].map((v) => String(Math.floor(v)).padStart(2, "0")).join(":");
  }
  setInterval(clock, 1000);

  // ---------------------------------------------------------------- native -> HUD
  window.HUD = {
    recv(m) {
      switch (m.type) {
        case "state": setState(m.state, m.module); break;
        case "module": setModule(m.module); break;
        case "telemetry": telemetry(m); break;
        case "model": $("model-val").textContent = "CORE: " + m.label; break;
        case "feed": feed(m, m.fresh !== false); break;
        case "feedCleared": feedEmpty(); break;
        case "user": Chat.user(m.text); break;
        case "tool": Chat.tool(m.text); break;
        case "reply": Chat.reply(m.text); break;
        case "stats":
          $("turns-val").textContent = m.turns; $("tok-val").textContent = m.context.toLocaleString("it-IT");
          $("cost-val").textContent = "$" + m.cost.toFixed(4); $("lat-val").textContent = m.latency;
          break;
        case "confirm": showAlert(m.text); break;
        case "confirmClear": hideAlert(); break;
        case "level": S.levelTarget = Math.max(0, Math.min(1, m.value)); break;
        case "mic": $("btn-mic").classList.toggle("on", !!m.on); break;
        case "visible": S.visible = !!m.value; if (S.visible) setTimeout(() => $("cmd").focus(), 30); break;
        case "focus": $("cmd").focus(); break;
        case "native": S.native = true; document.body.classList.add("native"); break;
      }
    },
  };

  // ---------------------------------------------------------------- demo mode (plain browser preview)
  const Demo = {
    handle(m) {
      if (m.type === "command") {
        const v = m.text.toLowerCase();
        const mod = /mail|posta/.test(v) ? "MAIL_PROTOCOL" : /calend|impegn|riunion/.test(v) ? "CALENDAR_SYNC" :
          /ricord|promemor/.test(v) ? "REMINDERS" : /svegli|timer/.test(v) ? "CLOCK" : /file|cartell|sposta/.test(v) ? "FILE_SYSTEM" : "NEURAL_LINK";
        setState("thinking", mod);
        setTimeout(() => HUD.recv({ type: "tool", text: "jarvis " + mod.toLowerCase() }), 500);
        setTimeout(() => {
          if (/elimina|cancella|invia/.test(v)) { showAlert("Inviare mail a marco@example.com, oggetto \"Relazione\" con allegato relazione.pdf"); return; }
          const long = /lungo|long/.test(v);
          HUD.recv({ type: "reply", text: long ? "Ecco il riepilogo completo, signore.\n\n" + "Questa e' una risposta lunga di prova per verificare lo scorrimento della chat. ".repeat(12) : "Certamente, signore. Fatto." });
          feed({ module: mod, text: "Demo: " + m.text });
          setState("speaking", mod);
          S.levelTarget = 0.6;
          setTimeout(() => setState("standby"), 2600);
        }, 1600);
      } else if (m.type === "confirm" || m.type === "cancel") {
        hideAlert(); setState("standby");
        HUD.recv({ type: "reply", text: m.type === "confirm" ? "Inviata." : "Annullato." });
      }
    },
  };

  // ---------------------------------------------------------------- boot sequence
  function boot() {
    const el = $("boot"), lines = $("boot-lines"), bar = $("boot-bar");
    const steps = ["INIZIALIZZAZIONE NUCLEO NEURALE", "COLLEGAMENTO EVENTKIT // POSTA", "PROTOCOLLI DI SICUREZZA",
      "TELEMETRIA HARDWARE", "RETE GLOBALE // UPLINK", "INTERFACCIA OLOGRAFICA"];
    let i = 0, done = false;
    const finish = () => { if (done) return; done = true; el.classList.add("done"); setTimeout(() => el.remove(), 700); $("cmd").focus(); };
    el.addEventListener("click", finish);
    const tick = () => {
      if (done) return;
      if (i < steps.length) {
        const d = document.createElement("div");
        d.innerHTML = "&gt; <span></span><b>OK</b>"; d.querySelector("span").textContent = steps[i];
        lines.appendChild(d); i++;
        bar.style.width = (i / steps.length * 100) + "%";
        setTimeout(tick, 150 + Math.random() * 90);
      } else setTimeout(finish, 350);
    };
    setTimeout(tick, 250);
  }

  // ---------------------------------------------------------------- boot
  resize(); clock();
  if (window.Globe) window.Globe.init($("globe"));
  Chat.restore();
  feedEmpty();
  requestAnimationFrame(frame);
  boot();
  if (native) post({ type: "ready" });
  else {
    let netI = 0;
    const demoTel = () => {
      netI += 0.3;
      telemetry({ cpu: 12 + Math.abs(Math.sin(netI)) * 25, ramUsed: 9.4, ramTotal: 16, batt: 82, charging: false, ac: false,
        netIn: 20000 + Math.abs(Math.sin(netI * 1.3)) * 400000, netOut: 8000 + Math.abs(Math.cos(netI)) * 60000, thermal: "NOMINALE", uptime: 93784 });
    };
    demoTel(); setInterval(demoTel, 1000);
    [["SYS", "Modalità anteprima (browser)"], ["REGISTRO", "compiti controlla: esito 0"], ["MAIL_PROTOCOL", "Lette 4 mail non lette"],
     ["CALENDAR_SYNC", "Evento creato: Verifica di matematica"], ["REMINDERS", "Promemoria: allega il file su Classroom"]]
      .forEach(([module, text], k) => feed({ module, text, ts: Date.now() - (5 - k) * 3600e3 }, false));
  }
})();
