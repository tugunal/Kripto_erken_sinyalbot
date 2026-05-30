import os
import ccxt
import pandas as pd
import numpy as np
import pandas_ta as ta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- AYARLAR ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
exchange = ccxt.binance({'enableRateLimit': True})

# =========================
# DATA FETCH & INDICATORS
# =========================
def get_data(symbol, tf="15m"):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=200)
        if not ohlcv:
            return None
            
        df = pd.DataFrame(ohlcv, columns=["t","o","h","l","c","v"])

        df["ema20"] = ta.ema(df["c"], length=20)
        df["ema50"] = ta.ema(df["c"], length=50)
        df["rsi"] = ta.rsi(df["c"], length=14)
        df["atr"] = ta.atr(df["h"], df["l"], df["c"], length=14)

        # Doğru ve optimize edilmiş VWAP hesabı
        typical_price = (df["h"] + df["l"] + df["c"]) / 3
        df["vwap"] = (df["v"] * typical_price).cumsum() / df["v"].cumsum()

        macd = ta.macd(df["c"])
        if macd is not None:
            df = pd.concat([df, macd], axis=1)

        return df
    except Exception as e:
        print(f"Veri çekme hatası: {e}")
        return None

# =========================
# VOLUME PROFILE (FAST)
# =========================
def volume_profile(df, bins=30):
    low = df["l"].min()
    high = df["h"].max()
    
    if low == high:
        return low

    levels = np.linspace(low, high, bins)
    vol = np.zeros(bins)

    # For döngüsü yerine hızlı numpy argmin kullanımı
    prices = df["c"].values
    volumes = df["v"].values
    
    for p, v in zip(prices, volumes):
        idx = np.abs(levels - p).argmin()
        vol[idx] += v

    poc = levels[np.argmax(vol)]
    return poc

# =========================
# FAKE BREAKOUT
# =========================
def fake_breakout(df):
    prev_high = df["h"].iloc[-2]
    prev_low = df["l"].iloc[-2]

    h = df["h"].iloc[-1]
    l = df["l"].iloc[-1]
    c = df["c"].iloc[-1]

    vwap = df["vwap"].iloc[-1]
    atr = df["atr"].iloc[-1]

    if h > prev_high and c < prev_high and c < vwap and (h - c) > atr:
        return "FAKE UP → SELL"
    if l < prev_low and c > prev_low and c > vwap and (c - l) > atr:
        return "FAKE DOWN → BUY"

    return "NO FAKE"

# =========================
# STRUCTURE (BOS / CHOCH)
# =========================
def structure(df):
    highs = df["h"].values
    lows = df["l"].values
    
    bos = 0
    choch = 0
    trend = 0

    # Son 50 mumu analiz etmek hız ve kararlılık için daha idealdir
    start_idx = max(5, len(df) - 50)
    for i in range(start_idx, len(df)):
        if highs[i] > max(highs[i-5:i]):
            bos += 1
            trend = 1
        if lows[i] < min(lows[i-5:i]):
            bos -= 1
            trend = -1

        if trend == 1 and lows[i] < lows[i-1]:
            choch += 1
        if trend == -1 and highs[i] > highs[i-1]:
            choch -= 1

    return bos, choch

# =========================
# ORDER BLOCK (BASIC)
# =========================
def order_block(df):
    # Son mumu bozmamak adına geriye dönük tarama
    for i in range(len(df)-6, len(df)-2):
        body = abs(df["c"].iloc[i] - df["o"].iloc[i])
        rng = df["h"].iloc[i] - df["l"].iloc[i]

        if rng > 0 and (body / rng) > 0.7:
            return {
                "low": df["l"].iloc[i],
                "high": df["h"].iloc[i]
            }
    return None

# =========================
# INDUCEMENT
# =========================
def inducement(df):
    h_prev = df["h"].iloc[-3:-1].max()
    l_prev = df["l"].iloc[-3:-1].min()

    h = df["h"].iloc[-1]
    l = df["l"].iloc[-1]
    c = df["c"].iloc[-1]

    if h > h_prev and c < h_prev:
        return "SELL SIDE LIQUIDITY GRAB"
    if l < l_prev and c > l_prev:
        return "BUY SIDE LIQUIDITY GRAB"

    return "NO INDUCEMENT"

# =========================
# SMC SCORE ENGINE
# =========================
def smc_engine(df):
    price = df["c"].iloc[-1]

    bos, choch = structure(df)
    ob = order_block(df)
    induc = inducement(df)
    poc = volume_profile(df)

    score = 50
    score += bos * 10
    score -= choch * 10

    if "BUY" in induc:
        score += 20
    if "SELL" in induc:
        score -= 20

    if ob and ob["low"] <= price <= ob["high"]:
        score += 15

    if abs(price - poc) / price < 0.005:
        score += 10

    fake = fake_breakout(df)
    if "SELL" in fake:
        score -= 25
    if "BUY" in fake:
        score += 25

    score = max(0, min(100, score))

    return {
        "price": price,
        "score": score,
        "bos": bos,
        "choch": choch,
        "ob": ob,
        "inducement": induc,
        "poc": poc,
        "fake": fake
    }

# =========================
# ENTRY ENGINE
# =========================
def execution(df, balance=1000, risk=1):
    res = smc_engine(df)
    price = res["price"]
    ob = res["ob"]

    entry = price
    sl = price * 0.98
    tp = price * 1.03

    if ob:
        entry = (ob["low"] + ob["high"]) / 2
        sl = ob["low"]
        tp = entry + (entry - sl) * 2

    # ZeroDivisionError Koruması
    risk_distance = abs(entry - sl)
    if risk_distance == 0:
        risk_distance = price * 0.01

    size = (balance * (risk/100)) / risk_distance

    if res["score"] < 70:
        return {"status": "NO TRADE", "data": res}

    return {
        "status": "EXECUTE",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": size,
        "data": res
    }

# =========================
# TELEGRAM COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏦 **SMC Algoritmik Tarama Botu Aktif!**\n\n"
        "Kullanım: `/tara PARİTE ZAMANDİLIMI`\n"
        "Örnek: `/tara BTC/USDT 15m`",
        parse_mode="Markdown"
    )

async def tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Eksik komut! Örnek: `/tara ETH/USDT 1h` ")
        return

    symbol = context.args[0].upper()
    tf = context.args[1]

    await update.message.reply_text(f"🔍 {symbol} ({tf}) için kurumsal emir akışı analiz ediliyor...")

    df = get_data(symbol, tf)
    if df is None:
        await update.message.reply_text("❌ Veri hatası! Pariteyi veya zaman dilimini kontrol edin.")
        return

    res = execution(df)
    d = res["data"]

    msg = (
        f"🏦 **SMC MARKET STRUCTURE REPORT**\n"
        f"───────────────────\n"
        f"💰 **Fiyat:** `{d['price']:.4f}`\n"
        f"🧠 **SMC Puanı:** `{d['score']}/100`\n\n"
        f"📈 **BOS:** `{d['bos']}` | 🔁 **CHOCH:** `{d['choch']}`\n"
        f"🧲 **Liquidity Grab:** `{d['inducement']}`\n"
        f"📊 **Volume POC:** `{d['poc']:.4f}`\n"
        f"⚡ **Breakout Durumu:** `{d['fake']}`\n"
        f"───────────────────\n"
        f"🚀 **SİNYAL DURUMU:** **{res['status']}**"
    )

    if res["status"] == "EXECUTE":
        msg += (
            f"\n\n🟢 **STRATEJİ PLANLANDI:**\n"
            f"• **Giriş (Entry):** `{res['entry']:.4f}`\n"
            f"• **Zarar Kes (SL):** `{res['sl']:.4f}`\n"
            f"• **Kar Al (TP):** `{res['tp']:.4f}`\n"
            f"• **Pozisyon Büyüklüğü:** `{res['size']:.4f}`"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN çevre değişkeni bulunamadı!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tara", tara))

    print("SMC BOT RUNNING ON CLOUD...")
    app.run_polling()

if __name__ == "__main__":
    main()
