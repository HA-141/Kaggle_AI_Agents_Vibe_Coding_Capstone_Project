/* app.js – MedTech Stock Analyst frontend logic */
'use strict';

// ── State ─────────────────────────────────────────────────
let selectedTicker = 'JNJ';
let selectedMode   = 'live';

// ── Company name lookup ──────────────────────────────────
const COMPANY_NAMES = {
  JNJ: 'Johnson & Johnson',
  NVO: 'Novo Nordisk',
  PFE: 'Pfizer',
  AMGN: 'Amgen',
  GSK: 'GSK',
};

// ── Ticker selection ──────────────────────────────────────
document.querySelectorAll('.ticker-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.ticker-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedTicker = btn.dataset.ticker;
  });
});

// ── Mode toggle ───────────────────────────────────────────
document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedMode = btn.dataset.mode;
    const datePicker = document.getElementById('datePicker');
    datePicker.style.display = selectedMode === 'backtest' ? 'block' : 'none';
  });
});

// Set max date for date input (yesterday)
const dateInput = document.getElementById('asOfDate');
const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);
dateInput.max = yesterday.toISOString().split('T')[0];
dateInput.value = '2024-01-01'; // sensible default for backtesting

// ── Agent names for progress display ─────────────────────
const AGENTS = [
  'Clinical Trials',
  'Prescriber Signals',
  'PubMed Momentum',
  'Gov Procurement',
  'Headline Sentiment',
  'Price Data',
  'Ensemble',
  'Report Writer',
];

const LOADING_STEPS = [
  'Querying ClinicalTrials.gov…',
  'Fetching CMS prescriber data…',
  'Searching PubMed publications…',
  'Checking USAspending contracts…',
  'Analysing GDELT news sentiment…',
  'Loading price history…',
  'Running ensemble ranking…',
  'Generating final report…',
];

let stepInterval = null;
let agentDoneCount = 0;

function startLoadingAnimation() {
  const progress = document.getElementById('agentProgress');
  const stepEl   = document.getElementById('loadingStep');
  progress.innerHTML = '';
  agentDoneCount = 0;
  let stepIdx = 0;

  AGENTS.forEach(name => {
    const chip = document.createElement('div');
    chip.className = 'agent-chip';
    chip.id = `chip-${name.replace(/\s/g, '-')}`;
    chip.textContent = name;
    progress.appendChild(chip);
  });

  stepInterval = setInterval(() => {
    stepEl.textContent = LOADING_STEPS[stepIdx % LOADING_STEPS.length];
    const chip = document.getElementById(`chip-${AGENTS[stepIdx % AGENTS.length].replace(/\s/g, '-')}`);
    if (chip && !chip.classList.contains('done')) chip.classList.add('done');
    stepIdx++;
  }, 2000);
}

function stopLoadingAnimation() {
  if (stepInterval) { clearInterval(stepInterval); stepInterval = null; }
  document.querySelectorAll('.agent-chip').forEach(c => c.classList.add('done'));
}

// ── Main analysis runner ──────────────────────────────────
async function runAnalysis() {
  const ticker  = selectedTicker;
  const mode    = selectedMode;
  const asOfDate = dateInput.value;

  if (mode === 'backtest' && !asOfDate) {
    alert('Please select an as-of date for backtest mode.');
    return;
  }

  // Show loading, hide results
  document.getElementById('controlPanel').style.display  = 'none';
  document.getElementById('loadingPanel').style.display  = 'block';
  document.getElementById('resultsSection').style.display = 'none';

  startLoadingAnimation();

  const payload = { ticker, mode };
  if (mode === 'backtest') payload.as_of_date = asOfDate;

  try {
    const res  = await fetch('/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    stopLoadingAnimation();

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      showError(err.detail || `HTTP ${res.status}`);
      return;
    }

    const data = await res.json();
    renderResults(data, ticker, mode, asOfDate);

  } catch (err) {
    stopLoadingAnimation();
    showError(err.message);
  }
}

// ── Error display ─────────────────────────────────────────
function showError(msg) {
  document.getElementById('loadingPanel').style.display = 'none';
  document.getElementById('controlPanel').style.display = 'block';
  const banner = document.createElement('div');
  banner.className = 'glass-card';
  banner.style.borderColor = 'rgba(239,68,68,0.4)';
  banner.innerHTML = `<p style="color:#ef4444;font-weight:600">⚠ Analysis failed</p>
    <p style="color:#94a3b8;font-size:.88rem;margin-top:8px;font-family:monospace">${escHtml(msg)}</p>`;
  document.querySelector('.container').insertBefore(banner, document.getElementById('controlPanel'));
  setTimeout(() => banner.remove(), 8000);
}

// ── Render results ────────────────────────────────────────
function renderResults(data, ticker, mode, date) {
  document.getElementById('loadingPanel').style.display  = 'none';
  document.getElementById('resultsSection').style.display = 'block';

  const ensemble = data.ensemble || {};
  const direction  = (ensemble.direction || ensemble.overall_signal || 'neutral').toLowerCase();
  const confidence = parseFloat(ensemble.confidence ?? ensemble.ensemble_confidence ?? 0);
  const rangeText = ensemble.magnitude_range || '';
  const magText = rangeText || 'No estimate';

  // Banner
  const dirLabel = direction === 'bullish' ? '↑ Bullish'
                 : direction === 'bearish' ? '↓ Bearish'
                 : '→ Neutral';
  const dirEl = document.getElementById('predDirection');
  dirEl.textContent = dirLabel;
  dirEl.className   = `prediction-direction direction-${direction}`;

  const companyName = COMPANY_NAMES[ticker] || ticker;
  document.getElementById('predTicker').textContent = ticker;
  document.getElementById('predCompanyName').textContent = companyName;
  document.getElementById('predDate').textContent =
    mode === 'backtest' ? `Backtest as of ${date}` : `Live – ${new Date().toLocaleDateString('en-GB')}`;
  document.getElementById('predMagnitude').textContent = 'Expected impact:';
  document.getElementById('predRange').textContent = magText;

  // Confidence ring
  const pct = Math.round(confidence * 100);
  document.getElementById('confPct').textContent = `${pct}%`;
  const circumference = 201;
  const offset = circumference - (confidence * circumference);
  const ringFill = document.getElementById('confRingFill');
  ringFill.style.strokeDashoffset = offset;
  ringFill.style.stroke = direction === 'bullish' ? '#10b981'
                        : direction === 'bearish' ? '#ef4444'
                        : '#f59e0b';

  // Indicators
  renderIndicators(data.indicator_outputs || []);

  // Report
  const reportText = typeof data.report === 'string' ? data.report
    : (data.report?.report_text ?? JSON.stringify(data.report, null, 2));
  document.getElementById('reportBody').textContent = reportText;

  // Price context
  if (data.price_context) {
    const priceCard = document.getElementById('priceCard');
    document.getElementById('priceTicker').textContent = ticker;
    priceCard.style.display = 'block';
    requestAnimationFrame(() => renderComboChart(data.price_context));
  }
}

// ── Render indicator cards ────────────────────────────────
function renderIndicators(indicators) {
  const grid = document.getElementById('indicatorsGrid');
  grid.innerHTML = '';

  // Sort by confidence desc (API returns already-ranked indicators)
  const sorted = [...indicators].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));

  sorted.forEach((ind, idx) => {
    const signal     = (ind.signal || 'neutral').toLowerCase();
    const confidence = Math.round((ind.confidence || 0) * 100);
    const magEstimate = ind.magnitude_estimate || '';
    const evidence   = ind.evidence_summary || ind.evidence || ind.reasoning || '';
    const dataLag = ind.data_as_of_lag_days;
    const lagText = dataLag != null ? `Lag: ${dataLag}d` : '';

    const card = document.createElement('div');
    card.className = `indicator-card signal-${signal}`;
    card.style.animationDelay = `${idx * 0.07}s`;

    card.innerHTML = `
      <span class="rank-badge">#${idx + 1}</span>
      <div class="ind-header">
        <div>
          <div class="ind-name">${escHtml(friendlyName(ind.indicator || ind.agent || ''))}</div>
          <div class="ind-source">${escHtml(ind.data_source || ind.source || '')}${lagText ? ' · ' + lagText : ''}</div>
        </div>
        <span class="signal-badge ${signal}">${signal}</span>
      </div>
      <div class="ind-bars">
        <div class="bar-row">
          <span class="bar-label">Confidence</span>
          <div class="bar-track"><div class="bar-fill conf" style="width:0%"
            data-target="${confidence}"></div></div>
          <span class="bar-value">${confidence}%</span>
        </div>
        ${magEstimate ? `<div class="bar-row">
          <span class="bar-label">Estimate</span>
          <span class="mag-estimate">${escHtml(magEstimate)}</span>
        </div>` : ''}
      </div>
      ${evidence ? `<div class="ind-evidence">${escHtml(String(evidence).slice(0, 280))}${evidence.length > 280 ? '…' : ''}</div>` : ''}
    `;

    grid.appendChild(card);
  });

  // Animate bars after paint
  requestAnimationFrame(() => {
    document.querySelectorAll('.bar-fill[data-target]').forEach(el => {
      const target = el.dataset.target;
      el.style.transition = 'width 0.8s ease';
      el.style.width = `${target}%`;
    });
  });
}

// ── Helpers ───────────────────────────────────────────────
function friendlyName(raw) {
  const map = {
    clinical_trials:    'Clinical Trial Execution',
    physician_adoption: 'Physician Adoption Signals',
    pubmed:             'Scientific Publication Momentum',
    usaspending:        'Government Procurement',
    gdelt:              'Headline Sentiment',
    headline_sentiment: 'Headline Sentiment',
    price_data:         'Price Data',
  };
  const key = raw.toLowerCase().replace(/[\s-]/g, '_');
  return map[key] || raw.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Reset UI ──────────────────────────────────────────────
function resetUI() {
  document.getElementById('resultsSection').style.display = 'none';
  document.getElementById('controlPanel').style.display  = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Combo chart (price line + volume bars) ────────────────
let _comboChart = null;

function renderComboChart(ctx) {
  const canvas = document.getElementById('comboChart');
  if (!canvas || !ctx.prices || ctx.prices.length < 2) return;
  if (_comboChart) { _comboChart.destroy(); _comboChart = null; }

  const labels = ctx.prices.map(p => p.date);
  const closes = ctx.prices.map(p => p.close);
  const volumes = ctx.prices.map(p => p.volume);

  function fmt(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return v;
  }

  _comboChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Close Price',
          data: closes,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.08)',
          borderWidth: 2,
          pointRadius: 2,
          pointBackgroundColor: '#3b82f6',
          fill: true,
          tension: 0.2,
          yAxisID: 'y',
          order: 1,
        },
        {
          label: 'Volume',
          type: 'bar',
          data: volumes,
          backgroundColor: 'rgba(148,163,184,0.2)',
          borderColor: 'rgba(148,163,184,0.3)',
          borderWidth: 0.5,
          borderRadius: 2,
          yAxisID: 'y1',
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'end',
          labels: {
            color: '#94a3b8',
            font: { size: 11, family: "'Inter', system-ui, sans-serif" },
            boxWidth: 14,
            usePointStyle: true,
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: 'rgba(12,17,32,0.92)',
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: ctx => ctx.dataset.label === 'Volume'
              ? 'Volume: ' + fmt(ctx.parsed.y)
              : 'Close: $' + ctx.parsed.y.toFixed(2),
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#475569', maxTicksLimit: 8, font: { size: 10, family: "'JetBrains Mono', monospace" } },
          grid: { display: false },
        },
        y: {
          position: 'left',
          ticks: { color: '#3b82f6', font: { size: 10, family: "'JetBrains Mono', monospace" }, callback: v => '$' + v.toFixed(0) },
          grid: { color: 'rgba(255,255,255,0.04)' },
          title: { display: true, text: 'Price ($)', color: '#3b82f6', font: { size: 10, family: "'Inter', system-ui, sans-serif" } },
        },
        y1: {
          position: 'right',
          ticks: { color: '#64748b', font: { size: 10, family: "'JetBrains Mono', monospace" }, callback: v => fmt(v) },
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Volume', color: '#64748b', font: { size: 10, family: "'Inter', system-ui, sans-serif" } },
        },
      },
      interaction: { intersect: false, mode: 'index' },
    },
  });
}

// ── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Nothing to initialise — all auth is handled server-side via Vertex AI
});
