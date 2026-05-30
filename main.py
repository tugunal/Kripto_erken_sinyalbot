import os
import ccxt
import pandas as pd
import pandas_ta as ta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- AYARLAR ---
# Token'ı güvenli bir şekilde işletim sisteminden (bulut panelinden) çekiyoruz
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# ---------------

# Rate limit koruması eklendi
exchange = ccxt.binance({'enableRateLimit': True})

def fetch_and_calculate(symbol: str, timeframe: str):
    """Borsadan verileri çeker ve istenen indikatörleri hesaplar."""
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # İndikatörler
        df['ema7'] = ta.ema(df['close'], length=7)
        df['ema20'] = ta.ema(df['close'], length=20)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        bbands = ta.bbands(df['close'], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        
        return df.iloc[-1]
    except Exception as e:
        print(f"Veri çekme hatası ({symbol} - {timeframe}): {e}")
        return None

def detect_candlestick_patterns(symbol: str, timeframe: str):
    """Basit mum formasyonlarını kontrol eder."""
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=5)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        last_open = df['open'].iloc[-1]
        last_close = df['close'].iloc[-1]
        last_high = df['high'].iloc[-1]
        last_low = df['low'].iloc[-1]
        
        body_size = abs(last_close - last_open)
        total_size = last_high - last_low
        
        pattern = "Belirgin Bir Formasyon Yok"
        if total_size > 0 and (body_size / total_size) < 0.1:
            pattern = "⌛ Doji Oluşumu! (Kararsız Piyasa)"
        elif (last_close > last_open) and ((last_open - last_low) > (body_size * 2)):
            pattern = "🔨 Çekiç (Hammer) - Dönüş Sinyali olabilir!"
            
        return pattern
    except:
        return "Hesaplanamadı."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 **Kripto Sinyal ve Analiz Botu Aktif!**\n\n"
        "Kullanım: `/tara PARİTE ZAMANDİLİMİ`\n"
        "Örnek: `/tara BTC/USDT 1h`",
        parse_mode="Markdown"
    )

async def tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Eksik komut! Örnek: `/tara BTC/USDT 4h` ")
        return
        
    symbol = context.args[0].upper()
    timeframe = context.args[1]
    
    await update.message.reply_text(f"🔍 {symbol} için {timeframe} teknik analizi yapılıyor...")
    
    data = fetch_and_calculate(symbol, timeframe)
    pattern = detect_candlestick_patterns(symbol, timeframe)
    
    if data is not None:
        fiyat = data['close']
        rsi_val = data.get('rsi', 0.0)
        macd_val = data.get('MACD_12_26_9', 0.0)
        macds_val = data.get('MACDs_12_26_9', 0.0)
        
        bb_ust = data.get('BBU_20_2.0', 0.0)
        bb_orta = data.get('BBM_20_2.0', 0.0)
        bb_alt = data.get('BBL_20_2.0', 0.0)
        
        durum = "Yatay / Nötr ⚪"
        if rsi_val < 30: durum = "Aşırı Satım (AL) 🟢"
        elif rsi_val > 70: durum = "Aşırı Alım (SAT) 🔴"

        rapor = (
            f"📊 **{symbol} — {timeframe.upper()} ANALİZİ**\n"
            f"───────────────────\n"
            f"💰 **Fiyat:** `{fiyat:,.4f}`\n"
            f"📈 **Durum:** {durum}\n"
            f"🕯️ **Formasyon:** {pattern}\n\n"
            f"🧠 **Göstergeler:**\n"
            f"• **RSI (14):** `{rsi_val:.2f}`\n"
            f"• **EMA 7/20/50:** `{data['ema7']:.2f}`/`{data['ema20']:.2f}`/`{data['ema50']:.2f}`\n"
            f"• **MACD:** `{macd_val:.4f}` | **VWAP:** `{data['vwap']:.2f}`\n\n"
            f"🌐 **Bollinger:**\n"
            f"• Üst: `{bb_ust:.2f}` | Alt: `{bb_alt:.2f}`\n"
            f"───────────────────\n"
            f"⚠️ _Yatırım tavsiyesi değildir._"
        )
        await update.message.reply_text(rapor, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Veri alınamadı!")

def main():
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN çevre değişkeni bulunamadı!")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tara", tara))
    print("Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
