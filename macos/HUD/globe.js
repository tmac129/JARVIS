/* J.A.R.V.I.S. HUD: rotating holographic globe (land as dots, graticule, network arcs).
   Pure Canvas 2D, no external data: the coastlines below are hand-simplified [lon, lat] outlines. */
(() => {
  "use strict";
  const D = Math.PI / 180;

  // ---------------------------------------------------------------- simplified land outlines [lon, lat]
  const LAND = [
    // North America
    [[-168,66],[-162,70],[-156,71.3],[-140,69.6],[-128,70],[-115,68.5],[-95,72],[-82,73],[-80,63],[-94,59],[-92,57],[-82,55],[-79,52],[-77,60],[-70,62],[-64,60],[-61,56],[-56,52],[-60,47],[-66,44],[-70,42],[-74,40.5],[-76,35],[-81,31],[-80,25.5],[-82,27],[-84,30],[-90,29],[-97,27.5],[-97,22],[-94,18.5],[-91,19],[-87,21.5],[-88,16],[-83,15],[-83.5,11],[-79.5,9],[-77.5,8.5],[-80,7.5],[-85,10],[-88,13.5],[-92,14.5],[-96,15.7],[-105,20],[-110,24],[-114.5,30],[-117,32.5],[-120.5,34.5],[-124,40],[-124.5,48],[-130,54.5],[-135,58],[-141,60],[-147,61],[-153,58],[-158,56],[-164,54.5],[-158,58.5],[-162,60],[-165,62.5],[-166,64.5]],
    // Baja California
    [[-117,32.5],[-114.7,31.5],[-112.5,29],[-109.5,23],[-110.5,23.2],[-112.2,25],[-114.2,28],[-116,30],[-117,32.5]],
    // Greenland
    [[-73,78],[-60,82],[-40,83.5],[-22,82],[-18,77],[-22,70],[-32,68],[-40,65],[-43,60],[-48,61],[-52,65],[-54,68],[-58,75.5],[-68,76.5]],
    // Canadian Arctic Archipelago, Baffin
    [[-120,70],[-105,69],[-95,72],[-80,74],[-75,79],[-62,82.5],[-90,81],[-105,79],[-122,76],[-125,72]],
    [[-77,62.5],[-64.5,62],[-61.5,66.5],[-68,70.5],[-77,72.7],[-89,73],[-85,69.5],[-81,68.5],[-73,66.5]],
    // Iceland
    [[-22.5,64],[-24,65.5],[-22,66.4],[-16,66.5],[-13.5,65.2],[-15,64.3],[-18.7,63.4]],
    // Caribbean
    [[-85,21.9],[-81.5,23.1],[-77,22],[-74.2,20.2],[-77.5,19.9],[-80,21.6]],
    [[-74.4,18.5],[-72.8,19.9],[-69.9,19.6],[-68.4,18.6],[-71.4,17.6]],
    // South America
    [[-77.5,8.5],[-72,12],[-64,10.5],[-60,8.5],[-52,5],[-50,0],[-44,-2.5],[-35,-5.5],[-35,-9],[-39,-13.5],[-41,-22],[-48,-26],[-53,-34],[-58,-38],[-62,-39],[-65,-42],[-65,-47],[-69,-51],[-68.5,-55],[-72,-53.5],[-75,-50],[-74,-43],[-73,-37],[-71.5,-30],[-70.5,-18],[-75,-15],[-79,-8],[-81,-4.5],[-80,0],[-79,2],[-77.5,4]],
    // Eurasia
    [[-9,43],[-9.5,39],[-9,37],[-6,36.5],[-2,36.7],[0,38.5],[3,42],[5,43.3],[9,44.3],[10.5,43],[12.5,41.5],[16,38],[15.7,40],[18.5,40.2],[16,41.5],[13.5,43.5],[12.3,45.3],[13.7,45.6],[15,44],[19.5,41.8],[20,39.5],[22.5,36.5],[24,38],[23,40.5],[26,40.7],[26.5,39],[28,36.7],[32,36.2],[36,36.5],[35.5,33],[34.3,31.3],[34.9,29.5],[37,25],[39,21.5],[42.5,15],[43.5,12.7],[45,13],[52,16],[55.5,17.5],[57.8,19.5],[59.8,22.5],[56.3,26.2],[54,24.2],[51.5,24.5],[50.8,26],[48.5,28.5],[48,30],[50.5,30],[54,26.8],[57,25.8],[61.5,25.2],[66.5,25.4],[68,23.8],[70,21],[72.8,21],[73,17],[74.5,13],[76.5,8.5],[77.5,8],[79.8,10.3],[80.2,13.5],[80,15.5],[82.3,17],[86.5,20],[87,21.5],[89,21.8],[91.8,22.4],[92.3,20.7],[94.5,16.5],[97.5,16.5],[98.5,13.5],[98.6,8.5],[100.3,5.5],[101.3,2.8],[103.5,1.3],[104.2,1.5],[103.4,4.5],[102.2,6.2],[100.4,7.4],[100,12.5],[100.9,13.4],[102.5,12.2],[105,8.7],[106.6,9.5],[109.2,11.6],[109.3,13.5],[106.6,17.5],[105.7,19],[107.5,21.5],[109.8,21.5],[110.5,20.3],[113,22.2],[117,23.5],[119.6,25.7],[121.8,28.5],[121.9,30.8],[120.5,32.5],[119.2,35],[122.5,37],[119,37.3],[118,38.5],[117.7,39.1],[121.5,40.5],[121.2,39],[124.3,40],[126.5,37.6],[126.3,34.5],[129.3,35.3],[129.5,37],[128.3,38.6],[129.8,41],[131.5,42.8],[135.5,43.8],[138.5,47],[140.5,51.5],[141.3,53.3],[137,54],[135.2,54.7],[140,57.5],[143,59.3],[148,59.4],[152,59],[155.5,59.4],[156.5,57.5],[156,53.5],[156.7,51],[158.6,52.9],[160,54.5],[162.5,56.3],[163.3,58],[165,60.2],[170,60],[173,61.8],[178,62.4],[180,65],[180,69],[176,69.8],[170,70],[160,69.6],[152,70.8],[143,72.7],[130,71],[128,72.5],[118,73.6],[112,76.5],[105,77.5],[100,76],[90,75.6],[80,73.5],[72,72.8],[69,73],[62,69.8],[59,68.5],[55,68.4],[49,67.7],[44,68.4],[40.5,67.7],[34,69.3],[29,70],[24,71],[18,69.8],[13,67.5],[10.5,64.5],[5,62],[5.5,58.5],[7,58],[10.6,59],[11.5,58.2],[12.5,56],[13,55.4],[16,56.2],[18.7,60],[17.3,62.5],[21.4,65],[25.4,65.4],[22.5,63.5],[21.4,60.6],[23,59.8],[29.8,60.2],[23.5,59.2],[21.5,57.5],[21,55.5],[19.5,54.4],[14,54],[11,54],[10,55],[8.6,57],[8.2,55.5],[8.5,53.7],[5,53.3],[3.5,51.4],[1.6,50.9],[-1.5,49.7],[-4.7,48.4],[-2.2,47.2],[-1.2,44.6],[-1.8,43.4]],
    // Great Britain, Ireland
    [[-5.7,50],[1.4,51.2],[1.7,52.7],[0.2,53.5],[-1.6,55.6],[-2,57.6],[-3,58.6],[-5,58.6],[-6.2,57.5],[-5.6,55.3],[-3,54.8],[-3.2,53.4],[-4.6,52.8],[-5.2,51.7],[-3.2,51.4]],
    [[-6,52.2],[-6.2,54],[-7.3,55.3],[-10,54.2],[-9.8,52.1],[-10.3,51.6]],
    // Mediterranean islands
    [[8.2,41],[9.8,41],[9.6,39],[8.4,38.9]],
    [[12.4,38.1],[15.6,38.3],[15.1,36.7],[12.7,37.6]],
    // Svalbard, Novaya Zemlya
    [[11,78.5],[17,76.6],[22,77.5],[27,80],[18,80.5],[11,79.8]],
    [[52,71],[56,70.6],[59,72],[69,77],[62,76.3],[54,73.5]],
    // Africa
    [[-17,21],[-16.5,24],[-13,27.8],[-9.7,30.5],[-9.5,33],[-6,35.8],[-2,35.1],[3,36.8],[10,37.3],[11,35.3],[10.2,34],[11.5,33],[15.5,32.3],[19,30.3],[20,32],[23,32.6],[25,31.7],[29,30.9],[32.3,31.3],[34.3,31.3],[32.6,29.8],[35,24],[37.3,19],[38.6,18],[39.7,15.5],[43.3,12.5],[44,10.5],[51.2,11.8],[51,10.4],[48.5,5],[46,2],[42.5,-1],[40.2,-3],[39.2,-6.5],[39.5,-10.5],[40.6,-15],[35.5,-22.5],[35.5,-24],[32.9,-26],[32.4,-29],[30,-31.4],[27,-33.6],[22.5,-34],[20,-34.8],[18.4,-34],[18,-32],[15.2,-27],[14.4,-22.5],[11.8,-17.2],[13.6,-12],[13.2,-9],[12.2,-6],[9.5,-2.5],[9.3,0.5],[9.8,3],[8.5,4.5],[6,4.3],[4.5,6.3],[1.5,6.2],[-2,4.7],[-7.5,4.4],[-11.4,6.8],[-13.3,9],[-15,11],[-16.8,13.2],[-17.5,14.7],[-16,18.5]],
    // Madagascar, Sri Lanka
    [[49.3,-12],[50.5,-15.5],[49.5,-17.5],[47.2,-25],[45,-25.5],[43.5,-22],[44.2,-16.5],[46.5,-15.7]],
    [[79.8,8.2],[80.2,9.8],[81.9,7.4],[81.2,6.1],[80,6]],
    // Japan
    [[130,31.3],[131.5,31.5],[132.2,33.9],[135,33.5],[136.8,34.3],[139.8,35],[140.8,36.8],[141,38.3],[142,39.5],[141.4,41.4],[140,40.7],[139.8,39],[138.5,37.5],[136.8,37.2],[135.5,35.6],[132,35.3],[130.9,33.9],[129.7,33]],
    [[140,41.5],[141.3,41.8],[143.2,42],[145.5,43.3],[144,44.1],[141.9,45.4],[141.4,43.3]],
    // Taiwan, Philippines
    [[120.1,23],[121,25.2],[122,25],[120.8,21.9]],
    [[120.6,18.5],[122.2,18.5],[122,16],[124,13.5],[123.5,13],[121,13.7],[120.6,14.5],[119.8,16.3]],
    [[122,7],[124,8],[125.5,9.7],[126.6,7.2],[125.5,5.8],[124,6.4]],
    // Indonesia, New Guinea
    [[95.3,5.6],[98,4],[100.4,0.5],[103.8,-1.3],[106,-3.2],[105.8,-5.8],[104.5,-5.9],[102,-4],[100.5,-1.5],[98.6,1.7]],
    [[105.2,-6.8],[108.5,-6.4],[112.6,-6.9],[114.5,-7.8],[114.4,-8.7],[110,-8.1],[106.4,-7.4]],
    [[109,1.5],[109.6,-0.5],[110.2,-2.9],[114.5,-3.6],[116.5,-3],[116,-1],[117.8,0.8],[119,1],[117.9,4.1],[119.2,5.3],[117,7],[115.5,5.3],[113,3.1],[111,1.7]],
    [[119.4,-5.5],[120.4,-5.5],[120.5,-2.8],[121.3,-1],[123.3,-0.9],[125,1.5],[124.4,0.5],[120.8,0.7],[120,-0.2],[118.8,-2.8]],
    [[131,-1.5],[134,-0.8],[137.5,-1.5],[141,-2.6],[145.7,-4.5],[147.5,-6.2],[150.8,-10.4],[147,-10.1],[144,-7.8],[141,-9.2],[138,-8.3],[137.8,-5.2],[134.5,-4],[132,-2.8]],
    // Australia, Tasmania, New Zealand
    [[113.5,-22],[114,-26.5],[115,-30],[115,-34],[118,-35],[123.5,-33.9],[126,-32.3],[131,-31.5],[135,-34.8],[137.8,-32.8],[137.5,-35.5],[140,-37.5],[143.5,-38.8],[147,-38],[150,-37.5],[151.3,-33.8],[153,-31],[153.5,-28],[153,-25],[150.8,-22.5],[146,-19],[145.3,-15],[143.5,-14],[142.5,-10.7],[141.5,-13.5],[141.6,-17],[140,-17.7],[136,-15.5],[136.8,-12.2],[133,-11.5],[130.2,-12.3],[129.5,-15],[126.5,-14],[124,-16.3],[122.2,-18],[121,-19.5],[116.8,-20.6]],
    [[144.6,-40.7],[148.3,-40.9],[148,-43.2],[146,-43.6],[145.2,-42.2]],
    [[172.7,-34.4],[174.5,-36],[175.8,-37],[178.5,-37.7],[177,-39.2],[176,-41.3],[174.6,-41.3],[175,-39.6],[173.8,-39.2],[174.6,-37.5]],
    [[172.7,-40.5],[174.3,-41.7],[172.8,-43.6],[171.2,-44.5],[169.5,-46.6],[166.5,-46.2],[168,-44],[171.4,-41.8]],
    // Antarctic Peninsula
    [[-57,-63.2],[-60,-63.8],[-65,-66],[-68,-68],[-75,-71],[-60,-74],[-57,-66]],
  ];

  function inPoly(lon, lat, p) {
    let ins = false;
    for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
      const [xi, yi] = p[i], [xj, yj] = p[j];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) ins = !ins;
    }
    return ins;
  }
  const isLand = (lon, lat) => lat < -71 + 2.5 * Math.cos(lon * D * 2) || LAND.some((p) => inPoly(lon, lat, p));
  const vec = (lat, lon) => [Math.cos(lat * D) * Math.sin(lon * D), Math.sin(lat * D), Math.cos(lat * D) * Math.cos(lon * D)];

  // land dots on a Fibonacci sphere
  const DOTS = [];
  {
    const N = 5200, GA = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (2 * (i + 0.5)) / N, lat = Math.asin(y) / D;
      let lon = ((i * GA) / D) % 360; if (lon > 180) lon -= 360;
      if (isLand(lon, lat)) DOTS.push(vec(lat, lon));
    }
  }
  // graticule polylines every 30 degrees
  const GRAT = [];
  for (let lat = -60; lat <= 60; lat += 30) { const l = []; for (let lon = -180; lon <= 180; lon += 6) l.push(vec(lat, lon)); GRAT.push(l); }
  for (let lon = -180; lon < 180; lon += 30) { const l = []; for (let lat = -90; lat <= 90; lat += 6) l.push(vec(lat, lon)); GRAT.push(l); }

  const HOME = { name: "HOME", lat: 42.5, lon: 12.5 };   // generic point in Italy, not a real address
  const HUBS = [
    { name: "ANTHROPIC // SFO", lat: 37.77, lon: -122.42, main: true },
    { name: "NYC", lat: 40.71, lon: -74.0 }, { name: "LON", lat: 51.5, lon: -0.12 }, { name: "FRA", lat: 50.11, lon: 8.68 },
    { name: "TYO", lat: 35.68, lon: 139.7 }, { name: "SIN", lat: 1.35, lon: 103.8 }, { name: "SYD", lat: -33.87, lon: 151.2 },
    { name: "GRU", lat: -23.55, lon: -46.63 }, { name: "DXB", lat: 25.2, lon: 55.27 }, { name: "JNB", lat: -26.2, lon: 28.05 },
    { name: "BOM", lat: 19.07, lon: 72.88 }, { name: "YVR", lat: 49.28, lon: -123.1 },
  ];
  HOME.v = vec(HOME.lat, HOME.lon);
  HUBS.forEach((h) => (h.v = vec(h.lat, h.lon)));

  function arcPoints(a, b, n = 48) {
    const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
    const om = Math.acos(dot), so = Math.sin(om) || 1, lift = 0.06 + om * 0.13, out = [];
    for (let i = 0; i <= n; i++) {
      const s = i / n, k1 = Math.sin((1 - s) * om) / so, k2 = Math.sin(s * om) / so, h = 1 + lift * Math.sin(Math.PI * s);
      out.push([(a[0] * k1 + b[0] * k2) * h, (a[1] * k1 + b[1] * k2) * h, (a[2] * k1 + b[2] * k2) * h]);
    }
    return out;
  }
  HUBS.forEach((h) => (h.arc = arcPoints(HOME.v, h.v)));

  // ---------------------------------------------------------------- renderer
  let cv, ctx, W = 0, H = 0, dpr = 1;
  let rot = -HOME.lon * D;            // start with Italy facing the viewer
  const TILT = 0.38;
  const ct = Math.cos(TILT), st = Math.sin(TILT);
  const arcs = [];                    // transient network links { hub, born, life }
  let nextArc = 1.5, lastUi = 0;

  function resize() {
    if (!cv) return;
    const r = cv.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }

  let acc = 0, SPR = null;
  function ringSprite(R, rgba, key) {
    if (SPR && SPR.key === key) return SPR.c;
    const half = R * 1.14 + 10, c = document.createElement("canvas");
    c.width = c.height = Math.ceil(half * 2 * dpr); c._half = half;
    const x = c.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.translate(half, half);
    for (const major of [false, true]) {
      x.beginPath();
      for (let i = 0; i < 90; i++) {
        if ((i % 15 === 0) !== major) continue;
        const a = (i / 90) * Math.PI * 2, r1 = R * 1.14, r2 = r1 + (major ? 7 : 3);
        x.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); x.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
      }
      x.strokeStyle = rgba(major ? 0.7 : 0.25); x.lineWidth = major ? 1.2 : 0.7; x.stroke();
    }
    SPR = { key, c };
    return c;
  }
  const GB = 6, GBUCK = Array.from({ length: GB }, () => []);

  function draw(t, dt, col, state) {
    if (!ctx || W < 10 || H < 10) return;
    // the globe turns slowly: 30 fps is enough and halves its cost
    acc += dt;
    if (acc < 1 / 31) return;
    dt = acc; acc = 0;
    const rgba = (a) => `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${a})`;
    const busy = state === "thinking" || state === "speaking";
    rot += dt * (busy ? 0.32 : 0.16);
    const cr = Math.cos(rot), sr = Math.sin(rot);
    const cx = W / 2, cy = H / 2 + 6, R = Math.max(10, Math.min(W * 0.36, (H - 30) * 0.4));
    // project: returns [sx, sy, z]
    const P = (v) => {
      const x = v[0] * cr + v[2] * sr, z1 = -v[0] * sr + v[2] * cr;
      const y = v[1] * ct - z1 * st, z = v[1] * st + z1 * ct;
      return [cx + x * R, cy - y * R, z, x * x + y * y];
    };
    const hidden = (p) => p[2] < 0 && p[3] < 1;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";

    // atmosphere
    let g = ctx.createRadialGradient(cx, cy, R * 0.7, cx, cy, R * 1.35);
    g.addColorStop(0, rgba(0)); g.addColorStop(0.72, rgba(0.13)); g.addColorStop(1, rgba(0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 1.35, 0, Math.PI * 2); ctx.fill();
    g = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, 0, cx, cy, R);
    g.addColorStop(0, rgba(0.1)); g.addColorStop(1, rgba(0.015));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = rgba(0.55); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();

    // decorative rings (eDEX style)
    ctx.save(); ctx.translate(cx, cy);
    ctx.rotate(t * 0.15);
    const rs = ringSprite(R, rgba, [Math.round(R), dpr, col[0] >> 3, col[1] >> 3, col[2] >> 3].join(","));
    ctx.drawImage(rs, -rs._half, -rs._half, rs._half * 2, rs._half * 2);
    ctx.rotate(-t * 0.45);
    ctx.strokeStyle = rgba(0.6); ctx.lineWidth = 2; ctx.beginPath();
    for (const [s, l] of [[0, .16], [.33, .1], [.5, .2], [.83, .07]]) {
      ctx.moveTo(Math.cos(s * Math.PI * 2) * R * 1.07, Math.sin(s * Math.PI * 2) * R * 1.07);
      ctx.arc(0, 0, R * 1.07, s * Math.PI * 2, (s + l) * Math.PI * 2);
    }
    ctx.stroke();
    ctx.restore();

    // graticule (front faint, back very faint)
    ctx.lineWidth = 0.6;
    for (const front of [false, true]) {
      ctx.beginPath();
      for (const line of GRAT) {
        let prev = null;
        for (const v of line) {
          const p = P(v);
          if (prev && (p[2] > 0) === front) { ctx.moveTo(prev[0], prev[1]); ctx.lineTo(p[0], p[1]); }
          prev = p;
        }
      }
      ctx.strokeStyle = rgba(front ? 0.16 : 0.035); ctx.stroke();
    }

    // land dots
    for (let b = 0; b < GB; b++) GBUCK[b].length = 0;
    ctx.beginPath();
    for (let i = 0; i < DOTS.length; i++) {
      const p = P(DOTS[i]);
      if (p[2] <= 0) { if (i % 3 === 0) ctx.rect(p[0], p[1], 1, 1); continue; }
      GBUCK[Math.min(GB - 1, (p[2] * GB) | 0)].push(p[0], p[1], 0.9 + p[2] * 1.1);
    }
    ctx.fillStyle = rgba(0.06); ctx.fill();
    for (let b = 0; b < GB; b++) {
      const L = GBUCK[b]; if (!L.length) continue;
      ctx.fillStyle = rgba(0.25 + ((b + 0.5) / GB) * 0.75); ctx.beginPath();
      for (let j = 0; j < L.length; j += 3) { const s = L[j + 2]; ctx.rect(L[j] - s / 2, L[j + 1] - s / 2, s, s); }
      ctx.fill();
    }

    // hubs
    ctx.font = "7px SF Mono, Menlo, monospace"; ctx.textAlign = "left";
    for (const h of HUBS) {
      const p = P(h.v); if (p[2] <= 0) continue;
      ctx.fillStyle = rgba(0.5 + p[2] * 0.5);
      ctx.beginPath(); ctx.arc(p[0], p[1], h.main ? 2.2 : 1.5, 0, Math.PI * 2); ctx.fill();
      if (p[2] > 0.35) { ctx.fillStyle = rgba(0.25 + p[2] * 0.4); ctx.fillText(h.main ? "SFO" : h.name, p[0] + 4, p[1] - 3); }
    }

    // network arcs: idle traffic to random hubs, permanent uplink to Anthropic while working
    nextArc -= dt;
    if (nextArc <= 0) {
      nextArc = 1.6 + Math.random() * 2.6;
      const h = HUBS[1 + Math.floor(Math.random() * (HUBS.length - 1))];
      arcs.push({ hub: h, born: t, life: 3.6 });
    }
    for (let i = arcs.length - 1; i >= 0; i--) if (t - arcs[i].born > arcs[i].life) arcs.splice(i, 1);
    const drawArc = (pts, head, alpha, width) => {
      const n = Math.floor(head * (pts.length - 1));
      if (n < 1) return;
      ctx.lineWidth = width;
      const proj = []; for (let i = 0; i <= n; i++) proj.push(P(pts[i]));
      const CH = 4;
      for (let c = 0; c < CH; c++) {
        const i0 = Math.floor((c * n) / CH), i1 = Math.floor(((c + 1) * n) / CH);
        ctx.beginPath();
        for (let i = Math.max(1, i0); i <= i1; i++) {
          const a = proj[i - 1], b = proj[i];
          if (!hidden(a) && !hidden(b)) { ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
        }
        ctx.strokeStyle = rgba(alpha * (0.35 + 0.65 * ((c + 1) / CH))); ctx.stroke();
      }
    };
    const packet = (pts, s, size) => {
      const p = P(pts[Math.min(pts.length - 1, Math.max(0, Math.round(s * (pts.length - 1))))]);
      if (hidden(p)) return;
      ctx.fillStyle = "rgba(255,255,255,0.95)"; ctx.beginPath(); ctx.arc(p[0], p[1], size, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(0.35); ctx.beginPath(); ctx.arc(p[0], p[1], size * 3, 0, Math.PI * 2); ctx.fill();
    };
    for (const a of arcs) {
      const age = t - a.born, head = Math.min(1, age / 1.1), fade = Math.min(1, (a.life - age) / 1.2);
      drawArc(a.hub.arc, head, 0.7 * fade, 1);
      if (head < 1) packet(a.hub.arc, head, 1.3);
    }
    const main = HUBS[0];
    if (busy) {
      drawArc(main.arc, 1, 1, 1.6);
      for (let k = 0; k < 3; k++) {
        let s = ((t * 0.9 + k / 3) % 1);
        if (state === "speaking") s = 1 - s;               // reply flowing back home
        packet(main.arc, s, 1.6);
      }
    }

    // home marker (orange accent, pulsing)
    const hp = P(HOME.v);
    if (hp[2] > 0) {
      const pulse = (t * 0.8) % 1;
      ctx.strokeStyle = `rgba(255,138,31,${0.9 * (1 - pulse)})`; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(hp[0], hp[1], 3 + pulse * 14, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = "rgba(255,170,80,1)"; ctx.beginPath(); ctx.arc(hp[0], hp[1], 2.6, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "rgba(255,138,31,0.7)"; ctx.lineWidth = 0.8;
      ctx.beginPath(); ctx.moveTo(hp[0] - 9, hp[1]); ctx.lineTo(hp[0] - 5, hp[1]); ctx.moveTo(hp[0] + 5, hp[1]); ctx.lineTo(hp[0] + 9, hp[1]);
      ctx.moveTo(hp[0], hp[1] - 9); ctx.lineTo(hp[0], hp[1] - 5); ctx.moveTo(hp[0], hp[1] + 5); ctx.lineTo(hp[0], hp[1] + 9); ctx.stroke();
      ctx.fillStyle = "rgba(255,170,80,0.9)"; ctx.fillText("HOME", hp[0] + 8, hp[1] + 11);
    }
    ctx.globalCompositeOperation = "source-over";

    // readouts (throttled)
    if (t - lastUi > 0.2) {
      lastUi = t;
      let lon = (-rot / D) % 360; if (lon > 180) lon -= 360; if (lon < -180) lon += 360;
      const el = (id) => document.getElementById(id);
      if (el("geo-rot")) el("geo-rot").textContent = (lon < 0 ? "W " : "E ") + Math.abs(lon).toFixed(1).padStart(5, "0") + "°";
      if (el("geo-links")) el("geo-links").textContent = "LINK " + String(arcs.length + (busy ? 1 : 0)).padStart(2, "0");
      if (el("geo-uplink")) el("geo-uplink").textContent = "ANTHROPIC // " + (state === "thinking" ? "TX" : state === "speaking" ? "RX" : "IDLE");
    }
  }

  window.Globe = {
    init(canvas) {
      cv = canvas; ctx = cv.getContext("2d");
      resize();
      window.addEventListener("resize", resize);
      if (window.ResizeObserver) new ResizeObserver(resize).observe(cv);
    },
    draw,
  };
})();
