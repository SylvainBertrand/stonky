// Technical indicator calculations – pure JS, no dependencies

export function sma(values, period) {
  return values.map((_, i) => {
    if (i < period - 1) return null;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    return sum / period;
  });
}

export function ema(values, period) {
  const k = 2 / (period + 1);
  const result = [];
  let prev = null;
  for (const v of values) {
    if (v == null) { result.push(null); continue; }
    prev = prev === null ? v : v * k + prev * (1 - k);
    result.push(prev);
  }
  return result;
}

export function bollingerBands(values, period = 20, numStd = 2) {
  const mid = sma(values, period);
  return values.map((_, i) => {
    if (i < period - 1) return { upper: null, middle: null, lower: null };
    const slice = values.slice(i - period + 1, i + 1);
    const mean = mid[i];
    const variance = slice.reduce((s, v) => s + (v - mean) ** 2, 0) / period;
    const std = Math.sqrt(variance);
    return { upper: mean + numStd * std, middle: mean, lower: mean - numStd * std };
  });
}

export function rsi(values, period = 14) {
  const result = new Array(period).fill(null);
  let avgGain = 0, avgLoss = 0;

  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d > 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  result.push(100 - 100 / (1 + avgGain / (avgLoss || 1e-10)));

  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    result.push(100 - 100 / (1 + avgGain / (avgLoss || 1e-10)));
  }
  return result;
}

export function macd(values, fast = 12, slow = 26, signal = 9) {
  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);
  const macdLine = fastEma.map((f, i) => (f != null && slowEma[i] != null) ? f - slowEma[i] : null);
  const signalLine = ema(macdLine, signal);
  const histogram = macdLine.map((m, i) => (m != null && signalLine[i] != null) ? m - signalLine[i] : null);
  return { macdLine, signalLine, histogram };
}
