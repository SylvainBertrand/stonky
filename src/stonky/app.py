"""Frontend: portfolio dashboard and stock price chart viewer (tkinter UI)."""

import threading
import tkinter as tk

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from stonky.data import Quote, StockData, fetch_quote, fetch_stock_data, load_portfolio
from stonky.indicators import bollinger_bands, ema, macd, rsi, sma


PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
PERIOD_LABELS = ["1 Month", "3 Months", "6 Months", "1 Year", "2 Years", "5 Years"]

DARK_BG = "#1e1e2e"
PANEL_BG = "#2a2a3e"
ACCENT = "#7c6af7"
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
ENTRY_BG = "#313244"
GREEN = "#a6e3a1"
RED = "#f38ba8"
BORDER = "#45475a"

# Indicator overlay colours
COLOR_SMA20 = "#89b4fa"
COLOR_SMA50 = "#f9e2af"
COLOR_SMA200 = "#cba6f7"
COLOR_EMA20 = "#94e2d5"
COLOR_BB = "#585b70"
COLOR_SIGNAL = "#f9e2af"

# Subplot height weights (proportional)
_PANEL_WEIGHTS = {"volume": 18, "rsi": 16, "macd": 16}
_MAIN_WEIGHT = 60


# ---------------------------------------------------------------- views -----

class StockChartApp(tk.Tk):
    """Root window — thin container that manages the active view."""

    def __init__(self, portfolio_path):
        super().__init__()
        self.title("Stonky")
        self.geometry("1200x800")
        self.minsize(900, 600)
        self.configure(bg=DARK_BG)

        symbols = load_portfolio(portfolio_path)
        self._dashboard = DashboardView(self, symbols, on_select=self._show_chart)
        self._chart_view: ChartView | None = None
        self._show_dashboard()

        self.lift()
        self.attributes("-topmost", True)
        self.after_idle(self.attributes, "-topmost", False)

    def _show_dashboard(self):
        if self._chart_view is not None:
            self._chart_view.pack_forget()
        self._dashboard.pack(fill=tk.BOTH, expand=True)

    def _show_chart(self, symbol: str):
        self._dashboard.pack_forget()
        if self._chart_view is not None:
            self._chart_view.destroy()
        self._chart_view = ChartView(self, symbol, on_back=self._show_dashboard)
        self._chart_view.pack(fill=tk.BOTH, expand=True)


class DashboardView(tk.Frame):
    """Scrollable grid of PortfolioTile widgets."""

    COLS = 4

    def __init__(self, master, symbols: list[str], *, on_select):
        super().__init__(master, bg=DARK_BG)

        # ── Header ──────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=DARK_BG, pady=14, padx=20)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="Portfolio Dashboard",
            font=("Helvetica", 18, "bold"), fg=TEXT, bg=DARK_BG,
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            text=f"{len(symbols)} stocks  —  double-click a tile to view chart",
            font=("Helvetica", 10), fg=SUBTEXT, bg=DARK_BG,
        ).pack(side=tk.LEFT, padx=(20, 0))

        # ── Scrollable canvas ────────────────────────────────────────────────
        container = tk.Frame(self, bg=DARK_BG)
        container.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._canvas = tk.Canvas(
            container, bg=DARK_BG, highlightthickness=0,
            yscrollcommand=scrollbar.set,
        )
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._canvas.yview)

        self._inner = tk.Frame(self._canvas, bg=DARK_BG)
        self._window_id = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw",
        )

        self._inner.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._canvas.bind(seq, self._on_mousewheel)

        # ── Tiles ────────────────────────────────────────────────────────────
        for i, sym in enumerate(symbols):
            row, col = divmod(i, self.COLS)
            PortfolioTile(self._inner, sym, on_select=on_select).grid(
                row=row, column=col, padx=10, pady=10,
            )

    def _on_frame_configure(self, _e=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._window_id, width=e.width)

    def _on_mousewheel(self, e):
        if e.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


class PortfolioTile(tk.Frame):
    """Fixed-size card showing live quote data for one stock."""

    W, H = 220, 120

    def __init__(self, master, symbol: str, *, on_select):
        super().__init__(
            master, bg=PANEL_BG, width=self.W, height=self.H,
            relief=tk.FLAT, cursor="hand2",
        )
        self.pack_propagate(False)
        self._symbol = symbol
        self._on_select = on_select
        self._pending_quote = None

        self._sym_lbl = tk.Label(
            self, text=symbol, font=("Helvetica", 14, "bold"), fg=TEXT, bg=PANEL_BG,
        )
        self._sym_lbl.pack(anchor="w", padx=10, pady=(10, 0))

        self._name_lbl = tk.Label(
            self, text="Loading…", font=("Helvetica", 9), fg=SUBTEXT, bg=PANEL_BG,
        )
        self._name_lbl.pack(anchor="w", padx=10)

        self._price_lbl = tk.Label(
            self, text="—", font=("Helvetica", 16, "bold"), fg=TEXT, bg=PANEL_BG,
        )
        self._price_lbl.pack(anchor="w", padx=10, pady=(6, 0))

        self._change_lbl = tk.Label(
            self, text="", font=("Helvetica", 10), fg=SUBTEXT, bg=PANEL_BG,
        )
        self._change_lbl.pack(anchor="w", padx=10)

        for w in (self, self._sym_lbl, self._name_lbl, self._price_lbl, self._change_lbl):
            w.bind("<Double-Button-1>", lambda _e: self._on_select(self._symbol))

        threading.Thread(target=self._fetch, daemon=True).start()
        self._poll()

    def _fetch(self):
        try:
            self._pending_quote = fetch_quote(self._symbol)
        except Exception as exc:
            self._pending_quote = exc

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._pending_quote is not None:
            q = self._pending_quote
            self._pending_quote = None
            if isinstance(q, Quote):
                self._update(q)
            else:
                self._name_lbl.config(text="Unavailable")
        else:
            self.after(100, self._poll)

    def _update(self, q: Quote):
        sign = "+" if q.change >= 0 else ""
        color = GREEN if q.change >= 0 else RED
        self._name_lbl.config(text=(q.long_name or q.symbol)[:24])
        self._price_lbl.config(text=f"{q.last_price:.2f}")
        self._change_lbl.config(
            text=f"{sign}{q.change:.2f} ({sign}{q.change_pct:.2f}%)",
            fg=color,
        )


class ChartView(tk.Frame):
    """Chart panel for a single stock symbol."""

    def __init__(self, master, symbol: str, *, on_back):
        super().__init__(master, bg=DARK_BG)
        self._symbol = symbol
        self._on_back = on_back
        self._pending_data = None
        self._current_data: StockData | None = None
        self._current_period = tk.StringVar(value="1y")

        # Indicator state
        self._chart_type = tk.StringVar(value="line")
        self._show_sma20 = tk.BooleanVar(value=False)
        self._show_sma50 = tk.BooleanVar(value=False)
        self._show_sma200 = tk.BooleanVar(value=False)
        self._show_ema20 = tk.BooleanVar(value=False)
        self._show_bb = tk.BooleanVar(value=False)
        self._show_volume = tk.BooleanVar(value=True)
        self._show_rsi = tk.BooleanVar(value=False)
        self._show_macd = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_data()
        self._poll()

    # --------------------------------------------------------------- UI -----

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        top = tk.Frame(self, bg=DARK_BG, pady=14, padx=20)
        top.pack(fill=tk.X)

        tk.Button(
            top, text="← Back",
            font=("Helvetica", 11), bg=PANEL_BG, fg=TEXT,
            activebackground=ENTRY_BG, relief=tk.FLAT, bd=0,
            padx=10, pady=4, cursor="hand2",
            command=self._on_back,
        ).pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(
            top, text=f"Stock Chart — {self._symbol}",
            font=("Helvetica", 18, "bold"), fg=TEXT, bg=DARK_BG,
        ).pack(side=tk.LEFT, padx=(0, 20))

        # ── Period selector ───────────────────────────────────────────────────
        tk.Label(
            top, text="Period:", fg=SUBTEXT, bg=DARK_BG, font=("Helvetica", 11),
        ).pack(side=tk.LEFT, padx=(0, 6))

        for period, label in zip(PERIODS, PERIOD_LABELS):
            tk.Radiobutton(
                top, text=label, value=period,
                variable=self._current_period,
                font=("Helvetica", 11),
                bg=DARK_BG, fg=SUBTEXT,
                selectcolor=PANEL_BG, activebackground=DARK_BG,
                activeforeground=TEXT, indicatoron=False,
                relief=tk.FLAT, bd=0, padx=8, pady=4,
                cursor="hand2",
                command=self._load_data,
            ).pack(side=tk.LEFT, padx=2)

        # ── Indicator toolbar ─────────────────────────────────────────────────
        self._build_indicator_toolbar()

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value=f"Loading {self._symbol}…")
        tk.Label(
            self, textvariable=self._status_var,
            font=("Helvetica", 10), fg=SUBTEXT, bg=DARK_BG, anchor="w", padx=22,
        ).pack(fill=tk.X)

        # ── Chart area ────────────────────────────────────────────────────────
        chart_frame = tk.Frame(self, bg=DARK_BG, padx=16, pady=8)
        chart_frame.pack(fill=tk.BOTH, expand=True)

        self._fig = Figure(facecolor=DARK_BG, layout="constrained")

        self._canvas_widget = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas_widget.draw()
        self._canvas_widget.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar_frame = tk.Frame(chart_frame, bg=DARK_BG)
        toolbar_frame.pack(fill=tk.X)
        toolbar = NavigationToolbar2Tk(self._canvas_widget, toolbar_frame)
        toolbar.config(bg=DARK_BG)
        toolbar.update()

        # ── Info panel ────────────────────────────────────────────────────────
        info_frame = tk.Frame(self, bg=DARK_BG, padx=20, pady=6)
        info_frame.pack(fill=tk.X)
        self._info_labels: dict[str, tk.Label] = {}
        for key in ("Company", "Exchange", "Currency", "Open", "High", "Low", "Close", "Change"):
            col = tk.Frame(info_frame, bg=PANEL_BG, padx=12, pady=6, relief=tk.FLAT)
            col.pack(side=tk.LEFT, padx=4, pady=4)
            tk.Label(col, text=key.upper(), fg=SUBTEXT, bg=PANEL_BG,
                     font=("Helvetica", 8, "bold")).pack(anchor="w")
            lbl = tk.Label(col, text="—", fg=TEXT, bg=PANEL_BG,
                           font=("Helvetica", 11, "bold"))
            lbl.pack(anchor="w")
            self._info_labels[key] = lbl

    def _build_indicator_toolbar(self):
        bar = tk.Frame(self, bg=PANEL_BG, pady=4, padx=16)
        bar.pack(fill=tk.X)

        def _sep():
            tk.Frame(bar, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        def _label(text):
            tk.Label(bar, text=text, fg=SUBTEXT, bg=PANEL_BG,
                     font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=(0, 4))

        def _radio(text, value):
            tk.Radiobutton(
                bar, text=text, value=value, variable=self._chart_type,
                font=("Helvetica", 9), bg=PANEL_BG, fg=TEXT,
                selectcolor=ENTRY_BG, activebackground=PANEL_BG,
                activeforeground=TEXT, indicatoron=False,
                relief=tk.FLAT, bd=0, padx=6, pady=2, cursor="hand2",
                command=self._rerender,
            ).pack(side=tk.LEFT, padx=1)

        def _check(text, var):
            tk.Checkbutton(
                bar, text=text, variable=var,
                font=("Helvetica", 9), bg=PANEL_BG, fg=TEXT,
                selectcolor=ENTRY_BG, activebackground=PANEL_BG,
                activeforeground=TEXT, relief=tk.FLAT, bd=0,
                padx=4, pady=2, cursor="hand2",
                command=self._rerender,
            ).pack(side=tk.LEFT, padx=1)

        _label("Type:")
        _radio("Line", "line")
        _radio("Candle", "candle")

        _sep()
        _label("MA:")
        _check("SMA 20", self._show_sma20)
        _check("SMA 50", self._show_sma50)
        _check("SMA 200", self._show_sma200)
        _check("EMA 20", self._show_ema20)
        _check("BB", self._show_bb)

        _sep()
        _label("Panels:")
        _check("Volume", self._show_volume)
        _check("RSI", self._show_rsi)
        _check("MACD", self._show_macd)

    # ----------------------------------------------------------- actions -----

    def _rerender(self):
        if self._current_data is not None:
            self._render_chart(self._current_data)

    def _load_data(self):
        period = self._current_period.get()
        self._status_var.set(f"Fetching data for {self._symbol}…")
        self._pending_data = None
        threading.Thread(
            target=self._fetch_and_plot, args=(self._symbol, period), daemon=True,
        ).start()

    def _fetch_and_plot(self, symbol: str, period: str):
        try:
            data = fetch_stock_data(symbol, period)
            self._pending_data = data
        except ValueError as exc:
            self._pending_data = str(exc)
        except Exception as exc:
            self._pending_data = f"Error fetching data: {exc}"

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._pending_data is not None:
            data = self._pending_data
            self._pending_data = None
            if isinstance(data, StockData):
                self._render_chart(data)
            else:
                self._status_var.set(f"Error: {data}")
        self.after(100, self._poll)

    # ---------------------------------------------------------- rendering -----

    def _render_chart(self, data: StockData):
        try:
            self._render_chart_inner(data)
        except Exception as exc:
            self._status_var.set(f"Error rendering chart: {exc}")

    def _render_chart_inner(self, data: StockData):  # noqa: PLR0912, PLR0915
        self._current_data = data

        history = data.history
        closes = history["Close"]
        opens = history["Open"]
        dates = history.index

        # ── Build active panel list and gridspec ──────────────────────────────
        active_panels: list[str] = []
        if self._show_volume.get():
            active_panels.append("volume")
        if self._show_rsi.get():
            active_panels.append("rsi")
        if self._show_macd.get():
            active_panels.append("macd")

        height_ratios = [_MAIN_WEIGHT] + [_PANEL_WEIGHTS[p] for p in active_panels]

        self._fig.clear()
        gs = self._fig.add_gridspec(
            len(active_panels) + 1, 1,
            height_ratios=height_ratios,
            hspace=0.05,
        )
        main_ax = self._fig.add_subplot(gs[0])
        sub_axes: dict[str, plt.Axes] = {
            name: self._fig.add_subplot(gs[i + 1], sharex=main_ax)
            for i, name in enumerate(active_panels)
        }

        # ── Style helper ─────────────────────────────────────────────────────
        def _style_ax(ax):
            ax.set_facecolor(PANEL_BG)
            ax.tick_params(colors=SUBTEXT, which="both", labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor(BORDER)

        _style_ax(main_ax)
        for ax in sub_axes.values():
            _style_ax(ax)

        # ── Main panel: line or candlestick ───────────────────────────────────
        if self._chart_type.get() == "candle":
            mc = mpf.make_marketcolors(
                up=GREEN, down=RED,
                edge={"up": GREEN, "down": RED},
                wick={"up": GREEN, "down": RED},
            )
            mpf_style = mpf.make_mpf_style(
                marketcolors=mc,
                facecolor=PANEL_BG,
                gridcolor=BORDER,
                gridstyle="--",
            )
            mpf.plot(
                history,
                type="candle",
                ax=main_ax,
                style=mpf_style,
                volume=False,
                returnfig=False,
            )
        else:
            net_change = closes.iloc[-1] - closes.iloc[0]
            line_color = GREEN if net_change >= 0 else RED
            main_ax.plot(dates, closes, color=line_color, linewidth=1.8, zorder=3)
            main_ax.fill_between(
                dates, closes, closes.min(),
                color=line_color, alpha=0.15, zorder=2,
            )
            main_ax.grid(True, color=BORDER, linestyle="--",
                         linewidth=0.5, alpha=0.6, zorder=1)
            main_ax.set_axisbelow(True)

            idx_max = closes.idxmax()
            idx_min = closes.idxmin()
            for idx, va, label_text in [
                (idx_max, "bottom", f"High\n{closes[idx_max]:.2f}"),
                (idx_min, "top",    f"Low\n{closes[idx_min]:.2f}"),
            ]:
                main_ax.annotate(
                    label_text,
                    xy=(idx, closes[idx]),
                    xytext=(0, 20 if va == "bottom" else -20),
                    textcoords="offset points",
                    arrowprops=dict(arrowstyle="-", color=SUBTEXT, lw=1),
                    color=SUBTEXT, fontsize=8, ha="center", va=va,
                )

        # ── Overlay indicators ────────────────────────────────────────────────
        overlay_active = any([
            self._show_sma20.get(), self._show_sma50.get(), self._show_sma200.get(),
            self._show_ema20.get(), self._show_bb.get(),
        ])

        if self._show_sma20.get():
            main_ax.plot(dates, sma(closes, 20), color=COLOR_SMA20, lw=1.2,
                         label="SMA 20", zorder=4)
        if self._show_sma50.get():
            main_ax.plot(dates, sma(closes, 50), color=COLOR_SMA50, lw=1.2,
                         label="SMA 50", zorder=4)
        if self._show_sma200.get():
            main_ax.plot(dates, sma(closes, 200), color=COLOR_SMA200, lw=1.2,
                         label="SMA 200", zorder=4)
        if self._show_ema20.get():
            main_ax.plot(dates, ema(closes, 20), color=COLOR_EMA20, lw=1.2,
                         label="EMA 20", zorder=4)
        if self._show_bb.get():
            upper, mid, lower = bollinger_bands(closes)
            main_ax.plot(dates, upper, color=COLOR_BB, lw=0.8, ls="--",
                         label="BB Upper", zorder=4)
            main_ax.plot(dates, mid, color=COLOR_BB, lw=0.8, ls="-",
                         label="BB Mid", zorder=4)
            main_ax.plot(dates, lower, color=COLOR_BB, lw=0.8, ls="--",
                         label="BB Lower", zorder=4)
            main_ax.fill_between(dates, upper, lower, color=COLOR_BB, alpha=0.06, zorder=2)

        if overlay_active:
            main_ax.legend(
                facecolor=PANEL_BG, edgecolor=BORDER,
                labelcolor=TEXT, fontsize=8, loc="upper left",
            )

        # ── Volume panel ──────────────────────────────────────────────────────
        if "volume" in sub_axes:
            vol_ax = sub_axes["volume"]
            colors = [GREEN if c >= o else RED for c, o in zip(closes, opens)]
            vol_ax.bar(dates, history["Volume"], color=colors, alpha=0.7, width=0.8)
            vol_ax.set_ylabel("Volume", color=SUBTEXT, fontsize=8, labelpad=4)
            vol_ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x:.0f}")
            )
            vol_ax.grid(True, color=BORDER, linestyle="--", linewidth=0.4, alpha=0.5)

        # ── RSI panel ─────────────────────────────────────────────────────────
        if "rsi" in sub_axes:
            rsi_ax = sub_axes["rsi"]
            rsi_vals = rsi(closes)
            rsi_ax.plot(dates, rsi_vals, color=ACCENT, lw=1.2)
            rsi_ax.axhline(70, color=RED,   lw=0.8, ls="--", alpha=0.7)
            rsi_ax.axhline(30, color=GREEN, lw=0.8, ls="--", alpha=0.7)
            rsi_ax.fill_between(
                dates, rsi_vals, 70, where=rsi_vals >= 70, color=RED, alpha=0.15)
            rsi_ax.fill_between(
                dates, rsi_vals, 30, where=rsi_vals <= 30, color=GREEN, alpha=0.15)
            rsi_ax.set_ylim(0, 100)
            rsi_ax.set_yticks([30, 70])
            rsi_ax.set_ylabel("RSI", color=SUBTEXT, fontsize=8, labelpad=4)
            rsi_ax.grid(True, color=BORDER, linestyle="--", linewidth=0.4, alpha=0.5)

        # ── MACD panel ────────────────────────────────────────────────────────
        if "macd" in sub_axes:
            macd_ax = sub_axes["macd"]
            m_line, s_line, hist = macd(closes)
            macd_ax.plot(dates, m_line, color=ACCENT, lw=1.2, label="MACD")
            macd_ax.plot(dates, s_line, color=COLOR_SIGNAL, lw=1.0, label="Signal")
            hist_colors = [GREEN if v >= 0 else RED for v in hist.fillna(0)]
            macd_ax.bar(dates, hist, color=hist_colors, alpha=0.6, width=0.8)
            macd_ax.axhline(0, color=BORDER, lw=0.8)
            macd_ax.set_ylabel("MACD", color=SUBTEXT, fontsize=8, labelpad=4)
            macd_ax.legend(facecolor=PANEL_BG, edgecolor=BORDER,
                           labelcolor=TEXT, fontsize=7, loc="upper left")
            macd_ax.grid(True, color=BORDER, linestyle="--", linewidth=0.4, alpha=0.5)

        # ── Axis labels: hide x-ticks on all but bottom panel ─────────────────
        all_axes = [main_ax] + [sub_axes[p] for p in active_panels]
        bottom_ax = all_axes[-1]
        for ax in all_axes[:-1]:
            plt.setp(ax.get_xticklabels(), visible=False)

        bottom_ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        bottom_ax.xaxis.set_major_locator(
            mdates.AutoDateLocator(minticks=4, maxticks=10)
        )
        self._fig.autofmt_xdate(rotation=30, ha="right")

        # ── Main axis labels & title ───────────────────────────────────────────
        main_ax.set_ylabel(f"Price ({data.currency})", color=SUBTEXT, labelpad=6)
        period_label = PERIOD_LABELS[PERIODS.index(data.period)]
        main_ax.set_title(
            f"{data.long_name} ({data.symbol})  —  {period_label}",
            color=TEXT, fontsize=13, pad=12,
        )

        self._canvas_widget.draw()

        # ── Info panel ────────────────────────────────────────────────────────
        last = history.iloc[-1]
        prev_close = history["Close"].iloc[-2] if len(history) > 1 else last["Open"]
        change = last["Close"] - prev_close
        pct = (change / prev_close * 100) if prev_close else 0
        change_color = GREEN if change >= 0 else RED
        sign = "+" if change >= 0 else ""

        updates = {
            "Company":  (data.long_name or data.symbol)[:22],
            "Exchange": data.exchange,
            "Currency": data.currency,
            "Open":     f"{last['Open']:.2f}",
            "High":     f"{last['High']:.2f}",
            "Low":      f"{last['Low']:.2f}",
            "Close":    f"{last['Close']:.2f}",
            "Change":   f"{sign}{change:.2f} ({sign}{pct:.2f}%)",
        }
        for key, val in updates.items():
            fg = change_color if key == "Change" else TEXT
            self._info_labels[key].config(text=val, fg=fg)

        self._status_var.set(
            f"Showing {len(history)} trading days for {data.symbol}. "
            f"Last close: {last['Close']:.2f}"
        )


# ----------------------------------------------------------------- main -----

def main():
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Stonky — portfolio dashboard")
    parser.add_argument(
        "portfolio",
        nargs="?",
        default="portfolio.csv",
        help="Path to portfolio CSV (default: portfolio.csv)",
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio)
    try:
        app = StockChartApp(portfolio_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
