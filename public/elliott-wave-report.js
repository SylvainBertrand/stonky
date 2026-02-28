// Elliott Wave Report Card HTML Generator

const COLORS = {
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

/**
 * Generate report card HTML for Elliott Wave analysis.
 * @param {object} analysis - Result from analyzeElliottWave()
 * @param {string} symbol - Stock ticker
 * @returns {string} HTML string
 */
export function generateElliottWaveReport(analysis, symbol) {
  if (!analysis) return errorHtml('No analysis data available.');
  if (!analysis.scenarios || analysis.scenarios.length === 0) {
    return errorHtml(analysis.summary || 'No wave patterns found.');
  }

  const ts = new Date().toLocaleString();
  const barCount = '—';

  const scenarioCards = analysis.scenarios.map(renderScenarioCard).join('');

  return `
<div style="font-family: monospace; color: ${COLORS.text}; padding: 0;">

  <div style="margin-bottom: 16px;">
    <div style="font-size: 11px; color: ${COLORS.sub}; margin-bottom: 4px;">
      Elliott Wave Analysis · ${ts}
    </div>
    <div style="
      background: ${COLORS.surface};
      border: 1px solid ${COLORS.border};
      border-radius: 6px;
      padding: 10px 14px;
      font-size: 13px;
      color: ${COLORS.text};
      line-height: 1.5;
    ">
      ${escHtml(analysis.summary)}
    </div>
  </div>

  <div style="display: flex; flex-direction: column; gap: 12px;">
    ${scenarioCards}
  </div>

</div>
`.trim();
}

function renderScenarioCard(scenario) {
  const { rank, confidence, label, description, direction, currentPosition,
          waves, targets, validationLevels, invalidationLevels,
          nextMove, scoreBreakdown, waveType } = scenario;

  const pct = Math.round(confidence * 100);
  const dirColor = direction === 'bullish' ? COLORS.green : COLORS.red;
  const borderColor = dirColor;
  const dirIcon = direction === 'bullish' ? '▲' : '▼';

  const targetsHtml = renderTargets(targets);
  const validationHtml = renderValidation(validationLevels);
  const invalidationHtml = renderInvalidation(invalidationLevels);
  const scoreHtml = renderScoreBreakdown(scoreBreakdown);
  const wavesHtml = renderWaveList(waves);
  const confBar = renderConfBar(pct, dirColor);

  const isOpen = rank === 1;

  return `
<div style="
  background: ${COLORS.surface};
  border: 1px solid ${COLORS.border};
  border-left: 3px solid ${borderColor};
  border-radius: 6px;
  overflow: hidden;
">
  <!-- Header (always visible) -->
  <div
    style="
      padding: 12px 14px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
    "
    onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'"
  >
    <span style="
      background: ${COLORS.bg};
      color: ${dirColor};
      font-weight: bold;
      font-size: 12px;
      padding: 2px 7px;
      border-radius: 4px;
      border: 1px solid ${borderColor}40;
      white-space: nowrap;
    ">#${rank} ${dirIcon} ${pct}%</span>

    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 13px; font-weight: bold; color: ${COLORS.text}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
        ${escHtml(label)}
      </div>
      <div style="font-size: 11px; color: ${COLORS.sub}; margin-top: 2px;">
        ${escHtml(currentPosition)}
      </div>
    </div>

    ${confBar}

    <span style="color: ${COLORS.sub}; font-size: 16px; user-select: none; flex-shrink: 0;">▾</span>
  </div>

  <!-- Expandable body -->
  <div style="display: ${isOpen ? 'block' : 'none'}; border-top: 1px solid ${COLORS.border}40; padding: 12px 14px;">

    ${wavesHtml ? `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Waves</div>
      ${wavesHtml}
    </div>` : ''}

    ${targetsHtml ? `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Targets</div>
      ${targetsHtml}
    </div>` : ''}

    ${validationHtml ? `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Validates if</div>
      ${validationHtml}
    </div>` : ''}

    ${invalidationHtml ? `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Invalidates if</div>
      ${invalidationHtml}
    </div>` : ''}

    <div style="margin-bottom: 12px;">
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Next expected move</div>
      <div style="font-size: 12px; color: ${COLORS.text}; background: ${COLORS.bg}; border-radius: 4px; padding: 8px 10px; line-height: 1.4;">
        ${escHtml(nextMove)}
      </div>
    </div>

    ${scoreHtml ? `
    <div>
      <div style="font-size: 11px; font-weight: bold; color: ${COLORS.sub}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Score breakdown</div>
      ${scoreHtml}
    </div>` : ''}

  </div>
</div>
`.trim();
}

function renderConfBar(pct, color) {
  return `
<div style="width: 60px; flex-shrink: 0;">
  <div style="background: ${COLORS.bg}; border-radius: 3px; height: 5px; overflow: hidden;">
    <div style="background: ${color}; width: ${pct}%; height: 100%; border-radius: 3px;"></div>
  </div>
</div>`.trim();
}

function renderWaveList(waves) {
  if (!waves || waves.length === 0) return '';
  const items = waves.map(w => {
    const dir = w.endPrice > w.startPrice ? '▲' : '▼';
    const dirColor = w.endPrice > w.startPrice ? COLORS.green : COLORS.red;
    const move = Math.abs(w.endPrice - w.startPrice).toFixed(2);
    return `<span style="
      display: inline-flex; align-items: center; gap: 4px;
      background: ${COLORS.bg}; border-radius: 3px;
      padding: 2px 6px; font-size: 11px; margin: 2px;
    ">
      <span style="font-weight: bold; color: ${COLORS.accent};">${escHtml(w.label)}</span>
      <span style="color: ${dirColor};">${dir}$${move}</span>
    </span>`;
  }).join('');
  return `<div style="display: flex; flex-wrap: wrap; gap: 0;">${items}</div>`;
}

function renderTargets(targets) {
  if (!targets || targets.length === 0) return '';
  return targets.filter(t => isFinite(t.price)).map(t => {
    const confColor = t.confidence === 'primary' ? COLORS.green
      : t.confidence === 'secondary' ? COLORS.blue
      : COLORS.sub;
    const icon = t.confidence === 'primary' ? '🎯' : t.confidence === 'secondary' ? '◎' : '○';
    return `<div style="display: flex; align-items: baseline; gap: 8px; font-size: 12px; margin-bottom: 3px;">
      <span>${icon}</span>
      <span style="color: ${confColor}; font-weight: bold; min-width: 70px;">$${t.price.toFixed(2)}</span>
      <span style="color: ${COLORS.sub}; font-size: 11px;">${escHtml(t.label)}</span>
    </div>`;
  }).join('');
}

function renderValidation(levels) {
  if (!levels || levels.length === 0) return '';
  return levels.map(v => `
    <div style="display: flex; align-items: baseline; gap: 8px; font-size: 12px; margin-bottom: 3px;">
      <span>✅</span>
      <span style="color: ${COLORS.green}; font-weight: bold; min-width: 70px;">
        ${v.condition === 'above' ? 'Above' : 'Below'} $${v.price.toFixed(2)}
      </span>
      <span style="color: ${COLORS.sub}; font-size: 11px;">${escHtml(v.description)}</span>
    </div>`).join('');
}

function renderInvalidation(levels) {
  if (!levels || levels.length === 0) return '';
  return levels.map(inv => {
    const icon = inv.severity === 'hard' ? '❌' : '⚠️';
    const col = inv.severity === 'hard' ? COLORS.red : COLORS.yellow;
    return `<div style="display: flex; align-items: baseline; gap: 8px; font-size: 12px; margin-bottom: 3px;">
      <span>${icon}</span>
      <span style="color: ${col}; font-weight: bold; min-width: 70px;">
        ${inv.condition === 'above' ? 'Above' : 'Below'} $${inv.price.toFixed(2)}
      </span>
      <span style="color: ${COLORS.sub}; font-size: 11px;">${escHtml(inv.description)}</span>
    </div>`;
  }).join('');
}

function renderScoreBreakdown(breakdown) {
  if (!breakdown) return '';
  const labels = {
    wave3FibRatio:    'Wave 3 Fib',
    wave5FibRatio:    'Wave 5 Fib',
    wave2Retracement: 'Wave 2 Ret',
    wave4Retracement: 'Wave 4 Ret',
    alternation:      'Alternation',
    channelFit:       'Channel',
    proportionality:  'Proportion',
    volumeConfirmation: 'Volume',
    subwaveValidity:  'Sub-waves',
  };

  return Object.entries(breakdown).map(([key, val]) => {
    const pct = Math.round((val ?? 0) * 100);
    const barColor = pct >= 70 ? COLORS.green : pct >= 40 ? COLORS.yellow : COLORS.red;
    const name = labels[key] ?? key;
    return `<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 11px;">
      <span style="color: ${COLORS.sub}; min-width: 90px; flex-shrink: 0;">${escHtml(name)}</span>
      <div style="flex: 1; background: ${COLORS.bg}; border-radius: 3px; height: 6px; overflow: hidden;">
        <div style="background: ${barColor}; width: ${pct}%; height: 100%; border-radius: 3px;"></div>
      </div>
      <span style="color: ${COLORS.text}; min-width: 32px; text-align: right;">${(val ?? 0).toFixed(2)}</span>
    </div>`;
  }).join('');
}

function errorHtml(msg) {
  return `<div style="
    color: ${COLORS.sub};
    font-size: 13px;
    font-style: italic;
    padding: 16px 0;
    text-align: center;
  ">${escHtml(msg)}</div>`;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
