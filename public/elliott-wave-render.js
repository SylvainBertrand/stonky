// Elliott Wave Chart Overlay Renderer
// Renders wave labels, target price lines, and invalidation lines on LightweightCharts

/**
 * Add Elliott Wave visual overlays to the main chart.
 *
 * @param {object} chart - LightweightCharts IChartApi instance
 * @param {Array} quotes - OHLCV data array
 * @param {object} analysis - Result from analyzeElliottWave()
 * @param {object} theme - T color theme object from app.js
 * @returns {{ remove: () => void }}
 */
export function renderElliottWave(chart, quotes, analysis, theme) {
  const cleanups = [];

  if (!analysis || !analysis.scenarios || analysis.scenarios.length === 0) {
    return { remove: () => {} };
  }

  const scenario = analysis.scenarios[0];
  if (!scenario) return { remove: () => {} };

  // Get the price series (candlestick or line) — we need to attach markers to it
  // LightweightCharts v4: we add a transparent line series for markers if needed
  // Actually, we create a separate line series just to host the wave markers
  const markerSeries = chart.addLineSeries({
    color: 'transparent',
    lineWidth: 0,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });

  // Set invisible data spanning the full range so markers attach correctly
  const markerData = quotes.map(q => ({ time: q.time, value: q.close }));
  markerSeries.setData(markerData);
  cleanups.push(() => { try { chart.removeSeries(markerSeries); } catch {} });

  // Build markers from wave endpoints
  const markers = buildWaveMarkers(scenario, quotes, theme);
  if (markers.length > 0) {
    markerSeries.setMarkers(markers);
  }

  // Add swing point markers (subtle dots for debugging/context)
  if (analysis.swingPoints && analysis.swingPoints.length > 0) {
    const swingMarkers = buildSwingMarkers(analysis.swingPoints, quotes, theme);
    // We add swing markers to a separate series to avoid overwriting wave markers
    const swingSeries = chart.addLineSeries({
      color: 'transparent',
      lineWidth: 0,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    swingSeries.setData(markerData);
    if (swingMarkers.length > 0) swingSeries.setMarkers(swingMarkers);
    cleanups.push(() => { try { chart.removeSeries(swingSeries); } catch {} });
  }

  // Add price lines for targets and invalidations
  // We need a reference to the price series — use the marker series for price lines
  const priceLines = [];

  for (const target of scenario.targets) {
    if (!isFinite(target.price)) continue;
    const alpha = target.confidence === 'primary' ? 'cc' : target.confidence === 'secondary' ? '80' : '50';
    try {
      const pl = markerSeries.createPriceLine({
        price: target.price,
        color: theme.green + alpha,
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: shortenLabel(target.label),
      });
      priceLines.push({ series: markerSeries, line: pl });
    } catch {}
  }

  for (const inv of scenario.invalidationLevels) {
    if (!isFinite(inv.price)) continue;
    const color = inv.severity === 'hard' ? theme.red + 'cc' : theme.yellow + '80';
    const style = inv.severity === 'hard'
      ? LightweightCharts.LineStyle.Dotted
      : LightweightCharts.LineStyle.Dashed;
    try {
      const pl = markerSeries.createPriceLine({
        price: inv.price,
        color,
        lineWidth: 1,
        lineStyle: style,
        axisLabelVisible: true,
        title: inv.severity === 'hard' ? '✕ Invalidation' : '⚠ Soft',
      });
      priceLines.push({ series: markerSeries, line: pl });
    } catch {}
  }

  cleanups.push(() => {
    for (const { series, line } of priceLines) {
      try { series.removePriceLine(line); } catch {}
    }
  });

  return {
    remove() {
      for (const fn of cleanups) fn();
    }
  };
}

function buildWaveMarkers(scenario, quotes, theme) {
  const markers = [];
  const { waves, direction } = scenario;
  if (!waves || waves.length === 0) return markers;

  // Add start of first wave
  const firstWave = waves[0];
  const startQ = quotes[firstWave.startIndex];
  if (startQ) {
    const bullish = direction === 'bullish';
    markers.push({
      time: startQ.time,
      position: bullish ? 'belowBar' : 'aboveBar',
      color: theme.sub,
      shape: 'circle',
      text: '0',
      size: 0.5,
    });
  }

  // Add end of each wave
  for (const wave of waves) {
    const q = quotes[wave.endIndex];
    if (!q) continue;

    const isImpulse = ['1', '3', '5'].includes(wave.label);
    const isCorrectiveImpulse = wave.label === 'A' || wave.label === 'C';
    const isUp = wave.endPrice > wave.startPrice;

    // Position: label above bar for swing highs, below for swing lows
    const position = isUp ? 'aboveBar' : 'belowBar';
    const color = isImpulse || isCorrectiveImpulse
      ? (isUp ? theme.green : theme.red)
      : theme.accent;

    markers.push({
      time: q.time,
      position,
      color,
      shape: 'circle',
      text: wave.label,
      size: 1,
    });
  }

  // Sort markers by time (required by LightweightCharts)
  markers.sort((a, b) => {
    const ta = typeof a.time === 'string' ? a.time : String(a.time);
    const tb = typeof b.time === 'string' ? b.time : String(b.time);
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });

  // Remove duplicate times (keep last)
  const seen = new Map();
  for (const m of markers) {
    const key = typeof m.time === 'string' ? m.time : String(m.time);
    seen.set(key, m);
  }

  return Array.from(seen.values());
}

function buildSwingMarkers(swingPoints, quotes, theme) {
  const markers = [];
  for (const sp of swingPoints) {
    const q = quotes[sp.index];
    if (!q) continue;
    markers.push({
      time: q.time,
      position: sp.type === 'HIGH' ? 'aboveBar' : 'belowBar',
      color: theme.border,
      shape: sp.type === 'HIGH' ? 'arrowDown' : 'arrowUp',
      text: '',
      size: 0.3,
    });
  }

  // Sort by time
  markers.sort((a, b) => {
    const ta = typeof a.time === 'string' ? a.time : String(a.time);
    const tb = typeof b.time === 'string' ? b.time : String(b.time);
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });

  // Deduplicate
  const seen = new Map();
  for (const m of markers) {
    const key = typeof m.time === 'string' ? m.time : String(m.time);
    if (!seen.has(key)) seen.set(key, m);
  }

  return Array.from(seen.values());
}

function shortenLabel(label) {
  // Keep label short for price axis
  return label.length > 20 ? label.slice(0, 20) + '…' : label;
}
