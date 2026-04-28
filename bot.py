"""
Stock Signal Bot v10
Faqat: Chart + Trendline + S/R + Halollik
pip install requests schedule beautifulsoup4 lxml matplotlib numpy pillow python-dotenv
"""

import os, io, gc, re, json, time, logging, threading, schedule
import requests, numpy as np
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# Matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    _t = plt.figure(); plt.close(_t)
    MPL = True
    logging.info("Matplotlib OK")
except Exception as e:
    MPL = False
    logging.warning("Matplotlib xato: " + str(e))

# ── SOZLAMALAR ──
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
PKEY  = os.environ.get("POLYGON_KEY", "")

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO",
    "JPM","V","LLY","MA","HD","CRM","COST","NFLX","AMD","WMT",
    "MCD","QCOM","GS","HOOD","PLTR","SOFI","COIN","SNAP","UBER",
    "SHOP","CRWD","NET","ARM","SMCI","MU","F","NKE","SBUX",
]


# ════════════════════════════════
# NARX VA SHAMLAR
# ════════════════════════════════

def get_price(ticker):
    # Polygon prev day
    try:
        r = requests.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
            f"?adjusted=true&apiKey={PKEY}", timeout=10)
        res = r.json().get("results", [])
        if res:
            d = res[0]
            o = d.get("o", 0); c = d.get("c", 0)
            chg = round((c - o) / o * 100, 2) if o > 0 else 0
            return {"p": c, "o": o, "h": d.get("h", 0), "l": d.get("l", 0),
                    "v": d.get("v", 0), "vw": d.get("vw", c), "chg": chg}
    except Exception:
        pass
    # Yahoo backup
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&range=2d", headers=HDR, timeout=10)
        m = r.json()["chart"]["result"][0]["meta"]
        p = m.get("regularMarketPrice", 0)
        prev = m.get("previousClose", 0)
        chg = round((p - prev) / prev * 100, 2) if prev > 0 else 0
        return {"p": p, "o": m.get("regularMarketOpen", p),
                "h": m.get("regularMarketDayHigh", p),
                "l": m.get("regularMarketDayLow", p),
                "v": m.get("regularMarketVolume", 0),
                "vw": p, "chg": chg}
    except Exception as e:
        logging.warning(f"narx {ticker}: {e}")
    return None


def get_candles(ticker, days=60):
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 20)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
            f"/{start}/{end}?adjusted=true&sort=asc&limit=100&apiKey={PKEY}",
            timeout=12)
        d = r.json().get("results", [])
        return d[-days:] if len(d) >= days else d
    except Exception:
        return []


# ════════════════════════════════
# TEXNIK HISOB
# ════════════════════════════════

def calc_sr(candles):
    if len(candles) < 10:
        return [], []
    H = np.array([c["h"] for c in candles])
    L = np.array([c["l"] for c in candles])
    C = np.array([c["c"] for c in candles])
    sups, ress = [], []
    for i in range(3, len(L) - 3):
        if L[i] == min(L[i-3:i+4]):
            sups.append(round(L[i], 2))
    for i in range(3, len(H) - 3):
        if H[i] == max(H[i-3:i+4]):
            ress.append(round(H[i], 2))

    def cluster(lvs, thr=0.015):
        if not lvs:
            return []
        lvs = sorted(set(lvs))
        out = [lvs[0]]
        for v in lvs[1:]:
            if abs(v - out[-1]) / out[-1] > thr:
                out.append(v)
        return out

    cur = C[-1]
    sv = sorted([v for v in cluster(sups) if v < cur], reverse=True)[:4]
    rv = sorted([v for v in cluster(ress) if v > cur])[:4]
    return sv, rv


def calc_trend(candles, lb=30):
    if len(candles) < lb:
        lb = len(candles)
    C  = np.array([c["c"] for c in candles[-lb:]])
    x  = np.arange(lb)
    sl, ic = np.polyfit(x, C, 1)
    if sl > C[-1] * 0.0003:
        d = "📈 Yuqoriga"
    elif sl < -C[-1] * 0.0003:
        d = "📉 Pastga"
    else:
        d = "➡️ Yon"
    return {"sl": sl, "ic": ic, "dir": d, "lb": lb}


def calc_atr(candles, p=14):
    if len(candles) < p + 1:
        return 0
    trs = [max(candles[i]["h"] - candles[i]["l"],
               abs(candles[i]["h"] - candles[i-1]["c"]),
               abs(candles[i]["l"] - candles[i-1]["c"]))
           for i in range(1, len(candles))]
    return round(np.mean(trs[-p:]), 2)


# ════════════════════════════════
# CHART — TradingView uslubi
# ════════════════════════════════

def draw_chart(ticker, candles, sups, ress, price, tr, at):
    logging.info(f"Chart: {ticker} MPL={MPL} candles={len(candles)}")
    if not MPL or len(candles) < 10:
        return None
    try:
        matplotlib.use("Agg")
        BG = "#131722"; GR = "#1e222d"
        BL = "#26a69a"; BR = "#ef5350"
        TX = "#d1d4dc"; MU = "#4a4e5a"

        fig = plt.figure(figsize=(14, 8), facecolor=BG)
        gs  = fig.add_gridspec(3, 1, height_ratios=[4, 1, 1],
                               hspace=0.0, left=0.01, right=0.87,
                               top=0.93, bottom=0.06)
        a1 = fig.add_subplot(gs[0])
        a2 = fig.add_subplot(gs[1], sharex=a1)
        a3 = fig.add_subplot(gs[2], sharex=a1)

        for ax in [a1, a2, a3]:
            ax.set_facecolor(BG)
            ax.tick_params(colors=MU, labelsize=7, length=2)
            for sp in ax.spines.values():
                sp.set_color(GR); sp.set_linewidth(0.4)
            ax.yaxis.set_label_position("right")
            ax.yaxis.tick_right()
            ax.grid(True, color=GR, linewidth=0.3, alpha=0.8)

        O = np.array([c["o"] for c in candles])
        H = np.array([c["h"] for c in candles])
        L = np.array([c["l"] for c in candles])
        C = np.array([c["c"] for c in candles])
        V = np.array([c["v"] for c in candles])
        n = len(candles)

        # X o'qi — sanalar
        step = max(1, n // 7)
        xp = list(range(0, n, step))
        xl = []
        for idx in xp:
            t = candles[idx].get("t", 0)
            if t:
                xl.append(datetime.fromtimestamp(t / 1000).strftime("%d %b"))
            else:
                xl.append("")
        for ax in [a2, a3]:
            ax.set_xticks(xp); ax.set_xticklabels(xl, fontsize=7, color=MU)
        a1.set_xticks(xp); a1.set_xticklabels([], visible=False)

        # Bollinger Bands
        if n >= 20:
            bm = np.convolve(C, np.ones(20) / 20, mode="valid")
            bs = np.array([C[i:i+20].std() for i in range(n - 19)])
            bx = np.arange(19, n)
            a1.plot(bx, bm + 2*bs, color="#5c6bc0", lw=0.6, ls=":", alpha=0.5)
            a1.plot(bx, bm - 2*bs, color="#5c6bc0", lw=0.6, ls=":", alpha=0.5)
            a1.fill_between(bx, bm - 2*bs, bm + 2*bs, color="#5c6bc0", alpha=0.03)

        # SMA 20
        if n >= 20:
            s20 = np.convolve(C, np.ones(20) / 20, mode="valid")
            a1.plot(range(19, n), s20, color="#7986cb", lw=1.0,
                    label="MA20", alpha=0.9)

        # SMA 50
        if n >= 50:
            s50 = np.convolve(C, np.ones(50) / 50, mode="valid")
            a1.plot(range(49, n), s50, color="#f59e0b", lw=1.0,
                    label="MA50", alpha=0.9)

        # SHAMLAR
        for i in range(n):
            o, h, l, c = O[i], H[i], L[i], C[i]
            col = BL if c >= o else BR
            a1.bar(i, max(abs(c - o), (h - l) * 0.003), bottom=min(o, c),
                   color=col, width=0.6, zorder=3, ec=col, lw=0.2)
            a1.plot([i, i], [l, h], color=col, lw=0.7, zorder=2)

        # TRENDLINE
        if tr:
            lb = tr["lb"]
            tx = np.arange(n - lb, n)
            ty = tr["sl"] * np.arange(lb) + tr["ic"]
            tc = BL if "Yuqoriga" in tr["dir"] else BR if "Pastga" in tr["dir"] else "#90a4ae"
            a1.plot(tx, ty, color=tc, lw=2.0, ls="-",
                    zorder=5, label="Trend", alpha=0.9)
            # Forecast
            fx = np.arange(n, n + 8)
            fy = tr["sl"] * np.arange(lb, lb + 8) + tr["ic"]
            a1.plot(fx, fy, color=tc, lw=1.2, ls=":", zorder=5, alpha=0.4)
            # Fill
            seg = C[n - lb:n]
            a1.fill_between(tx, ty, seg,
                            where=seg >= ty, color=BL, alpha=0.04)
            a1.fill_between(tx, ty, seg,
                            where=seg < ty, color=BR, alpha=0.04)

        # SUPPORT ZONALAR (ko'k)
        for i, s in enumerate(sups[:4]):
            zh = s * 0.007
            a1.axhspan(s - zh, s + zh, color="#00bcd4", alpha=0.13, zorder=1)
            a1.axhline(y=s, color="#00bcd4", lw=1.1, ls="--", alpha=0.8, zorder=4)
            a1.annotate(f"S{i+1} ${s}",
                        xy=(n - 1, s), xytext=(n + 0.5, s),
                        fontsize=8, color="#00bcd4", fontweight="bold",
                        va="center", annotation_clip=False)

        # RESISTANCE ZONALAR (qizil)
        for i, r in enumerate(ress[:4]):
            zh = r * 0.007
            a1.axhspan(r - zh, r + zh, color=BR, alpha=0.10, zorder=1)
            a1.axhline(y=r, color=BR, lw=1.1, ls="--", alpha=0.8, zorder=4)
            a1.annotate(f"R{i+1} ${r}",
                        xy=(n - 1, r), xytext=(n + 0.5, r),
                        fontsize=8, color=BR, fontweight="bold",
                        va="center", annotation_clip=False)

        # JORIY NARX (sariq badge)
        cur = price.get("p", C[-1])
        chg = price.get("chg", 0)
        a1.axhline(y=cur, color="#f5a623", lw=0.9, ls="-", zorder=5, alpha=0.9)
        a1.annotate(f"${round(cur, 2)}",
                    xy=(n - 1, cur), xytext=(n + 0.5, cur),
                    fontsize=9, color="#000", fontweight="bold",
                    va="center", annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.25",
                              fc="#f5a623", ec="#f5a623", alpha=0.95))

        sign = "+" if chg >= 0 else ""
        tc   = BL if chg >= 0 else BR
        a1.set_title(
            f"{ticker}  ${round(cur, 2)}  {sign}{chg}%  |  ATR ${at}",
            color=tc, fontsize=12, fontweight="bold",
            pad=8, loc="left", fontfamily="monospace"
        )
        a1.legend(loc="upper left", fontsize=8, facecolor="#1e222d",
                  labelcolor=TX, framealpha=0.9, edgecolor=GR,
                  ncol=4, handlelength=1.2)
        a1.set_xlim(-1, n + 12)

        # HAJM
        av = np.mean(V) if V.any() else 1
        for i, (o, c, v) in enumerate(zip(O, C, V)):
            col   = BL if c >= o else BR
            alpha = min(0.9, 0.3 + 0.7 * v / (av * 2))
            a2.bar(i, v, color=col, width=0.6, alpha=alpha)
        a2.axhline(y=av, color=MU, lw=0.6, ls="--", alpha=0.6)
        a2.set_ylabel("Vol", color=MU, fontsize=7)
        a2.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{round(x/1e9,1)}B" if x >= 1e9
            else f"{round(x/1e6)}M" if x >= 1e6 else f"{round(x/1e3)}K"))

        # RSI
        if len(C) >= 28:
            d  = np.diff(C)
            g  = np.where(d > 0, d, 0)
            ls = np.where(d < 0, -d, 0)
            ag = np.convolve(g,  np.ones(14) / 14, mode="valid")
            al = np.convolve(ls, np.ones(14) / 14, mode="valid")
            rs = np.where(al != 0, ag / al, 100)
            rsi = 100 - 100 / (1 + rs)
            rx  = list(range(27, len(C)))
            a3.plot(rx, rsi, color="#ce93d8", lw=1.1)
            a3.axhline(y=70, color=BR, lw=0.6, ls="--", alpha=0.6)
            a3.axhline(y=50, color=MU, lw=0.4, ls="--", alpha=0.4)
            a3.axhline(y=30, color=BL, lw=0.6, ls="--", alpha=0.6)
            a3.fill_between(rx, rsi, 70, where=rsi >= 70, color=BR, alpha=0.15)
            a3.fill_between(rx, rsi, 30, where=rsi <= 30, color=BL, alpha=0.15)
            a3.set_ylim(0, 100); a3.set_yticks([30, 50, 70])
            a3.set_ylabel("RSI", color=MU, fontsize=7)
            if len(rsi) > 0:
                cr  = round(rsi[-1], 1)
                rc  = BR if cr > 70 else BL if cr < 30 else "#ce93d8"
                a3.annotate(str(cr), xy=(rx[-1], rsi[-1]),
                            xytext=(n + 0.5, rsi[-1]),
                            fontsize=7, color=rc, fontweight="bold",
                            va="center", annotation_clip=False)

        plt.setp(a1.get_xticklabels(), visible=False)
        plt.setp(a2.get_xticklabels(), visible=False)
        fig.text(0.01, 0.005,
                 f"Stock Signal Bot v10 | {ticker} | "
                 + datetime.now().strftime("%d.%m.%Y %H:%M"),
                 color="#2a2e39", fontsize=7, fontfamily="monospace")

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100,
                    bbox_inches="tight", facecolor=BG, edgecolor="none")
        buf.seek(0)
        plt.close(fig); plt.close("all"); gc.collect()
        logging.info(f"Chart OK: {ticker}")
        return buf

    except Exception as e:
        logging.error(f"Chart xato: {e}")
        try: plt.close("all")
        except: pass
        gc.collect()
        return None


# ════════════════════════════════
# HALOLLIK — MUSAFFA.COM
# ════════════════════════════════

def check_halal(ticker):
    url = f"https://musaffa.com/stock/{ticker}"
    try:
        r    = requests.get(url, headers=HDR, timeout=15)
        text = BeautifulSoup(r.text, "lxml").get_text().lower()
        if any(w in text for w in ["halal", "compliant", "permissible"]):
            return "✅ HALOL", url
        if any(w in text for w in ["haram", "not compliant", "prohibited"]):
            return "❌ HAROM", url
        if any(w in text for w in ["doubtful", "questionable"]):
            return "⚠️ SHUBHALI", url
    except Exception as e:
        logging.warning(f"Musaffa {ticker}: {e}")
    return "❓ NOMA'LUM", url


# ════════════════════════════════
# TELEGRAM
# ════════════════════════════════

def tg_send(text, cid=None, markup=None):
    c = cid or CHAT
    u = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    p = {"chat_id": c, "text": text[:4000],
         "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        p["reply_markup"] = json.dumps(markup)
    try:
        r = requests.post(u, json=p, timeout=15)
        if r.status_code != 200:
            p.pop("parse_mode", None)
            requests.post(u, json=p, timeout=15)
    except Exception as e:
        logging.error(f"tg_send: {e}")


def tg_photo(buf, caption, cid=None, markup=None):
    if buf is None:
        return False
    c = cid or CHAT
    u = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        buf.seek(0)
        files = {"photo": ("chart.png", buf.read(), "image/png")}
        p = {"chat_id": c, "caption": caption[:1024], "parse_mode": "HTML"}
        if markup:
            p["reply_markup"] = json.dumps(markup)
        r = requests.post(u, data=p, files=files, timeout=30)
        ok = r.status_code == 200
        logging.info(f"tg_photo: {ok} | {r.status_code}")
        return ok
    except Exception as e:
        logging.error(f"tg_photo: {e}")
        return False


def main_kb():
    return {"inline_keyboard": [
        [{"text": "📊 Signal",   "callback_data": "signal"},
         {"text": "☪️ Halol",    "callback_data": "halol"}],
        [{"text": "🚀 IPO",      "callback_data": "ipo"},
         {"text": "📰 Yangilik", "callback_data": "news"}],
        [{"text": "⚡ Breakout", "callback_data": "breakout"}],
    ]}


def aksiya_kb(ticker):
    return {"inline_keyboard": [
        [{"text": "📺 TradingView",
          "url": f"https://www.tradingview.com/chart/?symbol={ticker}"},
         {"text": "☪️ Musaffa",
          "url": f"https://musaffa.com/stock/{ticker}"}],
        [{"text": "🔄 Yangilash", "callback_data": f"r_{ticker}"}],
    ]}


# ════════════════════════════════
# ASOSIY TAHLIL — FAQAT RASM + HALOLLIK
# ════════════════════════════════

def tahlil(ticker, cid):
    ticker = ticker.upper().strip()
    tg_send(f"🔍 <b>{ticker}</b> yuklanmoqda...", cid)

    # Narx
    p = get_price(ticker)
    if not p or p.get("p", 0) == 0:
        tg_send(f"❌ <b>{ticker}</b> topilmadi.", cid)
        return

    # Shamlar
    candles = get_candles(ticker, 60)
    if not candles:
        tg_send(f"❌ <b>{ticker}</b> grafik ma'lumoti topilmadi.", cid)
        return

    # Texnik
    sups, ress = calc_sr(candles)
    tr = calc_trend(candles)
    at = calc_atr(candles)

    # Chart
    buf = draw_chart(ticker, candles, sups, ress, p, tr, at)

    # Halollik
    halal_s, halal_url = check_halal(ticker)

    # Caption
    cur  = p.get("p", 0)
    chg  = p.get("chg", 0)
    sign = "+" if chg >= 0 else ""
    sup_s = "  ".join([f"${s}" for s in sups[:3]]) or "—"
    res_s = "  ".join([f"${r}" for r in ress[:3]]) or "—"

    caption = (
        f"<b>{ticker}</b>\n"
        f"💵 ${round(cur, 2)}  ({sign}{chg}%)\n"
        f"📈 {tr['dir']}  |  ATR: ${at}\n"
        f"🟢 S: {sup_s}\n"
        f"🔴 R: {res_s}\n"
        f"☪️ {halal_s}"
    )

    # Rasm yuborish
    if buf:
        ok = tg_photo(buf, caption, cid, aksiya_kb(ticker))
        if not ok:
            # Rasm yuborish ishlamasa matn yuboramiz
            tg_send(
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>{ticker}</b>\n"
                f"💵 ${round(cur, 2)}  ({sign}{chg}%)\n"
                f"📈 {tr['dir']}  |  ATR: ${at}\n\n"
                f"🟢 <b>Support:</b> {sup_s}\n"
                f"🔴 <b>Resistance:</b> {res_s}\n\n"
                f"☪️ <b>Halollik:</b> {halal_s}\n"
                f"🔗 <a href='{halal_url}'>Musaffa da ko'rish</a>\n\n"
                f"📺 <a href='https://www.tradingview.com/chart/?symbol={ticker}'>"
                f"TradingView da ko'rish</a>",
                cid, aksiya_kb(ticker)
            )
    else:
        tg_send(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>{ticker}</b>\n"
            f"💵 ${round(cur, 2)}  ({sign}{chg}%)\n"
            f"📈 {tr['dir']}  |  ATR: ${at}\n\n"
            f"🟢 <b>Support:</b> {sup_s}\n"
            f"🔴 <b>Resistance:</b> {res_s}\n\n"
            f"☪️ <b>Halollik:</b> {halal_s}\n"
            f"🔗 <a href='{halal_url}'>Musaffa da ko'rish</a>\n\n"
            f"📺 <a href='https://www.tradingview.com/chart/?symbol={ticker}'>"
            f"TradingView da ko'rish</a>",
            cid, aksiya_kb(ticker)
        )
    gc.collect()


# ════════════════════════════════
# SKREENER
# ════════════════════════════════

def skreener(halol=False, bo_only=False):
    tag = "HALOL " if halol else "BREAKOUT " if bo_only else ""
    logging.info(f"Skreener: {tag}")
    signals = []

    for ticker in WATCHLIST:
        p = get_price(ticker)
        if not p or p.get("p", 0) == 0:
            time.sleep(12); continue
        chg = p.get("chg", 0); c = p.get("p", 0)
        vu  = p.get("v", 0) * c

        if vu < 1_000_000: time.sleep(12); continue
        if not bo_only and not (2.0 <= abs(chg) <= 15.0): time.sleep(12); continue

        cn = get_candles(ticker, 45)
        sv, rs = calc_sr(cn)
        tr = calc_trend(cn) if cn else None
        at = calc_atr(cn)
        time.sleep(12)

        # Breakout tekshirish
        cur = c; av = np.mean([x["v"] for x in cn[-20:]]) if len(cn) >= 20 else vu
        vr  = (vu / av) if av > 0 else 1
        bo  = []
        for r in rs:
            if 0 < (cur - r) / r * 100 < 3:
                sc = 2 + (2 if vr > 1.5 else 0) + (1 if chg > 2 else 0)
                bo.append({"type": "RESISTANCE YORILDI", "level": r, "score": sc})
        for s in sv:
            if 0 < (s - cur) / s * 100 < 3:
                sc = 2 + (2 if vr > 1.5 else 0) + (1 if chg < -2 else 0)
                bo.append({"type": "SUPPORT YORILDI", "level": s, "score": sc})

        if halol:
            hs, _ = check_halal(ticker)
            if "HAROM" in hs: time.sleep(2); continue

        if bo_only and not bo: continue

        sab = []
        if abs(chg) > 5:    sab.append("Kuchli")
        if vu > 10_000_000: sab.append("Yuqori hajm")
        if bo:              sab.append("⚡ " + bo[0]["type"])
        if tr and "Yuqoriga" in tr["dir"]: sab.append("Uptrend")

        signals.append({
            "ticker": ticker, "chg": chg, "c": c,
            "vu": vu, "tr": tr["dir"] if tr else "—",
            "bo": bo[0]["type"] if bo else "—",
            "sab": " | ".join(sab) or "Mezon",
        })
        logging.info(f"  {ticker} {chg:+.1f}%")
        time.sleep(12)

    if not signals:
        tg_send(f"📊 {tag}Hozir shart bajargan aksiya topilmadi.")
        return

    signals.sort(key=lambda x: abs(x["chg"]), reverse=True)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"🤖 <b>AVTOMATIK {tag}SIGNAL</b>",
        f"🕐 {now}",
        f"Topilgan: <b>{len(signals)} ta</b>",
        "━━━━━━━━━━━━━━━━━━━━\n",
    ]
    for s in signals[:12]:
        em = "🟢" if s["chg"] > 0 else "🔴"
        sg = "+" if s["chg"] >= 0 else ""
        lines.append(
            f"{em} <b>{s['ticker']}</b>  ${round(s['c'], 2)}"
            f"  ({sg}{round(s['chg'], 1)}%)\n"
            f"  📈 {s['tr']}  ⚡ {s['bo']}\n"
            f"  {s['sab']}\n"
        )
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    tg_send("\n".join(lines), markup=main_kb())


# ════════════════════════════════
# IPO
# ════════════════════════════════

def get_ipos():
    lst = []
    try:
        r    = requests.get("https://api.nasdaq.com/api/ipo/calendar",
                            headers=HDR, timeout=15)
        data = r.json().get("data", {})
        for ipo in data.get("upcoming", {}).get("upcomingTable", {}).get("rows", [])[:6]:
            lst.append({
                "n": ipo.get("companyName", "N/A"),
                "t": ipo.get("proposedTickerSymbol", "N/A"),
                "b": ipo.get("proposedExchange", "N/A"),
                "p": ipo.get("priceRangeLow", "") + "-" + ipo.get("priceRangeHigh", ""),
                "d": ipo.get("expectedPriceDate", "N/A"),
                "s": "Kutilmoqda",
            })
        for ipo in data.get("recent", {}).get("recentTable", {}).get("rows", [])[:4]:
            lst.append({
                "n": ipo.get("companyName", "N/A"),
                "t": ipo.get("proposedTickerSymbol", "N/A"),
                "ip": ipo.get("ipoPrice", "N/A"),
                "cp": ipo.get("currentPrice", "N/A"),
                "ch": ipo.get("pctChange", "N/A"),
                "d":  ipo.get("pricedDate", "N/A"),
                "s":  "Yangi",
            })
    except Exception as e:
        logging.warning(f"IPO: {e}")
    return lst


def ipo_text(lst):
    if not lst: return "IPO ma'lumotlari topilmadi."
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = ["━━━━━━━━━━━━━━━━━━━━",
             "🚀 <b>IPO YANGILIKLARI</b>",
             f"🕐 {now}", "━━━━━━━━━━━━━━━━━━━━\n"]
    for i in lst:
        if i["s"] == "Kutilmoqda":
            lines.append(
                f"🗓 <b>{i['n']}</b> ({i['t']})\n"
                f"  🏦 {i['b']} | 💰 ${i['p']} | 📅 {i['d']}\n"
            )
        else:
            try: pct = float(str(i.get("ch","0")).replace("%","").replace("+","") or 0)
            except: pct = 0
            em = "🟢" if pct >= 0 else "🔴"
            lines.append(
                f"{em} <b>{i['n']}</b> ({i['t']})\n"
                f"  IPO: ${i.get('ip','—')} → ${i.get('cp','—')}"
                f"  {i.get('ch','—')}%\n"
                f"  📅 {i['d']}\n"
            )
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    return "\n".join(lines)


# ════════════════════════════════
# YANGILIKLAR
# ════════════════════════════════

def get_news(ticker=None, count=8):
    url  = (f"https://finance.yahoo.com/quote/{ticker}/news/"
            if ticker else "https://finance.yahoo.com/news/")
    news = []
    try:
        r    = requests.get(url, headers=HDR, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for art in soup.find_all("h3", limit=count * 2):
            a = art.find("a")
            if a and len(a.get_text(strip=True)) > 15:
                t = a.get_text(strip=True)
                h = a.get("href", "")
                if h and not h.startswith("http"):
                    h = "https://finance.yahoo.com" + h
                news.append({"t": t, "u": h})
            if len(news) >= count: break
    except Exception: pass
    return news


def news_html(lst):
    lines = []
    for n in lst:
        lines.append("• <a href='" + n["u"] + "'>" + n["t"][:70] + "</a>")
    return "\n".join(lines)


# ════════════════════════════════
# POLLING
# ════════════════════════════════

def polling():
    offset = None
    logging.info("Polling boshlandi...")

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                params={"timeout": 25, "offset": offset,
                        "allowed_updates": ["message", "callback_query"]},
                timeout=30)
            updates = r.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1

                # Callback
                if "callback_query" in upd:
                    cb  = upd["callback_query"]
                    d   = cb.get("data", "")
                    cid = str(cb["message"]["chat"]["id"])
                    requests.post(
                        f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"], "text": "⏳"},
                        timeout=5)

                    if d == "signal":
                        tg_send("🔍 Signal tekshirilmoqda...", cid)
                        threading.Thread(target=skreener, daemon=True).start()
                    elif d == "halol":
                        tg_send("☪️ Halol aksiyalar...", cid)
                        threading.Thread(target=lambda: skreener(halol=True), daemon=True).start()
                    elif d == "ipo":
                        threading.Thread(
                            target=lambda c=cid: tg_send(ipo_text(get_ipos()), c),
                            daemon=True).start()
                    elif d == "news":
                        def _news(c=cid):
                            news = get_news(count=8)
                            tg_send("📰 <b>YANGILIKLAR</b>\n\n" + news_html(news), c)
                        threading.Thread(target=_news, daemon=True).start()
                    elif d == "breakout":
                        tg_send("⚡ Breakout tekshirilmoqda...", cid)
                        threading.Thread(target=lambda: skreener(bo_only=True), daemon=True).start()
                    elif d.startswith("r_"):
                        tkr = d[2:]
                        threading.Thread(target=tahlil, args=(tkr, cid), daemon=True).start()
                    continue

                # Xabar
                msg  = upd.get("message", {})
                text = msg.get("text", "").strip()
                cid  = str(msg.get("chat", {}).get("id", ""))
                if not text or not cid: continue
                logging.info(f"'{text}' — {cid}")

                if text in ("/start", "/help"):
                    tg_send(
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "👋 <b>Stock Signal Bot v10</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "📊 Ticker yozing: <code>AAPL</code>, <code>NVDA</code>\n\n"
                        "Bot yuboradi:\n"
                        "  ✅ Grafik (trendline + S/R)\n"
                        "  ✅ Support va Resistance\n"
                        "  ✅ Halollik (Musaffa.com)\n\n"
                        "Buyruqlar:\n"
                        "  /signal — Signal\n"
                        "  /halol  — Halol aksiyalar\n"
                        "  /ipo    — IPO\n"
                        "  /news   — Yangiliklar\n",
                        cid, main_kb()
                    )
                elif text == "/signal":
                    tg_send("🔍 Signal tekshirilmoqda...", cid)
                    threading.Thread(target=skreener, daemon=True).start()
                elif text in ("/halol", "/halal"):
                    tg_send("☪️ Halol aksiyalar...", cid)
                    threading.Thread(target=lambda: skreener(halol=True), daemon=True).start()
                elif text == "/ipo":
                    threading.Thread(
                        target=lambda c=cid: tg_send(ipo_text(get_ipos()), c),
                        daemon=True).start()
                elif text in ("/news", "/yangilik"):
                    def _n2(c=cid):
                        news = get_news(count=8)
                        tg_send("📰 <b>YANGILIKLAR</b>\n\n" + news_html(news), c)
                    threading.Thread(target=_n2, daemon=True).start()
                elif text == "/breakout":
                    tg_send("⚡ Breakout tekshirilmoqda...", cid)
                    threading.Thread(target=lambda: skreener(bo_only=True), daemon=True).start()
                elif text.startswith("/"):
                    tg_send("❓ /help yozing.", cid)
                elif re.match(r"^[A-Za-z]{1,6}$", text):
                    threading.Thread(target=tahlil, args=(text, cid), daemon=True).start()
                else:
                    tg_send("💡 Ticker yozing: <code>AAPL</code>", cid, main_kb())

        except Exception as e:
            logging.error(f"Polling: {e}")
            time.sleep(5)


# ════════════════════════════════
# MAIN
# ════════════════════════════════

def main():
    logging.info("Stock Signal Bot v10 ishga tushdi")

    schedule.every(4).hours.do(skreener)
    schedule.every().day.at("09:35").do(skreener)
    schedule.every().day.at("16:05").do(skreener)

    threading.Thread(
        target=lambda: [(schedule.run_pending(), time.sleep(60))
                        for _ in iter(int, 1)],
        daemon=True).start()

    tg_send(
        "🤖 <b>Stock Signal Bot v10 ishga tushdi!</b>\n\n"
        "✅ Grafik (trendline + S/R + Bollinger)\n"
        "✅ Halollik — Musaffa.com\n"
        "✅ Tez va sodda\n\n"
        "💡 <code>AAPL</code> yozing!",
        markup=main_kb()
    )

    polling()


if __name__ == "__main__":
    main()
