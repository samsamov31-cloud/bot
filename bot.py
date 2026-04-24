"""
Stock Signal Telegram Bot v9.0
pip install requests schedule beautifulsoup4 lxml matplotlib numpy pillow openai python-dotenv
"""

import requests, schedule, time, logging, threading, re, io, json, os, gc
import numpy as np
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# ── Matplotlib ──
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    _f = plt.figure(); plt.close(_f)
    MPL = True
    logging.info("Matplotlib OK")
except Exception as e:
    MPL = False
    logging.warning("Matplotlib: " + str(e))

# ── OpenAI ──
try:
    from openai import OpenAI as _OAI
    AI = True
except ImportError:
    AI = False

# ═══════════════════════════════════════════
# SOZLAMALAR
# ═══════════════════════════════════════════
TG_TOKEN  = os.environ.get("TELEGRAM_TOKEN",   "")
TG_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
POLY_KEY  = os.environ.get("POLYGON_KEY",      "")
OAI_KEY   = os.environ.get("OPENAI_KEY",       "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO",
    "JPM","V","UNH","XOM","LLY","MA","JNJ","PG","HD","MRK",
    "ABBV","CVX","CRM","BAC","COST","NFLX","AMD","ADBE","WMT",
    "ACN","ORCL","MCD","QCOM","DIS","TXN","INTC","GS","HOOD",
    "PLTR","SOFI","COIN","SQ","SNAP","UBER","RBLX","PYPL",
    "SHOP","CRWD","DDOG","NET","SNOW","ARM","SMCI","MU","F",
]

chat_hist = {}

# ═══════════════════════════════════════════
# TELEGRAM — YUBORISH
# ═══════════════════════════════════════════

def tg(text, cid=None, markup=None):
    c = cid or TG_CHAT
    u = "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage"
    for i, chunk in enumerate([text[j:j+4000] for j in range(0, len(text), 4000)]):
        p = {"chat_id": c, "text": chunk, "parse_mode": "HTML",
             "disable_web_page_preview": True}
        if markup and i == 0:
            p["reply_markup"] = json.dumps(markup)
        try:
            r = requests.post(u, json=p, timeout=15)
            if r.status_code != 200:
                p.pop("parse_mode", None)
                requests.post(u, json=p, timeout=15)
        except Exception as e:
            logging.error("tg: " + str(e))
        time.sleep(0.3)


def tg_photo(buf, caption, cid=None, markup=None):
    if buf is None:
        return False
    c = cid or TG_CHAT
    u = "https://api.telegram.org/bot" + TG_TOKEN + "/sendPhoto"
    try:
        buf.seek(0)
        files = {"photo": ("chart.png", buf.read(), "image/png")}
        p = {"chat_id": c, "caption": caption[:1024], "parse_mode": "HTML"}
        if markup:
            p["reply_markup"] = json.dumps(markup)
        r = requests.post(u, data=p, files=files, timeout=30)
        return r.status_code == 200
    except Exception as e:
        logging.error("tg_photo: " + str(e))
        return False


def menu_asosiy():
    return {"inline_keyboard": [
        [{"text": "📊 Signal",    "callback_data": "signal"},
         {"text": "☪️ Halol",     "callback_data": "halol"}],
        [{"text": "🚀 IPO",       "callback_data": "ipo"},
         {"text": "📰 Yangilik",  "callback_data": "yangilik"}],
        [{"text": "⚡ Breakout",  "callback_data": "breakout"},
         {"text": "🌅 Ertalab",   "callback_data": "ertalab"}],
    ]}


def menu_aksiya(ticker):
    return {"inline_keyboard": [
        [{"text": "📺 TradingView",
          "url": "https://www.tradingview.com/chart/?symbol=" + ticker},
         {"text": "☪️ Musaffa",
          "url": "https://musaffa.com/stock/" + ticker}],
        [{"text": "🔄 Yangilash",   "callback_data": "y_" + ticker},
         {"text": "📰 Yangiliklar", "callback_data": "n_" + ticker}],
    ]}


# ═══════════════════════════════════════════
# POLYGON — NARX
# ═══════════════════════════════════════════

def narx(ticker):
    # 1. Polygon prev day (bepul)
    try:
        r = requests.get(
            "https://api.polygon.io/v2/aggs/ticker/" + ticker +
            "/prev?adjusted=true&apiKey=" + POLY_KEY, timeout=10)
        res = r.json().get("results", [])
        if res:
            d = res[0]
            o = d.get("o", 0); c = d.get("c", 0)
            chg = round((c - o) / o * 100, 2) if o > 0 else 0
            return {"price": c, "open": o, "high": d.get("h", 0),
                    "low": d.get("l", 0), "close": c,
                    "volume": d.get("v", 0), "vwap": d.get("vw", 0),
                    "chg": chg}
    except Exception:
        pass

    # 2. Yahoo Finance backup
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/" + ticker +
            "?interval=1d&range=2d", headers=HEADERS, timeout=10)
        meta = r.json()["chart"]["result"][0]["meta"]
        p    = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", 0)
        chg  = round((p - prev) / prev * 100, 2) if prev > 0 else 0
        return {"price": p, "open": meta.get("regularMarketOpen", p),
                "high": meta.get("regularMarketDayHigh", p),
                "low": meta.get("regularMarketDayLow", p),
                "close": p, "volume": meta.get("regularMarketVolume", 0),
                "vwap": p, "chg": chg}
    except Exception as e:
        logging.warning("narx (" + ticker + "): " + str(e))
    return None


def shamlar(ticker, days=60):
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days+20)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://api.polygon.io/v2/aggs/ticker/" + ticker +
            "/range/1/day/" + start + "/" + end +
            "?adjusted=true&sort=asc&limit=100&apiKey=" + POLY_KEY, timeout=15)
        d = r.json().get("results", [])
        return d[-days:] if len(d) >= days else d
    except Exception:
        return []


def kompaniya(ticker):
    try:
        r   = requests.get(
            "https://api.polygon.io/v3/reference/tickers/" + ticker +
            "?apiKey=" + POLY_KEY, timeout=10)
        res = r.json().get("results", {})

        # Kompaniya tavsifini tarjima qilish (AI orqali)
        desc_en = (res.get("description") or "")[:400]
        desc_uz = tarjima_uz(desc_en) if desc_en else ""

        return {
            "nomi":    res.get("name", ticker),
            "sektor":  res.get("sic_description", "N/A"),
            "kapital": res.get("market_cap", 0) or 0,
            "xodim":   res.get("total_employees", 0) or 0,
            "tavsif":  desc_uz or desc_en[:200],
        }
    except Exception:
        return {"nomi": ticker, "sektor": "N/A",
                "kapital": 0, "xodim": 0, "tavsif": ""}


def texnik(ticker):
    res = {"rsi": None, "sma50": None, "sma200": None}
    for ind, win, key in [("rsi", 14, "rsi"), ("sma", 50, "sma50"), ("sma", 200, "sma200")]:
        try:
            r = requests.get(
                "https://api.polygon.io/v1/indicators/" + ind + "/" + ticker +
                "?timespan=day&window=" + str(win) +
                "&series_type=close&limit=1&apiKey=" + POLY_KEY, timeout=10)
            v = r.json().get("results", {}).get("values", [])
            if v:
                res[key] = round(v[0]["value"], 2)
        except Exception:
            pass
        time.sleep(13)
    return res


# ═══════════════════════════════════════════
# AI — TARJIMA, STRATEGIYA, SUHBAT
# ═══════════════════════════════════════════

def ai_so(prompt, max_tok=500):
    if not AI or not OAI_KEY:
        return ""
    try:
        client = _OAI(api_key=OAI_KEY)
        resp   = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tok, temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.warning("AI: " + str(e))
        return ""


def tarjima_uz(matn):
    if not matn: return ""
    return ai_so(
        "Quyidagi inglizcha matnni O'ZBEK TILIGA tarjima qiling. "
        "Faqat tarjimani bering, boshqa narsa yozmang:\n\n" + matn[:300],
        max_tok=300
    )


def ai_strategiya(ticker, p, komp, tex, sups, ress, trend, breakouts, atr):
    if not AI or not OAI_KEY:
        return ("", None)
    cur = p.get("price", 0); chg = p.get("chg", 0)
    vol = p.get("volume", 0) * cur
    prompt = (
        "Siz professional texnik tahlilchisiz. "
        "Quyidagi aksiya uchun FAQAT O'ZBEK TILIDA strategiya bering.\n\n"
        "Ticker: " + ticker + " (" + komp.get("nomi","") + ")\n"
        "Narx: $" + str(round(cur,2)) + " (" + str(chg) + "%)\n"
        "Hajm: $" + str(round(vol/1e6,1)) + " mln\n"
        "RSI: " + str(tex.get("rsi","N/A")) + "\n"
        "SMA50: $" + str(tex.get("sma50","N/A")) + "\n"
        "Trend: " + (trend.get("dir","N/A") if trend else "N/A") + "\n"
        "Support: " + str(sups[:2]) + "\n"
        "Resistance: " + str(ress[:2]) + "\n"
        "ATR: $" + str(atr) + "\n"
        "Breakout: " + (breakouts[0]["type"] if breakouts else "yo'q") + "\n\n"
        "FAQAT JSON qaytaring (boshqa narsa yozmang):\n"
        "{\n"
        "  \"tahlil\": \"O'zbekcha qisqa tahlil (max 80 so'z)\",\n"
        "  \"signal\": \"SOTIB_OL yoki SOT yoki KUZAT\",\n"
        "  \"kirish\": narx_float,\n"
        "  \"stop\": narx_float,\n"
        "  \"profit\": narx_float,\n"
        "  \"sabab\": \"1-2 jumlada sabab\"\n"
        "}"
    )
    try:
        raw  = ai_so(prompt, max_tok=350)
        raw  = raw.replace("```json","").replace("```","").strip()
        data = json.loads(raw)
        matn = (
            "🤖 <b>AI Strategiyasi</b>\n\n"
            + str(data.get("tahlil","")) + "\n\n"
            "📌 Signal: <b>" + str(data.get("signal","")) + "</b>\n"
            "🎯 Kirish:      $" + str(data.get("kirish","")) + "\n"
            "🛑 Stop Loss:   $" + str(data.get("stop","")) + "\n"
            "💰 Take Profit: $" + str(data.get("profit","")) + "\n"
            "💡 " + str(data.get("sabab",""))
        )
        levels = {
            "kirish": float(data.get("kirish", cur)),
            "stop":   float(data.get("stop",   round(cur*0.97,2))),
            "profit": float(data.get("profit", round(cur*1.05,2))),
        }
        return (matn, levels)
    except Exception as e:
        logging.warning("AI strategiya: " + str(e))
        return ("", None)


def ai_suhbat(cid, savol):
    if not AI or not OAI_KEY:
        return "⚠️ AI hozir mavjud emas."
    if cid not in chat_hist:
        chat_hist[cid] = [{"role": "system", "content": (
            "Siz professional moliyaviy maslahatchi va investitsiya mutaxassisisiz. "
            "FAQAT O'ZBEK TILIDA javob bering. "
            "Amerika fond bozori, aksiyalar, halol investitsiya haqida bilimingiz bor. "
            "Javoblar qisqa va foydali bo'lsin. Emoji ishlating."
        )}]
    if len(chat_hist[cid]) > 20:
        chat_hist[cid] = chat_hist[cid][:1] + chat_hist[cid][-10:]
    chat_hist[cid].append({"role": "user", "content": savol})
    try:
        client = _OAI(api_key=OAI_KEY)
        resp   = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=chat_hist[cid],
            max_tokens=400, temperature=0.8,
        )
        javob = resp.choices[0].message.content.strip()
        chat_hist[cid].append({"role": "assistant", "content": javob})
        return javob
    except Exception as e:
        logging.error("AI suhbat: " + str(e))
        return "⚠️ AI hozir band. Keyinroq urinib ko'ring."


# ═══════════════════════════════════════════
# TEXNIK HISOB — S/R, TREND, ATR, BREAKOUT
# ═══════════════════════════════════════════

def sr(candles):
    if len(candles) < 10: return [], []
    H = np.array([c["h"] for c in candles])
    L = np.array([c["l"] for c in candles])
    C = np.array([c["c"] for c in candles])
    s, r = [], []
    for i in range(3, len(L)-3):
        if L[i] == min(L[i-3:i+4]): s.append(round(L[i],2))
    for i in range(3, len(H)-3):
        if H[i] == max(H[i-3:i+4]): r.append(round(H[i],2))
    def cl(lvs, t=0.02):
        if not lvs: return []
        lvs = sorted(set(lvs)); out = [lvs[0]]
        for v in lvs[1:]:
            if abs(v-out[-1])/out[-1] > t: out.append(v)
        return out
    cur = C[-1]
    return (sorted([v for v in cl(s) if v < cur], reverse=True)[:4],
            sorted([v for v in cl(r) if v > cur])[:4])


def trend(candles, lb=30):
    if len(candles) < lb: lb = len(candles)
    x = np.arange(lb)
    C = np.array([c["c"] for c in candles[-lb:]])
    sl, ic = np.polyfit(x, C, 1)
    if sl > C[-1]*0.0003:    d = "📈 Yuqoriga"
    elif sl < -C[-1]*0.0003: d = "📉 Pastga"
    else:                     d = "➡️ Yon"
    return {"sl": sl, "ic": ic, "dir": d, "lb": lb}


def atr(candles, p=14):
    if len(candles) < p+1: return 0
    trs = [max(candles[i]["h"]-candles[i]["l"],
               abs(candles[i]["h"]-candles[i-1]["c"]),
               abs(candles[i]["l"]-candles[i-1]["c"]))
           for i in range(1, len(candles))]
    return round(np.mean(trs[-p:]), 2)


def breakout(candles, sups, ress, price):
    if not candles or len(candles) < 5: return []
    cur = price.get("price",0); vol = price.get("volume",0)
    chg = price.get("chg",0)
    av  = np.mean([c["v"] for c in candles[-20:]]) if len(candles)>=20 else vol
    vr  = vol/av if av > 0 else 1
    res = []
    for r in ress:
        d = (cur-r)/r*100
        if 0 < d < 3:
            sc = 2; om = ["Resistance yorildi +"+str(round(d,1))+"%"]
            if vr>1.5: sc+=2; om.append("Hajm "+str(round(vr,1))+"x")
            if chg>2:  sc+=1; om.append("O'sish +"+str(round(chg,1))+"%")
            res.append({"type":"⚡ RESISTANCE YORILDI","level":r,
                        "score":sc,"omillar":om,
                        "signal":"🟢 KUCHLI SOTIB OL" if sc>=4 else "🟡 EHTIYOT BILAN"})
        elif -1 < d <= 0:
            res.append({"type":"🔔 Resistance ga yaqin","level":r,
                        "score":1,"omillar":["$"+str(r)+" — kuzat"],"signal":"👀 KUZAT"})
    for s in sups:
        d = (s-cur)/s*100
        if 0 < d < 3:
            sc = 2; om = ["Support yorildi -"+str(round(d,1))+"%"]
            if vr>1.5: sc+=2; om.append("Hajm "+str(round(vr,1))+"x")
            if chg<-2: sc+=1; om.append("Tushish "+str(round(chg,1))+"%")
            res.append({"type":"⚠️ SUPPORT YORILDI","level":s,
                        "score":sc,"omillar":om,
                        "signal":"🔴 KUCHLI SOT" if sc>=4 else "🟡 EHTIYOT BO'L"})
        elif -1 < d <= 0:
            res.append({"type":"🔔 Support ga yaqin","level":s,
                        "score":1,"omillar":["$"+str(s)+" — kuzat"],"signal":"👀 KUZAT"})
    return res


# ═══════════════════════════════════════════
# CHART — TradingView uslubida
# ═══════════════════════════════════════════

def chart(ticker, candles, sups, ress, price, tr, bo, at, ai_lev=None):
    logging.info("Chart: " + ticker + " MPL=" + str(MPL) + " candles=" + str(len(candles)))
    if not MPL or len(candles) < 10: return None
    try:
        matplotlib.use("Agg")
        BG="#131722"; GR="#1e222d"; BL="#26a69a"; BR="#ef5350"; TX="#d1d4dc"; MU="#4a4e5a"
        fig = plt.figure(figsize=(14,9), facecolor=BG)
        gs  = fig.add_gridspec(4,1,height_ratios=[4,1,1,1],hspace=0.0,
                               left=0.01,right=0.87,top=0.93,bottom=0.06)
        a1=fig.add_subplot(gs[0]); a2=fig.add_subplot(gs[1],sharex=a1)
        a3=fig.add_subplot(gs[2],sharex=a1); a4=fig.add_subplot(gs[3],sharex=a1)
        for ax in [a1,a2,a3,a4]:
            ax.set_facecolor(BG); ax.tick_params(colors=MU,labelsize=7,length=2)
            for sp in ax.spines.values(): sp.set_color(GR); sp.set_linewidth(0.4)
            ax.yaxis.set_label_position("right"); ax.yaxis.tick_right()
            ax.grid(True,color=GR,linewidth=0.3,alpha=0.8)

        O=np.array([c["o"] for c in candles]); H=np.array([c["h"] for c in candles])
        L=np.array([c["l"] for c in candles]); C=np.array([c["c"] for c in candles])
        V=np.array([c["v"] for c in candles]); n=len(candles)

        # X o'qi sanalar
        step = max(1, n//7)
        xp = list(range(0,n,step))
        xl = []
        for idx in xp:
            t = candles[idx].get("t",0)
            if t:
                from datetime import datetime as dt
                xl.append(dt.fromtimestamp(t/1000).strftime("%d %b"))
            else: xl.append("")
        for ax in [a2,a3,a4]:
            ax.set_xticks(xp); ax.set_xticklabels(xl,fontsize=7,color=MU)
        a1.set_xticks(xp); a1.set_xticklabels([],visible=False)

        # Bollinger Bands
        if n>=20:
            bm=np.convolve(C,np.ones(20)/20,mode="valid")
            bs=np.array([C[i:i+20].std() for i in range(n-19)])
            bx=np.arange(19,n)
            a1.plot(bx,bm+2*bs,color="#5c6bc0",lw=0.7,ls=":",alpha=0.5)
            a1.plot(bx,bm-2*bs,color="#5c6bc0",lw=0.7,ls=":",alpha=0.5)
            a1.fill_between(bx,bm-2*bs,bm+2*bs,color="#5c6bc0",alpha=0.03)

        # SMA
        if n>=20:
            s20=np.convolve(C,np.ones(20)/20,mode="valid")
            a1.plot(range(19,n),s20,color="#7986cb",lw=1.0,label="MA20",alpha=0.9)
        if n>=50:
            s50=np.convolve(C,np.ones(50)/50,mode="valid")
            a1.plot(range(49,n),s50,color="#f59e0b",lw=1.0,label="MA50",alpha=0.9)

        # Shamlar
        for i in range(n):
            o,h,l,c=O[i],H[i],L[i],C[i]
            col=BL if c>=o else BR
            a1.bar(i,max(abs(c-o),(h-l)*0.003),bottom=min(o,c),
                   color=col,width=0.6,zorder=3,ec=col,lw=0.2)
            a1.plot([i,i],[l,h],color=col,lw=0.7,zorder=2)

        # Trendline
        if tr:
            lb=tr["lb"]; tx=np.arange(n-lb,n)
            ty=tr["sl"]*np.arange(lb)+tr["ic"]
            tc=BL if "Yuqoriga" in tr["dir"] else BR if "Pastga" in tr["dir"] else "#90a4ae"
            a1.plot(tx,ty,color=tc,lw=2.0,ls="-",zorder=5,label="Trend",alpha=0.85)
            fx=np.arange(n,n+6); fy=tr["sl"]*np.arange(lb,lb+6)+tr["ic"]
            a1.plot(fx,fy,color=tc,lw=1.2,ls=":",zorder=5,alpha=0.4)

        # Support zona (ko'k)
        for i,s in enumerate(sups[:3]):
            zh=s*0.008
            a1.axhspan(s-zh,s+zh,color="#00bcd4",alpha=0.12,zorder=1)
            a1.axhline(y=s,color="#00bcd4",lw=1.0,ls="--",alpha=0.8,zorder=4)
            a1.annotate("S"+str(i+1)+" $"+str(s),xy=(n-1,s),xytext=(n+0.5,s),
                        fontsize=8,color="#00bcd4",fontweight="bold",
                        va="center",annotation_clip=False)

        # Resistance zona (qizil)
        for i,r in enumerate(ress[:3]):
            zh=r*0.008
            a1.axhspan(r-zh,r+zh,color=BR,alpha=0.10,zorder=1)
            a1.axhline(y=r,color=BR,lw=1.0,ls="--",alpha=0.8,zorder=4)
            a1.annotate("R"+str(i+1)+" $"+str(r),xy=(n-1,r),xytext=(n+0.5,r),
                        fontsize=8,color=BR,fontweight="bold",
                        va="center",annotation_clip=False)

        # AI chiziqlari
        if ai_lev:
            kir=ai_lev.get("kirish"); stp=ai_lev.get("stop"); prf=ai_lev.get("profit")
            if kir:
                a1.axhline(y=kir,color="#00e676",lw=1.8,ls="-.",zorder=6,alpha=0.95)
                a1.annotate("AI Kirish $"+str(round(kir,2)),xy=(n-1,kir),
                            xytext=(n+0.5,kir),fontsize=8,color="#00e676",
                            fontweight="bold",va="bottom",annotation_clip=False)
            if stp:
                a1.axhline(y=stp,color="#ff1744",lw=1.8,ls="-.",zorder=6,alpha=0.95)
                a1.annotate("Stop $"+str(round(stp,2)),xy=(n-1,stp),
                            xytext=(n+0.5,stp),fontsize=8,color="#ff1744",
                            fontweight="bold",va="top",annotation_clip=False)
            if prf:
                a1.axhline(y=prf,color="#69f0ae",lw=1.8,ls="-.",zorder=6,alpha=0.95)
                a1.annotate("Profit $"+str(round(prf,2)),xy=(n-1,prf),
                            xytext=(n+0.5,prf),fontsize=8,color="#69f0ae",
                            fontweight="bold",va="bottom",annotation_clip=False)
            if kir and stp: a1.axhspan(min(stp,kir),max(stp,kir),color=BR,alpha=0.05)
            if kir and prf: a1.axhspan(min(kir,prf),max(kir,prf),color=BL,alpha=0.04)

        # Breakout belgisi
        if bo:
            for b in bo:
                if "YORILDI" in b["type"]:
                    col=BL if "RESISTANCE" in b["type"] else BR
                    mk="^" if "RESISTANCE" in b["type"] else "v"
                    a1.scatter([n-1],[price.get("price",C[-1])],
                               color=col,s=200,marker=mk,zorder=9,
                               edgecolors="white",linewidths=0.5)

        # Joriy narx
        cur=price.get("price",C[-1]); chg=price.get("chg",0)
        a1.axhline(y=cur,color="#f5a623",lw=0.8,ls="-",zorder=5,alpha=0.9)
        a1.annotate("$"+str(round(cur,2)),xy=(n-1,cur),xytext=(n+0.5,cur),
                    fontsize=9,color="#000",fontweight="bold",va="center",
                    annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.25",fc="#f5a623",ec="#f5a623",alpha=0.95))

        sign="+" if chg>=0 else ""
        a1.set_title(ticker+"  $"+str(round(cur,2))+"  "+sign+str(chg)+"% | ATR $"+str(at),
                     color=BL if chg>=0 else BR,fontsize=11,fontweight="bold",
                     pad=8,loc="left",fontfamily="monospace")
        a1.legend(loc="upper left",fontsize=7.5,facecolor="#1e222d",labelcolor=TX,
                  framealpha=0.95,edgecolor=GR,ncol=4,handlelength=1.2)
        a1.set_xlim(-1,n+12)

        # Hajm
        av=np.mean(V) if V.any() else 1
        for i,(o,c,v) in enumerate(zip(O,C,V)):
            col=BL if c>=o else BR
            a2.bar(i,v,color=col,width=0.6,alpha=min(0.9,0.3+0.7*v/(av*2)))
        a2.axhline(y=av,color=MU,lw=0.6,ls="--",alpha=0.7)
        a2.set_ylabel("Vol",color=MU,fontsize=7)
        a2.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x,_: str(round(x/1e9,1))+"B" if x>=1e9
            else str(round(x/1e6))+"M" if x>=1e6 else str(round(x/1e3))+"K"))

        # RSI
        if len(C)>=28:
            d=np.diff(C); g=np.where(d>0,d,0); ls=np.where(d<0,-d,0)
            ag=np.convolve(g,np.ones(14)/14,mode="valid")
            al=np.convolve(ls,np.ones(14)/14,mode="valid")
            rs=np.where(al!=0,ag/al,100); rsi=100-100/(1+rs)
            rx=list(range(27,len(C)))
            a3.plot(rx,rsi,color="#ce93d8",lw=1.1)
            a3.axhline(y=70,color=BR,lw=0.6,ls="--",alpha=0.6)
            a3.axhline(y=50,color=MU,lw=0.4,ls="--",alpha=0.4)
            a3.axhline(y=30,color=BL,lw=0.6,ls="--",alpha=0.6)
            a3.fill_between(rx,rsi,70,where=rsi>=70,color=BR,alpha=0.15)
            a3.fill_between(rx,rsi,30,where=rsi<=30,color=BL,alpha=0.15)
            a3.set_ylim(0,100); a3.set_yticks([30,50,70])
            a3.set_ylabel("RSI",color=MU,fontsize=7)
            if len(rsi)>0:
                cr=round(rsi[-1],1); rc=BR if cr>70 else BL if cr<30 else "#ce93d8"
                a3.annotate(str(cr),xy=(rx[-1],rsi[-1]),xytext=(n+0.5,rsi[-1]),
                            fontsize=7,color=rc,fontweight="bold",
                            va="center",annotation_clip=False)

        # MACD
        if len(C)>=34:
            def ema(a,p):
                k=2.0/(p+1); out=np.zeros(len(a)); out[0]=a[0]
                for i in range(1,len(a)): out[i]=a[i]*k+out[i-1]*(1-k)
                return out
            e12=ema(C,12); e26=ema(C,26); ml=e12-e26
            sg=ema(ml,9); hs=ml-sg
            a4.plot(range(n),ml,color="#2196f3",lw=1.0,label="MACD")
            a4.plot(range(n),sg,color="#ff9800",lw=1.0,label="Signal")
            for i in range(n):
                col=BL if hs[i]>=0 else BR
                a4.bar(i,hs[i],color=col,width=0.6,
                       alpha=min(0.9,0.4+abs(hs[i])/(np.std(hs)+1e-9)*0.3))
            a4.axhline(y=0,color=MU,lw=0.4,alpha=0.6)
            a4.set_ylabel("MACD",color=MU,fontsize=7)
            a4.legend(loc="upper left",fontsize=6.5,facecolor="#1e222d",
                      labelcolor=TX,framealpha=0.9,edgecolor=GR,ncol=2)

        plt.setp(a1.get_xticklabels(),visible=False)
        plt.setp(a2.get_xticklabels(),visible=False)
        plt.setp(a3.get_xticklabels(),visible=False)
        fig.text(0.01,0.005,"Stock Signal Bot v9.0 | "+ticker+" | "+
                 datetime.now().strftime("%d.%m.%Y %H:%M"),
                 color="#2a2e39",fontsize=7,fontfamily="monospace")

        buf=io.BytesIO()
        plt.savefig(buf,format="png",dpi=100,bbox_inches="tight",
                    facecolor=BG,edgecolor="none")
        buf.seek(0)
        plt.close(fig); plt.close("all"); gc.collect()
        return buf
    except Exception as e:
        logging.error("Chart xato: "+str(e))
        try: plt.close("all")
        except: pass
        gc.collect()
        return None


# ═══════════════════════════════════════════
# HALOLLIK — MUSAFFA.COM
# ═══════════════════════════════════════════

def musaffa(ticker):
    url = "https://musaffa.com/stock/" + ticker
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        text = BeautifulSoup(r.text, "lxml").get_text().lower()
        if any(w in text for w in ["halal","compliant","permissible"]):
            return {"holat": "HALOL", "url": url}
        if any(w in text for w in ["haram","not compliant","prohibited"]):
            return {"holat": "HAROM", "url": url}
        if any(w in text for w in ["doubtful","questionable"]):
            return {"holat": "SHUBHALI", "url": url}
    except Exception as e:
        logging.warning("Musaffa: " + str(e))
    return {"holat": "NOMA'LUM", "url": url}


def h_emoji(s):
    return {"HALOL":"✅ HALOL","HAROM":"❌ HAROM",
            "SHUBHALI":"⚠️ SHUBHALI","NOMA'LUM":"❓ NOMA'LUM"}.get(s,"❓")


# ═══════════════════════════════════════════
# YAHOO — FUNDAMENTAL + YANGILIKLAR
# ═══════════════════════════════════════════

def yahoo_fund(ticker):
    res = {"pe":"N/A","eps":"N/A","div":"N/A","w52h":"N/A","w52l":"N/A","avg_vol":"N/A","beta":"N/A"}
    try:
        r    = requests.get("https://finance.yahoo.com/quote/"+ticker+"/",
                            headers=HEADERS,timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        for f,k in [("PE_RATIO","pe"),("EPS_RATIO","eps"),
                    ("FIFTY_TWO_WK_HIGH","w52h"),("FIFTY_TWO_WK_LOW","w52l"),
                    ("AVERAGE_VOLUME_3MONTH","avg_vol"),("BETA_3Y","beta"),
                    ("DIVIDEND_AND_YIELD","div")]:
            el=soup.find("fin-streamer",{"data-field":f})
            if el: res[k]=el.get_text(strip=True)
    except Exception: pass
    return res


def yangiliklar(ticker=None, count=6):
    url = ("https://finance.yahoo.com/quote/"+ticker+"/news/"
           if ticker else "https://finance.yahoo.com/news/")
    news = []
    try:
        r    = requests.get(url,headers=HEADERS,timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        for art in soup.find_all("h3",limit=count*2):
            a = art.find("a")
            if a and len(a.get_text(strip=True))>15:
                t=a.get_text(strip=True); h=a.get("href","")
                if h and not h.startswith("http"):
                    h="https://finance.yahoo.com"+h
                news.append({"sarlavha":t,"url":h})
            if len(news)>=count: break
    except Exception: pass
    return news


def news_html(lst, n=5):
    lines=[]
    for item in lst[:n]:
        t=item.get("sarlavha","")[:70]; u=item.get("url","")
        lines.append("• <a href='"+u+"'>"+t+"</a>")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# FINVIZ
# ═══════════════════════════════════════════

def finviz(ticker):
    res={"industry":"N/A","country":"N/A","target":"N/A","recom":"N/A","news":[]}
    try:
        r    = requests.get("https://finviz.com/quote.ashx?t="+ticker,
                            headers=HEADERS,timeout=15)
        soup = BeautifulSoup(r.text,"lxml")
        cells=soup.select("td.snapshot-td2"); labels=soup.select("td.snapshot-td2-cp")
        d={l.get_text(strip=True):c.get_text(strip=True) for l,c in zip(labels,cells)}
        res.update({"industry":d.get("Industry","N/A"),"country":d.get("Country","N/A"),
                    "target":d.get("Target Price","N/A"),"recom":d.get("Recom","N/A")})
        for row in soup.select("table.fullview-news-outer tr")[:4]:
            a=row.find("a",class_="tab-link-news")
            if a: res["news"].append({"sarlavha":a.get_text(strip=True),"url":a.get("href","")})
    except Exception: pass
    return res


# ═══════════════════════════════════════════
# TRADINGVIEW SIGNAL
# ═══════════════════════════════════════════

def tv_signal(ticker):
    res={"rating":"N/A","ma":"N/A","macd":"N/A","adx":"N/A","rsi":"N/A"}
    try:
        r=requests.post("https://scanner.tradingview.com/america/scan",
            json={"symbols":{"tickers":["NASDAQ:"+ticker,"NYSE:"+ticker,"AMEX:"+ticker]},
                  "columns":["Recommend.All","Recommend.MA","MACD.macd","MACD.signal","ADX","RSI"]},
            headers=HEADERS,timeout=12)
        data=r.json().get("data",[])
        if data:
            row=data[0].get("d",[])
            def lbl(v):
                if v is None: return "N/A"
                if v>=0.5:   return "💪 KUCHLI SOTIB OL"
                if v>=0.1:   return "🟢 SOTIB OL"
                if v>-0.1:   return "⚪ NEYTRAL"
                if v>-0.5:   return "🔴 SOT"
                return "💥 KUCHLI SOT"
            if len(row)>=4:
                res["rating"]=lbl(row[0]); res["ma"]=lbl(row[1])
                if row[2] is not None and row[3] is not None:
                    res["macd"]="🟢 Yuqoriga" if row[2]>row[3] else "🔴 Pastga"
                if len(row)>4 and row[4]: res["adx"]=round(row[4],1)
                if len(row)>5 and row[5]: res["rsi"]=round(row[5],1)
    except Exception: pass
    return res


# ═══════════════════════════════════════════
# IPO
# ═══════════════════════════════════════════

def ipos():
    lst = []
    try:
        r    = requests.get("https://api.nasdaq.com/api/ipo/calendar",
                            headers=HEADERS,timeout=15)
        data = r.json().get("data",{})
        for ipo in data.get("upcoming",{}).get("upcomingTable",{}).get("rows",[])[:8]:
            nomi = ipo.get("companyName","N/A")
            # Kompaniya tavsifi qo'shish
            lst.append({
                "nomi":   nomi,
                "ticker": ipo.get("proposedTickerSymbol","N/A"),
                "birja":  ipo.get("proposedExchange","N/A"),
                "narx":   ipo.get("priceRangeLow","")+"-"+ipo.get("priceRangeHigh",""),
                "sana":   ipo.get("expectedPriceDate","N/A"),
                "holat":  "Kutilmoqda",
            })
        for ipo in data.get("recent",{}).get("recentTable",{}).get("rows",[])[:4]:
            lst.append({
                "nomi":      ipo.get("companyName","N/A"),
                "ticker":    ipo.get("proposedTickerSymbol","N/A"),
                "ipo_narx":  ipo.get("ipoPrice","N/A"),
                "hozir":     ipo.get("currentPrice","N/A"),
                "daromad":   ipo.get("pctChange","N/A"),
                "sana":      ipo.get("pricedDate","N/A"),
                "holat":     "Yangi",
            })
    except Exception as e:
        logging.warning("IPO: "+str(e))
    return lst


def ipo_matn(lst):
    if not lst: return "IPO ma'lumotlari topilmadi."
    now=datetime.now().strftime("%d.%m.%Y %H:%M")
    lines=["━━━━━━━━━━━━━━━━━━━━",
           "🚀 <b>IPO YANGILIKLARI</b>","🕐 "+now,"━━━━━━━━━━━━━━━━━━━━\n"]
    for ipo in lst:
        if ipo["holat"]=="Kutilmoqda":
            lines.append(
                "🗓 <b>"+ipo["nomi"]+"</b> ("+ipo["ticker"]+")\n"
                "  🏦 "+ipo["birja"]+" | 💰 $"+ipo["narx"]+"\n"
                "  📅 Sana: "+ipo["sana"]+"\n"
            )
        else:
            try: pct=float(str(ipo.get("daromad","0")).replace("%","").replace("+","") or 0)
            except: pct=0
            em="🟢" if pct>=0 else "🔴"
            lines.append(
                em+" <b>"+ipo["nomi"]+"</b> ("+ipo["ticker"]+")\n"
                "  💰 IPO: $"+str(ipo.get("ipo_narx","N/A"))+
                " → Hozir: $"+str(ipo.get("hozir","N/A"))+"\n"
                "  📊 "+str(ipo.get("daromad","N/A"))+"% | 📅 "+ipo["sana"]+"\n"
            )
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# ERTALABKI YANGILIKLAR
# ═══════════════════════════════════════════

def ertalabki_yangilik():
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Bozor holatini olish
    bozor = ""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&range=2d",
            headers=HEADERS, timeout=10)
        meta = r.json()["chart"]["result"][0]["meta"]
        sp   = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", 0)
        chg  = round((sp-prev)/prev*100, 2) if prev > 0 else 0
        em   = "🟢" if chg >= 0 else "🔴"
        bozor += em + " S&P 500: $" + str(round(sp,2)) + " (" + ("+" if chg>=0 else "") + str(chg) + "%)\n"
    except: pass

    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?interval=1d&range=2d",
            headers=HEADERS, timeout=10)
        meta = r.json()["chart"]["result"][0]["meta"]
        nq   = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", 0)
        chg  = round((nq-prev)/prev*100, 2) if prev > 0 else 0
        em   = "🟢" if chg >= 0 else "🔴"
        bozor += em + " NASDAQ: $" + str(round(nq,2)) + " (" + ("+" if chg>=0 else "") + str(chg) + "%)\n"
    except: pass

    # Yangiliklar
    news = yangiliklar(count=6)

    matn = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌅 <b>ERTALABKI YANGILIKLAR</b>\n"
        "🕐 " + now + "\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📈 <b>Bozor holati</b>\n"
        + (bozor or "Ma'lumot yuklanmadi\n") + "\n"
        "📰 <b>Asosiy yangiliklar</b>\n"
        + news_html(news, 6) + "\n\n"
        "<i>Yaxshi savdolar! 📊</i>"
    )
    tg(matn, markup=menu_asosiy())


# ═══════════════════════════════════════════
# AKSIYA TO'LIQ TAHLILI
# ═══════════════════════════════════════════

def tahlil(ticker, cid):
    ticker = ticker.upper().strip()
    tg("🔍 <b>"+ticker+"</b> tahlil boshlanmoqda...\n"
       "⏳ Polygon • TV • Yahoo • Musaffa • AI", cid)

    # Ma'lumotlarni yig'ish
    p = narx(ticker)
    if not p or p.get("price",0) == 0:
        tg("❌ <b>"+ticker+"</b> topilmadi. Ticker to'g'riligini tekshiring.", cid)
        return
    time.sleep(13)

    k  = kompaniya(ticker);      time.sleep(13)
    tx = texnik(ticker);         time.sleep(2)
    cn = shamlar(ticker, 60)
    sv, rs = sr(cn)
    tr = trend(cn) if cn else None
    at = atr(cn)
    bo = breakout(cn, sv, rs, p)
    time.sleep(13)
    tv = tv_signal(ticker);      time.sleep(2)
    yf = yahoo_fund(ticker);     time.sleep(2)
    fv = finviz(ticker);         time.sleep(2)
    ms = musaffa(ticker);        time.sleep(2)

    # AI strategiya
    tg("🤖 AI strategiya hisoblanmoqda...", cid)
    ai_m, ai_l = ai_strategiya(ticker, p, k, tx, sv, rs, tr, bo, at)
    gc.collect()

    # ── 1. RASM ──
    ch = chart(ticker, cn, sv, rs, p, tr, bo, at, ai_l)
    cur = p.get("price",0); chg = p.get("chg",0)
    sign = "+" if chg>=0 else ""
    sup_s = " | ".join(["$"+str(s) for s in sv[:2]]) or "N/A"
    res_s = " | ".join(["$"+str(r) for r in rs[:2]]) or "N/A"
    cap = (
        "<b>"+ticker+"</b> — "+k["nomi"]+"\n"
        "💵 $"+str(round(cur,2))+"  ("+sign+str(chg)+"%)\n"
        "📈 "+(tr["dir"] if tr else "N/A")+"  ATR: $"+str(at)+"\n"
        "🟢 S: "+sup_s+"   🔴 R: "+res_s+"\n"
        "☪️ "+h_emoji(ms["holat"])
    )
    if ch:
        ok = tg_photo(ch, cap, cid, menu_aksiya(ticker))
        if not ok:
            tg("📺 <a href='https://www.tradingview.com/chart/?symbol="+ticker+
               "'>TradingView — "+ticker+"</a>\n"+cap, cid, menu_aksiya(ticker))
    else:
        tg("📺 <a href='https://www.tradingview.com/chart/?symbol="+ticker+
           "'>TradingView — "+ticker+"</a>\n"+cap, cid, menu_aksiya(ticker))

    # ── 2. NARX VA SIGNAL ──
    rsi=tx.get("rsi"); s50=tx.get("sma50"); s200=tx.get("sma200")
    vu = p.get("volume",0)*cur; cb = k["kapital"]/1e9
    bo_t = ""
    if bo:
        kuchli = [b for b in bo if b["score"]>=3]
        if kuchli:
            bo_t = "\n⚡ <b>Breakout:</b>\n"
            for b in kuchli:
                bo_t += "  "+b["type"]+" — $"+str(b["level"])+"\n"
                bo_t += "  → "+b["signal"]+"\n"

    tg(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>"+ticker+"</b> — "+k["nomi"]+"\n"
        "🏭 "+k["sektor"]+" | "+fv["industry"]+"\n"
        "🌍 "+fv["country"]+"  👥 "+str(k["xodim"])+" xodim\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 <b>Kompaniya haqida (O'zbekcha)</b>\n"
        "<i>"+k["tavsif"][:250]+"</i>\n\n"
        "💰 <b>Narx</b>\n"
        "  💵 Joriy:    <b>$"+str(round(cur,2))+"</b>  ("+sign+str(chg)+"%)\n"
        "  Ochilish: $"+str(round(p.get("open",0),2))+"\n"
        "  Yuqori:   $"+str(round(p.get("high",0),2))+"\n"
        "  Past:     $"+str(round(p.get("low",0),2))+"\n"
        "  VWAP:     $"+str(round(p.get("vwap",0),2))+"\n"
        "  52H max:  $"+str(yf.get("w52h","N/A"))+"  min: $"+str(yf.get("w52l","N/A"))+"\n\n"
        "📦 <b>Hajm</b>\n"
        "  Bugungi: <b>$"+str(round(vu/1e6,1))+" mln</b>"
        "  |  O'rtacha: "+str(yf.get("avg_vol","N/A"))+"\n\n"
        "🏦 <b>Bozor kapitali va fundamental</b>\n"
        "  Kapital: <b>$"+str(round(cb,1))+" mlrd</b>\n"
        "  P/E: "+str(yf.get("pe","N/A"))+"  |  EPS: "+str(yf.get("eps","N/A"))+"\n"
        "  Beta: "+str(yf.get("beta","N/A"))+"  |  Div: "+str(yf.get("div","N/A"))+"\n\n"
        "📐 <b>Texnik tahlil</b>\n"
        "  RSI: "+str(rsi or "N/A")+
        ("  ⚠️ Overbought" if rsi and rsi>70 else "  ✅ Oversold" if rsi and rsi<30 else "  ✅ Normal")+"\n"
        "  SMA50:  $"+str(s50 or "N/A")+("  ✅" if s50 and cur>s50 else "  ⚠️")+"\n"
        "  SMA200: $"+str(s200 or "N/A")+("  ✅ Bull" if s200 and cur>s200 else "  ⚠️ Bear")+"\n"
        "  ATR: $"+str(at)+"  |  Trend: "+(tr["dir"] if tr else "N/A")+"\n\n"
        "📏 <b>Support & Resistance</b>\n"
        "  🟢 Support:    "+sup_s+"\n"
        "  🔴 Resistance: "+res_s+"\n"
        +bo_t+"\n"
        "📺 <b>TradingView signali</b>\n"
        "  "+tv.get("rating","N/A")+"  |  MACD: "+tv.get("macd","N/A")+"\n\n"
        "🎯 <b>Yakuniy signal</b>\n"
        "  "+("🟢 SOTIB OL" if chg>=0 else "🔴 SOT")+"\n"
        "  Maqsad narx: $"+str(fv.get("target","N/A"))+"  |  Analitik: "+str(fv.get("recom","N/A")),
        cid
    )

    # ── 3. AI STRATEGIYA ──
    if ai_m:
        tg(ai_m, cid)

    # ── 4. HALOLLIK ──
    tg(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "☪️ <b>HALOLLIK HOLATI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "  Yakuniy: <b>"+h_emoji(ms["holat"])+"</b>\n\n"
        "  Musaffa.com asosida tekshirildi\n"
        "  🔗 <a href='"+ms["url"]+"'>Batafsil ko'rish</a>\n\n"
        "<i>⚠️ Moliyaviy maslahat emas.</i>",
        cid
    )

    # ── 5. YANGILIKLAR ──
    all_n = fv["news"] + yangiliklar(ticker, count=3)
    if all_n:
        tg(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📰 <b>"+ticker+" YANGILIKLARI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            +news_html(all_n, 5), cid
        )
    gc.collect()


# ═══════════════════════════════════════════
# AVTOMATIK SKREENER
# ═══════════════════════════════════════════

def skreener(halol=False, bo_only=False):
    tag = "HALOL " if halol else "BREAKOUT " if bo_only else ""
    logging.info("Skreener: "+tag)
    signals = []

    for ticker in WATCHLIST:
        p = narx(ticker)
        if not p or p.get("price",0)==0:
            time.sleep(13); continue
        chg = p.get("chg",0); c = p.get("price",0)
        vu  = p.get("volume",0)*c
        if vu < 1_000_000: time.sleep(13); continue
        if not bo_only and not (2.0<=abs(chg)<=15.0): time.sleep(13); continue
        k = kompaniya(ticker); time.sleep(13)
        if k["kapital"] < 2_000_000_000: continue
        tv = tv_signal(ticker); time.sleep(2)
        cn = shamlar(ticker, 45)
        sv, rs = sr(cn); tr = trend(cn) if cn else None
        bo = breakout(cn, sv, rs, p); time.sleep(13)
        if halol:
            ms = musaffa(ticker); time.sleep(2)
            if ms["holat"]=="HAROM": continue
        if bo_only and not bo: continue
        sab = []
        if abs(chg)>5:           sab.append("Kuchli harakat")
        if vu>10_000_000:        sab.append("Yuqori hajm")
        if "SOTIB OL" in tv.get("rating",""): sab.append("TV: BUY")
        if bo:                   sab.append(bo[0]["type"])
        if tr and "Yuqoriga" in tr["dir"]: sab.append("Uptrend")
        signals.append({
            "ticker":ticker,"nomi":k["nomi"],
            "signal":"BUY" if chg>0 else "SELL",
            "narx":c,"chg":chg,"vu":vu,"cap":k["kapital"],
            "tv":tv.get("rating","N/A"),
            "trend":tr["dir"] if tr else "N/A",
            "bo":bo[0]["type"] if bo else "—",
            "sab":" | ".join(sab) or "Mezon bajarildi",
        })
        logging.info("  "+ticker+" "+str(round(chg,1))+"%")
        time.sleep(13)

    if not signals:
        tg("📊 "+tag+"Hozir shart bajargan aksiya topilmadi.")
        return
    signals.sort(key=lambda x:abs(x["chg"]),reverse=True)
    now=datetime.now().strftime("%d.%m.%Y %H:%M")

    # AI xulosasi
    ai_x=""
    if AI and OAI_KEY and signals:
        try:
            inf="\n".join([s["ticker"]+": $"+str(round(s["narx"],2))+
                           " ("+str(round(s["chg"],1))+"%), "+s["trend"]
                           for s in signals[:3]])
            ai_x="\n\n🤖 <b>AI xulosasi:</b>\n"+ai_so(
                "Quyidagi 3 aksiyani O'ZBEK TILIDA 2 jumlada tushuntiring:\n"+inf,200)
        except: pass

    lines=["━━━━━━━━━━━━━━━━━━━━",
           "🤖 <b>AVTOMATIK "+tag+"SIGNAL</b>","🕐 "+now,
           "Topilgan: <b>"+str(len(signals))+" ta aksiya</b>","━━━━━━━━━━━━━━━━━━━━\n"]
    for s in signals[:10]:
        em="🟢" if s["signal"]=="BUY" else "🔴"
        am="SOTIB OL" if s["signal"]=="BUY" else "SOT"
        cb=s["cap"]/1e9; sg="+" if s["chg"]>=0 else ""
        lines.append(
            em+" <b>"+s["ticker"]+"</b> — "+s["nomi"]+"\n"
            "  💵 $"+str(round(s["narx"],2))+"  ("+sg+str(round(s["chg"],1))+"%)\n"
            "  📦 $"+str(round(s["vu"]/1e6,1))+"mln  🏦 $"+str(round(cb,1))+"mlrd\n"
            "  📈 "+s["trend"]+"  ⚡ "+s["bo"]+"\n"
            "  📺 "+s["tv"]+"\n"
            "  🎯 <b>"+am+"</b> — "+s["sab"]+"\n"
        )
    if ai_x: lines.append(ai_x)
    lines.append("\n<i>⚠️ Moliyaviy maslahat emas.</i>")
    tg("\n".join(lines), markup=menu_asosiy())


# ═══════════════════════════════════════════
# POLLING
# ═══════════════════════════════════════════

def polling():
    offset=None
    logging.info("Bot tayyor. Polling...")

    while True:
        try:
            r = requests.get(
                "https://api.telegram.org/bot"+TG_TOKEN+"/getUpdates",
                params={"timeout":25,"offset":offset,
                        "allowed_updates":["message","callback_query"]},
                timeout=30)
            updates=r.json().get("result",[])

            for upd in updates:
                offset=upd["update_id"]+1

                # Callback
                if "callback_query" in upd:
                    cb=upd["callback_query"]; d=cb.get("data","")
                    cid=str(cb["message"]["chat"]["id"])
                    requests.post("https://api.telegram.org/bot"+TG_TOKEN+
                                  "/answerCallbackQuery",
                                  json={"callback_query_id":cb["id"],"text":"⏳"},timeout=5)

                    if d=="signal":
                        tg("🔍 Signal tekshirilmoqda...",cid)
                        threading.Thread(target=skreener,daemon=True).start()
                    elif d=="halol":
                        tg("☪️ Halol aksiyalar...",cid)
                        threading.Thread(target=lambda:skreener(halol=True),daemon=True).start()
                    elif d=="ipo":
                        tg("🚀 IPO yuklanmoqda...",cid)
                        threading.Thread(target=lambda c=cid:tg(ipo_matn(ipos()),c),daemon=True).start()
                    elif d=="yangilik":
                        tg("📰 Yangiliklar yuklanmoqda...",cid)
                        def _yn(c=cid):
                            news=yangiliklar(count=8)
                            tg("━━━━━━━━━━━━━━━━━━━━\n📰 <b>MOLIYAVIY YANGILIKLAR</b>\n"
                               "━━━━━━━━━━━━━━━━━━━━\n\n"+news_html(news,8),c)
                        threading.Thread(target=_yn,daemon=True).start()
                    elif d=="breakout":
                        tg("⚡ Breakout tekshirilmoqda...",cid)
                        threading.Thread(target=lambda:skreener(bo_only=True),daemon=True).start()
                    elif d=="ertalab":
                        threading.Thread(target=ertalabki_yangilik,daemon=True).start()
                    elif d.startswith("y_"):
                        tkr=d[2:]
                        threading.Thread(target=tahlil,args=(tkr,cid),daemon=True).start()
                    elif d.startswith("n_"):
                        tkr=d[2:]
                        def _xb(t=tkr,c=cid):
                            news=yangiliklar(t,count=5)
                            tg("📰 <b>"+t+" YANGILIKLARI</b>\n\n"+news_html(news,5),c)
                        threading.Thread(target=_xb,daemon=True).start()
                    continue

                # Xabar
                msg=upd.get("message",{})
                text=msg.get("text","").strip()
                cid=str(msg.get("chat",{}).get("id",""))
                if not text or not cid: continue
                logging.info("'"+text+"' — "+cid)

                if text in ("/start","/help"):
                    tg(
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "👋 <b>Stock Signal Bot v9.0</b>\n"
                        "🤖 AI • Polygon • Yahoo • Musaffa\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "📌 <b>Qanday ishlatish:</b>\n"
                        "  • Ticker yozing: <code>AAPL</code>, <code>NVDA</code>\n"
                        "  • Savol bering: <i>TSLA haqida nima deysiz?</i>\n\n"
                        "<b>Buyruqlar:</b>\n"
                        "  /signal   — Signal tekshirish\n"
                        "  /halol    — Halol aksiyalar\n"
                        "  /ipo      — IPO yangiliklari\n"
                        "  /yangilik — Yangiliklar\n"
                        "  /ertalab  — Ertalabki yangilik\n"
                        "  /breakout — Breakout signallari\n\n"
                        "✅ Kompaniya tavsifi O'ZBEK TILIDA\n"
                        "✅ Bozor kapitali ko'rsatiladi\n"
                        "✅ Musaffa.com halollik tekshiruvi\n"
                        "✅ Ertalabki yangiliklar (08:00)\n"
                        "✅ AI strategiya rasmda chiziladi\n\n"
                        "⬇️ Quyidagi tugmalar:",
                        cid, menu_asosiy()
                    )
                elif text=="/signal":
                    tg("🔍 Signal tekshirilmoqda...",cid)
                    threading.Thread(target=skreener,daemon=True).start()
                elif text in ("/halol","/halal"):
                    tg("☪️ Halol aksiyalar...",cid)
                    threading.Thread(target=lambda:skreener(halol=True),daemon=True).start()
                elif text=="/ipo":
                    tg("🚀 IPO yuklanmoqda...",cid)
                    threading.Thread(target=lambda c=cid:tg(ipo_matn(ipos()),c),daemon=True).start()
                elif text in ("/yangilik","/news"):
                    def _yn2(c=cid):
                        news=yangiliklar(count=8)
                        tg("━━━━━━━━━━━━━━━━━━━━\n📰 <b>MOLIYAVIY YANGILIKLAR</b>\n"
                           "━━━━━━━━━━━━━━━━━━━━\n\n"+news_html(news,8),c)
                    threading.Thread(target=_yn2,daemon=True).start()
                elif text=="/ertalab":
                    threading.Thread(target=ertalabki_yangilik,daemon=True).start()
                elif text=="/breakout":
                    tg("⚡ Breakout tekshirilmoqda...",cid)
                    threading.Thread(target=lambda:skreener(bo_only=True),daemon=True).start()
                elif text.startswith("/"): tg("❓ Noma'lum buyruq. /help yozing.",cid)
                elif re.match(r"^[A-Za-z]{1,6}$",text):
                    threading.Thread(target=tahlil,args=(text,cid),daemon=True).start()
                else:
                    tg("🤖 AI javob tayyorlanmoqda...",cid)
                    def _ai(t=text,c=cid):
                        tg("🤖 <b>AI javobi:</b>\n\n"+ai_suhbat(c,t),c)
                    threading.Thread(target=_ai,daemon=True).start()

        except Exception as e:
            logging.error("Polling: "+str(e))
            time.sleep(5)


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    logging.info("Stock Signal Bot v9.0 ishga tushdi")

    schedule.every(4).hours.do(skreener)
    schedule.every().day.at("09:35").do(skreener)
    schedule.every().day.at("16:05").do(skreener)
    schedule.every().day.at("08:00").do(ertalabki_yangilik)  # Ertalabki yangilik

    threading.Thread(
        target=lambda:[(schedule.run_pending(),time.sleep(60)) for _ in iter(int,1)],
        daemon=True
    ).start()

    tg(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Stock Signal Bot v9.0 ishga tushdi!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Real vaqt narxlar\n"
        "✅ Kompaniya tavsifi O'zbekcha 🇺🇿\n"
        "✅ Bozor kapitali ko'rsatiladi\n"
        "✅ Musaffa.com halollik ☪️\n"
        "✅ AI strategiya rasmda\n"
        "✅ Ertalabki yangiliklar 🌅\n"
        "✅ S&P500 + NASDAQ holati\n\n"
        "💡 <code>AAPL</code> yozing yoki savol bering!",
        markup=menu_asosiy()
    )

    polling()


if __name__ == "__main__":
    main()
