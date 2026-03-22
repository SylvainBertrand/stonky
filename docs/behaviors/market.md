GIVEN the /market page is open
WHEN the page loads
THEN the regime banner shows a colored status (green/yellow/red)
AND regime label, breadth, momentum, sentiment, macro pills are visible
AND the scanner implication text is shown

GIVEN the /market page is open
WHEN I view the Breadth panel
THEN a chart shows SPX/RSP ratio over the last 12 months
AND the current breadth signal ("broad" or "narrow") is labeled

GIVEN the /market page is open
WHEN I view the Sentiment panel
THEN AAII bull-bear spread history is shown as a bar chart
AND the most recent NAAIM reading is visible
AND a "last scraped" timestamp is shown

GIVEN the /market page is open
WHEN I click "Refresh"
THEN a loading state is shown
AND data updates after the refresh completes

GIVEN the scanner page is open
WHEN the page loads
THEN a compact regime strip appears at the top showing current regime + implication
AND clicking it navigates to /market
