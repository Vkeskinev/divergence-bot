import os, asyncio, threading, logging, http.server, socketserver
from telegram import Bot
import random
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

async def main_bot():
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("⚠️ Няма токени - чакам в Environment")
        while True:
            await asyncio.sleep(3600)
    
    bot=Bot(token=BOT_TOKEN)
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=f"✅ TEST LIVE е стартиран!\nВреме: {datetime.now()}\nЩе пращам фалшив сигнал на всеки 2 мин за да проверим Telegram.", parse_mode='Markdown')
        logging.info("Telegram test message sent!")
    except Exception as e:
        logging.error(f"Telegram error {e}")

    counter = 0
    while True:
        counter += 1
        logging.info(f"Heartbeat #{counter} - bot is alive, scanning... {datetime.now()}")
        
        if counter % 2 == 0:
            try:
                msg = f"🧪 *TEST СИГНАЛ #{counter//2}*\n\n📊 EURCAD | TF: 15m\n💰 Цена: 1.49800 → 1.49950\n📦 Обем: 1,200,000 → 950,000 (-20.8%)\n🕐 {datetime.now()}\n\nТова е фалшив сигнал за тест!"
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
                logging.info(f"SIGNAL SENT #{counter//2}")
            except Exception as e:
                logging.error(f"Send error {e}")
        
        await asyncio.sleep(60)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot TEST running - heartbeat every 60s")

def run_http():
    port=int(os.environ.get("PORT",10000))
    with socketserver.TCPServer(("",port), Handler) as httpd:
        logging.info(f"HTTP server on port {port}")
        httpd.serve_forever()

if __name__=="__main__":
    threading.Thread(target=run_http, daemon=True).start()
    asyncio.run(main_bot())
