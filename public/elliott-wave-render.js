// Elliott Wave Chart Overlay — Dual-Count Professional Visualization
// Uses LightweightCharts from global scope (no imports needed)

/**
 * Render dual Elliott Wave counts on the main chart.
 *
 * @param {IChartApi} chart - LightweightCharts main chart instance
 * @param {ISeriesApi} priceSeries - The main price series (candlestick or line)
 * @param {Array} quotes - OHLCV data array
 * @param {object} analysis - Result from analyzeElliottWave()
 * @param {object} theme - T color theme object
 * @returns {{ remove: () => void }}
 */
export function renderElliottWave(chart, priceSeries, quotes, analysis, theme) {
  if (!analysis?.scenarios?.length || !quotes?.length) {
    return { remove: () => {} };
  }

  const allSeries     = [];   // LW series added to chart
  const allPriceLines = [];   // price lines added to priceSeries
  const cleanups      = [];   // arbitrary teardown fns
  let legendEl        = null;

  const s1 = analysis.scenarios[0];
  const s2 = analysis.scenarios[1] ?? null;

  // ── Color assignment ──────────────────────────────────────────────────────
  // Bullish counts = green, bearish = red.
  // If both scenarios share the same direction, use blue/yellow as alternate.
  const c1 = s1.direction === 'bullish' ? theme.green : theme.red;
  let c2 = null;
  if (s2) {
    if (s2.direction === s1.direction) {
      c2 = s2.direction === 'bullish' ? theme.blue : theme.yellow;
    } else {
      c2 = s2.direction === 'bullish' ? theme.green : theme.red;
    }
  }

  // ── 1. Wave path lines ────────────────────────────────────────────────────
  // Straight lines drawn only between swing turning points — the EW zigzag.
  const path1 = makeWavePath(chart, s1.waves, quotes, c1, true);
  if (path1) allSeries.push(path1);

  if (s2) {
    const path2 = makeWavePath(chart, s2.waves, quotes, c2, false);
    if (path2) allSeries.push(path2);
  }

  // ── 2. Wave label markers (on priceSeries) ────────────────────────────────
  const markers = [];
  gatherMarkers(markers, s1, quotes, c1);
  if (s2) gatherMarkers(markers, s2, quotes, c2);
  markers.sort((a, b) => cmpTime(a.time, b.time));
  try { priceSeries.setMarkers(markers); } catch {}
  cleanups.push(() => { try { priceSeries.setMarkers([]); } catch {}; });

  // ── 3. Fibonacci extension lines ──────────────────────────────────────────
  const priceExt = visibleRange(quotes);
  for (const [sc, col] of [[s1, c1], s2 ? [s2, c2] : null].filter(Boolean)) {
    for (const tgt of sc.targets ?? []) {
      if (!isFinite(tgt.price) || !inRange(tgt.price, priceExt)) continue;
      const opacity = tgt.confidence === 'primary' ? 'cc'
                    : tgt.confidence === 'secondary' ? '88' : '44';
      try {
        allPriceLines.push(priceSeries.createPriceLine({
          price: tgt.price,
          color: col + opacity,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Solid,
          axisLabelVisible: true,
          title: fibTitle(tgt),
        }));
      } catch {}
    }
  }

  // ── 4. Invalidation levels + shaded band ─────────────────────────────────
  for (const inv of s1.invalidationLevels ?? []) {
    if (!isFinite(inv.price)) continue;
    const hard = inv.severity === 'hard';
    const col  = hard ? theme.red : theme.yellow;
    try {
      allPriceLines.push(priceSeries.createPriceLine({
        price: inv.price,
        color: col + (hard ? 'aa' : '55'),
        lineWidth: hard ? 2 : 1,
        lineStyle: hard ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: hard ? '⛔ Invalidation' : '⚠ Caution',
      }));
    } catch {}

    // Shaded area below / above the invalidation line for hard levels
    if (hard) {
      const band = makeInvalidationBand(chart, quotes, inv.price, col);
      if (band) allSeries.push(band);
    }
  }

  // ── 5. Projected future path ──────────────────────────────────────────────
  const proj = s1.projectedWaves;
  if (proj?.length) {
    const projSeries = makeProjection(chart, quotes, proj, c1);
    if (projSeries) {
      allSeries.push(projSeries);
      // Add right-side breathing room so future bars are visible
      try { chart.timeScale().applyOptions({ rightOffset: 25 }); } catch {}
      cleanups.push(() => {
        try { chart.timeScale().applyOptions({ rightOffset: 0 }); } catch {};
      });
    }
  }

  // ── 6. Legend overlay ─────────────────────────────────────────────────────
  const container = document.getElementById('main-chart');
  if (container) {
    legendEl = makeLegend(s1, s2, c1, c2, theme);
    container.style.position = 'relative';
    container.appendChild(legendEl);
  }

  return {
    remove() {
      allPriceLines.forEach(pl => { try { priceSeries.removePriceLine(pl); } catch {}; });
      allSeries.forEach(s  => { try { chart.removeSeries(s);            } catch {}; });
      cleanups.forEach(fn  => fn());
      if (legendEl?.parentNode) legendEl.remove();
      legendEl = null;
    },
  };
}

// ── Wave path ─────────────────────────────────────────────────────────────
// Creates a LineSeries with data ONLY at the swing turning points.
// LightweightCharts draws straight lines between them → the EW zigzag.
function makeWavePath(chart, waves, quotes, color, isPrimary) {
  if (!waves?.length) return null;

  const pts = [];

  // Origin (start of first wave)
  const fw = waves[0];
  if (quotes[fw.startIndex]) {
    pts.push({ time: quotes[fw.startIndex].time, value: fw.startPrice });
  }

  // End of each wave segment
  for (const w of waves) {
    if (quotes[w.endIndex]) {
      pts.push({ time: quotes[w.endIndex].time, value: w.endPrice });
    }
  }

  const clean = dedupTime(pts.sort((a, b) => cmpTime(a.time, b.time)));
  if (clean.length < 2) return null;

  try {
    const s = chart.addLineSeries({
      color,
      lineWidth: isPrimary ? 2 : 1.5,
      lineStyle: isPrimary
        ? LightweightCharts.LineStyle.Solid
        : LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    s.setData(clean);
    return s;
  } catch { return null; }
}

// ── Wave label markers ────────────────────────────────────────────────────
function gatherMarkers(arr, scenario, quotes, color) {
  const { waves, direction } = scenario;
  if (!waves?.length) return;

  const bullish = direction === 'bullish';
  const fw = waves[0];

  // Origin dot (small, subdued)
  if (quotes[fw.startIndex]) {
    arr.push({
      time: quotes[fw.startIndex].time,
      position: bullish ? 'belowBar' : 'aboveBar',
      color: color + '70',
      shape: 'circle',
      text: '0',
      size: 0.5,
    });
  }

  // One marker per wave endpoint
  for (const wave of waves) {
    const q = quotes[wave.endIndex];
    if (!q) continue;
    const isUp = wave.endPrice > wave.startPrice;
    arr.push({
      time: q.time,
      position: isUp ? 'aboveBar' : 'belowBar',
      color,
      shape: 'circle',
      text: fmtLabel(wave.label, wave.degree),
      // Primary-degree labels render slightly larger
      size: wave.degree === 'primary' ? 1.5 : 1.0,
    });
  }
}

// Format wave label by Elliott Wave degree convention:
//   primary     → (1) (2) (A) (B)
//   intermediate → 1 2 A B         (plain)
//   minor        → i ii iii a b c  (lowercase / roman)
function fmtLabel(label, degree) {
  if (label === '0') return '0';
  if (degree === 'primary') return `(${label})`;
  if (degree === 'minor') {
    const n = parseInt(label);
    if (!isNaN(n) && n >= 1 && n <= 5) return ['i', 'ii', 'iii', 'iv', 'v'][n - 1];
    return String(label).toLowerCase();
  }
  return String(label); // intermediate: plain
}

// ── Invalidation band ────────────────────────────────────────────────────
// Area series spanning the full chart width, gradient-filled below the line.
function makeInvalidationBand(chart, quotes, price, color) {
  try {
    const s = chart.addAreaSeries({
      topColor:    color + '20',
      bottomColor: color + '08',
      lineColor:   color + '55',
      lineWidth: 1,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    s.setData([
      { time: quotes[0].time,                   value: price },
      { time: quotes[quotes.length - 1].time,   value: price },
    ]);
    return s;
  } catch { return null; }
}

// ── Projected future path ────────────────────────────────────────────────
// Dashed line extending right of current price showing expected wave path.
function makeProjection(chart, quotes, projectedWaves, color) {
  if (!projectedWaves?.length) return null;

  const lastQ    = quotes[quotes.length - 1];
  const interval = inferInterval(quotes);

  // Build points: current price → each projected turning point
  const pts = [{ time: lastQ.time, value: lastQ.close }];
  for (const pw of projectedWaves) {
    if (!isFinite(pw.targetPrice) || !(pw.estimatedBarsFromNow > 0)) continue;
    pts.push({
      time:  addBars(lastQ.time, pw.estimatedBarsFromNow, interval),
      value: pw.targetPrice,
    });
  }

  const clean = dedupTime(pts.sort((a, b) => cmpTime(a.time, b.time)));
  if (clean.length < 2) return null;

  try {
    const s = chart.addLineSeries({
      color: color + 'aa',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    s.setData(clean);

    // Add label markers at each projected turning point
    const mks = [];
    projectedWaves.forEach((pw, i) => {
      const pt = clean[i + 1]; // clean[0] = current price, clean[1..] = projections
      if (!pt) return;
      mks.push({
        time: pt.time,
        position: pw.direction === 'bullish' ? 'aboveBar' : 'belowBar',
        color: color + 'aa',
        shape: 'circle',
        text: fmtLabel(pw.label, pw.degree ?? 'intermediate'),
        size: 0.8,
      });
    });

    mks.sort((a, b) => cmpTime(a.time, b.time));
    if (mks.length) s.setMarkers(mks);

    return s;
  } catch { return null; }
}

// ── Legend ────────────────────────────────────────────────────────────────
function makeLegend(s1, s2, c1, c2, theme) {
  const el = document.createElement('div');
  el.style.cssText = [
    'position:absolute', 'top:8px', 'left:8px', 'z-index:10',
    `background:${theme.bg}ee`, 'padding:7px 12px', 'border-radius:6px',
    'font-size:11px', 'line-height:1.9', `color:${theme.text}`,
    `border:1px solid ${theme.border}`, 'pointer-events:none',
    'font-family:monospace', 'max-width:280px',
  ].join(';');

  const row = (col, s) =>
    `<div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">` +
    `<span style="color:${col};font-size:13px;">●</span> ` +
    `<b>${Math.round(s.confidence * 100)}%</b> — ${esc(s.label)}` +
    `</div>`;

  el.innerHTML =
    `<div style="color:${theme.sub};font-size:9px;letter-spacing:.8px;margin-bottom:2px;">ELLIOTT WAVE</div>` +
    row(c1, s1) +
    (s2 ? row(c2, s2) : '');

  return el;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function cmpTime(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0;
}

function dedupTime(sorted) {
  const out  = [];
  const seen = new Set();
  for (const p of sorted) {
    const k = String(p.time);
    if (!seen.has(k)) { seen.add(k); out.push(p); }
  }
  return out;
}

function visibleRange(quotes) {
  let lo = Infinity, hi = -Infinity;
  for (const q of quotes) {
    if (q.low  < lo) lo = q.low;
    if (q.high > hi) hi = q.high;
  }
  return { lo, hi, span: hi - lo };
}

function inRange(price, r) {
  return price >= r.lo - r.span * 1.5 && price <= r.hi + r.span * 1.5;
}

function fibTitle(tgt) {
  const pct = ((tgt.fibRatio ?? 1) * 100).toFixed(1);
  return `${pct}% (${tgt.price.toFixed(2)})`;
}

function inferInterval(quotes) {
  if (quotes.length < 2) return null;
  const a = quotes[quotes.length - 2].time;
  const b = quotes[quotes.length - 1].time;
  return (typeof b === 'number' && typeof a === 'number') ? b - a : null;
}

function addBars(time, bars, interval) {
  if (typeof time === 'string') {
    // ISO date — add calendar days (simple; skips no weekends deliberately)
    const d = new Date(time + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + bars);
    return d.toISOString().slice(0, 10);
  }
  return time + bars * (interval ?? 86400);
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
