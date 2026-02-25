import express from 'express';
import yahooFinance from 'yahoo-finance2';
import { parse } from 'csv-parse/sync';
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

yahooFinance.suppressNotices(['ripHistorical', 'yahooSurvey']);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.static(join(__dirname, 'public')));

// ── Retry with backoff for rate-limited requests ──────────────────────────
async function withRetry(fn, retries = 2, delayMs = 2000) {
  for (let i = 0; i <= retries; i++) {
    try {
      return await fn();
    } catch (err) {
      const isRateLimit = err.message?.includes('Too Many Requests') || 
                          err.message?.includes('429') ||
                          err.message?.includes('not valid JSON');
      if (!isRateLimit || i === retries) throw err;
      const wait = delayMs * Math.pow(1.5, i);
      console.log(`Rate limited – retrying in ${(wait / 1000).toFixed(1)}s… (attempt ${i + 1}/${retries})`);
      await new Promise(r => setTimeout(r, wait));
    }
  }
}

// ── Simple in-memory cache ────────────────────────────────────────────────
const cache = new Map();
function fromCache(key) {
  const e = cache.get(key);
  return e && Date.now() < e.exp ? e.data : null;
}
function toCache(key, data, ttlMs) {
  cache.set(key, { data, exp: Date.now() + ttlMs });
}

// ── Period config ─────────────────────────────────────────────────────────
const PERIODS = {
  '1w':  { days: 7,    interval: '1d' },
  '1mo': { days: 30,   interval: '1d' },
  '3mo': { days: 90,   interval: '1d' },
  '6mo': { days: 180,  interval: '1d' },
  '1y':  { days: 365,  interval: '1d' },
  '2y':  { days: 730,  interval: '1d' },
  '5y':  { days: 1825, interval: '1wk' },
};

// ── Mock data generator (fallback for rate limits) ───────────────────────
function generateMockHistory(symbol, days) {
  const quotes = [];
  let basePrice = 150 + Math.random() * 200;
  const now = new Date();
  
  for (let i = days; i >= 0; i--) {
    const date = new Date(now - i * 86400000);
    const dateStr = date.toISOString().split('T')[0];
    
    // Random walk with slight upward bias
    const change = (Math.random() - 0.48) * basePrice * 0.03;
    basePrice += change;
    
    const open = basePrice + (Math.random() - 0.5) * basePrice * 0.01;
    const close = basePrice + (Math.random() - 0.5) * basePrice * 0.01;
    const high = Math.max(open, close) + Math.random() * basePrice * 0.02;
    const low = Math.min(open, close) - Math.random() * basePrice * 0.02;
    const volume = Math.floor(10_000_000 + Math.random() * 50_000_000);
    
    quotes.push({
      time: dateStr,
      open: parseFloat(open.toFixed(2)),
      high: parseFloat(high.toFixed(2)),
      low: parseFloat(low.toFixed(2)),
      close: parseFloat(close.toFixed(2)),
      volume,
    });
  }
  
  return {
    symbol,
    currency: 'USD',
    exchange: 'MOCK',
    quotes,
  };
}

// ── Routes ────────────────────────────────────────────────────────────────
app.get('/api/portfolio', (req, res) => {
  try {
    const content = readFileSync(join(__dirname, 'portfolio.csv'), 'utf-8');
    const records = parse(content, { columns: true, skip_empty_lines: true, trim: true });
    res.json(records.map(r => r.symbol).filter(Boolean));
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Single batch request for all portfolio quotes
app.get('/api/quotes', async (req, res) => {
  const symbols = (req.query.symbols ?? '').split(',').map(s => s.trim()).filter(Boolean);
  if (!symbols.length) return res.json([]);

  const cacheKey = `quotes:${symbols.join(',')}`;
  const cached = fromCache(cacheKey);
  if (cached) return res.json(cached);

  try {
    // yahoo-finance2 quote() accepts an array → single API call for all symbols
    const raw = await withRetry(() => yahooFinance.quote(symbols));
    const results = raw.map(q => ({
      symbol: q.symbol,
      name: q.longName || q.shortName || q.symbol,
      price: q.regularMarketPrice,
      change: q.regularMarketChange,
      changePercent: q.regularMarketChangePercent,
      currency: q.currency,
    }));
    toCache(cacheKey, results, 5 * 60_000); // 5 min TTL for quotes
    res.json(results);
  } catch (err) {
    console.error('[quotes]', err.message);
    
    // Fallback: generate mock quotes when rate-limited
    if (err.message?.includes('Too Many Requests') || err.message?.includes('not valid JSON')) {
      console.log('Using mock quotes due to rate limiting');
      const mockResults = symbols.map(sym => {
        const price = 150 + Math.random() * 200;
        const change = (Math.random() - 0.5) * 10;
        return {
          symbol: sym,
          name: `${sym} Inc.`,
          price: parseFloat(price.toFixed(2)),
          change: parseFloat(change.toFixed(2)),
          changePercent: parseFloat((change / price * 100).toFixed(2)),
          currency: 'USD',
        };
      });
      toCache(cacheKey, mockResults, 5 * 60_000);
      return res.json(mockResults);
    }
    
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/history/:symbol', async (req, res) => {
  const { symbol } = req.params;
  const periodKey = req.query.period ?? '1y';
  const period = PERIODS[periodKey] ?? PERIODS['1y'];

  const cacheKey = `history:${symbol}:${periodKey}`;
  const cached = fromCache(cacheKey);
  if (cached) return res.json(cached);

  try {
    const now = new Date();
    const from = new Date(now - period.days * 86400000);

    const result = await withRetry(() => yahooFinance.chart(symbol, {
      period1: from,
      period2: now,
      interval: period.interval,
    }));

    const quotes = (result.quotes ?? [])
      .filter(r => r.open != null && r.close != null)
      .map(r => ({
        time: new Date(r.date).toISOString().split('T')[0],
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
        volume: r.volume ?? 0,
      }));

    const data = {
      symbol: result.meta.symbol ?? symbol,
      currency: result.meta.currency,
      exchange: result.meta.exchangeName,
      quotes,
    };
    toCache(cacheKey, data, 30 * 60_000); // 30 min TTL for history
    res.json(data);
  } catch (err) {
    console.error(`[history/${symbol}]`, err.message);
    
    // Fallback: generate mock data when rate-limited (for development)
    if (err.message?.includes('Too Many Requests') || err.message?.includes('not valid JSON')) {
      console.log(`Using mock data for ${symbol} due to rate limiting`);
      const mockData = generateMockHistory(symbol, period.days);
      toCache(cacheKey, mockData, 30 * 60_000);
      return res.json(mockData);
    }
    
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Stonky running at http://localhost:${PORT}`);
});
