GIVEN the /backtest page is open
WHEN I select "Momentum Breakout" strategy, choose a symbol, and click "Run Backtest"
THEN a loading state appears
AND results populate showing: equity curve, summary stats, trade list

GIVEN backtest results are showing
WHEN I view the summary stats
THEN Total Return, CAGR, Sharpe, Max Drawdown, Win Rate, and Trade count are all populated (not zero/null)

GIVEN backtest results are showing
WHEN I view the equity curve
THEN a line chart shows portfolio value over time
AND a buy-and-hold benchmark line is also shown

GIVEN backtest results are showing
WHEN I view the trade list
THEN rows show entry date, exit date, entry price, exit price, P&L% with green/red coloring

GIVEN the /backtest page is open
WHEN I click "Run Sweep"
THEN a heatmap renders showing metric values across parameter combinations
AND clicking a heatmap cell loads that parameter combo's results
