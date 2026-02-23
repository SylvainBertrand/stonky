"""Frontend: stock price history chart viewer (tkinter UI)."""

import threading
import tkinter as tk
from tkinter import messagebox

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from stonky.data import StockData, fetch_stock_data


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


class StockChartApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Stock Price History")
        self.geometry("1100x720")
        self.minsize(800, 560)
        self.configure(bg=DARK_BG)

        self._current_period = tk.StringVar(value="1y")
        self._current_symbol = ""
        self._fetch_thread = None

        self._build_ui()

    # ------------------------------------------------------------------ UI ---

    def _build_ui(self):
        # ── Top search bar ──────────────────────────────────────────────────
        top = tk.Frame(self, bg=DARK_BG, pady=14, padx=20)
        top.pack(fill=tk.X)

        tk.Label(
            top, text="Stock Chart", font=("Helvetica", 18, "bold"),
            fg=TEXT, bg=DARK_BG
        ).pack(side=tk.LEFT, padx=(0, 20))

        self._search_var = tk.StringVar()
        entry = tk.Entry(
            top, textvariable=self._search_var,
            font=("Helvetica", 14), width=14,
            bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, bd=0, highlightthickness=2,
            highlightcolor=ACCENT, highlightbackground=BORDER,
        )
        entry.pack(side=tk.LEFT, ipady=6, padx=(0, 8))
        entry.bind("<Return>", lambda _e: self._trigger_search())
        entry.focus_set()

        search_btn = tk.Button(
            top, text="Search",
            font=("Helvetica", 12, "bold"),
            bg=ACCENT, fg="#ffffff", activebackground="#9d8ff9",
            relief=tk.FLAT, bd=0, padx=16, pady=6, cursor="hand2",
            command=self._trigger_search,
        )
        search_btn.pack(side=tk.LEFT, padx=(0, 20))

        # ── Period selector ────────────────────────────────────────────────
        tk.Label(top, text="Period:", fg=SUBTEXT, bg=DARK_BG,
                 font=("Helvetica", 11)).pack(side=tk.LEFT, padx=(0, 6))

        for period, label in zip(PERIODS, PERIOD_LABELS):
            rb = tk.Radiobutton(
                top, text=label, value=period,
                variable=self._current_period,
                font=("Helvetica", 11),
                bg=DARK_BG, fg=SUBTEXT,
                selectcolor=PANEL_BG, activebackground=DARK_BG,
                activeforeground=TEXT, indicatoron=False,
                relief=tk.FLAT, bd=0, padx=8, pady=4,
                cursor="hand2",
                command=self._on_period_change,
            )
            rb.pack(side=tk.LEFT, padx=2)

        # ── Status bar ─────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Enter a ticker symbol and press Search.")
        status_bar = tk.Label(
            self, textvariable=self._status_var,
            font=("Helvetica", 10), fg=SUBTEXT, bg=DARK_BG, anchor="w",
            padx=22,
        )
        status_bar.pack(fill=tk.X)

        # ── Chart area ─────────────────────────────────────────────────────
        chart_frame = tk.Frame(self, bg=DARK_BG, padx=16, pady=8)
        chart_frame.pack(fill=tk.BOTH, expand=True)

        self._fig = Figure(facecolor=DARK_BG)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(PANEL_BG)
        self._ax.tick_params(colors=SUBTEXT)
        for spine in self._ax.spines.values():
            spine.set_edgecolor(BORDER)
        self._ax.set_xlabel("Date", color=SUBTEXT)
        self._ax.set_ylabel("Price (USD)", color=SUBTEXT)
        self._ax.set_title("Search for a ticker symbol to get started", color=TEXT,
                            fontsize=13, pad=12)
        self._fig.tight_layout(pad=2.5)

        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar_frame = tk.Frame(chart_frame, bg=DARK_BG)
        toolbar_frame.pack(fill=tk.X)
        toolbar = NavigationToolbar2Tk(self._canvas, toolbar_frame)
        toolbar.config(bg=DARK_BG)
        toolbar.update()

        # ── Info panel ─────────────────────────────────────────────────────
        self._info_frame = tk.Frame(self, bg=DARK_BG, padx=20, pady=6)
        self._info_frame.pack(fill=tk.X)
        self._info_labels: dict[str, tk.Label] = {}
        for key in ("Company", "Exchange", "Currency", "Open",
                    "High", "Low", "Close", "Change"):
            col = tk.Frame(self._info_frame, bg=PANEL_BG,
                           padx=12, pady=6, relief=tk.FLAT)
            col.pack(side=tk.LEFT, padx=4, pady=4)
            tk.Label(col, text=key.upper(), fg=SUBTEXT, bg=PANEL_BG,
                     font=("Helvetica", 8, "bold")).pack(anchor="w")
            lbl = tk.Label(col, text="—", fg=TEXT, bg=PANEL_BG,
                           font=("Helvetica", 11, "bold"))
            lbl.pack(anchor="w")
            self._info_labels[key] = lbl

    # ----------------------------------------------------------- actions -----

    def _trigger_search(self):
        symbol = self._search_var.get().strip().upper()
        if not symbol:
            self._status_var.set("Please enter a ticker symbol.")
            return
        self._current_symbol = symbol
        self._load_data()

    def _on_period_change(self):
        if self._current_symbol:
            self._load_data()

    def _load_data(self):
        symbol = self._current_symbol
        period = self._current_period.get()
        self._status_var.set(f"Fetching data for {symbol}…")
        self._fetch_thread = threading.Thread(
            target=self._fetch_and_plot, args=(symbol, period), daemon=True
        )
        self._fetch_thread.start()

    def _fetch_and_plot(self, symbol: str, period: str):
        try:
            data = fetch_stock_data(symbol, period)
            self.after(0, self._render_chart, data)
        except ValueError as exc:
            self.after(0, self._show_error, str(exc))
        except Exception as exc:
            self.after(0, self._show_error, f"Error fetching data: {exc}")

    # ---------------------------------------------------------- rendering -----

    def _render_chart(self, data: StockData):
        try:
            self._render_chart_inner(data)
        except Exception as exc:
            self._show_error(f"Error rendering chart: {exc}")

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
            val = closes[idx]
            self._ax.annotate(
                label_text,
                xy=(idx, val), xytext=(0, 20 if va == "bottom" else -20),
                textcoords="offset points",
                arrowprops=dict(arrowstyle="-", color=SUBTEXT, lw=1),
                color=SUBTEXT, fontsize=8, ha="center", va=va,
            )

        self._fig.tight_layout(pad=2.5)
        self._canvas.draw()

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

    def _show_error(self, msg: str):
        self._status_var.set(msg)
        messagebox.showerror("Error", msg)


# ----------------------------------------------------------------- main -----

def main():
    app = StockChartApp()
    app.mainloop()


if __name__ == "__main__":
    main()
