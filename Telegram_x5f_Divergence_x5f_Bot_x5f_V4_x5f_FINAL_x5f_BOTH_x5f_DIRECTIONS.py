
"""
V4 FINAL - ПЪЛНА ВЕРСИЯ
- И двете посоки: БУЛИШ + МЕЧИ обем
- Оставени малки TF: 1m,5m,15m,1h,4h,1D
- Delta + праг 20% + силна фаза преди
- Снимката ти е BEARISH пример, добавям и BULLISH обратното
"""

import os, asyncio, pandas as pd, numpy as np, yfinance as yf
from telegram import Bot
import logging

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "СЛОЖИ_ТОКЕНА_ОТ_BOTFATHER")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "СЛОЖИ_CHAT_ID")

ROLLING = 100
MIN_DROP_PCT = 20.0  # праг за спад на обема
MIN_DELTA_PCT = 25.0 # праг за спад на Delta

SYMBOLS = {
    "EURCAD": "EURCAD=X", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X", "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
    "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X", "EURGBP": "EURGBP=X",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "SP500": "^GSPC", "NASDAQ": "^IXIC", "DAX": "^GDAXI", "US30": "^DJI"
}

TFS = [
    ("1m", "1d", "1m"),
    ("5m", "5d", "5m"),
    ("15m", "5d", "15m"),
    ("1h", "1mo", "60m"),
    ("4h", "3mo", "60m"),
    ("1D", "1y", "1d"),
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

def calc(df, rolling=100):
    if 'Volume' not in df.columns or df['Volume'].sum()==0:
        df['Volume']=1_000_000
    df['buyVol']=np.where(df['Close']>=df['Open'], df['Volume'],0)
    df['sellVol']=np.where(df['Close']<df['Open'], df['Volume'],0)
    df['cumBuy']=df['buyVol'].rolling(rolling).sum()
    df['cumSell']=df['sellVol'].rolling(rolling).sum()
    df['delta']=df['cumBuy']-df['cumSell']  # оранжева линия
    df['bull_ratio']=df['cumBuy']/df['cumSell'].replace(0,1)
    df['bear_ratio']=df['cumSell']/df['cumBuy'].replace(0,1)
    return df

def pivots(arr, left=5, right=3):
    highs,lows=[],[]
    for i in range(left, len(arr)-right):
        w=arr[i-left:i+right+1]
        if arr[i]==np.max(w) and arr[i]>0: highs.append(i)
        if arr[i]==np.min(w) and arr[i]>0: lows.append(i)
    return highs,lows

def detect_both(df):
    if len(df)<ROLLING+150: return None
    high=df['High'].values; low=df['Low'].values
    cumBuy=df['cumBuy'].values; cumSell=df['cumSell'].values; delta=df['delta'].values
    
    ph_high,_=pivots(high)
    pl_low=pivots(low)[1]
    ph_buy,_=pivots(cumBuy)
    pl_buy=pivots(cumBuy)[1]
    ph_sell,_=pivots(cumSell)
    pl_sell=pivots(cumSell)[1]
    ph_delta,_=pivots(delta)
    pl_delta=pivots(delta)[1]
    
    # 1) BEARISH DISTRIBUTION - като на снимката ти
    # Цена HH, cumBuy LH, Delta пада, преди това силно булиш
    if len(ph_high)>=2 and len(ph_buy)>=2:
        p1,p2=ph_high[-2],ph_high[-1]
        b1,b2=ph_buy[-2],ph_buy[-1]
        if abs(p2-b2)<=7 and len(df)-p2<=12 and high[p2]>high[p1] and cumBuy[b2]<cumBuy[b1]:
            drop=(cumBuy[b1]-cumBuy[b2])/cumBuy[b1]*100
            if drop>=MIN_DROP_PCT:
                # Delta check
                max_delta=np.max(delta[max(0,b1-30):b1+1])
                delta_drop=(max_delta-delta[b2])/max_delta*100 if max_delta>0 else 0
                if delta_drop>=MIN_DELTA_PCT:
                    lookback=df.iloc[max(0,b1-200):b1]
                    strong=lookback['bull_ratio'].mean()>1.25
                    return {
                        "type":"BEARISH",
                        "title":"🔴🔥 МЕЧИ РАЗПРЕДЕЛЕНИЕ (като на снимката)",
                        "desc":"Цена прави по-висок връх, но силния БУЛИШ обем се изтощава + Delta се срива",
                        "price1":high[p1],"price2":high[p2],
                        "vol1":cumBuy[b1],"vol2":cumBuy[b2],"drop":drop,
                        "delta_max":max_delta,"delta_curr":delta[b2],"delta_drop":delta_drop,
                        "strong":strong,"time":df.index[p2]
                    }
    
    # 2) BULLISH ACCUMULATION - обратното - за мечи обем
    # Цена LL, cumSell LH (продавачите се изтощават), Delta се качва от дълбоко мечи към 0
    # Логика: първо силно МЕЧИ (червен fill), после cumSell пада, цената още пада но вече няма продавачи = reversal нагоре
    if len(pl_low)>=2 and len(ph_sell)>=2:
        p1,p2=pl_low[-2],pl_low[-1]
        s1,s2=ph_sell[-2],ph_sell[-1]  # върхове на cumSell
        if abs(p2-s2)<=7 and len(df)-p2<=12 and low[p2]<low[p1] and cumSell[s2]<cumSell[s1]:
            drop=(cumSell[s1]-cumSell[s2])/cumSell[s1]*100
            if drop>=MIN_DROP_PCT:
                min_delta=np.min(delta[max(0,s1-30):s1+1])
                delta_rise=(delta[s2]-min_delta)/abs(min_delta)*100 if min_delta!=0 else 0
                # Delta се качва от много отрицателна към 0
                if delta_rise>=MIN_DELTA_PCT or delta[s2]>min_delta:
                    lookback=df.iloc[max(0,s1-200):s1]
                    strong=lookback['bear_ratio'].mean()>1.25
                    return {
                        "type":"BULLISH",
                        "title":"🟢🔥 БИЧИ НАТРУПВАНЕ (обратното на снимката)",
                        "desc":"Цена прави по-ниско дъно, но силния МЕЧИ обем се изтощава + Delta се възстановява",
                        "price1":low[p1],"price2":low[p2],
                        "vol1":cumSell[s1],"vol2":cumSell[s2],"drop":drop,
                        "delta_max":min_delta,"delta_curr":delta[s2],"delta_drop":delta_rise,
                        "strong":strong,"time":df.index[p2]
                    }
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
            extra="✅ Преди това е имало силна фаза" if sig['strong'] else ""
            msg=(
                f"{sig['title']}\n\n"
                f"📊 *{name}* | TF: *{tf_label}* | Rolling {ROLLING}\n"
                f"💰 Цена: `{sig['price1']:.5f}` → `{sig['price2']:.5f}`\n"
                f"📦 Обем: `{sig['vol1']:,.0f}` → `{sig['vol2']:,.0f}` (-{sig['drop']:.1f}% ≥ {MIN_DROP_PCT}%)\n"
                f"🟠 Delta: `{sig['delta_max']:,.0f}` → `{sig['delta_curr']:,.0f}` ({sig['delta_drop']:+.1f}%)\n"
                f"{extra}\n"
                f"🕐 {sig['time']}\n\n"
                f"_{sig['desc']}_"
            )
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            logging.info(f"{sig['type']} {name} {tf_label}")
    except Exception as e:
        logging.error(f"{name} {tf_label} {e}")

async def main():
    bot=Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=f"✅ *V4 FINAL* стартира\nИ двете посоки:\n🔴 Bearish като на снимката (булиш обем → изтощение)\n🟢 Bullish обратното (мечи обем → изтощение)\nПрагове: обем ≥{MIN_DROP_PCT}% Delta ≥{MIN_DELTA_PCT}%\nTF: 1m,5m,15m,1h,4h,1D", parse_mode='Markdown')
    while True:
        for tf_label,period,interval in TFS:
            for name,ticker in SYMBOLS.items():
                await scan(bot,name,ticker,tf_label,period,interval)
                await asyncio.sleep(0.3)
        await asyncio.sleep(60)

if __name__=="__main__":
    if "СЛОЖИ" in BOT_TOKEN:
        BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
        CHAT_ID=os.getenv("TELEGRAM_CHAT_ID", CHAT_ID)
    asyncio.run(main())
