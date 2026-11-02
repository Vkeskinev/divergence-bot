
"""
FREE версия за Render Web Service - БЕЗ Flask, без външни зависимости
Работи 24/7, безплатен план
"""

import os, asyncio, threading
import pandas as pd, numpy as np, yfinance as yf
from telegram import Bot
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ROLLING = 100
MIN_DROP_PCT = 20.0
MIN_DELTA_PCT = 25.0

SYMBOLS = {
    "EURCAD": "EURCAD=X", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X", "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
    "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X", "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "SP500": "^GSPC", "NASDAQ": "^IXIC", "DAX": "^GDAXI"
}
TFS = [("1m","1d","1m"),("5m","5d","5m"),("15m","5d","15m"),("1h","1mo","60m"),("4h","3mo","60m"),("1D","1y","1d")]

logging.basicConfig(level=logging.INFO)

def calc(df, rolling=100):
    if 'Volume' not in df.columns or df['Volume'].sum()==0:
        df['Volume']=1_000_000
    df['buyVol']=np.where(df['Close']>=df['Open'], df['Volume'],0)
    df['sellVol']=np.where(df['Close']<df['Open'], df['Volume'],0)
    df['cumBuy']=df['buyVol'].rolling(rolling).sum()
    df['cumSell']=df['sellVol'].rolling(rolling).sum()
    df['delta']=df['cumBuy']-df['cumSell']
    df['bull_ratio']=df['cumBuy']/df['cumSell'].replace(0,1)
    df['bear_ratio']=df['cumSell']/df['cumBuy'].replace(0,1)
    return df

def pivots(arr, left=5, right=3):
    highs=[]
    for i in range(left, len(arr)-right):
        w=arr[i-left:i+right+1]
        if arr[i]==np.max(w) and arr[i]>0: highs.append(i)
    lows=[]
    for i in range(left, len(arr)-right):
        w=arr[i-left:i+right+1]
        if arr[i]==np.min(w) and arr[i]>0: lows.append(i)
    return highs,lows

def detect_both(df):
    if len(df)<ROLLING+150: return None
    high=df['High'].values; low=df['Low'].values
    cumBuy=df['cumBuy'].values; cumSell=df['cumSell'].values; delta=df['delta'].values
    ph_high = pivots(high)[0]
    pl_low = pivots(low)[1]
    ph_buy = pivots(cumBuy)[0]
    ph_sell = pivots(cumSell)[0]
    
    if len(ph_high)>=2 and len(ph_buy)>=2:
        p1,p2=ph_high[-2],ph_high[-1]
        b1,b2=ph_buy[-2],ph_buy[-1]
        if abs(p2-b2)<=7 and len(df)-p2<=12 and high[p2]>high[p1] and cumBuy[b2]<cumBuy[b1]:
            drop=(cumBuy[b1]-cumBuy[b2])/cumBuy[b1]*100
            if drop>=MIN_DROP_PCT:
                max_delta=np.max(delta[max(0,b1-30):b1+1])
                delta_drop=(max_delta-delta[b2])/max_delta*100 if max_delta>0 else 0
                if delta_drop>=MIN_DELTA_PCT:
                    return {"type":"BEARISH","title":"🔴🔥 МЕЧИ РАЗПРЕДЕЛЕНИЕ","price1":high[p1],"price2":high[p2],"vol1":cumBuy[b1],"vol2":cumBuy[b2],"drop":drop,"delta_max":max_delta,"delta_curr":delta[b2],"delta_drop":delta_drop,"time":df.index[p2]}
    if len(pl_low)>=2 and len(ph_sell)>=2:
        p1,p2=pl_low[-2],pl_low[-1]
        s1,s2=ph_sell[-2],ph_sell[-1]
        if abs(p2-s2)<=7 and len(df)-p2<=12 and low[p2]<low[p1] and cumSell[s2]<cumSell[s1]:
            drop=(cumSell[s1]-cumSell[s2])/cumSell[s1]*100
            if drop>=MIN_DROP_PCT:
                min_delta=np.min(delta[max(0,s1-30):s1+1])
                delta_rise=(delta[s2]-min_delta)/abs(min_delta)*100 if min_delta!=0 else 0
                if delta_rise>=MIN_DELTA_PCT or delta[s2]>min_delta:
                    return {"type":"BULLISH","title":"🟢🔥 БИЧИ НАТРУПВАНЕ","price1":low[p1],"price2":low[p2],"vol1":cumSell[s1],"vol2":cumSell[s2],"drop":drop,"delta_max":min_delta,"delta_curr":delta[s2],"delta_drop":delta_rise,"time":df.index[p2]}
    return None

async def scan(bot, name, ticker, tf_label, period, interval):
    try:
        df=yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty: return
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if tf_label=="4h": df=df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df=calc(df, ROLLING)
        df.dropna(inplace=True)
        sig=detect_both(df)
        if sig:
            msg=(f"{sig['title']}\n\n📊 *{name}* | TF: *{tf_label}* | Rolling {ROLLING}\n💰 Цена: `{sig['price1']:.5f}` → `{sig['price2']:.5f}`\n📦 Обем: `{sig['vol1']:,.0f}` → `{sig['vol2']:,.0f}` (-{sig['drop']:.1f}%)\n🟠 Delta: `{sig['delta_max']:,.0f}` → `{sig['delta_curr']:,.0f}`\n🕐 {sig['time']}")
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"{name} {tf_label} {e}")

async def main_bot():
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("⚠️ Няма токени - чакам да ги сложиш в Environment")
        while True:
            await asyncio.sleep(3600)
    bot=Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=CHAT_ID, text=f"✅ *V4 FREE стартира на Render*\nБезплатен план, работи 24/7\nПрагове: обем ≥{MIN_DROP_PCT}% Delta ≥{MIN_DELTA_PCT}%", parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Telegram грешка: {e}")
    while True:
        for tf_label,period,interval in TFS:
            for name,ticker in SYMBOLS.items():
                await scan(bot,name,ticker,tf_label,period,interval)
                await asyncio.sleep(0.3)
        await asyncio.sleep(60)

# Simple HTTP server to keep Render happy (no Flask needed)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running - Divergence V4 - Free')
    def log_message(self, format, *args):
        return

def run_http():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    logging.info(f"HTTP server on port {port}")
    server.serve_forever()

if __name__=="__main__":
    threading.Thread(target=run_http, daemon=True).start()
    asyncio.run(main_bot())
