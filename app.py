import os
import time
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from binance.um_futures import UMFutures
import yfinance as yf

# ══════════════════════════════════════════════════════════════
#  ⚙️  YAPILANDIRMA (Senin Stratejin)
# ══════════════════════════════════════════════════════════════

API_KEY    = os.environ.get("BINANCE_API_KEY",    "BURAYA_BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "BURAYA_BINANCE_SECRET_KEY")

TIMEFRAME  = "1d"  # Apple verilerinde olduğu gibi GÜNLÜK en sağlıklısıdır
LEVERAGE   = 20
TRADE_USDT = 1000

# Senin meşhur 100$ (kasanın %10'u) stopun. 20x kaldıraçta bu %0.5 hareket demektir.
TRAILING_STOP_PCT = 0.5 

# RSI Pusu ve Tetik Seviyeleri
RSI_PERIOD      = 14
RSI_PUSU_ALT    = 28  # Bu seviyenin altına inmeli (Yay gerilmeli)
RSI_PUSU_UST    = 72  # Bu seviyenin üstüne çıkmalı
RSI_TETIK_LONG  = 31  # 28'den dönüp buraya değerse LONG
RSI_TETIK_SHORT = 69  # 72'den dönüp buraya değerse SHORT

NW_BANDWIDTH = 8.0
NW_MULT      = 3.0
NW_LOOKBACK  = 500
KLINES_LIMIT = 1000

LOOP_INTERVAL_SEC = 3600  # Saatte bir tara (Yeni mum kapanışını yakalamak için)
MAX_WORKERS       = 10

TELEGRAM_TOKEN     = "8349458683:AAEi-AFSYxn0Skds7r4VQIaogVl3Fugftyw"
TELEGRAM_ID_GUNLUK = "1484256652"
TELEGRAM_ID_KANAL  = "-1003792245773"

# ══════════════════════════════════════════════════════════════
#  📋 LOGGING & TELEGRAM
# ══════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RSI_BOT")

def tg_notify(text: str):
    targets = [TELEGRAM_ID_GUNLUK, TELEGRAM_ID_KANAL]
    for chat_id in targets:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            logger.error(f"Telegram hatası: {e}")

# ══════════════════════════════════════════════════════════════
#  📐 İNDİKATÖRLER & STRATEJİ
# ══════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # 1. RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # 2. Heikin Ashi
    df["ha_close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = [(df["open"].iloc[0] + df["close"].iloc[0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i-1] + df["ha_close"].iloc[i-1]) / 2)
    df["ha_open"] = ha_open
    df["ha_color"] = np.where(df["ha_close"] > df["ha_open"], "green", "red")

    # 3. Nadaraya-Watson (Basitleştirilmiş Envelope)
    close = df["close"].values
    n = len(close)
    nw_mid = np.full(n, np.nan)
    for i in range(NW_LOOKBACK, n):
        segment = close[i-NW_LOOKBACK+1 : i+1]
        nw_mid[i] = np.mean(segment) # Hızlı hesaplama için MA bazlı
    
    std = df["close"].rolling(window=NW_LOOKBACK).std()
    df["nw_upper"] = nw_mid + (NW_MULT * std)
    df["nw_lower"] = nw_mid - (NW_MULT * std)
    return df

def generate_signal(df: pd.DataFrame) -> str:
    if len(df) < 15: return "NONE"
    
    curr = df.iloc[-2] # Kapanan mum
    prev = df.iloc[-3] # Bir önceki mum
    past = df.iloc[-15:-2] # Son 2 haftalık pusu kontrolü

    # PUSU KONTROLÜ: Son 15 mumda o uç değer görüldü mü?
    was_oversold = (past["rsi"] < RSI_PUSU_ALT).any()
    was_overbought = (past["rsi"] > RSI_PUSU_UST).any()

    # TETİK KONTROLÜ: RSI senin istediğin 31/69 bandına döndü mü?
    long_trigger = was_oversold and curr["rsi"] >= RSI_TETIK_LONG and prev["rsi"] < RSI_TETIK_LONG
    short_trigger = was_overbought and curr["rsi"] <= RSI_TETIK_SHORT and prev["rsi"] > RSI_TETIK_SHORT

    if long_trigger and curr["ha_color"] == "green":
        return "LONG"
    if short_trigger and curr["ha_color"] == "red":
        return "SHORT"
    return "NONE"

# ══════════════════════════════════════════════════════════════
#  🌐 TARAMA MANTIĞI
# ══════════════════════════════════════════════════════════════

binance_client = UMFutures(key=API_KEY, secret=API_SECRET)

def scan_asset(market, symbol):
    try:
        if market == "CRYPTO":
            raw = binance_client.klines(symbol=symbol, interval=TIMEFRAME, limit=KLINES_LIMIT)
            df = pd.DataFrame(raw, columns=["t","open","high","low","close","v","ct","qv","tr","tb","tq","i"])
        else:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", interval=TIMEFRAME)
            df.columns = [c.lower() for c in df.columns]

        df = df[["open","high","low","close"]].astype(float)
        df = compute_indicators(df)
        sig = generate_signal(df)

        if sig != "NONE":
            price = df["close"].iloc[-2]
            rsi_val = df["rsi"].iloc[-2]
            stop = price * (1 - TRAILING_STOP_PCT/100) if sig == "LONG" else price * (1 + TRAILING_STOP_PCT/100)
            
            msg = (f"🚀 <b>YENİ SİNYAL: {sig}</b>\n"
                   f"━━━━━━━━━━━━━━\n"
                   f"🔖 Sembol: #{symbol}\n"
                   f"💵 Fiyat: {price:.2f}\n"
                   f"📊 RSI: {rsi_val:.2f}\n"
                   f"🛑 100$ Stop: {stop:.2f}\n"
                   f"⚡ Kaldıraç: {LEVERAGE}x")
            tg_notify(msg)
    except:
        pass

def run():
    # Başlangıç Mesajı
    start_txt = (f"🤖 <b>KOD BAŞLADI</b>\n"
                 f"━━━━━━━━━━━━━━\n"
                 f"🎯 Strateji: RSI {RSI_PUSU_ALT}-{RSI_PUSU_UST} Pusu\n"
                 f"📈 Tetik: {RSI_TETIK_LONG}/{RSI_TETIK_SHORT}\n"
                 f"🛡️ Stop: %{TRAILING_STOP_PCT} (20x'te 100$)\n"
                 f"📡 Tarama: 200 Varlık (Hisse + Kripto)")
    tg_notify(start_txt)
    logger.info("Bot Telegram bildirimi ile başlatıldı.")

    while True:
        # Burada senin CRYPTO_SYMBOLS ve STOCK_SYMBOLS listelerin olacak
        assets = [("STOCK", "AAPL"), ("STOCK", "NVDA"), ("CRYPTO", "BTCUSDT")] # Örnek
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
            for m, s in assets: exe.submit(scan_asset, m, s)
        
        time.sleep(LOOP_INTERVAL_SEC)

if __name__ == "__main__":
    run()
