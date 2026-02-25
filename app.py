import yfinance as yf
import pandas as pd
import requests
import time
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- ⚙️ AYARLAR ---
TOKEN = "8349458683:AAEi-AFSYxn0Skds7r4VQIaogVl3Fugftyw"
ID_GUNLUK = "1484256652"          
ID_KANAL = "-1003792245773"       

def telegram_gonder(chat_id, mesaj):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": mesaj, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

# --- 📋 LİSTELER ---
kripto_liste = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "XRPUSDT", "ADAUSDT", "DOTUSDT", "LINKUSDT", "DOGEUSDT", "KASUSDT"]
hisse_liste = ["THYAO.IS", "SISE.IS", "EREGL.IS", "KCHOL.IS", "ASELS.IS", "TUPRS.IS", "GARAN.IS", "NVDA", "TSLA", "AAPL", "MSFT", "GC=F"]

def heikin_ashi_hesapla(df):
    ha_df = pd.DataFrame(index=df.index)
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    return ha_df['HA_Close']

def veri_getir(sembol, interval, period):
    try:
        if "USDT" in sembol: # Kripto ise Binance'ten çek
            limit = 300
            # Binance interval dönüşümü
            b_int = interval.replace("m", "m").replace("h", "h").replace("d", "d")
            url = f"https://api.binance.com/api/v3/klines?symbol={sembol}&interval={b_int}&limit={limit}"
            data = requests.get(url).json()
            df = pd.DataFrame(data, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume', '', '', '', '', '', ''])
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            return df
        else: # Hisse ise Yahoo'dan çek
            t = yf.Ticker(sembol)
            return t.history(period=period, interval=interval)
    except: return None

def tarama_motoru(periyot_adi, interval, period, sma_ayar, bekleme, hedef_id):
    while True:
        tam_liste = kripto_liste + hisse_liste
        for sembol in tam_liste:
            try:
                df = veri_getir(sembol, interval, period)
                if df is None or df.empty or len(df) < max(sma_ayar): continue
                
                ha_close = heikin_ashi_hesapla(df)
                sma_kisa = ha_close.rolling(window=sma_ayar[0]).mean()
                sma_uzun = ha_close.rolling(window=sma_ayar[1]).mean()
                fiyat_normal = float(df['Close'].iloc[-1])

                if sma_kisa.iloc[-2] <= sma_uzun.iloc[-2] and sma_kisa.iloc[-1] > sma_uzun.iloc[-1]:
                    avg_vol = df['Volume'].tail(15).mean()
                    cvd_onay = "✅ GÜÇLÜ CVD" if df['Volume'].iloc[-1] > (avg_vol * 1.1) else "⚠️ ZAYIF HACİM"
                    
                    msg = (f"🚀 {sembol} {periyot_adi} SİNYAL\n"
                           f"💰 Fiyat: {fiyat_normal:.2f}\n"
                           f"📊 Durum: {cvd_onay}\n"
                           f"🕯️ Binance & HA Filtresi Aktif")
                    telegram_gonder(hedef_id, msg)
                
                time.sleep(0.5)
            except: continue
        time.sleep(bekleme)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hybrid Engine Online")

if __name__ == "__main__":
    telegram_gonder(ID_KANAL, "🔗 BİNANCE ENTEGRASYONU TAMAMLANDI!\nKriptolar anlık, hisseler Yahoo üzerinden taranıyor.")
    
    Thread(target=tarama_motoru, args=("Günlük", "1d", "2y", (20, 140), 1800, ID_GUNLUK)).start()
    Thread(target=tarama_motoru, args=("4 Saat", "4h", "100d", (50, 200), 900, ID_KANAL)).start()
    Thread(target=tarama_motoru, args=("1 Saat", "1h", "30d", (50, 200), 600, ID_KANAL)).start()
    Thread(target=tarama_motoru, args=("15 Dakika", "15m", "7d", (20, 50), 300, ID_KANAL)).start()
    
    server = HTTPServer(('0.0.0.0', 10000), HealthHandler)
    server.serve_forever()
