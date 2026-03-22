GIVEN a stock detail page is open
WHEN the chart loads
THEN candlestick bars are visible for the last 6 months of data
AND volume bars are visible below the chart

GIVEN a stock detail page is open
WHEN I toggle "EMA 21" in the chart controls
THEN a line overlay appears on the chart
AND toggling it off removes the line

GIVEN a stock detail page is open
WHEN I toggle "Supertrend" in the chart controls
THEN the Supertrend line appears with correct bull/bear coloring

GIVEN a stock detail page is open
WHEN I toggle "Patterns" in the chart controls
THEN YOLOv8 bounding boxes appear on the chart for detected patterns
AND each box has a label showing the pattern name and confidence

GIVEN a stock detail page is open
WHEN I toggle "Forecast" in the chart controls
THEN a shaded forecast band appears to the right of the last candle
AND a dashed median line is visible

GIVEN a stock detail page is open
WHEN I toggle "EW" in the chart controls
THEN wave pivot labels appear on the chart (or the toggle is hidden if no EW data)

GIVEN a stock detail page is open
WHEN I click "Reset View"
THEN the chart resets to show the default time range

GIVEN a stock detail page is open
WHEN I change the timeframe to "Weekly"
THEN the chart redraws with weekly candles
AND indicator overlays recalculate for the weekly timeframe

GIVEN a stock detail page is open
WHEN I select "1H" timeframe
THEN the chart redraws with 1-hour candles
AND the visible range defaults to the last 5 days

GIVEN a stock detail page is open
WHEN I select "4H" timeframe
THEN the chart redraws with 4-hour candles aggregated from 1H data

GIVEN a stock detail page is open
WHEN I select "1M" timeframe
THEN the chart redraws with monthly candles aggregated from daily data

GIVEN a stock detail page is open with daily data showing
WHEN I pan left beyond the initially loaded data
THEN additional historical bars appear automatically without a visible jump
AND a brief "Loading..." indicator appears and disappears

GIVEN a stock detail page is open
WHEN all available historical data has been loaded
THEN panning left further shows no more data loads
AND the oldest available date is reached gracefully

GIVEN a stock detail page is open
WHEN I select "1H" or "4H" and intraday data has not been ingested
THEN a message appears: "Intraday data not yet available — runs nightly"
