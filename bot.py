import os, asyncio, threading, logging, http.server, socketserver
import pandas as pd, numpy as np, yfinance as yf
from telegram import Bot
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ROLLING = 100
MIN_DROP_PCT = 15.0
MIN_DELTA_PCT = 15.0
SEND_CYCLE_SUMMARY = True  # Ако спами много, сложи False

SYMBOLS = {
    "EURCAD": "EURCAD=X", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X", "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
    "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X", "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "SP500": "^GSPC", "NASDAQ": "^IXIC", "DAX": "^GDAXI"
}
# V4.3 - ВЪРНАТИ 1m и 5m както искаш
TFS = [("1m","1d","1m"),("5m","5d","5m"),("15m","5d","15m"),("1h","1mo","60m"),("4h","3mo","60m"),("1D","1y","1d")]

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
sent_cache = set()

def calc(df, rolling=100):
    if 'Volume' not in df.columns or df['Volume'].sum()==0: df['Volume']=1_000_000
    df['buyVol']=np.where(df['Close']>=df['Open'], df['Volume'],0)
    df['sellVol']=np.where(df['Close']<df['Open'], df['Volume'],0)
    df['cumBuy']=df['buyVol'].rolling(rolling).sum()
    df['cumSell']=df['sellVol'].rolling(rolling).sum()
    df['delta']=df['cumBuy']-df['cumSell']
    return df

def pivots(arr, left=5, right=3):
    highs=[]; lows=[]
    for i in range(left, len(arr)-right):
        w=arr[i-left:i+right+1]
        if arr[i]==np.max(w) and arr[i]>0: highs.append(i)
        if arr[i]==np.min(w) and arr[i]>0: lows.append(i)
    return highs,lows

def detect_both(df):
    if len(df)<ROLLING+50: return None
    high=df['High'].values; low=df['Low'].values
    cumBuy=df['cumBuy'].values; cumSell=df['cumSell'].values; delta=df['delta'].values
    ph_high = pivots(high)[0]; pl_low = pivots(low)[1]
    ph_buy = pivots(cumBuy)[0]; ph_sell = pivots(cumSell)[0]
    if len(ph_high)>=2 and len(ph_buy)>=2:
        p1,p2=ph_high[-2],ph_high[-1]; b1,b2=ph_buy[-2],ph_buy[-1]
        if abs(p2-b2)<=7 and len(df)-p2<=12 and high[p2]>high[p1] and cumBuy[b2]<cumBuy[b1]:
            drop=(cumBuy[b1]-cumBuy[b2])/cumBuy[b1]*100 if cumBuy[b1]>0 else 0
            if drop>=MIN_DROP_PCT:
                max_delta=np.max(delta[max(0,b1-30):b1+1])
                delta_drop=(max_delta-delta[b2])/max_delta*100 if max_delta>0 else 0
                if delta_drop>=MIN_DELTA_PCT:
                    return {"type":"BEARISH","title":"🔴 МЕЧИ РАЗПРЕДЕЛЕНИЕ","price1":high[p1],"price2":high[p2],"vol1":cumBuy[b1],"vol2":cumBuy[b2],"drop":drop,"delta_max":max_delta,"delta_curr":delta[b2],"delta_drop":delta_drop,"time":df.index[p2]}
    if len(pl_low)>=2 and len(ph_sell)>=2:
        p1,p2=pl_low[-2],pl_low[-1]; s1,s2=ph_sell[-2],ph_sell[-1]
        if abs(p2-s2)<=7 and len(df)-p2<=12 and low[p2]<low[p1] and cumSell[s2]<cumSell[s1]:
            drop=(cumSell[s1]-cumSell[s2])/cumSell[s1]*100 if cumSell[s1]>0 else 0
            if drop>=MIN_DROP_PCT:
                min_delta=np.min(delta[max(0,s1-30):s1+1])
                delta_rise=(delta[s2]-min_delta)/abs(min_delta)*100 if min_delta!=0 else 0
                if delta_rise>=MIN_DELTA_PCT or delta[s2]>min_delta:
                    return {"type":"BULLISH","title":"🟢 БИЧИ НАТРУПВАНЕ","price1":low[p1],"price2":low[p2],"vol1":cumSell[s1],"vol2":cumSell[s2],"drop":drop,"delta_max":min_delta,"delta_curr":delta[s2],"delta_drop":delta_rise,"time":df.index[p2]}
    return None

async def scan(bot, name, ticker, tf_label, period, interval):
    global sent_cache
    try:
        df=yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True, threads=False)
        if df.empty: 
            logging.info(f"Scan {name} {tf_label} - empty")
            return 0
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if tf_label=="4h": df=df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df=calc(df, ROLLING); df.dropna(inplace=True)
        sig=detect_both(df)
        if sig:
            key = f"{name}_{tf_label}_{sig['time']}"
            if key in sent_cache:
                logging.info(f"Scan {name} {tf_label} - duplicate skipped")
                return 0
            sent_cache.add(key)
            if len(sent_cache) > 200: sent_cache.clear()
            msg=f"{sig['title']}\n\n📊 *{name}* | TF: *{tf_label}* | Rolling {ROLLING}\n💰 Цена: `{sig['price1']:.5f}` → `{sig['price2']:.5f}`\n📦 Обем: `{sig['vol1']:,.0f}` → `{sig['vol2']:,.0f}` (-{sig['drop']:.1f}%)\n🟠 Delta: `{sig['delta_max']:,.0f}` → `{sig['delta_curr']:,.0f}` (-{sig['delta_drop']:.1f}%)\n🕐 {sig['time']}"
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            logging.info(f"SIGNAL {name} {tf_label} {sig['type']} {sig['drop']:.1f}%")
            return 1
        else:
            logging.info(f"Scan {name} {tf_label} - no signal")
            return 0
    except Exception as e:
        logging.error(f"{name} {tf_label} {e}")
        return 0

async def main_bot():
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("⚠️ Няма токени")
        while True: await asyncio.sleep(3600)
    bot=Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=f"✅ *V4.3 LIVE*\nПрагове: {MIN_DROP_PCT}% / {MIN_DELTA_PCT}%\nTF: 1m, 5m, 15m, 1h, 4h, 1D (върнати!)\nЩе казвам когато няма открити!", parse_mode='Markdown')
    logging.info("Bot V4.3 started with 1m,5m")
    while True:
        total_signals = 0
        total_checks = len(TFS) * len(SYMBOLS)
        for tf_label,period,interval in TFS:
            for name,ticker in SYMBOLS.items():
                sig = await scan(bot,name,ticker,tf_label,period,interval)
                total_signals += sig
                await asyncio.sleep(1)
        
        # ТУК Е НОВОТО - казва когато няма открити
        if total_signals == 0:
            msg_log = f"=== ЦИКЪЛ ЗАВЪРШЕН: НЯМА ОТКРИТИ ДИВЕРГЕНЦИИ | Проверени {total_checks} | {datetime.now().strftime('%H:%M:%S')} ==="
            logging.info(msg_log)
            if SEND_CYCLE_SUMMARY:
                try:
                    await bot.send_message(chat_id=CHAT_ID, text=f"ℹ️ *Цикъл завършен*\nНяма открити дивергенции\nПроверени: {total_checks} (
