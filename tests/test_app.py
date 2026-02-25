"""GUI tests for stonky.app.

Strategy:
- Tests requiring a display are auto-skipped when none is available.
- fetch_stock_data and fetch_quote are always mocked — no network calls.
- threading.Thread is patched in fixtures to prevent background fetches
  from starting automatically, so tests can inject data and call _poll()
  or _update() directly for deterministic behaviour.
"""

import threading
from unittest.mock import patch

import pandas as pd
import pytest
import tkinter as tk

from stonky.app import ChartView, DashboardView, PortfolioTile, StockChartApp
from stonky.data import Quote, StockData


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


def _make_quote(
    symbol: str = "AAPL",
    last_price: float = 150.0,
    previous_close: float = 148.0,
) -> Quote:
    return Quote(
        symbol=symbol,
        long_name="Apple Inc.",
        exchange="NMS",
        currency="USD",
        last_price=last_price,
        previous_close=previous_close,
        year_high=200.0,
        year_low=100.0,
    )


# --------------------------------------------------------------- fixtures ---

@pytest.fixture
def app():
    """StockChartApp with a 2-symbol mock portfolio; no threads started."""
    with patch("stonky.app.load_portfolio", return_value=["AAPL", "MSFT"]):
        with patch("stonky.app.threading.Thread"):
            try:
                _app = StockChartApp("portfolio.csv")
            except tk.TclError as exc:
                pytest.skip(f"No display available: {exc}")
            _app.withdraw()
    yield _app
    try:
        _app.destroy()
    except Exception:
        pass


@pytest.fixture
def chart_view(app):
    """ChartView with no background fetch (thread patched out)."""
    with patch("stonky.app.threading.Thread"):
        view = ChartView(app, "AAPL", on_back=lambda: None)
    yield view
    try:
        view.destroy()
    except Exception:
        pass


@pytest.fixture
def tile(app):
    """PortfolioTile with no background fetch (thread patched out)."""
    with patch("stonky.app.threading.Thread"):
        t = PortfolioTile(app, "AAPL", on_select=lambda s: None)
    yield t
    try:
        t.destroy()
    except Exception:
        pass


# --------------------------------------------------- StockChartApp ---------

class TestStockChartApp:
    def test_dashboard_is_shown_on_startup(self, app):
        assert app._dashboard.winfo_manager() == "pack"

    def test_chart_view_is_none_on_startup(self, app):
        assert app._chart_view is None

    def test_show_chart_creates_chart_view(self, app):
        with patch("stonky.app.threading.Thread"):
            app._show_chart("AAPL")
        assert app._chart_view is not None
        assert isinstance(app._chart_view, ChartView)

    def test_show_chart_hides_dashboard(self, app):
        with patch("stonky.app.threading.Thread"):
            app._show_chart("AAPL")
        assert not app._dashboard.winfo_ismapped()

    def test_show_dashboard_hides_chart_view(self, app):
        with patch("stonky.app.threading.Thread"):
            app._show_chart("AAPL")
        app._show_dashboard()
        assert app._dashboard.winfo_manager() == "pack"

    def test_show_chart_twice_replaces_chart_view(self, app):
        with patch("stonky.app.threading.Thread"):
            app._show_chart("AAPL")
            first = app._chart_view
            app._show_chart("MSFT")
        assert app._chart_view is not first
        assert app._chart_view._symbol == "MSFT"


# ------------------------------------------------------ DashboardView ------

class TestDashboardView:
    def test_creates_tile_for_each_symbol(self, app):
        inner = app._dashboard._inner
        tiles = [w for w in inner.winfo_children() if isinstance(w, PortfolioTile)]
        assert len(tiles) == 2

    def test_tile_symbols_match_portfolio(self, app):
        inner = app._dashboard._inner
        symbols = {w._symbol for w in inner.winfo_children() if isinstance(w, PortfolioTile)}
        assert symbols == {"AAPL", "MSFT"}

    def test_on_select_callback_is_forwarded(self, app):
        selected = []
        with patch("stonky.app.threading.Thread"):
            view = DashboardView(app, ["TSLA"], on_select=lambda s: selected.append(s))
        tile = next(
            w for w in view._inner.winfo_children() if isinstance(w, PortfolioTile)
        )
        tile._on_select("TSLA")
        assert selected == ["TSLA"]
        view.destroy()


# ------------------------------------------------------ PortfolioTile ------

class TestPortfolioTile:
    def test_initial_name_shows_loading(self, tile):
        assert tile._name_lbl.cget("text") == "Loading…"

    def test_initial_price_shows_dash(self, tile):
        assert tile._price_lbl.cget("text") == "—"

    def test_symbol_label_shows_symbol(self, tile):
        assert tile._sym_lbl.cget("text") == "AAPL"

    def test_update_sets_price(self, tile):
        tile._update(_make_quote(last_price=150.25))
        assert tile._price_lbl.cget("text") == "150.25"

    def test_update_sets_name(self, tile):
        tile._update(_make_quote())
        assert tile._name_lbl.cget("text") == "Apple Inc."

    def test_update_shows_positive_change(self, tile):
        tile._update(_make_quote(last_price=150.0, previous_close=148.0))
        text = tile._change_lbl.cget("text")
        assert text.startswith("+")
        assert "2.00" in text

    def test_update_shows_negative_change(self, tile):
        tile._update(_make_quote(last_price=146.0, previous_close=148.0))
        text = tile._change_lbl.cget("text")
        assert text.startswith("-")

    def test_poll_calls_update_when_quote_pending(self, tile):
        q = _make_quote(last_price=200.0)
        tile._pending_quote = q
        tile._poll()
        assert tile._price_lbl.cget("text") == "200.00"

    def test_poll_shows_unavailable_on_exception(self, tile):
        tile._pending_quote = RuntimeError("network error")
        tile._poll()
        assert tile._name_lbl.cget("text") == "Unavailable"

    def test_poll_clears_pending_quote_after_consuming(self, tile):
        tile._pending_quote = _make_quote()
        tile._poll()
        assert tile._pending_quote is None

    def test_double_click_calls_on_select(self, app):
        selected = []
        with patch("stonky.app.threading.Thread"):
            t = PortfolioTile(app, "TSLA", on_select=lambda s: selected.append(s))
        # Double-click binding delegates to _on_select; invoke it directly
        # (event_generate with Double modifier is blocked in headless Xvfb)
        t._on_select(t._symbol)
        assert selected == ["TSLA"]
        t.destroy()


# --------------------------------------------------------- ChartView --------

class TestChartViewInit:
    def test_initial_status_contains_symbol(self, chart_view):
        assert "AAPL" in chart_view._status_var.get()

    def test_default_period_is_1y(self, chart_view):
        assert chart_view._current_period.get() == "1y"

    def test_info_labels_start_with_dash(self, chart_view):
        for key in ("Company", "Exchange", "Currency", "Open", "High", "Low", "Close", "Change"):
            assert chart_view._info_labels[key].cget("text") == "—"


class TestChartViewFetchAndPlot:
    def test_sets_pending_data_on_success(self, chart_view):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            chart_view._fetch_and_plot("AAPL", "1y")
        assert chart_view._pending_data is data

    def test_sets_error_string_on_value_error(self, chart_view):
        with patch("stonky.app.fetch_stock_data", side_effect=ValueError("No data found")):
            chart_view._fetch_and_plot("FAKE", "1y")
        assert chart_view._pending_data == "No data found"

    def test_sets_error_string_on_unexpected_exception(self, chart_view):
        with patch("stonky.app.fetch_stock_data", side_effect=RuntimeError("timeout")):
            chart_view._fetch_and_plot("AAPL", "1y")
        assert "timeout" in chart_view._pending_data

    def test_calls_fetch_with_correct_args(self, chart_view):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data) as mock_fetch:
            chart_view._fetch_and_plot("AAPL", "6mo")
        mock_fetch.assert_called_once_with("AAPL", "6mo")


class TestChartViewPoll:
    def test_renders_chart_when_stock_data_pending(self, chart_view):
        data = _make_stock_data()
        chart_view._pending_data = data
        chart_view._poll()
        assert "AAPL" in chart_view._status_var.get()

    def test_shows_error_when_string_pending(self, chart_view):
        chart_view._pending_data = "No data found"
        chart_view._poll()
        assert "No data found" in chart_view._status_var.get()

    def test_clears_pending_data_after_consuming(self, chart_view):
        chart_view._pending_data = _make_stock_data()
        chart_view._poll()
        assert chart_view._pending_data is None

    def test_does_not_modify_status_when_nothing_pending(self, chart_view):
        chart_view._status_var.set("previous status")
        chart_view._pending_data = None
        chart_view._poll()
        assert chart_view._status_var.get() == "previous status"


class TestChartViewRender:
    def test_updates_status_with_symbol(self, chart_view):
        chart_view._render_chart(_make_stock_data("AAPL"))
        assert "AAPL" in chart_view._status_var.get()

    def test_updates_exchange_label(self, chart_view):
        chart_view._render_chart(_make_stock_data())
        assert chart_view._info_labels["Exchange"].cget("text") == "NMS"

    def test_updates_currency_label(self, chart_view):
        chart_view._render_chart(_make_stock_data())
        assert chart_view._info_labels["Currency"].cget("text") == "USD"

    def test_updates_company_label(self, chart_view):
        chart_view._render_chart(_make_stock_data())
        assert chart_view._info_labels["Company"].cget("text") != "—"

    def test_shows_error_on_render_failure(self, chart_view):
        data = _make_stock_data()
        with patch.object(chart_view, "_render_chart_inner", side_effect=RuntimeError("bad render")):
            chart_view._render_chart(data)
        assert "bad render" in chart_view._status_var.get()

    def test_render_failure_does_not_raise(self, chart_view):
        data = _make_stock_data()
        with patch.object(chart_view, "_render_chart_inner", side_effect=RuntimeError("oops")):
            chart_view._render_chart(data)  # must not raise


class TestChartViewBack:
    def test_back_button_calls_on_back(self, app):
        called = []
        with patch("stonky.app.threading.Thread"):
            view = ChartView(app, "AAPL", on_back=lambda: called.append(True))
        view._on_back()
        assert called == [True]
        view.destroy()


class TestChartViewFullFlow:
    def test_successful_fetch_updates_status(self, chart_view):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            chart_view._fetch_and_plot("AAPL", "1y")
        chart_view._poll()
        status = chart_view._status_var.get()
        assert "Showing" in status
        assert "AAPL" in status

    def test_successful_fetch_populates_info_panel(self, chart_view):
        data = _make_stock_data()
        with patch("stonky.app.fetch_stock_data", return_value=data):
            chart_view._fetch_and_plot("AAPL", "1y")
        chart_view._poll()
        assert chart_view._info_labels["Currency"].cget("text") == "USD"
        assert chart_view._info_labels["Exchange"].cget("text") == "NMS"

    def test_failed_fetch_shows_error_in_status(self, chart_view):
        with patch("stonky.app.fetch_stock_data",
                   side_effect=ValueError('No data found for "FAKE"')):
            chart_view._fetch_and_plot("FAKE", "1y")
        chart_view._poll()
        assert "Error" in chart_view._status_var.get()

    def test_fetch_runs_off_main_thread(self, chart_view):
        """Fetch must NOT block the UI thread."""
        called_from: list[threading.Thread] = []

        def recording_fetch(symbol, period):
            called_from.append(threading.current_thread())
            return _make_stock_data(symbol, period)

        with patch("stonky.app.fetch_stock_data", side_effect=recording_fetch):
            chart_view._load_data()
            # Find and join the thread that was just started
            for t in threading.enumerate():
                if t.daemon and t is not threading.main_thread():
                    t.join(timeout=5.0)

        assert len(called_from) >= 1
        assert called_from[0] is not threading.main_thread()
