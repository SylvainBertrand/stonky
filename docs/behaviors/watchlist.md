GIVEN the watchlist management page is open
WHEN I create a new watchlist
THEN it appears in the watchlist selector
AND I can immediately add symbols to it

GIVEN a watchlist exists with symbols
WHEN I select it in the scanner
THEN the scanner operates on that watchlist's symbols only

GIVEN the watchlist management page is open
WHEN I remove a symbol from a watchlist
THEN it disappears from the list immediately
