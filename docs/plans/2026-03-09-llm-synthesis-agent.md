# LLM Synthesis Agent Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-powered synthesis agent that consumes all P0+P1 signal outputs for a stock and produces structured, human-readable trade setup analysis.

**Architecture:** Nightly batch job collects all signals (P0 composite, YOLOv8 patterns, EW, Chronos-2 forecast) into `AggregatedSignals`, sends to LLM via provider abstraction (Ollama default, Claude stub), parses structured JSON response, stores in `synthesis_results` table, displays in frontend.

**Tech Stack:** Python (FastAPI, SQLAlchemy, httpx for Ollama), React/TypeScript (TanStack Query), Alembic migration

---

## Chunk 1: Backend Core (LLM Provider + Signal Aggregator + Synthesis Agent)

### Task 1: LLM Provider Abstraction

**Files:**
- Create: `backend/app/llm/__init__.py`
- Create: `backend/app/llm/provider.py`

- [ ] **Step 1: Create `backend/app/llm/__init__.py`**
Empty package init.

- [ ] **Step 2: Create `backend/app/llm/provider.py`**
Contains `LLMProvider` Protocol, `OllamaProvider` (functional, uses httpx), `ClaudeProvider` (stub), and `get_provider()` factory.

### Task 2: Signal Aggregator

**Files:**
- Create: `backend/app/analysis/signal_aggregator.py`

- [ ] **Step 1: Create signal aggregator with `AggregatedSignals` dataclass and `aggregate_signals()` async function**
Pulls latest data from indicator_cache, pattern_detections, and forecast_cache. Returns None if no P0 scan results exist.

### Task 3: Synthesis Agent

**Files:**
- Create: `backend/app/analysis/synthesis_agent.py`

- [ ] **Step 1: Create synthesis agent with `SynthesisResult` dataclass, prompt builders, `synthesize()`, and `_parse_response()`**
System prompt, user prompt template built from AggregatedSignals, JSON extraction with markdown fence handling, fallback on parse failure.

---

## Chunk 2: Database + API + Scheduler

### Task 4: DB Model + Migration

**Files:**
- Create: `backend/app/models/synthesis_result.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/004_add_synthesis_results.py`

- [ ] **Step 1: Create SQLAlchemy model for `synthesis_results` table**
- [ ] **Step 2: Register model in `backend/app/models/__init__.py`**
- [ ] **Step 3: Create Alembic migration 004**

### Task 5: API Router

**Files:**
- Create: `backend/app/api/synthesis.py`
- Create: `backend/app/schemas/synthesis.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create Pydantic schemas for synthesis API responses**
- [ ] **Step 2: Create API router with GET /{symbol}, POST /scan, GET /scan/status**
- [ ] **Step 3: Register router in main.py**

### Task 6: Scheduler + Config

**Files:**
- Modify: `backend/app/scheduler.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add LLM config settings to config.py**
- [ ] **Step 2: Add synthesis nightly job to scheduler.py (9 AM ET cron)**

---

## Chunk 3: Backend Tests

### Task 7: Unit Tests

**Files:**
- Create: `backend/tests/unit/test_synthesis_agent.py`
- Create: `backend/tests/unit/test_signal_aggregator.py`

- [ ] **Step 1: Write test_synthesis_agent.py** — parse_response (valid JSON, markdown fences, malformed, empty), build_user_prompt structure, mock LLM provider
- [ ] **Step 2: Write test_signal_aggregator.py** — missing YOLO results, missing forecast, no P0 results returns None
- [ ] **Step 3: Run tests and verify all pass**

---

## Chunk 4: Frontend Integration

### Task 8: Frontend Types + API Client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/scanner.ts`

- [ ] **Step 1: Add SynthesisData interface to types/index.ts**
- [ ] **Step 2: Add synthesisApi to api/scanner.ts**

### Task 9: TradeSetupCard Component + StockDetailPage

**Files:**
- Create: `frontend/src/components/stock/TradeSetupCard.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`

- [ ] **Step 1: Create TradeSetupCard component** — colored header by bias, confidence badge, summary, confluence/conflicts, entry/stop/target, key risk, parse error handling
- [ ] **Step 2: Integrate TradeSetupCard at top of StockDetailPage**

### Task 10: Scanner Integration

**Files:**
- Modify: `frontend/src/components/scanner/ResultsTable.tsx`
- Modify: `frontend/src/pages/ScannerPage.tsx`

- [ ] **Step 1: Add Setup column to ResultsTable** — setup_type label + bias dot + confidence badge
- [ ] **Step 2: Add "Run Analysis" button to ScannerPage header**
- [ ] **Step 3: Fetch synthesis data in ScannerPage and pass to ResultsTable**

---

## Chunk 5: Config + Docs

### Task 11: Environment + Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add LLM config vars to .env.example**
- [ ] **Step 2: Add Ollama setup section to README.md**

---
