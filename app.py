from flask import Flask, request
import requests
import os

app = Flask(name)

# Senin bilgilerini buraya sabitledim
TOKEN = "8246285336:AAGahOnnxKIlgkukCJGm-jmWYCYAeuZyQBY"
CHAT_ID = "1484256652"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return "Veri gelmedi", 400
        
    ticker = data.get('ticker', 'Bilinmiyor')
    price = data.get('price', '0')
    action = data.get('action', 'Sinyal')
    
    # Telegram'a gidecek mesajın tasarımı
    message = f"🚀 *{action} SİNYALİ!*\n\n📈 *Sembol:* {ticker}\n💰 *Fiyat:* {price}\n⏰ *Durum:* Kesişme Gerçekleşti"
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)
    
    return "Sinyal Telegram'a iletildi", 200

if name == 'main':
    # Render'ın verdiği portu otomatik kullanır
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))
