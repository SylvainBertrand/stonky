# stonky

Stock price history chart viewer with interactive candlestick charts and technical indicators.

Built with Express, LightweightCharts, and Yahoo Finance API.

## Features

- Portfolio dashboard with real-time quotes
- Interactive candlestick and line charts
- Technical indicators: SMA, EMA, Bollinger Bands, RSI, MACD
- Multiple time periods (1w, 1mo, 3mo, 6mo, 1y, 2y, 5y)
- Selectable chart update rate (1min, 5min, 15min, 30min, 1h, 1day)
- Automatic fallback to mock data during rate limiting

## Setup

Install dependencies:

```bash
npm install
```

## Run

Start the server:

```bash
npm start
```

Then open http://localhost:3000 in your browser.

## Configuration

Edit `portfolio.csv` to customize your stock portfolio. Each row should have a `symbol` column with the stock ticker.
