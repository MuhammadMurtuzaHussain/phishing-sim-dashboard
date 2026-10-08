(() => {
  'use strict';
  const root = document.documentElement;
  const D = JSON.parse(document.getElementById('data').textContent);
  const SVGNS = 'http://www.w3.org/2000/svg';
  const MINUS = '−';
  const NUDGES = D.nudges.filter(n => n.key !== 'none');

  // ---- formatting --------------------------------------------------------------------------
  const pct = (x, d = 1) => (x * 100).toFixed(d) + '%';
  const sgn = (x, d = 1) => { const v = +(x * 100).toFixed(d); return (v > 0 ? '+' : v < 0 ? MINUS : '') + Math.abs(v).toFixed(d); };
  const ciPct = e => pct(e.lo) + ' to ' + pct(e.hi);
  const ciPp = e => sgn(e.lo) + ' to ' + sgn(e.hi);
  const int = n => n.toLocaleString('en-IE');
  const tick = v => (v > 0 ? '+' : v < 0 ? MINUS : '') + Math.abs(v);

  // ---- DOM helpers (all text goes through textContent) ----------------------------------------
  function node(ns, tag, attrs, kids) {
    const e = ns ? document.createElementNS(ns, tag) : document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'text') e.textContent = v; else e.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids || []) e.append(c);
    return e;
  }
  const S = (tag, attrs, kids) => node(SVGNS, tag, attrs, kids);
  const H = (tag, attrs, kids) => node(null, tag, attrs, kids);

  // ---- scales and text measurement ----------------------------------------------------------
  const lin = (d0, d1, r0, r1) => v => r0 + (v - d0) * (r1 - r0) / (d1 - d0);
  function niceStep(span, target) {
    const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw - 1e-12);
  }
  function niceDomain(lo, hi, target) {
    const step = niceStep(hi - lo, target);
    return { lo: Math.floor(lo / step + 1e-9) * step, hi: Math.ceil(hi / step - 1e-9) * step, step };
  }
  function tickList(d) {
    const out = [];
    for (let v = d.lo; v <= d.hi + d.step / 1000; v += d.step) out.push(+v.toFixed(6));
    return out;
  }
  const mctx = document.createElement('canvas').getContext('2d');
  const tw = (s, size, weight) => {
    mctx.font = (weight || 400) + ' ' + size + 'px "Schibsted Grotesk", system-ui, sans-serif';
    return mctx.measureText(s).width;
  };

  // ---- tooltip -------------------------------------------------------------------------------
  const tipEl = H('div', { class: 'tip', role: 'status', hidden: true });
  document.body.append(tipEl);
  function setTip(title, rows, note) {
    tipEl.replaceChildren(H('div', { class: 'tip-title', text: title }));
    for (const r of rows) {
      const row = H('div', { class: 'tip-row' });
      if (r.key) row.append(H('span', { class: 'tip-key', style: '--k:' + r.key }));
      row.append(H('span', { class: 'tip-val', text: r.value }), H('span', { class: 'tip-lab', text: r.label }));
      tipEl.append(row);
    }
    if (note) tipEl.append(H('div', { class: 'tip-note', text: note }));
  }
  function placeTip(x, y) {
    tipEl.hidden = false;
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let left = x + 14, top = y + 14;
    if (left + w > innerWidth - 8) left = x - w - 14;
    if (top + h > innerHeight - 8) top = y - h - 14;
    tipEl.style.left = Math.max(8, left) + 'px';
    tipEl.style.top = Math.max(8, top) + 'px';
  }
  const hideTip = () => { tipEl.hidden = true; };
  function hover(target, build, key) {
    target.setAttribute('data-tip', '');
    const show = (x, y) => { build(); placeTip(x, y); if (key != null) activate(key); };
    target.addEventListener('pointerenter', e => show(e.clientX, e.clientY));
    target.addEventListener('pointermove', e => placeTip(e.clientX, e.clientY));
    target.addEventListener('pointerleave', e => { if (e.pointerType !== 'touch') { hideTip(); activate(null); } });
    target.addEventListener('focus', () => { const b = target.getBoundingClientRect(); show(b.left + b.width / 2, b.top + b.height / 2); });
    target.addEventListener('blur', () => { hideTip(); activate(null); });
  }
  document.addEventListener('pointerdown', e => { if (!e.target.closest('[data-tip]')) { hideTip(); activate(null); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { hideTip(); activate(null); } });

  function activate(key) {
    document.querySelectorAll('.is-active').forEach(e => e.classList.remove('is-active'));
    if (key == null) return;
    document.querySelectorAll('[data-key="' + CSS.escape(key) + '"]').forEach(e => e.classList.add('is-active'));
  }

  // ---- label placement for scatter plots ----------------------------------------------------
  // Each label tries a few rings of positions around its dot, cheapest first. Labels that end up
  // further out than the first ring get a thin leader line so they stay tied to their point.
  const DEGREES = [0, 180, -90, 90, -35, 215, 35, 145, -62, 242, 62, 118];
  function placeLabels(items, bounds, fixed) {
    const size = 13, h = 17;
    const boxes = fixed.slice();
    const area = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) *
                           Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
    const dotHit = (b, c) => {
      const nx = Math.max(b.x, Math.min(c.px, b.x + b.w)), ny = Math.max(b.y, Math.min(c.py, b.y + b.h));
      const d = Math.hypot(nx - c.px, ny - c.py), r = c.r + 3;
      return d < r ? (r - d) * 6 : 0;
    };
    const crowd = it => items.filter(o => o !== it && Math.hypot(o.px - it.px, o.py - it.py) < 90).length;
    for (const it of items.slice().sort((a, b) => crowd(b) - crowd(a))) {
      const w = tw(it.label, size, 580) + 2;
      let best = null;
      for (let ring = 0; ring < 5; ring++) {
        const d = it.r + 6 + ring * 15;
        DEGREES.forEach((deg, idx) => {
          const a = deg * Math.PI / 180, cx = Math.cos(a), cy = Math.sin(a);
          const anchor = cx > 0.5 ? 'start' : cx < -0.5 ? 'end' : 'middle';
          const x = anchor === 'start' ? it.px + cx * d : anchor === 'end' ? it.px + cx * d - w : it.px + cx * d - w / 2;
          const y = cy > 0.7 ? it.py + cy * d : cy < -0.7 ? it.py + cy * d - h : it.py + cy * d - h / 2;
          const box = { x, y, w, h };
          let cost = ring * 14 + idx * 0.6;
          if (x < bounds.l || x + w > bounds.r || y < bounds.t || y + h > bounds.b) cost += 5000;
          for (const b of boxes) cost += area(box, b) * 3;
          for (const o of items) cost += dotHit(box, o) * 20;
          if (!best || cost < best.cost) best = { cost, box, anchor, ring, cx, cy };
        });
      }
      boxes.push(best.box);
      it.la = best.anchor;
      it.lx = best.anchor === 'start' ? best.box.x : best.anchor === 'end' ? best.box.x + w : best.box.x + w / 2;
      it.ly = best.box.y + h / 2;
      const nx = Math.max(best.box.x, Math.min(it.px, best.box.x + w)), ny = Math.max(best.box.y, Math.min(it.py, best.box.y + h));
      const dx = nx - it.px, dy = ny - it.py, len = Math.hypot(dx, dy) || 1;
      if (len > it.r + 10) it.leader = [it.px + dx / len * (it.r + 1), it.py + dy / len * (it.r + 1), nx - dx / len * 3, ny - dy / len * 3];
    }
  }

  // ---- scatter ------------------------------------------------------------------------------------
  function scatter(o) {
    const { W, m } = o, Hh = o.height;
    const pw = W - m.l - m.r, ph = Hh - m.t - m.b;
    const px = lin(o.xd.lo, o.xd.hi, m.l, m.l + pw), py = lin(o.yd.lo, o.yd.hi, m.t + ph, m.t);
    const rx = px(o.ref.x), ry = py(o.ref.y);
    const svg = S('svg', { viewBox: '0 0 ' + W + ' ' + Hh, role: 'group', 'aria-label': o.aria, class: o.whiskers === 'hover' ? 'hw' : null });

    svg.append(
      S('rect', { class: 'wash-good', x: m.l, y: m.t, width: rx - m.l, height: ry - m.t }),
      S('rect', { class: 'wash-bad', x: rx, y: ry, width: m.l + pw - rx, height: m.t + ph - ry }));
    for (const v of tickList(o.xd)) {
      svg.append(S('line', { class: 'grid', x1: px(v), x2: px(v), y1: m.t, y2: m.t + ph }),
                 S('text', { class: 'tick', x: px(v), y: m.t + ph + 17, 'text-anchor': 'middle', text: o.xf(v) }));
    }
    for (const v of tickList(o.yd)) {
      svg.append(S('line', { class: 'grid', x1: m.l, x2: m.l + pw, y1: py(v), y2: py(v) }),
                 S('text', { class: 'tick', x: m.l - 8, y: py(v), 'text-anchor': 'end', 'dominant-baseline': 'central', text: o.yf(v) }));
    }
    svg.append(
      S('line', { class: 'axisline', x1: m.l, x2: m.l + pw, y1: m.t + ph, y2: m.t + ph }),
      S('line', { class: 'axisline', x1: m.l, x2: m.l, y1: m.t, y2: m.t + ph }),
      S('line', { class: 'axisline', x1: rx, x2: rx, y1: m.t, y2: m.t + ph }),
      S('line', { class: 'axisline', x1: m.l, x2: m.l + pw, y1: ry, y2: ry }));

    // Notes that sit on the plot are obstacles for the point labels.
    const fixed = [];
    const note = (cls, text, x, y, anchor) => {
      svg.append(S('text', { class: cls, x, y, 'text-anchor': anchor, text }));
      const w = tw(text, 12.5, 400);
      fixed.push({ x: anchor === 'end' ? x - w : x, y: y - 13, w, h: 16 });
    };
    note('quad', o.quad.tl, m.l + 8, m.t + 18, 'start');
    note('quad', o.quad.br, m.l + pw - 8, m.t + ph - 8, 'end');
    if (o.refNote) {
      note('refnote', o.refNote.x, rx + 6, m.t + 30, 'start');
      note('refnote', o.refNote.y, m.l + pw - 6, ry - 6, 'end');
    }
    if (o.origin) {
      svg.append(S('circle', { class: 'origin', cx: rx, cy: ry, r: 4.5 }));
      note('refnote', o.origin, rx + 9, ry + 17, 'start');
    }

    const items = o.items.map(it => Object.assign({}, it, { px: px(it.x), py: py(it.y) }));
    placeLabels(items, { l: m.l, t: m.t, r: m.l + pw, b: m.t + ph }, fixed);
    for (const it of items) {
      const g = S('g', { class: 'pt', tabindex: 0, role: 'img', 'aria-label': it.aria, 'data-key': it.key });
      const cap = 5;
      g.append(
        S('line', { class: 'whisker', x1: px(it.xl), x2: px(it.xh), y1: it.py, y2: it.py }),
        S('line', { class: 'whisker', x1: px(it.xl), x2: px(it.xl), y1: it.py - cap, y2: it.py + cap }),
        S('line', { class: 'whisker', x1: px(it.xh), x2: px(it.xh), y1: it.py - cap, y2: it.py + cap }),
        S('line', { class: 'whisker', x1: it.px, x2: it.px, y1: py(it.yl), y2: py(it.yh) }),
        S('line', { class: 'whisker', x1: it.px - cap, x2: it.px + cap, y1: py(it.yl), y2: py(it.yl) }),
        S('line', { class: 'whisker', x1: it.px - cap, x2: it.px + cap, y1: py(it.yh), y2: py(it.yh) }),
        ...(it.leader ? [S('line', { class: 'leader', x1: it.leader[0], y1: it.leader[1], x2: it.leader[2], y2: it.leader[3] })] : []),
        S('circle', { class: 'hit', cx: it.px, cy: it.py, r: Math.max(14, it.r + 8) }),
        S('circle', { class: 'dot', cx: it.px, cy: it.py, r: it.r }),
        S('text', { class: 'lbl', x: it.lx, y: it.ly, 'text-anchor': it.la, 'dominant-baseline': 'central', text: it.label }));
      hover(g, () => setTip(...o.tip(it)), it.key);
      svg.append(g);
    }
    svg.append(
      S('text', { class: 'axis-title', x: m.l + pw / 2, y: Hh - 6, 'text-anchor': 'middle', text: o.xTitle }),
      S('text', { class: 'axis-title', transform: 'translate(14 ' + (m.t + ph / 2) + ') rotate(-90)', 'text-anchor': 'middle', text: o.yTitle }));
    return svg;
  }

  function drawNudges(W) {
    const narrow = W < 520;
    const items = NUDGES.map(n => ({
      key: n.key, label: n.label, r: 6.5, n,
      x: n.d_click.est * 100, xl: n.d_click.lo * 100, xh: n.d_click.hi * 100,
      y: n.d_report.est * 100, yl: n.d_report.lo * 100, yh: n.d_report.hi * 100,
      aria: n.label + ': clicks ' + sgn(n.d_click.est) + ' points, reports ' + sgn(n.d_report.est) + ' points against no nudge',
    }));
    return scatter({
      W, height: Math.round(Math.max(360, Math.min(540, W * 0.82))),
      m: { t: 12, r: 14, b: 50, l: narrow ? 46 : 54 },
      xd: niceDomain(Math.min(0, ...items.map(i => i.xl)) - 0.5, Math.max(0, ...items.map(i => i.xh)) + 0.5, narrow ? 4 : 7),
      yd: niceDomain(Math.min(0, ...items.map(i => i.yl)) - 0.5, Math.max(0, ...items.map(i => i.yh)) + 0.5, narrow ? 5 : 7),
      ref: { x: 0, y: 0 }, origin: 'No nudge', xf: tick, yf: tick, items,
      quad: { tl: 'Fewer clicks, more reports', br: 'More clicks, fewer reports' },
      xTitle: narrow ? 'Change in click rate (points)' : 'Change in click rate against no nudge (percentage points)',
      yTitle: narrow ? 'Change in report rate (points)' : 'Change in report rate (percentage points)',
      aria: 'Scatter plot of each nudge: change in click rate across, change in report rate up, both against emails with no nudge. The table below lists every value.',
      tip: it => [it.n.label, [
        { value: sgn(it.n.d_click.est) + ' pp', label: 'clicks (' + ciPp(it.n.d_click) + ')' },
        { value: sgn(it.n.d_report.est) + ' pp', label: 'reports (' + ciPp(it.n.d_report) + ')' },
        { value: it.n.median_minutes_to_report.toFixed(0) + ' min', label: 'median time to report' },
      ], int(it.n.n) + ' emails, 95% intervals'],
    });
  }

  function drawDepartments(W) {
    const narrow = W < 520;
    const items = D.departments.map(d => ({
      key: d.name, label: d.name, r: 4.5 + Math.sqrt(d.employees / 220) * 5.5, d,
      x: d.click.est * 100, xl: d.click.lo * 100, xh: d.click.hi * 100,
      y: d.report.est * 100, yl: d.report.lo * 100, yh: d.report.hi * 100,
      aria: d.name + ': click rate ' + pct(d.click.est) + ', report rate ' + pct(d.report.est),
    }));
    return scatter({
      W, height: Math.round(Math.max(400, Math.min(580, W * 0.95))),
      m: { t: 12, r: 14, b: 50, l: narrow ? 46 : 54 },
      xd: niceDomain(0, Math.max(...items.map(i => i.xh)) + 1, narrow ? 4 : 7),
      yd: niceDomain(0, Math.max(...items.map(i => i.yh)) + 1, narrow ? 5 : 6),
      ref: { x: D.overall.click.est * 100, y: D.overall.report.est * 100 },
      refNote: { x: 'All staff ' + pct(D.overall.click.est), y: 'All staff ' + pct(D.overall.report.est) },
      xf: v => v + '%', yf: v => v + '%', items,
      quad: { tl: 'Click less, report more', br: 'Click more, report less' },
      whiskers: 'hover',
      xTitle: 'Click rate (share of emails)', yTitle: 'Report rate (share of emails)',
      aria: 'Scatter plot of departments: click rate across, report rate up. The table beside it lists every value.',
      tip: it => [it.d.name, [
        { value: pct(it.d.click.est), label: 'click rate (' + ciPct(it.d.click) + ')' },
        { value: pct(it.d.report.est), label: 'report rate (' + ciPct(it.d.report) + ')' },
        { value: it.d.median_minutes_to_report.toFixed(0) + ' min', label: 'median time to report' },
      ], int(it.d.employees) + ' employees, ' + int(it.d.n) + ' emails'],
    });
  }

  // ---- heatmaps ------------------------------------------------------------------------------------
  const EDGES = [1, 3, 6, 10];
  function stepOf(benefitPp) {
    const a = Math.abs(benefitPp);
    let k = 0;
    EDGES.forEach((e, i) => { if (a >= e) k = i + 1; });
    return k === 0 ? 'n' : (benefitPp > 0 ? 'b' : 'o') + k;
  }
  const cellFor = {};
  D.cells.forEach(c => { cellFor[c.department + '|' + c.nudge] = c; });

  function heatGrid(metric) {
    const box = H('div', { class: 'heat-wrap' });
    box.append(H('h3', {}, [metric === 'click' ? 'Clicks ' : 'Reports ',
      H('span', { text: metric === 'click' ? '(fewer is better)' : '(more is better)' })]));
    const grid = H('div', { class: 'heat', style: '--cols:' + NUDGES.length, role: 'group',
      'aria-label': 'Change in ' + metric + ' rate against no nudge, by department and nudge' });
    grid.append(H('div'));
    for (const n of NUDGES) grid.append(H('div', { class: 'hh', text: D.short[n.key] }));
    for (const dept of D.order) {
      const first = cellFor[dept + '|' + NUDGES[0].key];
      grid.append(H('div', { class: 'hr' }, [dept, H('small', { text: int(first.control_n) + ' control emails' })]));
      for (const n of NUDGES) {
        const c = cellFor[dept + '|' + n.key], d = c['d_' + metric];
        const sig = d.lo > 0 || d.hi < 0;
        const benefit = (metric === 'click' ? -d.est : d.est) * 100;
        const step = stepOf(benefit);
        const rate = metric === 'click' ? c.click.est : c.report.est;
        const ctrl = metric === 'click' ? c.control_click : c.control_report;
        const cell = H('button', {
          type: 'button', class: 'cell ' + (sig ? 'sig' : 'soft'),
          style: '--bg:var(--' + step + ');--fg:var(--' + step + '-ink)',
          'aria-label': dept + ', ' + n.label + ': ' + metric + ' rate ' + sgn(d.est) + ' points against no nudge' +
            (sig ? ', interval excludes zero' : ', interval includes zero'),
        }, [H('span', { text: sgn(d.est) })]);
        hover(cell, () => setTip(dept + ': ' + n.label, [
          { value: pct(rate), label: metric + ' rate with the nudge (' + int(c.n) + ' emails)' },
          { value: pct(ctrl), label: 'with no nudge (' + int(c.control_n) + ' emails)' },
          { value: sgn(d.est) + ' pp', label: 'change (' + ciPp(d) + ')' },
        ], sig ? 'The 95% interval excludes zero.' : 'The 95% interval includes zero, so this could be chance.'));
        grid.append(cell);
      }
    }
    box.append(grid);
    return box;
  }

  function drawHeats() {
    const legend = H('div', { class: 'heat-legend' });
    const scale = H('span', { class: 'scale', 'aria-hidden': 'true' });
    for (const s of ['o4', 'o3', 'o2', 'o1', 'n', 'b1', 'b2', 'b3', 'b4']) scale.append(H('i', { style: '--c:var(--' + s + ')' }));
    legend.append(H('span', { text: 'Worse than control' }), scale, H('span', { text: 'Better than control' }),
      H('span', { text: 'Colour steps at 1, 3, 6 and 10 points' }));
    return [legend, heatGrid('click'), heatGrid('report')];
  }

  // ---- campaigns ----------------------------------------------------------------------------------
  function wrap(text, width, size) {
    const lines = [];
    let line = '';
    for (const word of text.split(' ')) {
      const next = line ? line + ' ' + word : word;
      if (line && tw(next, size) > width) { lines.push(line); line = word; } else line = next;
    }
    if (line) lines.push(line);
    return lines;
  }

  function drawCampaigns(W) {
    const C = D.campaigns, narrow = W < 560;
    const m = { t: 40, r: narrow ? 18 : 104, b: narrow ? 48 : 86, l: 46 };
    const Hh = Math.round(Math.max(330, Math.min(440, W * 0.56))) + (narrow ? 0 : 0);
    const pw = W - m.l - m.r, ph = Hh - m.t - m.b, slot = pw / C.length;
    const yd = niceDomain(0, Math.max(...C.map(c => Math.max(c.click.hi, c.report.hi))) * 100 + 1, 6);
    const px = i => m.l + slot * (i + .5), py = lin(yd.lo, yd.hi, m.t + ph, m.t);
    const svg = S('svg', { viewBox: '0 0 ' + W + ' ' + Hh, role: 'group',
      'aria-label': 'Line chart of click rate and report rate for each of the six campaigns, with 95% bands. The table view lists every value.' });

    for (const v of tickList(yd)) {
      svg.append(S('line', { class: 'grid', x1: m.l, x2: m.l + pw, y1: py(v), y2: py(v) }),
                 S('text', { class: 'tick', x: m.l - 8, y: py(v), 'text-anchor': 'end', 'dominant-baseline': 'central', text: v + '%' }));
    }
    svg.append(S('line', { class: 'axisline', x1: m.l, x2: m.l + pw, y1: m.t + ph, y2: m.t + ph }));

    C.forEach((c, i) => {
      const month = new Date(c.date + 'T00:00:00Z').toLocaleString('en-IE', { month: 'short', timeZone: 'UTC' });
      const t = S('text', { class: 'xlab-id', x: px(i), y: m.t + ph + 18, 'text-anchor': 'middle' });
      t.append(c.id + ' ');
      t.append(S('tspan', { class: 'xlab', text: month }));
      svg.append(t);
      if (!narrow) {
        wrap(c.lure, slot - 10, 11.5).slice(0, 3).forEach((line, j) =>
          svg.append(S('text', { class: 'xlab', x: px(i), y: m.t + ph + 35 + j * 14, 'text-anchor': 'middle', text: line })));
      }
    });

    for (const key of ['click', 'report']) {
      const up = C.map((c, i) => px(i) + ',' + py(c[key].hi * 100));
      const lo = C.map((c, i) => px(i) + ',' + py(c[key].lo * 100)).reverse();
      svg.append(S('polygon', { class: 'band ' + key, points: up.concat(lo).join(' ') }));
    }
    for (const key of ['click', 'report']) {
      svg.append(S('polyline', { class: 'line ' + key, points: C.map((c, i) => px(i) + ',' + py(c[key].est * 100)).join(' ') }));
      C.forEach((c, i) => svg.append(S('circle', { class: 'mk ' + key, cx: px(i), cy: py(c[key].est * 100), r: 4.5 })));
    }

    // End labels sit in the right margin, nudged apart with short leaders so converging lines stay readable.
    if (!narrow) {
      const last = C[C.length - 1], i = C.length - 1;
      const rows = ['click', 'report'].map(k => ({ k, y: py(last[k].est * 100), text: (k === 'click' ? 'Clicks ' : 'Reports ') + pct(last[k].est) }))
        .sort((p, q) => p.y - q.y);
      const gap = 20;
      if (rows[1].y - rows[0].y < gap) {
        const mid = (rows[0].y + rows[1].y) / 2;
        rows[0].ly = mid - gap / 2; rows[1].ly = mid + gap / 2;
      } else rows.forEach(r => { r.ly = r.y; });
      for (const r of rows) {
        svg.append(
          S('line', { class: 'leader', x1: px(i) + 7, y1: r.y, x2: px(i) + 15, y2: r.ly }),
          S('text', { class: 'lbl', x: px(i) + 19, y: r.ly, 'text-anchor': 'start', 'dominant-baseline': 'central', text: r.text }));
      }
    }

    // Legend.
    const lg = S('g', { class: 'legend' });
    let x = m.l;
    for (const [key, text] of [['click', 'Click rate'], ['report', 'Report rate']]) {
      lg.append(S('line', { class: 'line ' + key, x1: x, x2: x + 18, y1: 14, y2: 14 }), S('text', { x: x + 25, y: 14, 'dominant-baseline': 'central', text }));
      x += 25 + tw(text, 12.5) + 22;
    }
    lg.append(S('rect', { class: 'band report', x, y: 8, width: 18, height: 12, rx: 2, style: 'opacity:.22' }),
              S('text', { x: x + 25, y: 14, 'dominant-baseline': 'central', text: '95% interval' }));
    svg.append(lg);

    C.forEach((c, i) => {
      const g = S('g', { class: 'slot', tabindex: 0, role: 'img',
        'aria-label': c.id + ', ' + c.lure + ': click rate ' + pct(c.click.est) + ', report rate ' + pct(c.report.est) });
      g.append(S('line', { class: 'xhair', x1: px(i), x2: px(i), y1: m.t, y2: m.t + ph }),
               S('rect', { class: 'hit', x: px(i) - slot / 2, y: m.t, width: slot, height: ph }));
      hover(g, () => setTip(c.id + ', ' + c.lure.toLowerCase(), [
        { key: 'var(--click)', value: pct(c.click.est), label: 'click rate (' + ciPct(c.click) + ')' },
        { key: 'var(--report)', value: pct(c.report.est), label: 'report rate (' + ciPct(c.report) + ')' },
      ], int(c.n) + ' emails, sent ' + c.date));
      svg.append(g);
    });
    return svg;
  }

  // ---- wiring ------------------------------------------------------------------------------------
  const regs = [];
  function register(id, draw) {
    const r = { el: document.getElementById(id), draw, width: 0 };
    regs.push(r);
    return r;
  }
  function render(r) {
    const w = Math.floor(r.el.getBoundingClientRect().width);
    if (!w || w === r.width) return;
    r.width = w;
    hideTip();
    r.el.replaceChildren(...[].concat(r.draw(w)));
  }

  function init() {
    register('chart-nudge', drawNudges);
    register('chart-dept', drawDepartments);
    register('chart-heat', drawHeats);
    register('chart-campaign', drawCampaigns);
    const ro = new ResizeObserver(() => regs.forEach(render));
    regs.forEach(r => { render(r); ro.observe(r.el); });

    document.querySelectorAll('.toggle').forEach(btn => btn.addEventListener('click', () => {
      const on = btn.closest('.fig').classList.toggle('show-table');
      btn.textContent = on ? 'Show as chart' : 'Show as table';
      btn.setAttribute('aria-pressed', on);
    }));
    document.querySelectorAll('tr[data-key]').forEach(tr => {
      tr.addEventListener('pointerenter', () => activate(tr.dataset.key));
      tr.addEventListener('pointerleave', () => activate(null));
    });

    const btn = document.getElementById('theme');
    const current = () => root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const label = () => { const dark = current() === 'dark'; btn.textContent = dark ? 'Light mode' : 'Dark mode'; btn.setAttribute('aria-pressed', dark); };
    try { const saved = localStorage.getItem('theme'); if (saved === 'dark' || saved === 'light') root.dataset.theme = saved; } catch (e) { /* storage unavailable */ }
    label();
    btn.addEventListener('click', () => {
      root.dataset.theme = current() === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('theme', root.dataset.theme); } catch (e) { /* storage unavailable */ }
      label();
    });
  }

  const fontsReady = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  Promise.race([fontsReady, new Promise(res => setTimeout(res, 1500))]).then(init);
})();
