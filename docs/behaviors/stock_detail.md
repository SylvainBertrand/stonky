GIVEN a stock detail page is open
WHEN the page loads
THEN the Trade Setup card (LLM synthesis) is visible at the top
AND it shows: setup type, bias, confidence, summary text, entry/stop/target, R/R

GIVEN a stock detail page is open AND synthesis analysis exists
WHEN the Trade Setup card loads
THEN the summary text is non-empty and references actual signals (not a placeholder)
AND entry, stop, and target levels are shown (or clearly marked as unavailable)

GIVEN a stock detail page is open
WHEN the Chart Patterns section loads
THEN detected YOLOv8 patterns are listed with name and confidence
AND if no patterns exist, "No patterns detected" is shown (not empty/blank)

GIVEN a stock detail page is open
WHEN the Chronos-2 Forecast section loads
THEN direction, expected move %, and confidence are shown
AND if no forecast exists, "Not yet forecasted" is shown

GIVEN a stock detail page is open
WHEN the Elliott Wave section loads
THEN either a wave count or "No clear wave structure detected" is shown (never blank)
