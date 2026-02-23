"""GUI tests for stonky.app.

Strategy:
- One StockChartApp instance per test (function scope) for isolation.
- Tests requiring a display are auto-skipped when none is available.
- fetch_stock_data is always mocked — no network calls.
- The threading flow: join the background thread, then app.update() to
  flush the after(0, ...) callbacks that were queued from that thread.
"""

import threading
from unittest.mock import patch

import pandas as pd
import pytest
import tkinter as tk

from stonky.app import StockChartApp
from stonky.data import StockData


# ---------------------------------------------------------------- helpers ---

def _make_stock_data(symbol: str = "AAPL", period: str = "1y") -> StockData:
    index = pd.date_range("2025-01-01", periods=10, freq="B", tz="America/New_York")
    history = pd.DataFrame(
        {
            "Open":   [100.0 + i for i in range(10)],
            "High":   [105.0 + i for i in range(10)],
            "Low":    [95.0 + i for i in range(10)],
            "Close":  [102.0 + i for i in range(10)],
            "Volume": [1_000_000] * 10,
        },
        index=index,
    )
    return StockData(
        symbol=symbol,
        period=period,
        history=history,
        long_name="Apple Inc.",
        exchange="NMS",
        currency="USD",
    )


def _immediate_after(delay, callback=None, *args):
    """Patch target for after(): execute the callback synchronously.

    Used in full-flow tests to avoid depending on a running mainloop to
    flush after(0, ...) callbacks queued from the background thread.
    """
    if callback is not None:
        callback(*args)


# ---------------------------------------------------------------- fixture ---

@pytest.fixture
def app():
    try:
        _app = StockChartApp()
    except tk.TclError as exc:
        pytest.skip(f"No display available: {exc}")
    _app.withdraw()  # keep hidden during tests
    yield _app
    try:
        _app.destroy()
    except Exception:
        pass


# --------------------------------------------------------- trigger_search ---

class TestTriggerSearch:
    def test_empty_input_does_not_start_thread(self, app):
        app._search_var.set("")
        app._trigger_search()
        assert app._fetch_thread is None

    def test_empty_input_sets_status_message(self, app):
        app._search_var.set("")
        app._trigger_search()
        assert "Please enter" in app._status_var.get()

    def test_symbol_is_uppercased_and_stripped(self, app):
        data = _make_stock_data("MSFT", "1y")
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after"):
                app._search_var.set("  msft  ")
                app._trigger_search()
                if app._fetch_thread:
                    app._fetch_thread.join(timeout=5.0)
        assert app._current_symbol == "MSFT"

    def test_valid_symbol_sets_fetching_status(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after"):
                app._search_var.set("AAPL")
                app._trigger_search()
                # check status before thread finishes
                assert "Fetching" in app._status_var.get()
                if app._fetch_thread:
                    app._fetch_thread.join(timeout=5.0)


# ------------------------------------------------------------ load_data ----

class TestLoadData:
    def test_spawns_daemon_thread(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after"):
                app._current_symbol = "AAPL"
                app._load_data()
        thread = app._fetch_thread
        assert thread is not None
        assert thread.daemon is True
        thread.join(timeout=5.0)

    def test_fetch_runs_off_main_thread(self, app):
        """Fetch must NOT block the UI thread."""
        called_from: list[threading.Thread] = []

        def recording_fetch(symbol, period):
            called_from.append(threading.current_thread())
            return _make_stock_data(symbol, period)

        with patch("stonky.app.fetch_stock_data", side_effect=recording_fetch):
            with patch.object(app, "after"):
                app._current_symbol = "AAPL"
                app._load_data()
                app._fetch_thread.join(timeout=5.0)

        assert len(called_from) == 1
        assert called_from[0] is not threading.main_thread()

    def test_status_shows_fetching_for_symbol(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after"):
                app._current_symbol = "TSLA"
                app._load_data()
                app._fetch_thread.join(timeout=5.0)
        assert "TSLA" in app._status_var.get()


# -------------------------------------------------------- fetch_and_plot ---

class TestFetchAndPlot:
    def test_calls_fetch_stock_data_with_correct_args(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data) as mock_fetch:
            with patch.object(app, "after"):
                app._fetch_and_plot("AAPL", "1y")
        mock_fetch.assert_called_once_with("AAPL", "1y")

    def test_schedules_render_chart_on_success(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after") as mock_after:
                app._fetch_and_plot("AAPL", "1y")
        mock_after.assert_called_once_with(0, app._render_chart, data)

    def test_schedules_show_error_on_value_error(self, app):
        with patch("stonky.app.fetch_stock_data", side_effect=ValueError("No data found")):
            with patch.object(app, "after") as mock_after:
                app._fetch_and_plot("FAKE", "1y")
        mock_after.assert_called_once_with(0, app._show_error, "No data found")

    def test_schedules_show_error_on_unexpected_exception(self, app):
        with patch("stonky.app.fetch_stock_data", side_effect=RuntimeError("timeout")):
            with patch.object(app, "after") as mock_after:
                app._fetch_and_plot("AAPL", "1y")
        delay, callback, msg = mock_after.call_args[0]
        assert delay == 0
        # bound methods compare unequal by identity; compare the underlying function
        assert callback.__func__ is StockChartApp._show_error
        assert "timeout" in msg

    def test_does_not_call_after_before_fetch_completes(self, app):
        """after() must only be called after fetch_stock_data returns."""
        order: list[str] = []

        def slow_fetch(symbol, period):
            order.append("fetch")
            return _make_stock_data(symbol, period)

        def recording_after(*args, **kwargs):
            order.append("after")
            # don't actually schedule — we just want the ordering
        with patch("stonky.app.fetch_stock_data", side_effect=slow_fetch):
            with patch.object(app, "after", side_effect=recording_after):
                app._fetch_and_plot("AAPL", "1y")

        assert order == ["fetch", "after"]


# ---------------------------------------------------------- render_chart ---

class TestRenderChart:
    def test_updates_status_bar_with_symbol(self, app):
        data = _make_stock_data("AAPL", "1y")
        app._render_chart(data)
        assert "AAPL" in app._status_var.get()

    def test_updates_exchange_label(self, app):
        data = _make_stock_data()
        app._render_chart(data)
        assert app._info_labels["Exchange"].cget("text") == "NMS"

    def test_updates_currency_label(self, app):
        data = _make_stock_data()
        app._render_chart(data)
        assert app._info_labels["Currency"].cget("text") == "USD"

    def test_updates_company_label(self, app):
        data = _make_stock_data()
        app._render_chart(data)
        assert app._info_labels["Company"].cget("text") != "—"

    def test_shows_error_on_render_failure(self, app):
        data = _make_stock_data()
        with patch.object(app, "_render_chart_inner", side_effect=RuntimeError("bad render")):
            app._render_chart(data)
        assert "bad render" in app._status_var.get()

    def test_render_failure_does_not_raise(self, app):
        """Render errors must be caught — never crash the UI thread."""
        data = _make_stock_data()
        with patch.object(app, "_render_chart_inner", side_effect=RuntimeError("oops")):
            app._render_chart(data)  # must not raise


# ------------------------------------------------------ show_error ---------

class TestShowError:
    def test_sets_status_bar(self, app):
        app._show_error("Something went wrong")
        assert "Something went wrong" in app._status_var.get()

    def test_does_not_block(self, app):
        """_show_error must return immediately — no modal dialogs."""
        import time
        start = time.monotonic()
        app._show_error("test error")
        elapsed = time.monotonic() - start
        assert elapsed < 0.5


# --------------------------------------------------------- full flow --------

class TestFullFlow:
    """End-to-end tests for the fetch → render pipeline.

    _fetch_and_plot is called directly on the main thread (threading is already
    covered in TestLoadData). after() is patched with _immediate_after so
    callbacks run synchronously without needing a running mainloop.
    """

    def test_successful_fetch_updates_status(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after", side_effect=_immediate_after):
                app._fetch_and_plot("AAPL", "1y")
        status = app._status_var.get()
        assert "Showing" in status
        assert "AAPL" in status

    def test_successful_fetch_populates_info_panel(self, app):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            with patch.object(app, "after", side_effect=_immediate_after):
                app._fetch_and_plot("AAPL", "1y")
        assert app._info_labels["Currency"].cget("text") == "USD"
        assert app._info_labels["Exchange"].cget("text") == "NMS"

    def test_failed_fetch_shows_error_in_status(self, app):
        with patch("stonky.app.fetch_stock_data",
                   side_effect=ValueError('No data found for "FAKE"')):
            with patch.object(app, "after", side_effect=_immediate_after):
                app._fetch_and_plot("FAKE", "1y")
        assert "Error" in app._status_var.get()

    def test_second_fetch_overwrites_first(self, app):
        data1 = _make_stock_data("AAPL", "1y")
        data2 = _make_stock_data("MSFT", "1y")
        with patch("stonky.app.fetch_stock_data", return_value=data1):
            with patch.object(app, "after", side_effect=_immediate_after):
                app._fetch_and_plot("AAPL", "1y")
        with patch("stonky.app.fetch_stock_data", return_value=data2):
            with patch.object(app, "after", side_effect=_immediate_after):
                app._fetch_and_plot("MSFT", "1y")
        assert "MSFT" in app._status_var.get()
        assert "AAPL" not in app._status_var.get()
