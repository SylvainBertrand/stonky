import { sma, ema, bollingerBands, rsi, macd } from '/indicators.js';

// ── Theme ──────────────────────────────────────────────────────────────────
const T = {
  bg:      '#1e1e2e',
  surface: '#2a2a3e',
  border:  '#45475a',
  text:    '#cdd6f4',
  sub:     '#a6adc8',
  accent:  '#7c6af7',
  green:   '#a6e3a1',
  red:     '#f38ba8',
  yellow:  '#f9e2af',
  blue:    '#89b4fa',
  mauve:   '#cba6f7',
};

const BASE_CHART_OPTS = {
  layout: { background: { color: T.bg }, textColor: T.text },
  grid: { vertLines: { color: T.surface }, horzLines: { color: T.surface } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: T.border },
  timeScale: { borderColor: T.border, timeVisible: true },
  handleScroll: true,
  handleScale: true,
};

// ── State ──────────────────────────────────────────────────────────────────
const nameCache = new Map(); // symbol → company name
const historyCache = new Map(); // key -> history payload
const pendingHistoryRequests = new Map(); // key -> Promise<history payload>

let state = {
  period: '6mo',
  interval: '1d',
  chartType: 'candlestick',
  indicators: new Set(['volume']),
  currentSymbol: null,
  historyData: null,
  charts: {},          // { main, volume, rsi, macd }
  series: {},          // all LW series objects
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── API helpers ────────────────────────────────────────────────────────────
async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function showDashboard() {
  $('dashboard-view').classList.remove('hidden');
  $('chart-view').classList.add('hidden');
  destroyCharts();

  const grid = $('portfolio-grid');
  grid.innerHTML = '';

  let symbols;
  try { symbols = await api('/api/portfolio'); }
  catch { grid.innerHTML = '<p style="color:var(--red);padding:20px">Failed to load portfolio</p>'; return; }

  // Render skeleton cards first
  for (const sym of symbols) {
    const card = createCard(sym);
    grid.appendChild(card);
  }

  // Fetch all quotes in one batched request (server sequences them to avoid rate limiting)
  let quotes = [];
  try { quotes = await api(`/api/quotes?symbols=${symbols.join(',')}`); }
  catch { /* cards will show error state */ }

  quotes.forEach((q, i) => {
    const card = grid.children[i];
    if (q.error) {
      card.querySelector('.card-price').textContent = 'Error';
      card.querySelector('.card-price').className = 'card-price card-error';
      return;
    }
    nameCache.set(q.symbol, q.name);
    updateCard(card, q);
  });
}

function createCard(symbol) {
  const card = document.createElement('div');
  card.className = 'stock-card';
  card.innerHTML = `
    <div class="card-symbol">${symbol}</div>
    <div class="card-name">&nbsp;</div>
    <div class="card-price card-loading">Loading…</div>
    <div class="card-change">&nbsp;</div>
  `;
  card.addEventListener('click', () => openChart(symbol));
  return card;
}

function updateCard(card, q) {
  card.querySelector('.card-name').textContent = q.name;
  card.querySelector('.card-price').textContent = fmt(q.price, q.currency);
  card.querySelector('.card-price').className = 'card-price';
  const pct = q.changePercent ?? 0;
  const sign = pct >= 0 ? '+' : '';
  const cl = pct >= 0 ? 'up' : 'down';
  card.querySelector('.card-change').textContent = `${sign}${pct.toFixed(2)}%`;
  card.querySelector('.card-change').className = `card-change ${cl}`;
}

function fmt(price, currency) {
  if (price == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency ?? 'USD', minimumFractionDigits: 2 }).format(price);
}

// ── Chart view ─────────────────────────────────────────────────────────────
async function openChart(symbol) {
  state.currentSymbol = symbol;
  $('dashboard-view').classList.add('hidden');
  $('chart-view').classList.remove('hidden');
  $('chart-symbol').textContent = symbol;
  $('chart-name').textContent = nameCache.get(symbol) ?? '';
  $('chart-price-info').innerHTML = '';
  await loadChart();
}

function getHistoryKey(symbol, period, interval) {
  return `${symbol}:${period}:${interval}`;
}

async function getHistory(symbol, period, interval, { forceRefresh = false } = {}) {
  const key = getHistoryKey(symbol, period, interval);

  if (!forceRefresh && historyCache.has(key)) {
    return historyCache.get(key);
  }

  if (!forceRefresh && pendingHistoryRequests.has(key)) {
    return pendingHistoryRequests.get(key);
  }

  const request = (async () => {
    const params = new URLSearchParams({ period, interval });
    const data = await api(`/api/history/${symbol}?${params.toString()}`);
    historyCache.set(key, data);
    return data;
  })().finally(() => {
    pendingHistoryRequests.delete(key);
  });

  pendingHistoryRequests.set(key, request);
  return request;
}

function rerenderChartFromCurrentData() {
  if (!state.historyData) return;
  destroyCharts();
  renderCharts(state.historyData);
}

async function loadChart({ forceRefresh = false } = {}) {
  const sym = state.currentSymbol;
  showLoading(true);
  destroyCharts();

  let data;
  try {
    data = await getHistory(sym, state.period, state.interval, { forceRefresh });
  } catch (e) {
    showLoading(false);
    $('main-chart').innerHTML = `<p style="color:var(--red);padding:20px">Failed to load data: ${e.message}</p>`;
    return;
  }

  state.historyData = data;
  renderCharts(data);
  showLoading(false);
}

function showLoading(on) {
  $('chart-loading').style.display = on ? 'flex' : 'none';
}

// ── Chart rendering ────────────────────────────────────────────────────────
function renderCharts(data) {
  const quotes = data.quotes;
  const closes = quotes.map(q => q.close);
  const times  = quotes.map(q => q.time);

  // ── Main chart
  const mainEl = $('main-chart');
  const mainChart = LightweightCharts.createChart(mainEl, {
    ...BASE_CHART_OPTS,
    width: mainEl.clientWidth,
    height: mainEl.clientHeight,
  });

  let priceSeries;
  if (state.chartType === 'candlestick') {
    priceSeries = mainChart.addCandlestickSeries({
      upColor: T.green, downColor: T.red,
      borderUpColor: T.green, borderDownColor: T.red,
      wickUpColor: T.green, wickDownColor: T.red,
    });
    priceSeries.setData(quotes.map(q => ({ time: q.time, open: q.open, high: q.high, low: q.low, close: q.close })));
  } else {
    priceSeries = mainChart.addLineSeries({ color: T.accent, lineWidth: 2 });
    priceSeries.setData(quotes.map(q => ({ time: q.time, value: q.close })));
  }

  state.series.price = priceSeries;
  state.charts.main = mainChart;

  // Overlay indicators on main chart
  addOverlayIndicators(mainChart, quotes, closes, times);

  // Update price info on crosshair move
  mainChart.subscribeCrosshairMove(param => updatePriceInfo(param, quotes, data));

  // ── Sub-pane charts
  const allCharts = [mainChart];

  if (state.indicators.has('volume')) {
    const el = $('volume-chart');
    el.classList.remove('hidden');
    addPaneLabel(el, 'Volume');
    const chart = createSubChart(el, { rightPriceScale: { visible: false } });
    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    chart.priceScale('').applyOptions({ scaleMargins: { top: 0.1, bottom: 0 } });
    volSeries.setData(quotes.map(q => ({
      time: q.time,
      value: q.volume,
      color: q.close >= q.open ? T.green + '80' : T.red + '80',
    })));
    state.charts.volume = chart;
    state.series.volume = volSeries;
    allCharts.push(chart);
  }

  if (state.indicators.has('rsi')) {
    const el = $('rsi-chart');
    el.classList.remove('hidden');
    addPaneLabel(el, 'RSI (14)');
    const chart = createSubChart(el);
    const rsiVals = rsi(closes, 14);
    const rsiSeries = chart.addLineSeries({ color: T.mauve, lineWidth: 1.5, priceScaleId: 'right' });
    rsiSeries.setData(times.map((t, i) => rsiVals[i] != null ? { time: t, value: rsiVals[i] } : null).filter(Boolean));
    // Overbought/oversold lines
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
    state.charts.rsi = chart;
    allCharts.push(chart);
  }

  if (state.indicators.has('macd')) {
    const el = $('macd-chart');
    el.classList.remove('hidden');
    addPaneLabel(el, 'MACD (12,26,9)');
    const chart = createSubChart(el);
    const { macdLine, signalLine, histogram } = macd(closes);

    const histSeries = chart.addHistogramSeries({ color: T.blue + '80', priceScaleId: 'right' });
    histSeries.setData(times.map((t, i) => histogram[i] != null
      ? { time: t, value: histogram[i], color: histogram[i] >= 0 ? T.green + '80' : T.red + '80' }
      : null).filter(Boolean));

    const macdSeries = chart.addLineSeries({ color: T.blue, lineWidth: 1.5, priceScaleId: 'right' });
    macdSeries.setData(times.map((t, i) => macdLine[i] != null ? { time: t, value: macdLine[i] } : null).filter(Boolean));

    const sigSeries = chart.addLineSeries({ color: T.yellow, lineWidth: 1, priceScaleId: 'right' });
    sigSeries.setData(times.map((t, i) => signalLine[i] != null ? { time: t, value: signalLine[i] } : null).filter(Boolean));

    state.charts.macd = chart;
    allCharts.push(chart);
  }

  // Sync time scales across all sub-charts
  syncTimeScales(allCharts);

  // Fit content
  for (const c of allCharts) c.timeScale().fitContent();

  // Resize observer
  setupResizeObserver(allCharts);
}

function addOverlayIndicators(chart, quotes, closes, times) {
  if (state.indicators.has('sma20')) {
    addLineSeries(chart, times, sma(closes, 20), T.blue, 'SMA 20');
  }
  if (state.indicators.has('sma50')) {
    addLineSeries(chart, times, sma(closes, 50), T.yellow, 'SMA 50');
  }
  if (state.indicators.has('sma200')) {
    addLineSeries(chart, times, sma(closes, 200), T.red, 'SMA 200');
  }
  if (state.indicators.has('ema20')) {
    addLineSeries(chart, times, ema(closes, 20), T.mauve, 'EMA 20');
  }
  if (state.indicators.has('bb')) {
    const bands = bollingerBands(closes, 20);
    const upperData = times.map((t, i) => bands[i].upper != null ? { time: t, value: bands[i].upper } : null).filter(Boolean);
    const midData   = times.map((t, i) => bands[i].middle != null ? { time: t, value: bands[i].middle } : null).filter(Boolean);
    const lowerData = times.map((t, i) => bands[i].lower != null ? { time: t, value: bands[i].lower } : null).filter(Boolean);

    const s1 = chart.addLineSeries({ color: T.accent + '60', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed });
    s1.setData(upperData);
    const s2 = chart.addLineSeries({ color: T.accent, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed });
    s2.setData(midData);
    const s3 = chart.addLineSeries({ color: T.accent + '60', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed });
    s3.setData(lowerData);
  }
}

function addLineSeries(chart, times, values, color, title) {
  const series = chart.addLineSeries({ color, lineWidth: 1.5, title, priceLineVisible: false, lastValueVisible: false });
  series.setData(times.map((t, i) => values[i] != null ? { time: t, value: values[i] } : null).filter(Boolean));
  return series;
}

function createSubChart(el, extraOpts = {}) {
  return LightweightCharts.createChart(el, {
    ...BASE_CHART_OPTS,
    width: el.clientWidth,
    height: el.clientHeight,
    timeScale: { ...BASE_CHART_OPTS.timeScale, visible: false },
    ...extraOpts,
  });
}

function syncTimeScales(charts) {
  // Bidirectional sync of visible logical range
  charts.forEach((src, si) => {
    src.timeScale().subscribeVisibleLogicalRangeChange(range => {
      if (!range) return;
      charts.forEach((dst, di) => {
        if (di !== si) dst.timeScale().setVisibleLogicalRange(range);
      });
    });
  });
  // Show bottom axis only on main (first) chart – already handled by createSubChart
}

function addPaneLabel(el, text) {
  const label = document.createElement('div');
  label.className = 'pane-label';
  label.textContent = text;
  el.style.position = 'relative';
  el.appendChild(label);
}

function destroyCharts() {
  for (const c of Object.values(state.charts)) {
    try { c.remove(); } catch {}
  }
  state.charts = {};
  state.series = {};
  // Remove pane labels
  for (const id of ['volume-chart', 'rsi-chart', 'macd-chart']) {
    const el = $(id);
    el.classList.add('hidden');
    el.innerHTML = '';
  }
  $('main-chart').innerHTML = '';
}

// ── Price info panel ───────────────────────────────────────────────────────
function updatePriceInfo(param, quotes, meta) {
  const el = $('chart-price-info');
  let q = quotes[quotes.length - 1];
  if (param.time) {
    const found = quotes.find(r => r.time === param.time);
    if (found) q = found;
  }
  if (!q) return;

  const change = q.close - q.open;
  const changePct = (change / q.open) * 100;
  const sign = change >= 0 ? '+' : '';
  const cl = change >= 0 ? 'up' : 'down';

  el.innerHTML = `
    <span class="price">${q.close?.toFixed(2)} <small style="color:var(--sub)">${meta.currency ?? ''}</small></span>&nbsp;
    <span class="change ${cl}">${sign}${change.toFixed(2)} (${sign}${changePct.toFixed(2)}%)</span>
    <br><small style="color:var(--sub)">O ${q.open?.toFixed(2)} · H ${q.high?.toFixed(2)} · L ${q.low?.toFixed(2)}</small>
  `;
}

// ── Resize ─────────────────────────────────────────────────────────────────
function setupResizeObserver(charts) {
  const els = [$('main-chart'), $('volume-chart'), $('rsi-chart'), $('macd-chart')];
  const ro = new ResizeObserver(() => {
    charts.forEach((chart, i) => {
      if (i === 0) {
        const el = $('main-chart');
        chart.resize(el.clientWidth, el.clientHeight);
      } else {
        const el = els[i];
        if (el && !el.classList.contains('hidden')) {
          chart.resize(el.clientWidth, el.clientHeight);
        }
      }
    });
  });
  for (const el of [$('chart-area')]) ro.observe(el);
}

// ── Event listeners ────────────────────────────────────────────────────────
$('back-btn').addEventListener('click', showDashboard);

$('refresh-btn').addEventListener('click', showDashboard);

$('period-group').addEventListener('click', e => {
  const btn = e.target.closest('[data-period]');
  if (!btn) return;
  if (state.period === btn.dataset.period) return;
  state.period = btn.dataset.period;
  $('period-group').querySelectorAll('.btn-seg').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadChart();
});

$('type-group').addEventListener('click', e => {
  const btn = e.target.closest('[data-type]');
  if (!btn) return;
  if (state.chartType === btn.dataset.type) return;
  state.chartType = btn.dataset.type;
  $('type-group').querySelectorAll('.btn-seg').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  rerenderChartFromCurrentData();
});

$('interval-select').addEventListener('change', e => {
  state.interval = e.target.value;
  loadChart();
});

document.querySelectorAll('[data-indicator]').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.indicator;
    if (state.indicators.has(key)) {
      state.indicators.delete(key);
      btn.classList.remove('active');
    } else {
      state.indicators.add(key);
      btn.classList.add('active');
    }
    rerenderChartFromCurrentData();
  });
});

// ── Init ───────────────────────────────────────────────────────────────────
showDashboard();
