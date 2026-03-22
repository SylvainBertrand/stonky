GIVEN the scanner page is open
WHEN I click "Run Scan" with a watchlist selected
THEN a loading indicator appears
AND results populate the table within 30 seconds
AND each row shows: symbol, composite score, profile matches, chart patterns, forecast direction

GIVEN scan results are showing
WHEN I click a symbol row
THEN the stock detail view opens for that symbol

GIVEN scan results are showing
WHEN I hover over a profile badge (e.g. "MB")
THEN a tooltip shows the full profile name

GIVEN scan results are showing
WHEN I sort by "Score" column
THEN rows reorder highest-to-lowest score

GIVEN the scanner page is open
WHEN no watchlist is selected
THEN the "Run Scan" button is disabled or shows a prompt to select a watchlist
