/* J.A.R.V.I.S. HUD: Canvas 2D holographic core + panels. Native bridge via pywebview (window.pywebview.api.post) */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  // dentro la finestra di JARVIS per Windows esiste window.pywebview; in un browser normale parte la demo
  const pyMode = !!window.pywebview;
  const native = pyMode;
  const queue = [];
  let pyReady = false;
  const flush = () => { pyReady = true; queue.splice(0).forEach((s) => window.pywebview.api.post(s)); };
  if (pyMode) window.addEventListener("pywebviewready", flush);
  const post = (m) => {
    if (!pyMode) return Demo.handle(m);
    const s = JSON.stringify(m);
    if (pyReady) window.pywebview.api.post(s); else queue.push(s);
  };

  // ---------------------------------------------------------------- state
  const S = {
    state: "standby",
    level: 0, levelTarget: 0,          // audio level 0..1 (voice in step 3)
    visible: true,
    turns: 0, cost: 0,
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
    MAIL_PROTOCOL: "POSTA // GMAIL", CALENDAR_SYNC: "CALENDARIO // GOOGLE", REMINDERS: "PROMEMORIA // GOOGLE TASKS",
    CLOCK: "SVEGLIE E TIMER // PIANIFICAZIONE", FILE_SYSTEM: "ESPLORA RISORSE // FILE SYSTEM", CONTACTS: "RUBRICA // CONTATTI",
    CONFIRM: "PROTOCOLLO DI SICUREZZA", NEURAL_LINK: "NUCLEO AI // ELABORAZIONE",
  };

  function setState(st, module) {
    S.state = st;
    document.body.className = st + (S.native ? " native" : "");
    $("status-text").textContent = STATUS[st] || st.toUpperCase();
    if (module) setModule(module);
    else if (st === "standby") setModule(null);
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
  const col = COLORS.standby.slice();
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
    // level: real audio when provided, synthetic shimmer while thinking
    if (S.state === "thinking") S.levelTarget = 0.35 + 0.25 * Math.abs(noise(1, t));
    else if (S.state === "standby" || S.state === "alert") S.levelTarget = 0;
    else S.levelTarget = Math.max(0, S.levelTarget - dt * 1.6);   // voice pulses decay between words
    S.level += (S.levelTarget - S.level) * Math.min(1, dt * 12);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2 - 18;
    const R = Math.min(W * 0.3, (H - 60) * 0.29);
    ctx.translate(cx, cy);
    ctx.globalCompositeOperation = "lighter";

    // ambient glow
    let g = ctx.createRadialGradient(0, 0, R * 0.2, 0, 0, R * 1.9);
    g.addColorStop(0, rgba(0.16)); g.addColorStop(0.5, rgba(0.05)); g.addColorStop(1, rgba(0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, R * 1.9, 0, Math.PI * 2); ctx.fill();

    // outer tick ring (compass)
    ctx.save();
    ctx.rotate(-phase * 0.04);
    for (let i = 0; i < 144; i++) {
      const a = (i / 144) * Math.PI * 2, major = i % 12 === 0, mid = i % 4 === 0;
      const r1 = R * 1.42, r2 = r1 + (major ? 12 : mid ? 6 : 3);
      ctx.strokeStyle = rgba(major ? 0.75 : 0.32); ctx.lineWidth = major ? 1.4 : 0.8;
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2); ctx.stroke();
    }
    ctx.fillStyle = rgba(0.55); ctx.font = "8px SF Mono, Menlo, monospace"; ctx.textAlign = "center";
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2, r = R * 1.42 + 22;
      ctx.save(); ctx.translate(Math.cos(a) * r, Math.sin(a) * r); ctx.rotate(a + Math.PI / 2);
      ctx.fillText(String(i * 30).padStart(3, "0"), 0, 0); ctx.restore();
    }
    ctx.restore();

    // thin full circles
    ctx.strokeStyle = rgba(0.18); ctx.lineWidth = 1;
    for (const rr of [1.36, 1.25, 0.9]) { ctx.beginPath(); ctx.arc(0, 0, R * rr, 0, Math.PI * 2); ctx.stroke(); }

    // segmented rotating arcs
    for (const [rr, w, sp, segs, al] of RINGS) {
      const rot = phase * sp * 2 * Math.PI * 0.5;
      ctx.strokeStyle = rgba(al); ctx.lineWidth = w; ctx.lineCap = "butt";
      for (const [s, l] of segs) {
        ctx.beginPath(); ctx.arc(0, 0, R * rr, rot + s * Math.PI * 2, rot + (s + l) * Math.PI * 2); ctx.stroke();
      }
    }

    // tilted orbital rings with travelling nodes
    for (let k = 0; k < 3; k++) {
      const tilt = 0.28 + k * 0.1, rot = phase * (0.12 + k * 0.05) * (k % 2 ? -1 : 1) + k * 2.1;
      const rx = R * (1.16 + k * 0.05), ry = rx * tilt;
      ctx.strokeStyle = rgba(0.22 + (S.state === "thinking" ? 0.2 : 0)); ctx.lineWidth = 0.9;
      ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, rot, 0, Math.PI * 2); ctx.stroke();
      const na = phase * (1.1 + k * 0.4) + k;
      const nx = Math.cos(na) * rx, ny = Math.sin(na) * ry;
      const px = nx * Math.cos(rot) - ny * Math.sin(rot), py = nx * Math.sin(rot) + ny * Math.cos(rot);
      ctx.fillStyle = rgba(0.95); ctx.beginPath(); ctx.arc(px, py, 2.4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(0.25); ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2); ctx.fill();
    }

    // radial waveform (voice / processing)
    const bars = 120, base = R * 0.92;
    ctx.lineWidth = 1.6;
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2;
      const amp = 2 + S.level * R * 0.32 * (0.5 + 0.5 * noise(i * 0.6, t * (1 + S.level * 2)));
      ctx.strokeStyle = rgba(0.25 + S.level * 0.6);
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * base, Math.sin(a) * base);
      ctx.lineTo(Math.cos(a) * (base + amp), Math.sin(a) * (base + amp)); ctx.stroke();
    }

    // radar sweep
    ctx.save(); ctx.rotate(phase * 0.9);
    g = ctx.createLinearGradient(0, 0, R * 0.9, 0);
    g.addColorStop(0, rgba(0)); g.addColorStop(1, rgba(0.35));
    ctx.strokeStyle = g; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(R * 0.9, 0); ctx.stroke();
    ctx.restore();

    // particle sphere
    const ay = phase * 0.35, ax = 0.35 + Math.sin(t * 0.3) * 0.15;
    const cya = Math.cos(ay), sya = Math.sin(ay), cxa = Math.cos(ax), sxa = Math.sin(ax);
    const sr = R * (0.72 + S.level * 0.05);
    for (let i = 0; i < N; i++) {
      let [x, y, z, ph] = pts[i];
      let x1 = x * cya + z * sya, z1 = -x * sya + z * cya;
      let y1 = y * cxa - z1 * sxa, z2 = y * sxa + z1 * cxa;
      const p = 1 / (1.6 - z2 * 0.5);
      const px = x1 * sr * p * 1.6, py = y1 * sr * p * 1.6;
      const depth = (z2 + 1) / 2;
      const tw = 0.6 + 0.4 * Math.sin(t * 2 + ph * 20);
      ctx.fillStyle = rgba((0.12 + depth * 0.75) * tw);
      const s = 0.6 + depth * 1.6;
      ctx.fillRect(px - s / 2, py - s / 2, s, s);
    }

    // meridians
    ctx.strokeStyle = rgba(0.12); ctx.lineWidth = 0.8;
    for (let k = 0; k < 4; k++) {
      const a = ay + (k * Math.PI) / 4;
      ctx.beginPath(); ctx.ellipse(0, 0, Math.abs(Math.cos(a)) * sr + 0.1, sr, 0, 0, Math.PI * 2); ctx.stroke();
    }

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
    ctx.save(); ctx.rotate(-phase * 0.8); ctx.lineWidth = 3; ctx.strokeStyle = rgba(0.6);
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2;
      ctx.beginPath(); ctx.arc(0, 0, cr * 1.45, a, a + Math.PI * 0.13); ctx.stroke();
    }
    ctx.restore();

    ctx.globalCompositeOperation = "source-over";
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- sparklines
  const series = { cpu: [], netIn: [], netOut: [] };
  function spark(id, arrays, max) {
    const c = $(id), x = c.getContext("2d");
    const w = c.clientWidth, h = c.clientHeight, d = Math.min(window.devicePixelRatio || 1, 2);
    if (c.width !== Math.round(w * d)) { c.width = Math.round(w * d); c.height = Math.round(h * d); }
    x.setTransform(d, 0, 0, d, 0, 0); x.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.body).getPropertyValue("--c-rgb").trim();
    arrays.forEach((arr, k) => {
      const m = max || Math.max(1, ...arr);
      x.beginPath();
      arr.forEach((v, i) => { const px = (i / 59) * w, py = h - 1 - (v / m) * (h - 3); i ? x.lineTo(px, py) : x.moveTo(px, py); });
      x.strokeStyle = `rgba(${css},${k ? 0.4 : 0.9})`; x.lineWidth = 1; x.stroke();
      if (!k) { x.lineTo(w, h); x.lineTo(0, h); x.closePath(); x.fillStyle = `rgba(${css},0.08)`; x.fill(); }
    });
  }
  const push = (arr, v) => { arr.push(v); if (arr.length > 60) arr.shift(); };
  const fmtRate = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB/s" : (b / 1024).toFixed(0) + " KB/s";
  const fmtUp = (s) => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "g " : "") + h + "h " + m + "m"; };

  function telemetry(m) {
    $("cpu-val").textContent = m.cpu.toFixed(0) + "%"; $("cpu-bar").style.width = m.cpu + "%";
    $("ram-val").textContent = `${m.ramUsed.toFixed(1)} / ${m.ramTotal.toFixed(0)} GB`; $("ram-bar").style.width = (m.ramUsed / m.ramTotal * 100) + "%";
    if (m.batt >= 0) { $("batt-val").textContent = m.batt + "%" + (m.charging ? " // CARICA" : m.ac ? " // RETE" : ""); $("batt-bar").style.width = m.batt + "%"; }
    else { $("batt-val").textContent = "N/D"; }
    $("net-val").textContent = `↓${fmtRate(m.netIn)} ↑${fmtRate(m.netOut)}`;
    $("thermal-val").textContent = m.thermal; $("uptime-val").textContent = fmtUp(m.uptime);
    push(series.cpu, m.cpu); push(series.netIn, m.netIn); push(series.netOut, m.netOut);
    spark("cpu-spark", [series.cpu], 100); spark("net-spark", [series.netIn, series.netOut]);
  }


  // ---------------------------------------------------------------- feed / transcript
  function feed(item, fresh = true) {
    const ul = $("feed");
    const empty = ul.querySelector(".empty"); if (empty) empty.remove();
    ul.querySelectorAll("li.fresh").forEach((li) => li.classList.remove("fresh"));
    const li = document.createElement("li");
    if (fresh) li.className = "fresh";
    const d = item.ts ? new Date(item.ts) : new Date();
    const hm = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    li.innerHTML = `<div class="meta"><span>${hm}</span><span class="tag"></span></div><div class="txt"></div>`;
    li.querySelector(".tag").textContent = item.module || "SYS";
    li.querySelector(".txt").textContent = item.text;
    ul.prepend(li);
    while (ul.children.length > 30) ul.lastChild.remove();
  }

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
    $("t-user").textContent = v; $("t-tool").textContent = ""; $("t-reply").textContent = "";
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
        case "user": $("t-user").textContent = m.text; $("t-tool").textContent = ""; $("t-reply").textContent = ""; break;
        case "tool": $("t-tool").textContent = m.text; break;
        case "reply": {
          const r = $("t-reply");
          r.textContent = m.text;
          r.classList.toggle("long", m.text.length > 260);
          r.scrollTop = 0;
          break;
        }
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
          HUD.recv({ type: "reply", text: "Certamente, signore. Fatto." });
          feed({ module: mod, text: "Demo: " + m.text });
          setState("speaking", mod);
          S.levelTarget = 0.6;
          setTimeout(() => setState("standby"), 1800);
        }, 1600);
      } else if (m.type === "confirm" || m.type === "cancel") {
        hideAlert(); setState("standby");
        HUD.recv({ type: "reply", text: m.type === "confirm" ? "Inviata." : "Annullato." });
      }
    },
  };

  // ---------------------------------------------------------------- boot
  resize(); clock();
  requestAnimationFrame(frame);
  $("feed").innerHTML = '<li class="empty">Nessuna azione registrata.</li>';
  if (native) post({ type: "ready" });
  else {
    let netI = 0;
    setInterval(() => {
      netI += 0.3;
      telemetry({ cpu: 12 + Math.abs(Math.sin(netI)) * 25, ramUsed: 9.4, ramTotal: 16, batt: 82, charging: false, ac: false,
        netIn: 20000 + Math.abs(Math.sin(netI * 1.3)) * 400000, netOut: 8000 + Math.abs(Math.cos(netI)) * 60000, thermal: "NOMINALE", uptime: 93784 });
    }, 1000);
    feed({ module: "SYS", text: "Modalità anteprima (browser)" }, false);
  }
  $("cmd").focus();
})();
