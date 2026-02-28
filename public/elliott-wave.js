// Elliott Wave Analysis Engine — pure JS, no dependencies
// Self-contained: includes its own ATR and all helper math

const CONFIG = {
  atrPeriod: 14,
  zigzagMultipliers: [0.5, 1.0, 2.0],

  maxCandidatesPerLevel: 200,
  minWaveBars: 3,
  allowDiagonals: true,
  allowComplexCorrections: false,

  fibTolerance: 0.05,
  fibRatios: [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618, 2.618, 4.236],

  scoringWeights: {
    wave3FibRatio:    0.20,
    wave5FibRatio:    0.10,
    wave2Retracement: 0.10,
    wave4Retracement: 0.10,
    alternation:      0.10,
    channelFit:       0.15,
    proportionality:  0.10,
    volumeConfirmation: 0.05,
    subwaveValidity:  0.10,
  },

  maxScenarios: 4,
  clusteringBarTolerance: 3,
  includeSoftInvalidation: true,
};

// ── ATR ────────────────────────────────────────────────────────────────────
function atr(quotes, period = 14) {
  const trs = [];
  for (let i = 0; i < quotes.length; i++) {
    const { high, low, close } = quotes[i];
    const prevClose = i > 0 ? quotes[i - 1].close : close;
    trs.push(Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose)));
  }
  // SMA of TR over period
  const result = new Array(Math.min(period - 1, trs.length)).fill(null);
  for (let i = period - 1; i < trs.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += trs[j];
    result.push(sum / period);
  }
  return result;
}

// ── Fibonacci helpers ──────────────────────────────────────────────────────
function nearestFibScore(ratio, idealRatios = CONFIG.fibRatios, tolerance = CONFIG.fibTolerance) {
  if (!isFinite(ratio) || ratio <= 0) return 0;
  let best = Infinity;
  for (const r of idealRatios) {
    best = Math.min(best, Math.abs(ratio - r));
  }
  return Math.max(0, 1 - best / tolerance);
}

function fibScore(ratio, idealRatios) {
  return nearestFibScore(ratio, idealRatios);
}

// ── Swing Point Detection ──────────────────────────────────────────────────
function detectSwingPoints(quotes, multiplier) {
  const atrVals = atr(quotes, CONFIG.atrPeriod);

  // Get median ATR (ignore nulls)
  const validAtrs = atrVals.filter(v => v != null);
  if (validAtrs.length === 0) return [];
  const medianAtr = validAtrs.sort((a, b) => a - b)[Math.floor(validAtrs.length / 2)];
  const threshold = medianAtr * multiplier;

  const swings = [];
  let trend = null; // 'up' or 'down'
  let extremeIdx = 0;
  let extremePrice = quotes[0].close;

  for (let i = 1; i < quotes.length; i++) {
    const h = quotes[i].high;
    const l = quotes[i].low;

    if (trend === null) {
      if (h - extremePrice >= threshold) {
        // Started moving up — extremeIdx was a low
        swings.push({ index: extremeIdx, price: quotes[extremeIdx].low, type: 'LOW' });
        trend = 'up';
        extremeIdx = i;
        extremePrice = h;
      } else if (extremePrice - l >= threshold) {
        // Started moving down — extremeIdx was a high
        swings.push({ index: extremeIdx, price: quotes[extremeIdx].high, type: 'HIGH' });
        trend = 'down';
        extremeIdx = i;
        extremePrice = l;
      } else {
        // No trend yet, track both extremes
        if (h > extremePrice) { extremeIdx = i; extremePrice = h; }
        if (l < extremePrice) { extremeIdx = i; extremePrice = l; }
      }
      continue;
    }

    if (trend === 'up') {
      if (h > extremePrice) { extremeIdx = i; extremePrice = h; }
      else if (extremePrice - l >= threshold) {
        swings.push({ index: extremeIdx, price: quotes[extremeIdx].high, type: 'HIGH' });
        trend = 'down';
        extremeIdx = i;
        extremePrice = l;
      }
    } else {
      if (l < extremePrice) { extremeIdx = i; extremePrice = l; }
      else if (h - extremePrice >= threshold) {
        swings.push({ index: extremeIdx, price: quotes[extremeIdx].low, type: 'LOW' });
        trend = 'up';
        extremeIdx = i;
        extremePrice = h;
      }
    }
  }

  // Add final point
  if (trend === 'up') {
    swings.push({ index: extremeIdx, price: quotes[extremeIdx].high, type: 'HIGH' });
  } else if (trend === 'down') {
    swings.push({ index: extremeIdx, price: quotes[extremeIdx].low, type: 'LOW' });
  }

  return enforceAlternation(swings, quotes);
}

function enforceAlternation(swings, quotes) {
  if (swings.length === 0) return swings;
  const result = [swings[0]];
  for (let i = 1; i < swings.length; i++) {
    const prev = result[result.length - 1];
    const curr = swings[i];
    if (curr.type === prev.type) {
      // Keep the more extreme one
      if (curr.type === 'HIGH') {
        if (curr.price > prev.price) result[result.length - 1] = curr;
      } else {
        if (curr.price < prev.price) result[result.length - 1] = curr;
      }
    } else {
      result.push(curr);
    }
  }
  return result;
}

// ── Hard Rules ─────────────────────────────────────────────────────────────
// Returns true if candidate is VALID (passes all hard rules)

function checkWave2Rule(w1Start, w1End, w2End) {
  // Wave 2 never retraces beyond Wave 1 origin
  const bullish = w1End.price > w1Start.price;
  if (bullish) return w2End.price > w1Start.price;
  else return w2End.price < w1Start.price;
}

function checkWave3NotShortest(w1Start, w1End, w2End, w3End, w4End, w5End) {
  if (!w5End) return true; // incomplete — can't check yet
  const w1Len = Math.abs(w1End.price - w1Start.price);
  const w3Len = Math.abs(w3End.price - w2End.price);
  const w5Len = Math.abs(w5End.price - w4End.price);
  return w3Len >= Math.min(w1Len, w5Len);
}

function checkWave4Rule(w1Start, w1End, w4End, allowDiagonal = false) {
  if (allowDiagonal) return true;
  const bullish = w1End.price > w1Start.price;
  if (bullish) return w4End.price > w1End.price;
  else return w4End.price < w1End.price;
}

function checkWave3ExceedsWave1(w1End, w3End, bullish) {
  if (bullish) return w3End.price > w1End.price;
  else return w3End.price < w1End.price;
}

function checkWaveDirections(w1Start, w1End, w2End, w3End, w4End, w5End) {
  const bullish = w1End.price > w1Start.price;
  // W2 must be opposite W1
  const w2Corr = bullish ? w2End.price < w1End.price : w2End.price > w1End.price;
  if (!w2Corr) return false;
  // W3 same as W1
  if (!checkWave3ExceedsWave1(w1End, w3End, bullish)) return false;
  // W4 opposite W1
  if (w4End) {
    const w4Corr = bullish ? w4End.price < w3End.price : w4End.price > w3End.price;
    if (!w4Corr) return false;
  }
  // W5 same as W1
  if (w5End && w4End) {
    const w5Impu = bullish ? w5End.price > w4End.price : w5End.price < w4End.price;
    if (!w5Impu) return false;
  }
  return true;
}

// ── Impulse Candidate Generation ───────────────────────────────────────────
function generateImpulseCandidates(swings, quotes, partial = false) {
  const candidates = [];
  if (swings.length < 3) return candidates;

  const minPoints = partial ? 3 : 6; // need at least 6 points for W0-W5 (6 swing points = 5 waves)

  for (let start = 0; start <= swings.length - minPoints; start++) {
    // Try windows of 6 swing points (W0, W1_end, W2_end, W3_end, W4_end, W5_end)
    const maxEnd = partial ? Math.min(start + 6, swings.length) : Math.min(start + 7, swings.length);
    for (let end = start + minPoints; end <= maxEnd; end++) {
      const seg = swings.slice(start, end);
      const candidate = tryBuildImpulse(seg, quotes, partial && end === start + minPoints);
      if (candidate) candidates.push(candidate);
    }
  }

  return candidates.slice(0, CONFIG.maxCandidatesPerLevel);
}

function tryBuildImpulse(seg, quotes, isPartial) {
  // seg[0]=origin, seg[1]=W1end, seg[2]=W2end, seg[3]=W3end, [seg[4]=W4end, seg[5]=W5end]
  if (seg.length < 4) return null;

  const [origin, w1e, w2e, w3e] = seg;
  const w4e = seg[4] ?? null;
  const w5e = seg[5] ?? null;

  // Determine direction
  const bullish = w1e.price > origin.price;

  // W1 and origin must alternate properly
  if (bullish && w1e.type !== 'HIGH') return null;
  if (!bullish && w1e.type !== 'LOW') return null;

  // Hard rule: wave directions
  if (!checkWaveDirections(origin, w1e, w2e, w3e, w4e, w5e)) return null;

  // Hard rule: Wave 2 never retraces beyond origin
  if (!checkWave2Rule(origin, w1e, w2e)) return null;

  // Hard rule: Wave 4 doesn't enter Wave 1 territory
  if (w4e && !checkWave4Rule(origin, w1e, w4e, false)) return null;

  // Hard rule: Wave 3 not shortest (only when all 5 waves present)
  if (w5e && !checkWave3NotShortest(origin, w1e, w2e, w3e, w4e, w5e)) return null;

  // Build wave segments
  const waves = [];
  const points = [origin, w1e, w2e, w3e];
  if (w4e) points.push(w4e);
  if (w5e) points.push(w5e);

  const labels = ['1', '2', '3', '4', '5'];
  for (let i = 0; i < points.length - 1; i++) {
    waves.push({
      label: labels[i],
      startIndex: points[i].index,
      endIndex: points[i + 1].index,
      startPrice: points[i].price,
      endPrice: points[i + 1].price,
      degree: 'intermediate',
    });
  }

  const completeWaves = w5e ? 5 : waves.length;
  const lastWave = waves[waves.length - 1];

  return {
    type: 'impulse',
    bullish,
    waves,
    origin,
    w1e, w2e, w3e,
    w4e: w4e ?? null,
    w5e: w5e ?? null,
    partial: !w5e,
    currentWave: w5e ? '5' : w4e ? '5' : w3e ? '4' : '3',
    completeWaves,
    lastIndex: (w5e ?? w4e ?? w3e ?? w2e ?? w1e).index,
  };
}

// ── Corrective Candidate Generation ───────────────────────────────────────
function generateCorrectiveCandidates(swings, quotes) {
  const candidates = [];
  if (swings.length < 3) return candidates;

  for (let start = 0; start <= swings.length - 3; start++) {
    const seg = swings.slice(start, start + 4); // A-origin, A-end, B-end, C-end
    if (seg.length < 3) continue;

    const candidate = tryBuildCorrective(seg, quotes);
    if (candidate) candidates.push(candidate);
  }

  return candidates.slice(0, CONFIG.maxCandidatesPerLevel);
}

function tryBuildCorrective(seg, quotes) {
  if (seg.length < 3) return null;
  const [origin, ae, be, ce] = seg;

  const bullishA = ae.price > origin.price;

  // B should retrace some of A but not exceed origin
  const bRetrace = Math.abs(be.price - ae.price) / Math.abs(ae.price - origin.price);

  // Detect subtype
  let subtype = 'zigzag';
  if (ce) {
    const cLen = Math.abs(ce.price - be.price);
    const aLen = Math.abs(ae.price - origin.price);

    // Flat: B retraces > 80% of A
    if (bRetrace > 0.8) {
      subtype = ce.price > ae.price ? 'expanded_flat' : 'flat';
    }
  }

  // Direction checks
  const aUp = ae.price > origin.price;
  if (be) {
    const bDown = be.price < ae.price;
    if (aUp && !bDown) return null;
    if (!aUp && bDown) return null;
  }

  const waves = [];
  const points = [origin, ae, be];
  if (ce) points.push(ce);

  const labels = ['A', 'B', 'C'];
  for (let i = 0; i < points.length - 1; i++) {
    waves.push({
      label: labels[i],
      startIndex: points[i].index,
      endIndex: points[i + 1].index,
      startPrice: points[i].price,
      endPrice: points[i + 1].price,
      degree: 'intermediate',
    });
  }

  return {
    type: 'corrective',
    subtype,
    bullish: !aUp, // corrective wave after a down A is part of a bullish larger pattern
    waves,
    origin,
    ae, be,
    ce: ce ?? null,
    partial: !ce,
    currentWave: ce ? 'C' : 'C',
    lastIndex: (ce ?? be ?? ae).index,
  };
}

// ── Scoring ────────────────────────────────────────────────────────────────
function scoreCandidate(candidate, quotes) {
  const W = CONFIG.scoringWeights;
  const breakdown = {};
  let total = 0;

  if (candidate.type === 'impulse') {
    const { w1e, w2e, w3e, w4e, w5e, origin, bullish } = candidate;

    // Wave 3 Fib ratio vs Wave 1
    const w1Len = Math.abs(w1e.price - origin.price);
    const w3Len = Math.abs(w3e.price - w2e.price);
    const w3Ratio = w1Len > 0 ? w3Len / w1Len : 0;
    breakdown.wave3FibRatio = fibScore(w3Ratio, [1.618, 2.618, 1.0, 2.0]);
    total += breakdown.wave3FibRatio * W.wave3FibRatio;

    // Wave 5 Fib ratio vs Wave 1
    if (w5e && w4e) {
      const w5Len = Math.abs(w5e.price - w4e.price);
      const w5Ratio = w1Len > 0 ? w5Len / w1Len : 0;
      breakdown.wave5FibRatio = fibScore(w5Ratio, [0.618, 1.0, 1.618]);
    } else {
      breakdown.wave5FibRatio = 0.5; // neutral if incomplete
    }
    total += breakdown.wave5FibRatio * W.wave5FibRatio;

    // Wave 2 retracement of Wave 1
    const w2Ret = w1Len > 0 ? Math.abs(w2e.price - w1e.price) / w1Len : 0;
    breakdown.wave2Retracement = fibScore(w2Ret, [0.5, 0.618, 0.382, 0.786]);
    total += breakdown.wave2Retracement * W.wave2Retracement;

    // Wave 4 retracement of Wave 3
    if (w4e) {
      const w4Ret = w3Len > 0 ? Math.abs(w4e.price - w3e.price) / w3Len : 0;
      breakdown.wave4Retracement = fibScore(w4Ret, [0.382, 0.236, 0.5]);
    } else {
      breakdown.wave4Retracement = 0.5;
    }
    total += breakdown.wave4Retracement * W.wave4Retracement;

    // Alternation: W2 vs W4 character
    breakdown.alternation = scoreAlternation(w1e, w2e, w3e, w4e, quotes);
    total += breakdown.alternation * W.alternation;

    // Channel fit
    breakdown.channelFit = scoreChannel(origin, w1e, w2e, w3e, w4e, w5e, bullish);
    total += breakdown.channelFit * W.channelFit;

    // Proportionality (time)
    breakdown.proportionality = scoreProportionality(candidate, quotes);
    total += breakdown.proportionality * W.proportionality;

    // Volume confirmation
    breakdown.volumeConfirmation = scoreVolume(candidate, quotes);
    total += breakdown.volumeConfirmation * W.volumeConfirmation;

    // Sub-wave validity (simplified)
    breakdown.subwaveValidity = 0.5; // placeholder
    total += breakdown.subwaveValidity * W.subwaveValidity;

  } else {
    // Corrective pattern — simpler scoring
    const { ae, be, ce, origin } = candidate;
    const aLen = Math.abs(ae.price - origin.price);
    breakdown.wave3FibRatio = 0.5;
    breakdown.wave5FibRatio = 0.5;

    // B retracement
    const bRet = aLen > 0 ? Math.abs(be.price - ae.price) / aLen : 0;
    breakdown.wave2Retracement = fibScore(bRet, [0.5, 0.618, 0.382, 0.786]);
    total += breakdown.wave2Retracement * W.wave2Retracement;

    // C vs A
    if (ce) {
      const cLen = Math.abs(ce.price - be.price);
      const cRatio = aLen > 0 ? cLen / aLen : 0;
      breakdown.wave4Retracement = fibScore(cRatio, [1.0, 0.618, 1.618]);
      total += breakdown.wave4Retracement * W.wave4Retracement;
    } else {
      breakdown.wave4Retracement = 0.5;
      total += 0.5 * W.wave4Retracement;
    }

    breakdown.alternation = 0.5;
    breakdown.channelFit = 0.5;
    breakdown.proportionality = 0.5;
    breakdown.volumeConfirmation = 0.5;
    breakdown.subwaveValidity = 0.5;

    total += 0.5 * (W.wave3FibRatio + W.wave5FibRatio + W.alternation + W.channelFit + W.proportionality + W.volumeConfirmation + W.subwaveValidity);
  }

  return { score: Math.min(1, Math.max(0, total)), breakdown };
}

function scoreAlternation(w1e, w2e, w3e, w4e, quotes) {
  if (!w4e) return 0.5;
  // Compare sharpness: retracement depth and number of bars
  const w1Len = Math.abs(w1e.price - w2e.price);
  const w3Len = Math.abs(w3e.price - w4e.price);
  const w2Bars = w2e.index - w1e.index;
  const w4Bars = w4e.index - w3e.index;

  if (w1Len === 0 || w3Len === 0) return 0.5;

  // W2 and W4 differ in retracement — one deep, one shallow
  const retRatio = Math.min(w1Len, w3Len) / Math.max(w1Len, w3Len);
  const barRatio = w2Bars > 0 && w4Bars > 0 ? Math.min(w2Bars, w4Bars) / Math.max(w2Bars, w4Bars) : 0.5;

  // High score if they differ significantly
  const retScore = 1 - retRatio;
  const barScore = 1 - barRatio;
  return (retScore + barScore) / 2;
}

function scoreChannel(origin, w1e, w2e, w3e, w4e, w5e, bullish) {
  if (!w4e || !w5e) return 0.5;
  // Draw line through W2 end and W4 end
  // Parallel line through W3 end
  // Score how close W5 end is to that parallel line

  const x1 = w2e.index, y1 = w2e.price;
  const x2 = w4e.index, y2 = w4e.price;
  if (x2 === x1) return 0.5;

  const slope = (y2 - y1) / (x2 - x1);
  // Channel line: through W3, same slope
  const channelAt = (x) => w3e.price + slope * (x - w3e.index);
  const predicted = channelAt(w5e.index);
  const actual = w5e.price;
  const w3Len = Math.abs(w3e.price - w2e.price);
  if (w3Len === 0) return 0.5;

  const err = Math.abs(actual - predicted) / w3Len;
  return Math.max(0, 1 - err * 3);
}

function scoreProportionality(candidate, quotes) {
  const { waves } = candidate;
  if (waves.length < 2) return 0.5;
  const lens = waves.map(w => w.endIndex - w.startIndex);
  const avg = lens.reduce((a, b) => a + b, 0) / lens.length;
  if (avg === 0) return 0.5;
  // Penalize extreme outliers
  const maxRatio = Math.max(...lens) / avg;
  return Math.max(0, 1 - (maxRatio - 2) * 0.2);
}

function scoreVolume(candidate, quotes) {
  if (!candidate.w3e || !candidate.w1e || !candidate.origin) return 0.5;
  const { origin, w1e, w2e, w3e } = candidate;

  const avgVolInWave = (a, b) => {
    const start = Math.min(a.index, b.index);
    const end = Math.max(a.index, b.index);
    if (end <= start) return 0;
    let sum = 0;
    for (let i = start; i <= end && i < quotes.length; i++) sum += quotes[i].volume ?? 0;
    return sum / (end - start + 1);
  };

  const vol1 = avgVolInWave(origin, w1e);
  const vol3 = avgVolInWave(w2e, w3e);
  if (vol1 === 0) return 0.5;

  // W3 should have higher volume than W1
  return vol3 > vol1 ? Math.min(1, vol3 / vol1 * 0.5) : 0.2;
}

// ── Clustering ─────────────────────────────────────────────────────────────
function clusterCandidates(scoredCandidates) {
  const clusters = [];
  const used = new Set();

  for (let i = 0; i < scoredCandidates.length; i++) {
    if (used.has(i)) continue;
    const c1 = scoredCandidates[i];
    const cluster = [i];
    used.add(i);

    for (let j = i + 1; j < scoredCandidates.length; j++) {
      if (used.has(j)) continue;
      const c2 = scoredCandidates[j];
      if (areSimilar(c1.candidate, c2.candidate)) {
        cluster.push(j);
        used.add(j);
      }
    }
    clusters.push(cluster);
  }

  // Pick best from each cluster
  return clusters.map(cluster => {
    const best = cluster.reduce((a, b) =>
      scoredCandidates[a].score >= scoredCandidates[b].score ? a : b
    );
    return scoredCandidates[best];
  });
}

function areSimilar(c1, c2) {
  if (c1.type !== c2.type) return false;
  if (c1.bullish !== c2.bullish) return false;
  const t = CONFIG.clusteringBarTolerance;
  // Compare last index and wave count
  if (Math.abs(c1.lastIndex - c2.lastIndex) > t) return false;
  if (c1.waves.length !== c2.waves.length) return false;
  return true;
}

// ── Projections ────────────────────────────────────────────────────────────
function computeProjections(candidate, quotes) {
  const targets = [];
  const validationLevels = [];
  const invalidationLevels = [];

  if (candidate.type === 'impulse') {
    const { origin, w1e, w2e, w3e, w4e, w5e, bullish, currentWave } = candidate;
    const w1Len = Math.abs(w1e.price - origin.price);

    if (!w5e) {
      // In wave 3 or 4 — project wave 3 targets
      if (!w4e) {
        const base = w2e.price;
        const dir = bullish ? 1 : -1;
        targets.push({
          price: base + dir * w1Len * 1.618,
          label: 'Wave 3 target (1.618 ext)',
          fibRatio: 1.618,
          confidence: 'primary',
        });
        targets.push({
          price: base + dir * w1Len * 2.618,
          label: 'Wave 3 target (2.618 ext)',
          fibRatio: 2.618,
          confidence: 'secondary',
        });
        targets.push({
          price: base + dir * w1Len * 1.0,
          label: 'Wave 3 min (1.0 ext)',
          fibRatio: 1.0,
          confidence: 'stretch',
        });

        // Validation: price breaks beyond W1 end
        validationLevels.push({
          price: w1e.price,
          condition: bullish ? 'above' : 'below',
          description: 'Price confirms Wave 3 impulse start',
        });

        // Hard invalidation: W2 retraces beyond origin
        invalidationLevels.push({
          price: origin.price,
          condition: bullish ? 'below' : 'above',
          description: 'Wave 2 exceeds Wave 1 origin — count invalid',
          severity: 'hard',
        });
      } else {
        // In wave 4, project wave 5 targets from w4e
        const base = w4e.price;
        const dir = bullish ? 1 : -1;
        targets.push({
          price: base + dir * w1Len * 0.618,
          label: 'Wave 5 target (0.618 ext)',
          fibRatio: 0.618,
          confidence: 'primary',
        });
        targets.push({
          price: base + dir * w1Len * 1.0,
          label: 'Wave 5 target (1.0 ext)',
          fibRatio: 1.0,
          confidence: 'secondary',
        });

        // Invalidation: W4 enters W1 territory
        invalidationLevels.push({
          price: w1e.price,
          condition: bullish ? 'below' : 'above',
          description: 'Wave 4 enters Wave 1 territory — count invalid',
          severity: 'hard',
        });

        if (CONFIG.includeSoftInvalidation) {
          const w3Len = Math.abs(w3e.price - w2e.price);
          const softLevel = bullish ? w3e.price - w3Len * 0.5 : w3e.price + w3Len * 0.5;
          invalidationLevels.push({
            price: softLevel,
            condition: bullish ? 'below' : 'above',
            description: 'Wave 4 retraces > 50% of Wave 3 — count weakened',
            severity: 'soft',
          });
        }
      }
    } else {
      // Wave 5 complete or in corrective after 5
      const w5Len = Math.abs(w5e.price - w4e.price);
      invalidationLevels.push({
        price: w4e.price,
        condition: bullish ? 'below' : 'above',
        description: 'Price breaks back below Wave 4 end — corrective may extend',
        severity: 'soft',
      });
    }
  } else {
    // Corrective
    const { origin, ae, be, ce, bullish } = candidate;
    const aLen = Math.abs(ae.price - origin.price);
    const dir = ae.price > origin.price ? -1 : 1; // corrective direction for C

    if (!ce) {
      const base = be.price;
      targets.push({
        price: base + dir * aLen * 1.0,
        label: 'Wave C target (1.0 ext of A)',
        fibRatio: 1.0,
        confidence: 'primary',
      });
      targets.push({
        price: base + dir * aLen * 1.618,
        label: 'Wave C target (1.618 ext of A)',
        fibRatio: 1.618,
        confidence: 'secondary',
      });
    }

    // Invalidation: B exceeds A origin (in zigzag)
    if (candidate.subtype === 'zigzag') {
      invalidationLevels.push({
        price: origin.price,
        condition: ae.price > origin.price ? 'above' : 'below',
        description: 'Wave B exceeds Wave A origin — zigzag invalid',
        severity: 'hard',
      });
    }
  }

  return { targets, validationLevels, invalidationLevels };
}

function buildNextMove(candidate, targets) {
  const { type, bullish, currentWave } = candidate;
  const dir = bullish ? 'up' : 'down';
  const oppDir = bullish ? 'down' : 'up';

  if (!targets.length) return 'Insufficient data for projection.';

  const primary = targets.find(t => t.confidence === 'primary');
  const p = primary ? `$${primary.price.toFixed(2)}` : 'next level';

  if (type === 'impulse') {
    if (!candidate.w4e) return `Continue ${dir} toward ${p} (Wave 3 extension), then pull back for Wave 4.`;
    if (!candidate.w5e) return `Pullback continues for Wave 4, then final ${dir} leg toward ${p} (Wave 5).`;
    return `Five-wave impulse may be complete. Expect corrective move ${oppDir}.`;
  } else {
    if (!candidate.ce) return `Corrective Wave C extends ${dir} toward ${p}.`;
    return `Corrective pattern may be complete. Watch for resumption of prior trend.`;
  }
}

// ── Scenario Label ─────────────────────────────────────────────────────────
function buildScenarioLabel(candidate) {
  const dir = candidate.bullish ? 'Bullish' : 'Bearish';
  if (candidate.type === 'impulse') {
    const waveNum = candidate.w5e ? '5-wave complete' : candidate.w4e ? 'Wave 4 correction' : 'Wave 3 in progress';
    return `${dir} Impulse — ${waveNum}`;
  } else {
    const sub = candidate.subtype === 'flat' ? 'Flat' : candidate.subtype === 'expanded_flat' ? 'Expanded Flat' : 'Zigzag';
    return `${dir} Corrective ${sub}`;
  }
}

function buildCurrentPosition(candidate) {
  if (candidate.type === 'impulse') {
    if (candidate.w5e) return 'Wave 5 complete';
    if (candidate.w4e) return 'Wave 4 correction';
    return 'Wave 3 in progress';
  }
  if (candidate.ce) return 'Wave C complete';
  return 'Wave C in progress';
}

// ── Main Export ────────────────────────────────────────────────────────────
/**
 * Run Elliott Wave analysis on OHLCV data.
 * @param {Array<{time, open, high, low, close, volume}>} quotes
 * @param {object} [options]
 * @returns {ElliottWaveResult}
 */
export function analyzeElliottWave(quotes, options = {}) {
  const cfg = { ...CONFIG, ...options };

  if (!quotes || quotes.length < 30) {
    return {
      scenarios: [],
      swingPoints: [],
      summary: 'Insufficient data for Elliott Wave analysis (need at least 30 bars).',
    };
  }

  // Step 1: Detect swing points at 3 granularity levels
  const [fineSwings, mediumSwings, coarseSwings] = cfg.zigzagMultipliers.map(m =>
    detectSwingPoints(quotes, m)
  );

  const primarySwings = mediumSwings;

  if (primarySwings.length < 4) {
    return {
      scenarios: [],
      swingPoints: primarySwings,
      summary: 'Not enough swing points detected. Try a longer time period.',
    };
  }

  // Step 2 & 3: Generate candidates with hard-rule filtering
  const impulseCandidates = generateImpulseCandidates(primarySwings, quotes, true);
  const correctiveCandidates = generateCorrectiveCandidates(primarySwings, quotes);

  const allCandidates = [...impulseCandidates, ...correctiveCandidates];

  if (allCandidates.length === 0) {
    return {
      scenarios: [],
      swingPoints: primarySwings,
      summary: 'No valid wave patterns found in current data.',
    };
  }

  // Step 4: Score all candidates
  const scored = allCandidates.map(c => {
    const { score, breakdown } = scoreCandidate(c, quotes);
    return { candidate: c, score, breakdown };
  });

  // Sort by score descending
  scored.sort((a, b) => b.score - a.score);

  // Step 5: Cluster and select top N
  const clustered = clusterCandidates(scored);
  clustered.sort((a, b) => b.score - a.score);

  const totalScore = clustered.reduce((s, c) => s + c.score, 0);
  const topN = clustered.slice(0, cfg.maxScenarios);

  // Normalize confidence
  const topTotal = topN.reduce((s, c) => s + c.score, 0);

  // Step 6: Build scenarios with projections
  const scenarios = topN.map((item, idx) => {
    const { candidate, score, breakdown } = item;
    const { targets, validationLevels, invalidationLevels } = computeProjections(candidate, quotes);
    const confidence = topTotal > 0 ? score / topTotal : 1 / topN.length;

    return {
      rank: idx + 1,
      confidence: Math.round(confidence * 100) / 100,
      label: buildScenarioLabel(candidate),
      description: `${candidate.type === 'impulse' ? 'Impulse' : 'Corrective'} wave pattern detected with ${candidate.waves.length} waves identified.`,
      waveType: candidate.type,
      currentPosition: buildCurrentPosition(candidate),
      direction: candidate.bullish ? 'bullish' : 'bearish',
      waves: candidate.waves,
      targets,
      validationLevels,
      invalidationLevels,
      nextMove: buildNextMove(candidate, targets),
      scoreBreakdown: breakdown,
    };
  });

  const topScenario = scenarios[0];
  const summary = topScenario
    ? `${topScenario.label} (${Math.round(topScenario.confidence * 100)}% confidence). ${topScenario.nextMove}`
    : 'Analysis complete.';

  return {
    scenarios,
    swingPoints: primarySwings,
    summary,
  };
}
