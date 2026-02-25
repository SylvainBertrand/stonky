"""Frontend: portfolio dashboard and stock price chart viewer (tkinter UI)."""

import threading
import tkinter as tk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from stonky.data import Quote, StockData, fetch_quote, fetch_stock_data, load_portfolio


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
        self._current_period = tk.StringVar(value="1y")

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

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value=f"Loading {self._symbol}…")
        tk.Label(
            self, textvariable=self._status_var,
            font=("Helvetica", 10), fg=SUBTEXT, bg=DARK_BG, anchor="w", padx=22,
        ).pack(fill=tk.X)

        # ── Chart area ────────────────────────────────────────────────────────
        chart_frame = tk.Frame(self, bg=DARK_BG, padx=16, pady=8)
        chart_frame.pack(fill=tk.BOTH, expand=True)

        self._fig = Figure(facecolor=DARK_BG)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(PANEL_BG)
        self._ax.tick_params(colors=SUBTEXT)
        for spine in self._ax.spines.values():
            spine.set_edgecolor(BORDER)
        self._ax.set_xlabel("Date", color=SUBTEXT)
        self._ax.set_ylabel("Price", color=SUBTEXT)
        self._ax.set_title(f"Loading {self._symbol}…", color=TEXT, fontsize=13, pad=12)
        self._fig.tight_layout(pad=2.5)

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

    # ----------------------------------------------------------- actions -----

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

    def _render_chart_inner(self, data: StockData):
        self._ax.clear()
        self._ax.set_facecolor(PANEL_BG)

        dates = data.history.index
        closes = data.history["Close"]

        net_change = closes.iloc[-1] - closes.iloc[0]
        line_color = GREEN if net_change >= 0 else RED

        self._ax.plot(dates, closes, color=line_color, linewidth=1.8, zorder=3)
        self._ax.fill_between(dates, closes, closes.min(),
                               color=line_color, alpha=0.15, zorder=2)

        self._ax.grid(True, color=BORDER, linestyle="--",
                      linewidth=0.5, alpha=0.6, zorder=1)
        self._ax.set_axisbelow(True)

        self._ax.tick_params(colors=SUBTEXT, which="both")
        for spine in self._ax.spines.values():
            spine.set_edgecolor(BORDER)

        self._ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        self._ax.xaxis.set_major_locator(
            mdates.AutoDateLocator(minticks=4, maxticks=10)
        )
        self._fig.autofmt_xdate(rotation=30, ha="right")

        self._ax.set_xlabel("Date", color=SUBTEXT, labelpad=6)
        self._ax.set_ylabel(f"Price ({data.currency})", color=SUBTEXT, labelpad=6)

        period_label = PERIOD_LABELS[PERIODS.index(data.period)]
        self._ax.set_title(
            f"{data.long_name} ({data.symbol})  —  {period_label}",
            color=TEXT, fontsize=13, pad=12,
        )

        idx_max = closes.idxmax()
        idx_min = closes.idxmin()
        for idx, va, label_text in [
            (idx_max, "bottom", f"High\n{closes[idx_max]:.2f}"),
            (idx_min, "top",    f"Low\n{closes[idx_min]:.2f}"),
        ]:
            self._ax.annotate(
                label_text,
                xy=(idx, closes[idx]),
                xytext=(0, 20 if va == "bottom" else -20),
                textcoords="offset points",
                arrowprops=dict(arrowstyle="-", color=SUBTEXT, lw=1),
                color=SUBTEXT, fontsize=8, ha="center", va=va,
            )

        self._fig.tight_layout(pad=2.5)
        self._canvas_widget.draw()

        last = data.history.iloc[-1]
        prev_close = data.history["Close"].iloc[-2] if len(data.history) > 1 else last["Open"]
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
            f"Showing {len(data.history)} trading days for {data.symbol}. "
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
