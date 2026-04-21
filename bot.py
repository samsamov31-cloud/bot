"""
Stock Signal Telegram Bot v8.0
Tartib:
  1. Rasm (chart + AI strategiya chiziqlari)
  2. Narx va signal (qisqa matn)
  3. Halollik (Musaffa + Akooda)
  4. Yangiliklar
  5. IPO (faqat /ipo buyrug'ida)

pip install requests schedule beautifulsoup4 lxml matplotlib numpy pillow openai
"""

import requests, schedule, time, logging, threading, re, io, json, os
import numpy as np
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# .env fayldan o'qish (lokal ishlatish uchun)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False

try:
    from openai import OpenAI
    OPENAI_OK = True
except ImportError:
    OPENAI_OK = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# ═══════════════════════════════════════════
# SOZLAMALAR — Environment Variables
# Railway Variables bo'limiga qo'shing!
# ═══════════════════════════════════════════
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
POLYGON_KEY      = os.environ.get("POLYGON_KEY",      "")
OPENAI_KEY       = os.environ.get("OPENAI_KEY",       "")

MIN_VOL   = 1_000_000
MIN_CHG   = 2.0
MAX_CHG   = 15.0
MIN_CAP   = 2_000_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO",
    "JPM","V","UNH","XOM","LLY","MA","JNJ","PG","HD","MRK",
    "ABBV","CVX","CRM","BAC","COST","NFLX","AMD","ADBE","WMT",
    "TMO","ACN","ORCL","MCD","QCOM","DIS","TXN","INTC","INTU",
    "AMGN","CAT","GS","HOOD","PLTR","SOFI","COIN","SQ","SNAP",
    "UBER","LYFT","RBLX","PYPL","SHOP","CRWD","DDOG","NET",
    "SNOW","ARM","SMCI","MU","LRCX","AMAT","MRVL","F","GM",
    "WFC","C","MS","BLK","SCHW","AXP","NKE","SBUX","ABNB",
]

chat_history = {}

# ═══════════════════════════════════════════
# POLYGON — NARX VA MA'LUMOTLAR
# ═══════════════════════════════════════════

def get_price(ticker):
    try:
        r = requests.get(
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/"
            + ticker + "?apiKey=" + POLYGON_KEY, timeout=10)
        d = r.json().get("ticker", {})
        day = d.get("day", {}); prev = d.get("prevDay", {}); last = d.get("lastTrade", {})
        return {
            "price":  last.get("p") or day.get("c", 0),
            "open":   day.get("o", 0), "high": day.get("h", 0),
            "low":    day.get("l", 0), "close": day.get("c", 0),
            "volume": day.get("v", 0), "vwap":  day.get("vw", 0),
            "prev":   prev.get("c", 0), "chg":  d.get("todaysChangePerc", 0),
        }
    except Exception:
        return None


def get_candles(ticker, days=90):
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days+30)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://api.polygon.io/v2/aggs/ticker/" + ticker +
            "/range/1/day/" + start + "/" + end +
            "?adjusted=true&sort=asc&limit=150&apiKey=" + POLYGON_KEY, timeout=15)
        d = r.json().get("results", [])
        return d[-days:] if len(d) >= days else d
    except Exception:
        return []


def get_details(ticker):
    try:
        r   = requests.get(
            "https://api.polygon.io/v3/reference/tickers/" + ticker +
            "?apiKey=" + POLYGON_KEY, timeout=10)
        res = r.json().get("results", {})
        return {
            "name":   res.get("name", ticker),
            "sector": res.get("sic_description", "N/A"),
            "cap":    res.get("market_cap", 0) or 0,
            "emp":    res.get("total_employees", 0) or 0,
            "desc":   (res.get("description") or "")[:300],
        }
    except Exception:
        return {"name": ticker, "sector": "N/A", "cap": 0, "emp": 0, "desc": ""}


def get_technicals(ticker):
    res = {"rsi": None, "sma50": None, "sma200": None}
    for ind, win, key in [("rsi",14,"rsi"),("sma",50,"sma50"),("sma",200,"sma200")]:
        try:
            r = requests.get(
                "https://api.polygon.io/v1/indicators/" + ind + "/" + ticker +
                "?timespan=day&window=" + str(win) +
                "&series_type=close&limit=1&apiKey=" + POLYGON_KEY, timeout=10)
            vals = r.json().get("results", {}).get("values", [])
            if vals:
                res[key] = round(vals[0]["value"], 2)
        except Exception:
            pass
        time.sleep(13)
    return res


# ═══════════════════════════════════════════
# TEXNIK TAHLIL — S/R, TREND, ATR, BREAKOUT
# ═══════════════════════════════════════════

def calc_sr(candles):
    if len(candles) < 10:
        return [], []
    highs  = np.array([c["h"] for c in candles])
    lows   = np.array([c["l"] for c in candles])
    closes = np.array([c["c"] for c in candles])
    sups, ress = [], []
    for i in range(3, len(lows)-3):
        if lows[i] == min(lows[i-3:i+4]):
            sups.append(round(lows[i], 2))
    for i in range(3, len(highs)-3):
        if highs[i] == max(highs[i-3:i+4]):
            ress.append(round(highs[i], 2))

    def cluster(lvs, thr=0.02):
        if not lvs: return []
        lvs = sorted(set(lvs)); out = [lvs[0]]
        for lv in lvs[1:]:
            if abs(lv-out[-1])/out[-1] > thr: out.append(lv)
        return out

    cur = closes[-1]
    return (sorted([s for s in cluster(sups) if s < cur], reverse=True)[:4],
            sorted([r for r in cluster(ress) if r > cur])[:4])


def calc_trend(candles, lb=30):
    if len(candles) < lb: lb = len(candles)
    recent = candles[-lb:]
    x = np.arange(len(recent))
    closes = np.array([c["c"] for c in recent])
    slope, intercept = np.polyfit(x, closes, 1)
    if slope > closes[-1]*0.0003:    d = "📈 Yuqoriga"
    elif slope < -closes[-1]*0.0003: d = "📉 Pastga"
    else:                             d = "➡️ Yon"
    return {"slope": slope, "intercept": intercept, "dir": d, "lb": lb}


def calc_atr(candles, p=14):
    if len(candles) < p+1: return 0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return round(np.mean(trs[-p:]), 2)


def detect_breakout(candles, sups, ress, price):
    if not candles or len(candles) < 5: return []
    cur = price.get("price", 0)
    vol = price.get("volume", 0)
    chg = price.get("chg", 0)
    avg_vol = np.mean([c["v"] for c in candles[-20:]]) if len(candles) >= 20 else vol
    vr = vol/avg_vol if avg_vol > 0 else 1
    results = []

    for res in ress:
        dist = (cur-res)/res*100
        if 0 < dist < 3:
            score = 2; omil = ["Resistance yorildi +"+str(round(dist,1))+"%"]
            if vr > 1.5: score += 2; omil.append("Hajm "+str(round(vr,1))+"x")
            if chg > 2:  score += 1; omil.append("O'sish +"+str(round(chg,1))+"%")
            results.append({
                "type": "RESISTANCE YORILDI", "emoji": "⚡",
                "level": res, "score": score, "omillar": omil,
                "signal": "KUCHLI SOTIB OL" if score >= 4 else "EHTIYOT BILAN SOTIB OL",
            })
        elif -1 < dist <= 0:
            results.append({
                "type": "Resistance ga yaqin", "emoji": "🔔",
                "level": res, "score": 1, "omillar": ["$"+str(res)+" — kuzat"],
                "signal": "KUZAT",
            })

    for sup in sups:
        dist = (sup-cur)/sup*100
        if 0 < dist < 3:
            score = 2; omil = ["Support yorildi -"+str(round(dist,1))+"%"]
            if vr > 1.5: score += 2; omil.append("Hajm "+str(round(vr,1))+"x")
            if chg < -2: score += 1; omil.append("Tushish "+str(round(chg,1))+"%")
            results.append({
                "type": "SUPPORT YORILDI", "emoji": "⚠️",
                "level": sup, "score": score, "omillar": omil,
                "signal": "KUCHLI SOT" if score >= 4 else "EHTIYOT BO'L",
            })
        elif -1 < dist <= 0:
            results.append({
                "type": "Support ga yaqin", "emoji": "🔔",
                "level": sup, "score": 1, "omillar": ["$"+str(sup)+" — kuzat"],
                "signal": "KUZAT",
            })
    return results


# ═══════════════════════════════════════════
# CHART — RASM (AI STRATEGIYA CHIZIQLARI)
# ═══════════════════════════════════════════

def draw_chart(ticker, candles, sups, ress, price, trend, breakouts, atr, ai_levels=None):
    """
    TradingView uslubida professional chart.
    ai_levels = {"buy_zone": float, "stop_loss": float, "take_profit": float}
    """
    if not MATPLOTLIB_OK or len(candles) < 10:
        return None
    try:
        # ── Layout: 4 panel ──
        fig = plt.figure(figsize=(18, 11), facecolor="#131722")
        gs  = fig.add_gridspec(
            4, 1,
            height_ratios=[5, 1, 1, 1],
            hspace=0.0,
            left=0.01, right=0.88,
            top=0.93, bottom=0.06
        )
        ax1 = fig.add_subplot(gs[0])   # Narx
        ax2 = fig.add_subplot(gs[1], sharex=ax1)  # Hajm
        ax3 = fig.add_subplot(gs[2], sharex=ax1)  # RSI
        ax4 = fig.add_subplot(gs[3], sharex=ax1)  # MACD

        BG    = "#131722"
        GRID  = "#1e222d"
        BULL  = "#26a69a"
        BEAR  = "#ef5350"
        TEXT  = "#d1d4dc"
        MUTED = "#4a4e5a"

        for ax in [ax1, ax2, ax3, ax4]:
            ax.set_facecolor(BG)
            ax.tick_params(colors=MUTED, labelsize=8, length=3, width=0.5)
            for sp in ax.spines.values():
                sp.set_color(GRID)
                sp.set_linewidth(0.5)
            ax.yaxis.set_label_position("right")
            ax.yaxis.tick_right()
            ax.grid(True, color=GRID, linewidth=0.4, alpha=0.8)

        opens  = np.array([c["o"] for c in candles])
        highs  = np.array([c["h"] for c in candles])
        lows   = np.array([c["l"] for c in candles])
        closes = np.array([c["c"] for c in candles])
        vols   = np.array([c["v"] for c in candles])
        ts     = [c.get("t", 0) for c in candles]
        n      = len(candles)
        xs     = np.arange(n)

        # ── X o'qi: sana yorliqlari ──
        step  = max(1, n // 8)
        xtick_pos  = list(range(0, n, step))
        xtick_lbls = []
        for idx in xtick_pos:
            t = ts[idx]
            if t:
                from datetime import datetime as dt
                xtick_lbls.append(dt.fromtimestamp(t/1000).strftime("%d %b"))
            else:
                xtick_lbls.append("")
        for ax in [ax2, ax3, ax4]:
            ax.set_xticks(xtick_pos)
            ax.set_xticklabels(xtick_lbls, fontsize=7, color=MUTED)
        ax1.set_xticks(xtick_pos)
        ax1.set_xticklabels([], visible=False)

        # ── Bollinger Bands (20,2) ──
        if n >= 20:
            bb_mid  = np.convolve(closes, np.ones(20)/20, mode="valid")
            bb_std  = np.array([closes[i:i+20].std() for i in range(n-19)])
            bb_up   = bb_mid + 2*bb_std
            bb_dn   = bb_mid - 2*bb_std
            bx      = np.arange(19, n)
            ax1.plot(bx, bb_up, color="#5c6bc0", linewidth=0.7,
                     linestyle=":", alpha=0.6, label="BB")
            ax1.plot(bx, bb_dn, color="#5c6bc0", linewidth=0.7,
                     linestyle=":", alpha=0.6)
            ax1.fill_between(bx, bb_dn, bb_up,
                             color="#5c6bc0", alpha=0.04)

        # ── SMA 20 ──
        if n >= 20:
            sma20 = np.convolve(closes, np.ones(20)/20, mode="valid")
            ax1.plot(range(19, n), sma20, color="#7986cb",
                     linewidth=1.0, label="MA20", zorder=4, alpha=0.9)

        # ── SMA 50 ──
        if n >= 50:
            sma50 = np.convolve(closes, np.ones(50)/50, mode="valid")
            ax1.plot(range(49, n), sma50, color="#f59e0b",
                     linewidth=1.0, label="MA50", zorder=4, alpha=0.9)

        # ── SMA 200 ──
        if n >= 200:
            sma200 = np.convolve(closes, np.ones(200)/200, mode="valid")
            ax1.plot(range(199, n), sma200, color="#ef5350",
                     linewidth=0.8, label="MA200", zorder=4, alpha=0.7)

        # ── SHAMLAR ──
        w = 0.6
        for i in range(n):
            o_, h_, l_, c_ = opens[i], highs[i], lows[i], closes[i]
            bull = c_ >= o_
            col  = BULL if bull else BEAR
            # Sham tanasi
            body_h = max(abs(c_ - o_), (h_ - l_) * 0.003)
            ax1.bar(i, body_h, bottom=min(o_, c_),
                    color=col, width=w, zorder=3,
                    edgecolor=col, linewidth=0.3)
            # Wick
            ax1.plot([i, i], [l_, h_],
                     color=col, linewidth=0.7, zorder=2, solid_capstyle="round")

        # ── SUPPORT ZONALAR (ko'k to'rtburchak, TradingView uslubi) ──
        for idx, s in enumerate(sups[:3]):
            zone_h = s * 0.008
            ax1.axhspan(s - zone_h, s + zone_h,
                        color="#00bcd4", alpha=0.12, zorder=1)
            ax1.axhline(y=s, color="#00bcd4", linewidth=1.0,
                        linestyle="--", alpha=0.8, zorder=4)
            ax1.annotate(
                "S" + str(idx+1) + "  $" + str(round(s, 2)),
                xy=(n - 1, s),
                xytext=(n + 0.5, s),
                fontsize=8, color="#00bcd4", fontweight="bold",
                va="center", annotation_clip=False
            )

        # ── RESISTANCE ZONALAR (qizil to'rtburchak) ──
        for idx, r in enumerate(ress[:3]):
            zone_h = r * 0.008
            ax1.axhspan(r - zone_h, r + zone_h,
                        color="#ef5350", alpha=0.10, zorder=1)
            ax1.axhline(y=r, color="#ef5350", linewidth=1.0,
                        linestyle="--", alpha=0.8, zorder=4)
            ax1.annotate(
                "R" + str(idx+1) + "  $" + str(round(r, 2)),
                xy=(n - 1, r),
                xytext=(n + 0.5, r),
                fontsize=8, color="#ef5350", fontweight="bold",
                va="center", annotation_clip=False
            )

        # ── TRENDLINE ──
        if trend:
            lb = trend["lb"]
            tx = np.arange(n - lb, n)
            ty = trend["slope"] * np.arange(lb) + trend["intercept"]
            tc = (BULL if "Yuqoriga" in trend["dir"] else
                  BEAR if "Pastga" in trend["dir"] else "#90a4ae")
            ax1.plot(tx, ty, color=tc, linewidth=1.8,
                     linestyle="solid", zorder=5,
                     label="Trend", alpha=0.85)
            # Forecast punktir
            fx = np.arange(n, n + 8)
            fy = trend["slope"] * np.arange(lb, lb + 8) + trend["intercept"]
            ax1.plot(fx, fy, color=tc, linewidth=1.2,
                     linestyle=":", zorder=5, alpha=0.4)
            # Trendline fill
            if len(ty) > 1:
                seg_closes = closes[n-lb:n]
                ax1.fill_between(tx, ty, seg_closes,
                                 where=seg_closes >= ty,
                                 color=BULL, alpha=0.04)
                ax1.fill_between(tx, ty, seg_closes,
                                 where=seg_closes < ty,
                                 color=BEAR, alpha=0.04)

        # ── AI STRATEGIYA CHIZIQLARI ──
        if ai_levels:
            bz = ai_levels.get("buy_zone")
            sl = ai_levels.get("stop_loss")
            tp = ai_levels.get("take_profit")

            if bz:
                ax1.axhline(y=bz, color="#00e676", linewidth=1.8,
                            linestyle="-.", zorder=6, alpha=0.95)
                ax1.annotate(
                    "AI Kirish  $" + str(round(bz, 2)),
                    xy=(n-1, bz), xytext=(n+0.5, bz),
                    fontsize=8, color="#00e676", fontweight="bold",
                    va="bottom", annotation_clip=False
                )
            if sl:
                ax1.axhline(y=sl, color="#ff1744", linewidth=1.8,
                            linestyle="-.", zorder=6, alpha=0.95)
                ax1.annotate(
                    "Stop  $" + str(round(sl, 2)),
                    xy=(n-1, sl), xytext=(n+0.5, sl),
                    fontsize=8, color="#ff1744", fontweight="bold",
                    va="top", annotation_clip=False
                )
            if tp:
                ax1.axhline(y=tp, color="#69f0ae", linewidth=1.8,
                            linestyle="-.", zorder=6, alpha=0.95)
                ax1.annotate(
                    "Profit  $" + str(round(tp, 2)),
                    xy=(n-1, tp), xytext=(n+0.5, tp),
                    fontsize=8, color="#69f0ae", fontweight="bold",
                    va="bottom", annotation_clip=False
                )
            # Zonalar
            if bz and sl:
                ax1.axhspan(min(sl, bz), max(sl, bz),
                            color="#ef5350", alpha=0.06, zorder=1)
            if bz and tp:
                ax1.axhspan(min(bz, tp), max(bz, tp),
                            color="#00e676", alpha=0.05, zorder=1)

        # ── BREAKOUT BELGISI ──
        if breakouts:
            for bo in breakouts:
                if "YORILDI" in bo["type"]:
                    col = BULL if "RESISTANCE" in bo["type"] else BEAR
                    mk  = "^" if "RESISTANCE" in bo["type"] else "v"
                    ax1.scatter([n-1], [price.get("price", closes[-1])],
                                color=col, s=200, marker=mk,
                                zorder=9, edgecolors="white", linewidths=0.5)

        # ── JORIY NARX (TradingView sariq badge) ──
        cur  = price.get("price", closes[-1])
        chg  = price.get("chg", 0)
        sign = "+" if chg >= 0 else ""
        ax1.axhline(y=cur, color="#f5a623", linewidth=0.8,
                    linestyle="-", zorder=5, alpha=0.9)
        # O'ng tomon narx badge
        ax1.annotate(
            "$" + str(round(cur, 2)),
            xy=(n-1, cur), xytext=(n+0.5, cur),
            fontsize=9, color="#000000", fontweight="bold",
            va="center", annotation_clip=False,
            bbox=dict(boxstyle="round,pad=0.3", fc="#f5a623",
                      ec="#f5a623", alpha=0.95)
        )

        # ── TITLE ──
        ax1.set_title(
            ticker + " · 1D · NASDAQ     " +
            "$" + str(round(cur, 2)) + "   " +
            sign + str(round(chg, 2)) + "%   " +
            "ATR " + str(atr),
            color=TEXT, fontsize=11, fontweight="bold",
            pad=8, loc="left",
            fontfamily="monospace"
        )
        ax1.legend(
            loc="upper left", fontsize=7.5,
            facecolor="#1e222d", labelcolor=TEXT,
            framealpha=0.95, edgecolor=GRID,
            ncol=5, columnspacing=1.0, handlelength=1.5
        )
        ax1.set_xlim(-1, n + 12)

        # ── HAJM PANELI ──
        avg_vol = np.mean(vols) if vols.any() else 1
        for i, (o_, c_, v) in enumerate(zip(opens, closes, vols)):
            col   = BULL if c_ >= o_ else BEAR
            alpha = min(0.9, 0.3 + 0.7 * v / (avg_vol * 2))
            ax2.bar(i, v, color=col, width=w, alpha=alpha, zorder=3)
        ax2.axhline(y=avg_vol, color=MUTED, linewidth=0.6,
                    linestyle="--", alpha=0.7)
        ax2.set_ylabel("Vol", color=MUTED, fontsize=7)
        ax2.yaxis.set_major_formatter(
            mticker.FuncFormatter(
                lambda x, _: (str(round(x/1e9, 1)) + "B" if x >= 1e9
                              else str(round(x/1e6)) + "M" if x >= 1e6
                              else str(round(x/1e3)) + "K")
            )
        )

        # ── RSI PANELI ──
        if len(closes) >= 28:
            d   = np.diff(closes)
            g   = np.where(d > 0, d, 0)
            ls  = np.where(d < 0, -d, 0)
            ag  = np.convolve(g,  np.ones(14)/14, mode="valid")
            al_ = np.convolve(ls, np.ones(14)/14, mode="valid")
            rs_ = np.where(al_ != 0, ag/al_, 100)
            rsi = 100 - 100/(1 + rs_)
            rx  = list(range(14 + 13, len(closes)))
            ax3.plot(rx, rsi, color="#ce93d8", linewidth=1.1, zorder=3)
            ax3.axhline(y=70, color=BEAR, linewidth=0.6, linestyle="--", alpha=0.6)
            ax3.axhline(y=50, color=MUTED, linewidth=0.4, linestyle="--", alpha=0.4)
            ax3.axhline(y=30, color=BULL, linewidth=0.6, linestyle="--", alpha=0.6)
            ax3.fill_between(rx, rsi, 70, where=rsi >= 70,
                             color=BEAR, alpha=0.15)
            ax3.fill_between(rx, rsi, 30, where=rsi <= 30,
                             color=BULL, alpha=0.15)
            ax3.set_ylim(0, 100)
            ax3.set_yticks([30, 50, 70])
            ax3.set_ylabel("RSI", color=MUTED, fontsize=7)
            # Hozirgi RSI qiymati
            if len(rsi) > 0:
                cur_rsi = round(rsi[-1], 1)
                rsi_col = BEAR if cur_rsi > 70 else BULL if cur_rsi < 30 else "#ce93d8"
                ax3.annotate(
                    str(cur_rsi),
                    xy=(rx[-1], rsi[-1]), xytext=(n + 0.5, rsi[-1]),
                    fontsize=7, color=rsi_col, fontweight="bold",
                    va="center", annotation_clip=False
                )

        # ── MACD PANELI ──
        if len(closes) >= 34:
            def ema(arr, p):
                k   = 2.0 / (p + 1)
                out = np.zeros(len(arr))
                out[0] = arr[0]
                for i in range(1, len(arr)):
                    out[i] = arr[i] * k + out[i-1] * (1 - k)
                return out

            ema12    = ema(closes, 12)
            ema26    = ema(closes, 26)
            macd_l   = ema12 - ema26
            signal_l = ema(macd_l, 9)
            hist     = macd_l - signal_l

            mx = np.arange(n)
            ax4.plot(mx, macd_l,   color="#2196f3", linewidth=1.0,
                     label="MACD",   zorder=3)
            ax4.plot(mx, signal_l, color="#ff9800", linewidth=1.0,
                     label="Signal", zorder=3)
            # Histogram
            for i in range(n):
                col   = "#26a69a" if hist[i] >= 0 else "#ef5350"
                alpha = min(0.9, 0.4 + abs(hist[i]) / (np.std(hist) + 1e-9) * 0.3)
                ax4.bar(i, hist[i], color=col, width=w,
                        alpha=alpha, zorder=2)
            ax4.axhline(y=0, color=MUTED, linewidth=0.5, alpha=0.6)
            ax4.set_ylabel("MACD", color=MUTED, fontsize=7)
            ax4.legend(loc="upper left", fontsize=6.5,
                       facecolor="#1e222d", labelcolor=TEXT,
                       framealpha=0.9, edgecolor=GRID,
                       ncol=2, handlelength=1.2)

        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.setp(ax3.get_xticklabels(), visible=False)

        # ── WATERMARK ──
        fig.text(
            0.01, 0.005,
            "Stock Signal Bot v8.0  |  " + ticker + "  |  " +
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            color="#2a2e39", fontsize=7, fontfamily="monospace"
        )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150,
                    bbox_inches="tight", facecolor="#131722",
                    edgecolor="none")
        buf.seek(0)
        plt.close(fig)
        return buf

    except Exception as e:
        logging.error("Chart xato: " + str(e))
        try: plt.close("all")
        except Exception: pass
        return None


# ═══════════════════════════════════════════
# AI — STRATEGIYA VA SUHBAT
# ═══════════════════════════════════════════

def ai_strategiya(ticker, price, details, tech, sups, ress, trend, breakouts, atr):
    """
    AI strategiyani hisoblaydi va rasm uchun darajalarni qaytaradi.
    Qaytaradi: (matn, {"buy_zone": x, "stop_loss": x, "take_profit": x})
    """
    if not OPENAI_OK:
        return ("", None)
    try:
        client = OpenAI(api_key=OPENAI_KEY)
        cur    = price.get("price", 0)
        chg    = price.get("chg", 0)
        vol    = price.get("volume", 0) * cur
        sup1   = sups[0] if sups else round(cur*0.97, 2)
        res1   = ress[0] if ress else round(cur*1.03, 2)
        tdir   = trend["dir"] if trend else "N/A"
        bo_str = breakouts[0]["type"] if breakouts else "yo'q"

        prompt = (
            "Siz professional texnik tahlilchisiz. "
            "Quyidagi aksiya uchun FAQAT O'ZBEK TILIDA qisqa strategiya bering.\n\n"
            "Ticker: " + ticker + " | Narx: $" + str(round(cur,2)) +
            " (" + str(round(chg,2)) + "%)\n"
            "Hajm: $" + str(round(vol/1e6,1)) + " mln\n"
            "RSI: " + str(tech.get("rsi","N/A")) + "\n"
            "SMA50: $" + str(tech.get("sma50","N/A")) + "\n"
            "SMA200: $" + str(tech.get("sma200","N/A")) + "\n"
            "Trend: " + tdir + "\n"
            "Support 1: $" + str(sup1) + "\n"
            "Resistance 1: $" + str(res1) + "\n"
            "ATR: $" + str(atr) + "\n"
            "Breakout: " + bo_str + "\n\n"
            "JAVOB FORMATI (JSON):\n"
            "{\n"
            '  "matn": "O\'zbek tilida qisqa tahlil (max 100 so\'z)",\n'
            '  "signal": "SOTIB_OL yoki SOT yoki KUZAT",\n'
            '  "buy_zone": narx (float),\n'
            '  "stop_loss": narx (float),\n'
            '  "take_profit": narx (float),\n'
            '  "sabab": "1-2 jumlada sabab"\n'
            "}\n\n"
            "Faqat JSON qaytaring, boshqa narsa yozmang."
        )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.6,
        )
        raw = resp.choices[0].message.content.strip()
        # JSON tozalash
        raw = raw.replace("```json","").replace("```","").strip()
        data = json.loads(raw)

        matn = (
            "🤖 <b>AI Strategiyasi</b>\n\n"
            + str(data.get("matn","")) + "\n\n"
            + "📌 Signal: <b>" + str(data.get("signal","")) + "</b>\n"
            + "🎯 Kirish:      $" + str(data.get("buy_zone","")) + "\n"
            + "🛑 Stop Loss:   $" + str(data.get("stop_loss","")) + "\n"
            + "💰 Take Profit: $" + str(data.get("take_profit","")) + "\n"
            + "💡 " + str(data.get("sabab",""))
        )

        levels = {
            "buy_zone":    float(data.get("buy_zone", cur)),
            "stop_loss":   float(data.get("stop_loss", round(cur*0.97,2))),
            "take_profit": float(data.get("take_profit", round(cur*1.05,2))),
        }
        return (matn, levels)

    except Exception as e:
        logging.error("AI strategiya xato: " + str(e))
        return ("", None)


def ai_savol(chat_id, savol):
    if not OPENAI_OK:
        return "⚠️ AI hozir mavjud emas."
    try:
        client = OpenAI(api_key=OPENAI_KEY)
        if chat_id not in chat_history:
            chat_history[chat_id] = [{
                "role": "system",
                "content": (
                    "Siz professional moliyaviy maslahatchi va investitsiya mutaxassisisiz. "
                    "FAQAT O'ZBEK TILIDA javob bering. "
                    "Amerika fond bozori, aksiyalar, kripto, halol investitsiya haqida bilimingiz bor. "
                    "Javoblar qisqa, aniq va foydali bo'lsin. Emoji ishlating."
                )
            }]
        if len(chat_history[chat_id]) > 20:
            chat_history[chat_id] = chat_history[chat_id][:1] + chat_history[chat_id][-10:]

        chat_history[chat_id].append({"role": "user", "content": savol})
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=chat_history[chat_id],
            max_tokens=500,
            temperature=0.8,
        )
        javob = resp.choices[0].message.content.strip()
        chat_history[chat_id].append({"role": "assistant", "content": javob})
        return javob
    except Exception as e:
        logging.error("AI savol: " + str(e))
        return "⚠️ AI hozir band. Keyinroq urinib ko'ring."


# ═══════════════════════════════════════════
# HALOLLIK — MUSAFFA + AKOODA
# ═══════════════════════════════════════════

def check_musaffa(ticker):
    url = "https://musaffa.com/stock/" + ticker
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        text = BeautifulSoup(r.text, "lxml").get_text().lower()
        if any(w in text for w in ["halal","compliant","permissible"]):
            return {"status": "HALOL",    "url": url}
        if any(w in text for w in ["haram","not compliant","prohibited"]):
            return {"status": "HAROM",    "url": url}
        if any(w in text for w in ["doubtful","questionable"]):
            return {"status": "SHUBHALI", "url": url}
    except Exception:
        pass
    return {"status": "NOMA'LUM", "url": url}


def check_akooda(ticker):
    url = "https://akooda.co/stocks/" + ticker
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        text = BeautifulSoup(r.text, "lxml").get_text().lower()
        if any(w in text for w in ["halal","compliant","passed"]):
            return {"status": "HALOL",    "url": url}
        if any(w in text for w in ["haram","not compliant","failed"]):
            return {"status": "HAROM",    "url": url}
        if any(w in text for w in ["doubtful","borderline"]):
            return {"status": "SHUBHALI", "url": url}
    except Exception:
        pass
    return {"status": "NOMA'LUM", "url": url}


def get_halal(ticker):
    m  = check_musaffa(ticker); time.sleep(2)
    a  = check_akooda(ticker)
    ms = m["status"]; as_ = a["status"]
    if "HAROM" in [ms, as_]:                final = "HAROM"
    elif ms == "HALOL" or as_ == "HALOL":   final = "HALOL"
    elif "SHUBHALI" in [ms, as_]:           final = "SHUBHALI"
    else:                                   final = "NOMA'LUM"
    return {"final": final, "musaffa": ms, "akooda": as_,
            "musaffa_url": m["url"], "akooda_url": a["url"]}


def h_emoji(s):
    return {"HALOL":"✅ HALOL","HAROM":"❌ HAROM",
            "SHUBHALI":"⚠️ SHUBHALI","NOMA'LUM":"❓ NOMA'LUM"}.get(s,"❓")


# ═══════════════════════════════════════════
# TRADINGVIEW
# ═══════════════════════════════════════════

def get_tv(ticker):
    try:
        r = requests.post(
            "https://scanner.tradingview.com/america/scan",
            json={
                "symbols": {"tickers": [
                    "NASDAQ:"+ticker,"NYSE:"+ticker,"AMEX:"+ticker
                ]},
                "columns": ["Recommend.All","Recommend.MA",
                            "MACD.macd","MACD.signal","ADX","RSI"]
            },
            headers=HEADERS, timeout=12
        )
        data = r.json().get("data",[])
        if data:
            row = data[0].get("d",[])
            def lbl(v):
                if v is None: return "N/A"
                if v >= 0.5:  return "💪 KUCHLI SOTIB OL"
                if v >= 0.1:  return "🟢 SOTIB OL"
                if v > -0.1:  return "⚪ NEYTRAL"
                if v > -0.5:  return "🔴 SOT"
                return "💥 KUCHLI SOT"
            if len(row) >= 4:
                return {
                    "rating": lbl(row[0]),
                    "ma":     lbl(row[1]),
                    "macd":   "Yuqoriga" if row[2] and row[3] and row[2]>row[3] else "Pastga",
                    "adx":    round(row[4],1) if len(row)>4 and row[4] else "N/A",
                    "rsi":    round(row[5],1) if len(row)>5 and row[5] else "N/A",
                }
    except Exception:
        pass
    return {"rating":"N/A","ma":"N/A","macd":"N/A","adx":"N/A","rsi":"N/A"}


# ═══════════════════════════════════════════
# YAHOO FINANCE
# ═══════════════════════════════════════════

def get_yahoo(ticker):
    res = {"pe":"N/A","eps":"N/A","div":"N/A","w52h":"N/A","w52l":"N/A","avg_vol":"N/A","beta":"N/A"}
    try:
        r    = requests.get("https://finance.yahoo.com/quote/"+ticker+"/",
                            headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        for field, key in [
            ("PE_RATIO","pe"),("EPS_RATIO","eps"),
            ("FIFTY_TWO_WK_HIGH","w52h"),("FIFTY_TWO_WK_LOW","w52l"),
            ("AVERAGE_VOLUME_3MONTH","avg_vol"),("BETA_3Y","beta"),
            ("DIVIDEND_AND_YIELD","div")
        ]:
            el = soup.find("fin-streamer",{"data-field":field})
            if el: res[key] = el.get_text(strip=True)
    except Exception:
        pass
    return res


def get_news(ticker=None, count=5):
    url  = ("https://finance.yahoo.com/quote/"+ticker+"/news/"
            if ticker else "https://finance.yahoo.com/news/")
    news = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        for art in soup.find_all("h3", limit=count*2):
            a = art.find("a")
            if a and len(a.get_text(strip=True)) > 15:
                title = a.get_text(strip=True)
                href  = a.get("href","")
                if href and not href.startswith("http"):
                    href = "https://finance.yahoo.com" + href
                news.append({"title": title, "url": href})
            if len(news) >= count: break
    except Exception:
        pass
    return news


def news_html(news_list, count=5):
    lines = []
    for n in news_list[:count]:
        t = n.get("title","")[:70]
        u = n.get("url","")
        lines.append("• <a href='" + u + "'>" + t + "</a>")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# FINVIZ
# ═══════════════════════════════════════════

def get_finviz(ticker):
    res = {"industry":"N/A","country":"N/A","target":"N/A","recom":"N/A","news":[]}
    try:
        r    = requests.get("https://finviz.com/quote.ashx?t="+ticker,
                            headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        cells  = soup.select("td.snapshot-td2")
        labels = soup.select("td.snapshot-td2-cp")
        data   = {l.get_text(strip=True):c.get_text(strip=True)
                  for l,c in zip(labels,cells)}
        res.update({
            "industry": data.get("Industry","N/A"),
            "country":  data.get("Country","N/A"),
            "target":   data.get("Target Price","N/A"),
            "recom":    data.get("Recom","N/A"),
        })
        for row in soup.select("table.fullview-news-outer tr")[:4]:
            a = row.find("a", class_="tab-link-news")
            if a:
                res["news"].append({"title":a.get_text(strip=True),"url":a.get("href","")})
    except Exception:
        pass
    return res


# ═══════════════════════════════════════════
# IPO
# ═══════════════════════════════════════════

def get_ipos():
    ipos = []
    try:
        r    = requests.get("https://api.nasdaq.com/api/ipo/calendar",
                            headers=HEADERS, timeout=15)
        data = r.json().get("data",{})
        for ipo in data.get("upcoming",{}).get("upcomingTable",{}).get("rows",[])[:6]:
            ipos.append({
                "nomi":   ipo.get("companyName","N/A"),
                "ticker": ipo.get("proposedTickerSymbol","N/A"),
                "birja":  ipo.get("proposedExchange","N/A"),
                "narx":   ipo.get("priceRangeLow","")+"-"+ipo.get("priceRangeHigh",""),
                "sana":   ipo.get("expectedPriceDate","N/A"),
                "holat":  "Kutilmoqda",
            })
        for ipo in data.get("recent",{}).get("recentTable",{}).get("rows",[])[:4]:
            ipos.append({
                "nomi":      ipo.get("companyName","N/A"),
                "ticker":    ipo.get("proposedTickerSymbol","N/A"),
                "ipo_narxi": ipo.get("ipoPrice","N/A"),
                "hozir":     ipo.get("currentPrice","N/A"),
                "daromad":   ipo.get("pctChange","N/A"),
                "sana":      ipo.get("pricedDate","N/A"),
                "holat":     "Yangi",
            })
    except Exception as e:
        logging.warning("IPO: " + str(e))
    return ipos


def ipo_xabari(ipos):
    if not ipos: return "IPO ma'lumotlari topilmadi."
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = ["━━━━━━━━━━━━━━━━━━━━",
             "🚀 <b>IPO YANGILIKLARI</b>",
             "🕐 " + now, "━━━━━━━━━━━━━━━━━━━━\n"]
    for ipo in ipos:
        if ipo["holat"] == "Kutilmoqda":
            lines.append(
                "🗓 <b>"+ipo["nomi"]+"</b> ("+ipo["ticker"]+")\n"
                "  🏦 "+ipo["birja"]+" | 💰 $"+ipo["narx"]+" | 📅 "+ipo["sana"]+"\n"
            )
        else:
            try: pct = float(str(ipo.get("daromad","0")).replace("%","").replace("+","") or 0)
            except Exception: pct = 0
            em = "🟢" if pct >= 0 else "🔴"
            lines.append(
                em+" <b>"+ipo["nomi"]+"</b> ("+ipo["ticker"]+")\n"
                "  💰 IPO: $"+str(ipo.get("ipo_narxi","N/A"))+
                " → Hozir: $"+str(ipo.get("hozir","N/A"))+"\n"
                "  📊 "+str(ipo.get("daromad","N/A"))+"% | 📅 "+ipo["sana"]+"\n"
            )
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════

def send_msg(text, chat_id=None, markup=None):
    cid    = chat_id or TELEGRAM_CHAT_ID
    url    = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": cid, "text": chunk,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        if markup and i == len(chunks)-1:
            payload["reply_markup"] = json.dumps(markup)
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code != 200:
                payload.pop("parse_mode", None)
                requests.post(url, json=payload, timeout=15)
        except Exception as e:
            logging.error("send_msg: " + str(e))
        time.sleep(0.3)


def send_photo(buf, caption, chat_id=None, markup=None):
    if buf is None: return False
    cid = chat_id or TELEGRAM_CHAT_ID
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto"
    try:
        buf.seek(0)
        files   = {"photo": ("chart.png", buf.read(), "image/png")}
        payload = {"chat_id": cid, "caption": caption[:1024], "parse_mode": "HTML"}
        if markup: payload["reply_markup"] = json.dumps(markup)
        r = requests.post(url, data=payload, files=files, timeout=30)
        return r.status_code == 200
    except Exception as e:
        logging.error("send_photo: " + str(e))
        return False


def asosiy_menu():
    return {"inline_keyboard": [
        [{"text":"📊 Signal","callback_data":"signal"},
         {"text":"☪️ Halol","callback_data":"halol"}],
        [{"text":"🚀 IPO","callback_data":"ipo"},
         {"text":"📰 Yangilik","callback_data":"yangilik"}],
        [{"text":"⚡ Breakout","callback_data":"breakout"}],
    ]}


def aksiya_menu(ticker):
    return {"inline_keyboard": [
        [{"text":"📺 TradingView",
          "url":"https://www.tradingview.com/chart/?symbol="+ticker},
         {"text":"☪️ Musaffa",
          "url":"https://musaffa.com/stock/"+ticker}],
        [{"text":"🔄 Yangilash","callback_data":"yangi_"+ticker},
         {"text":"📰 Yangiliklar","callback_data":"xabar_"+ticker}],
    ]}


# ═══════════════════════════════════════════
# ASOSIY TARTIB: RASM → SIGNAL → HALOL → YANGILIK
# ═══════════════════════════════════════════

def ticker_tahlil(ticker, chat_id):
    ticker = ticker.upper().strip()

    # Yuklash xabari
    send_msg(
        "🔍 <b>" + ticker + "</b> tahlil boshlanmoqda...\n"
        "⏳ Ma'lumotlar yuklanmoqda...",
        chat_id
    )

    # 1. Ma'lumotlarni yig'ish
    price = get_price(ticker)
    if not price or price.get("price", 0) == 0:
        send_msg("❌ <b>" + ticker + "</b> topilmadi.", chat_id)
        return
    time.sleep(13)

    details   = get_details(ticker);      time.sleep(13)
    tech      = get_technicals(ticker);   time.sleep(2)
    candles   = get_candles(ticker, 90)
    sups, ress = calc_sr(candles)
    trend      = calc_trend(candles) if candles else None
    atr        = calc_atr(candles)
    breakouts  = detect_breakout(candles, sups, ress, price)
    time.sleep(13)
    tv         = get_tv(ticker);      time.sleep(2)
    yahoo      = get_yahoo(ticker);   time.sleep(2)
    finviz     = get_finviz(ticker);  time.sleep(2)
    halal      = get_halal(ticker);   time.sleep(2)

    # 2. AI strategiya
    send_msg("🤖 AI strategiya hisoblanmoqda...", chat_id)
    ai_matn, ai_levels = ai_strategiya(ticker, price, details, tech,
                                        sups, ress, trend, breakouts, atr)

    # ── QADAM 1: RASM (chart + AI chiziqlari) ──
    chart = draw_chart(ticker, candles, sups, ress, price,
                       trend, breakouts, atr, ai_levels)

    cur = price.get("price", 0)
    chg = price.get("chg", 0)
    sign = "+" if chg >= 0 else ""
    sup_str = " | ".join(["$"+str(s) for s in sups[:2]]) or "N/A"
    res_str = " | ".join(["$"+str(r) for r in ress[:2]]) or "N/A"
    tdir    = trend["dir"] if trend else "N/A"

    caption = (
        "<b>" + ticker + "</b> — " + details["name"] + "\n"
        "💵 $" + str(round(cur,2)) + "  (" + sign + str(round(chg,2)) + "%)\n"
        "📈 " + tdir + "  |  ATR: $" + str(atr) + "\n"
        "🟢 S: " + sup_str + "  🔴 R: " + res_str + "\n"
        "☪️ " + h_emoji(halal["final"])
    )

    if chart:
        ok = send_photo(chart, caption, chat_id, aksiya_menu(ticker))
        if not ok:
            send_msg(
                "📺 <a href='https://www.tradingview.com/chart/?symbol="+ticker+"'>"
                "TradingView — " + ticker + "</a>\n" + caption,
                chat_id, aksiya_menu(ticker)
            )
    else:
        send_msg(
            "📺 <a href='https://www.tradingview.com/chart/?symbol="+ticker+"'>"
            "TradingView — " + ticker + "</a>\n" + caption,
            chat_id, aksiya_menu(ticker)
        )

    # ── QADAM 2: NARX VA SIGNAL ──
    rsi    = tech.get("rsi")
    sma50  = tech.get("sma50")
    sma200 = tech.get("sma200")
    vol_usd = price.get("volume",0) * cur
    cap_b   = details["cap"] / 1e9

    bo_text = ""
    if breakouts:
        strong = [b for b in breakouts if b["score"] >= 3]
        if strong:
            bo_text = "\n⚡ <b>Breakout:</b>\n"
            for bo in strong:
                bo_text += "  " + bo["emoji"] + " " + bo["type"] + " $" + str(bo["level"]) + "\n"
                bo_text += "  → " + bo["signal"] + "\n"

    signal_matn = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>" + ticker + "</b> — " + details["name"] + "\n"
        "🏭 " + details["sector"] + "\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 <b>Narx</b>\n"
        "  💵 Joriy:    <b>$" + str(round(cur,2)) + "</b>  (" + sign + str(round(chg,2)) + "%)\n"
        "  🔓 Ochilish: $" + str(round(price.get("open",0),2)) + "\n"
        "  🔺 Yuqori:   $" + str(round(price.get("high",0),2)) + "\n"
        "  🔻 Past:     $" + str(round(price.get("low",0),2)) + "\n"
        "  📍 VWAP:     $" + str(round(price.get("vwap",0),2)) + "\n"
        "  52H: $" + str(yahoo.get("w52h","N/A")) + " / $" + str(yahoo.get("w52l","N/A")) + "\n\n"
        "📦 <b>Hajm</b>\n"
        "  Bugungi: <b>$" + str(round(vol_usd/1e6,1)) + " mln</b>"
        "  |  O'rtacha: " + str(yahoo.get("avg_vol","N/A")) + "\n\n"
        "🏦 <b>Fundamental</b>\n"
        "  Bozor kap: <b>$" + str(round(cap_b,1)) + " mlrd</b>\n"
        "  P/E: " + str(yahoo.get("pe","N/A")) +
        "  |  EPS: " + str(yahoo.get("eps","N/A")) + "\n"
        "  Beta: " + str(yahoo.get("beta","N/A")) +
        "  |  Div: " + str(yahoo.get("div","N/A")) + "\n\n"
        "📐 <b>Texnik tahlil</b>\n"
        "  RSI(14): " + str(rsi or "N/A") +
        ("  ⚠️ Yuqori" if rsi and rsi > 70 else "  ✅ Past" if rsi and rsi < 30 else "  ✅ Normal") + "\n"
        "  SMA50:  $" + str(sma50 or "N/A") + ("  ✅" if sma50 and cur > sma50 else "  ⚠️") + "\n"
        "  SMA200: $" + str(sma200 or "N/A") + ("  ✅ Bull" if sma200 and cur > sma200 else "  ⚠️ Bear") + "\n"
        "  ATR: $" + str(atr) + "\n\n"
        "📈 <b>Trend:</b> " + tdir + "\n"
        "🟢 <b>Support:</b>    " + sup_str + "\n"
        "🔴 <b>Resistance:</b> " + res_str + "\n"
        + bo_text + "\n"
        "📺 <b>TradingView:</b> " + tv.get("rating","N/A") + "\n"
        "  MACD: " + tv.get("macd","N/A") +
        "  |  ADX: " + str(tv.get("adx","N/A")) + "\n\n"
        "🎯 <b>Yakuniy signal:</b> " +
        ("🟢 SOTIB OL" if chg >= 0 else "🔴 SOT") + "\n"
        "  Narx maqsadi: $" + str(finviz.get("target","N/A")) +
        "  |  Analitik: " + str(finviz.get("recom","N/A"))
    )
    send_msg(signal_matn, chat_id)

    # ── QADAM 3: AI STRATEGIYA ──
    if ai_matn:
        send_msg(ai_matn, chat_id)

    # ── QADAM 4: HALOLLIK ──
    halal_matn = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "☪️ <b>HALOLLIK HOLATI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "  Yakuniy: <b>" + h_emoji(halal["final"]) + "</b>\n\n"
        "  Musaffa.com: " + h_emoji(halal["musaffa"]) + "\n"
        "  Akooda.com:  " + h_emoji(halal["akooda"]) + "\n\n"
        "  🔗 <a href='" + halal["musaffa_url"] + "'>Musaffa da batafsil ko'rish</a>\n"
        "  🔗 <a href='" + halal["akooda_url"] + "'>Akooda da batafsil ko'rish</a>\n\n"
        "<i>⚠️ Moliyaviy maslahat emas.</i>"
    )
    send_msg(halal_matn, chat_id)

    # ── QADAM 5: YANGILIKLAR ──
    all_news = finviz.get("news",[]) + get_news(ticker, count=3)
    if all_news:
        send_msg(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📰 <b>" + ticker + " YANGILIKLARI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + news_html(all_news, 5),
            chat_id
        )


# ═══════════════════════════════════════════
# AVTOMATIK SKREENER
# ═══════════════════════════════════════════

def skreener(halol_only=False, breakout_only=False):
    tag = "HALOL " if halol_only else "BREAKOUT " if breakout_only else ""
    logging.info("Skreener: " + tag + "boshlandi")
    signals = []

    for ticker in WATCHLIST:
        price = get_price(ticker)
        if not price or price.get("price",0) == 0:
            time.sleep(13); continue

        chg     = price.get("chg", 0)
        c       = price.get("price", 0)
        vol_usd = price.get("volume", 0) * c

        if vol_usd < MIN_VOL:
            time.sleep(13); continue
        if not breakout_only and not (MIN_CHG <= abs(chg) <= MAX_CHG):
            time.sleep(13); continue

        details = get_details(ticker); time.sleep(13)
        if details["cap"] < MIN_CAP: continue

        tv       = get_tv(ticker); time.sleep(2)
        candles  = get_candles(ticker, 60)
        sups, ress = calc_sr(candles)
        trend    = calc_trend(candles) if candles else None
        breakouts = detect_breakout(candles, sups, ress, price)
        time.sleep(13)

        if halol_only:
            halal = get_halal(ticker); time.sleep(2)
            if halal["final"] == "HAROM": continue

        if breakout_only and not breakouts: continue

        sabablar = []
        if abs(chg) > 5:           sabablar.append("Kuchli harakat")
        if vol_usd > 10_000_000:   sabablar.append("Yuqori hajm")
        if "SOTIB OL" in tv.get("rating",""): sabablar.append("TV: BUY")
        if breakouts:              sabablar.append(breakouts[0]["type"])
        if trend and "Yuqoriga" in trend["dir"]: sabablar.append("Uptrend")

        signals.append({
            "ticker":   ticker, "nomi":    details["name"],
            "signal":   "BUY" if chg > 0 else "SELL",
            "narx":     c,     "chg":     chg,
            "vol_usd":  vol_usd, "cap":   details["cap"],
            "tv":       tv.get("rating","N/A"),
            "trend":    trend["dir"] if trend else "N/A",
            "breakout": breakouts[0]["type"] if breakouts else "—",
            "sabab":    " | ".join(sabablar) or "Mezon bajarildi",
        })
        logging.info("  " + ticker + " " + str(round(chg,1)) + "%")
        time.sleep(13)

    if not signals:
        send_msg("📊 " + tag + "Hozir shart bajargan aksiya topilmadi.")
        return

    signals.sort(key=lambda x: abs(x["chg"]), reverse=True)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # AI xulosasi
    ai_xulosa = ""
    if OPENAI_OK and signals:
        try:
            client = OpenAI(api_key=OPENAI_KEY)
            top3   = signals[:3]
            info   = "\n".join([
                s["ticker"]+": $"+str(round(s["narx"],2))+
                " ("+str(round(s["chg"],1))+"%), "+s["trend"]
                for s in top3
            ])
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":
                    "Quyidagi 3 ta aksiyani O'ZBEK TILIDA 2 jumlada tushuntiring:\n" +
                    info + "\nEng muhim narsani aytib bering."}],
                max_tokens=200, temperature=0.7,
            )
            ai_xulosa = "\n\n🤖 <b>AI xulosasi:</b>\n" + resp.choices[0].message.content.strip()
        except Exception:
            pass

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🤖 <b>AVTOMATIK " + tag + "SIGNAL</b>",
        "🕐 " + now,
        "Topilgan: <b>" + str(len(signals)) + " ta aksiya</b>",
        "━━━━━━━━━━━━━━━━━━━━\n",
    ]
    for s in signals[:10]:
        em   = "🟢" if s["signal"] == "BUY" else "🔴"
        amal = "SOTIB OL" if s["signal"] == "BUY" else "SOT"
        cap  = s["cap"] / 1e9
        sign = "+" if s["chg"] >= 0 else ""
        lines.append(
            em + " <b>" + s["ticker"] + "</b> — " + s["nomi"] + "\n"
            "  💵 $" + str(round(s["narx"],2)) + "  (" + sign + str(round(s["chg"],1)) + "%)\n"
            "  📦 $" + str(round(s["vol_usd"]/1e6,1)) + " mln  " +
            "🏦 $" + str(round(cap,1)) + " mlrd\n"
            "  📈 " + s["trend"] + "  ⚡ " + s["breakout"] + "\n"
            "  📺 " + s["tv"] + "\n"
            "  🎯 <b>" + amal + "</b> — " + s["sabab"] + "\n"
        )

    if ai_xulosa:
        lines.append(ai_xulosa)
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    send_msg("\n".join(lines), markup=asosiy_menu())


# ═══════════════════════════════════════════
# TELEGRAM POLLING
# ═══════════════════════════════════════════

def polling():
    offset = None
    logging.info("Bot tayyor. Xabarlar tinglanmoqda...")

    while True:
        try:
            r = requests.get(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/getUpdates",
                params={"timeout":30,"offset":offset,
                        "allowed_updates":["message","callback_query"]},
                timeout=35
            )
            updates = r.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1

                # ── Callback tugmalari ──
                if "callback_query" in upd:
                    cb      = upd["callback_query"]
                    data    = cb.get("data","")
                    chat_id = str(cb["message"]["chat"]["id"])
                    requests.post(
                        "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/answerCallbackQuery",
                        json={"callback_query_id":cb["id"],"text":"⏳"},timeout=5
                    )

                    if data == "signal":
                        send_msg("🔍 Signallar tekshirilmoqda...", chat_id)
                        threading.Thread(target=skreener, daemon=True).start()

                    elif data == "halol":
                        send_msg("☪️ Halol aksiyalar tekshirilmoqda...", chat_id)
                        threading.Thread(
                            target=lambda: skreener(halol_only=True), daemon=True
                        ).start()

                    elif data == "ipo":
                        send_msg("🚀 IPO yuklanmoqda...", chat_id)
                        def _ipo(c=chat_id):
                            send_msg(ipo_xabari(get_ipos()), c)
                        threading.Thread(target=_ipo, daemon=True).start()

                    elif data == "yangilik":
                        send_msg("📰 Yangiliklar yuklanmoqda...", chat_id)
                        def _yn(c=chat_id):
                            news = get_news(count=8)
                            send_msg(
                                "━━━━━━━━━━━━━━━━━━━━\n"
                                "📰 <b>MOLIYAVIY YANGILIKLAR</b>\n"
                                "━━━━━━━━━━━━━━━━━━━━\n\n" +
                                news_html(news, 8), c
                            )
                        threading.Thread(target=_yn, daemon=True).start()

                    elif data == "breakout":
                        send_msg("⚡ Breakout signallari tekshirilmoqda...", chat_id)
                        threading.Thread(
                            target=lambda: skreener(breakout_only=True), daemon=True
                        ).start()

                    elif data.startswith("yangi_"):
                        tkr = data.replace("yangi_","")
                        threading.Thread(
                            target=ticker_tahlil, args=(tkr, chat_id), daemon=True
                        ).start()

                    elif data.startswith("xabar_"):
                        tkr = data.replace("xabar_","")
                        def _xabar(t=tkr, c=chat_id):
                            news = get_news(t, count=5)
                            send_msg(
                                "📰 <b>" + t + " YANGILIKLARI</b>\n\n" +
                                news_html(news, 5), c
                            )
                        threading.Thread(target=_xabar, daemon=True).start()
                    continue

                # ── Oddiy xabarlar ──
                msg     = upd.get("message",{})
                text    = msg.get("text","").strip()
                chat_id = str(msg.get("chat",{}).get("id",""))
                if not text or not chat_id: continue

                logging.info("'" + text + "' — " + chat_id)

                if text in ("/start","/help"):
                    send_msg(
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "👋 <b>Stock Signal Bot v8.0</b>\n"
                        "🤖 AI • Polygon • TV • Yahoo • Musaffa\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "📌 <b>Qanday ishlatish:</b>\n"
                        "  • Ticker yozing: <code>AAPL</code>, <code>NVDA</code>\n"
                        "  • Savol bering: <i>TSLA haqida nima deysiz?</i>\n\n"
                        "<b>Buyruqlar:</b>\n"
                        "  /signal   — Signallar\n"
                        "  /halol    — Halol aksiyalar\n"
                        "  /ipo      — IPO yangiliklari\n"
                        "  /yangilik — Yangiliklar\n"
                        "  /breakout — Breakout signallari\n\n"
                        "🤖 AI O'ZBEK TILIDA strategiya chizadi\n"
                        "☪️ Musaffa + Akooda halollik tekshiruvi\n\n"
                        "⬇️ Tugmalar:",
                        chat_id, asosiy_menu()
                    )

                elif text == "/signal":
                    send_msg("🔍 Signallar tekshirilmoqda...", chat_id)
                    threading.Thread(target=skreener, daemon=True).start()

                elif text in ("/halol","/halal"):
                    send_msg("☪️ Halol aksiyalar tekshirilmoqda...", chat_id)
                    threading.Thread(
                        target=lambda: skreener(halol_only=True), daemon=True
                    ).start()

                elif text == "/ipo":
                    send_msg("🚀 IPO yuklanmoqda...", chat_id)
                    def _ipo2(c=chat_id):
                        send_msg(ipo_xabari(get_ipos()), c)
                    threading.Thread(target=_ipo2, daemon=True).start()

                elif text in ("/yangilik","/news"):
                    send_msg("📰 Yangiliklar yuklanmoqda...", chat_id)
                    def _yn2(c=chat_id):
                        news = get_news(count=8)
                        send_msg(
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "📰 <b>MOLIYAVIY YANGILIKLAR</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n\n" +
                            news_html(news, 8), c
                        )
                    threading.Thread(target=_yn2, daemon=True).start()

                elif text == "/breakout":
                    send_msg("⚡ Breakout signallari tekshirilmoqda...", chat_id)
                    threading.Thread(
                        target=lambda: skreener(breakout_only=True), daemon=True
                    ).start()

                elif text.startswith("/"):
                    send_msg("❓ Noma'lum buyruq. /help yozing.", chat_id)

                elif re.match(r"^[A-Za-z]{1,6}$", text):
                    threading.Thread(
                        target=ticker_tahlil, args=(text, chat_id), daemon=True
                    ).start()

                else:
                    # Istalgan savol — AI javob beradi
                    send_msg("🤖 AI javob tayyorlanmoqda...", chat_id)
                    def _ai(t=text, c=chat_id):
                        javob = ai_savol(c, t)
                        send_msg("🤖 <b>AI javobi:</b>\n\n" + javob, c)
                    threading.Thread(target=_ai, daemon=True).start()

        except Exception as e:
            logging.error("Polling xato: " + str(e))
            time.sleep(5)


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    logging.info("Stock Signal Bot v8.0 ishga tushdi")

    schedule.every(4).hours.do(skreener)
    schedule.every().day.at("09:35").do(skreener)
    schedule.every().day.at("16:05").do(skreener)
    schedule.every().day.at("08:00").do(lambda: send_msg(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌅 <b>ERTALABKI YANGILIKLAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n" +
        news_html(get_news(count=6), 6)
    ))

    threading.Thread(
        target=lambda: [(schedule.run_pending(), time.sleep(60))
                        for _ in iter(int,1)],
        daemon=True
    ).start()

    send_msg(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Stock Signal Bot v8.0 ishga tushdi!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Real vaqt narxlar\n"
        "✅ AI strategiya rasmga chiziladi 🎨\n"
        "✅ Kirish, Stop Loss, Take Profit chiziqlari\n"
        "✅ Musaffa.com + Akooda.com ☪️\n"
        "✅ Trendline + S/R + Breakout\n"
        "✅ TradingView + Yahoo + Finviz\n"
        "✅ Tartibli xabarlar\n\n"
        "💡 <code>AAPL</code> yozing yoki savol bering!",
        markup=asosiy_menu()
    )

    polling()


if __name__ == "__main__":
    main()
