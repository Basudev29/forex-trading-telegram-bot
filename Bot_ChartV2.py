import requests
import pandas as pd
import pandas_ta as ta
import asyncio
import nest_asyncio
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')  # Render ke liye yeh line zaroori hai
import matplotlib.pyplot as plt
import io
import numpy as np
from scipy.signal import find_peaks

nest_asyncio.apply()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== DETAILS =====
TELEGRAM_TOKEN = '8377055187:AAGinbhefXUOk9vj2miXAcfI1B-1_Hgr-cw'
YOUR_CHAT_ID = 966554382945

# Risk Settings
user_balance = 10000.0
max_risk_percent = 1.0
reward_risk_ratio = 2

# Pairs
PAIRS = {
    'EUR/USD': ('EUR', 'USD'),
    'GBP/USD': ('GBP', 'USD'),
    'USD/JPY': ('USD', 'JPY'),
    'AUD/USD': ('AUD', 'USD'),
    'USD/CAD': ('USD', 'CAD'),
    'NZD/USD': ('NZD', 'USD'),
    'USD/CHF': ('USD', 'CHF')
}

# API Functions
def get_live_rate(base_curr, quote_curr):
    url = f"https://api.frankfurter.app/latest?from={base_curr}&to={quote_curr}"
    try:
        data = requests.get(url).json()
        if 'rates' in data:
            return data['rates'][quote_curr]
        return None
    except:
        return None

def get_historical_data(base_curr, quote_curr, days=365):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    url = f"https://api.frankfurter.app/{start_date}..{end_date}?from={base_curr}&to={quote_curr}"
    try:
        data = requests.get(url).json()
        if 'rates' not in data:
            return pd.DataFrame()
        
        df_data = []
        for date_str, currencies in data['rates'].items():
            rate = currencies.get(quote_curr)
            if rate is not None:
                df_data.append({'date': date_str, 'close': rate})
        
        if not df_data:
            return pd.DataFrame()
        
        df = pd.DataFrame(df_data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df['close'] = df['close'].astype(float)
        
        df['open'] = df['close'].shift(1)
        df['high'] = df['close'].rolling(window=5).max()
        df['low'] = df['close'].rolling(window=5).min()
        df = df.dropna().reset_index(drop=True)
        return df
    except:
        return pd.DataFrame()

# Support & Resistance
def find_support_resistance(df):
    if len(df) < 30:
        return [], []
    
    recent = df[-90:]
    highs = recent['high'].values
    lows = recent['low'].values
    
    # Find peaks (resistance)
    peaks, _ = find_peaks(highs, distance=10, prominence=0.0005)
    resistance = highs[peaks]
    
    # Find troughs (support)
    troughs, _ = find_peaks(-lows, distance=10, prominence=0.0005)
    support = lows[troughs]
    
    # Take top 3
    resistance = sorted(set(resistance.round(5)), reverse=True)[:3]
    support = sorted(set(support.round(5)))[:3]
    
    return support, resistance

# Chart with S/R
def generate_chart(df, pair_name):
    if df.empty or len(df) < 20:
        return None
    
    try:
        plt.figure(figsize=(12, 8))
        plt.style.use('dark_background')
        
        recent = df[-60:]
        plt.plot(recent['date'], recent['close'], label='Price', color='cyan', linewidth=2)
        
        sma_20 = ta.sma(df['close'], length=20)
        sma_50 = ta.sma(df['close'], length=50)
        plt.plot(recent['date'], sma_20[-60:], label='SMA 20', color='yellow', alpha=0.8)
        plt.plot(recent['date'], sma_50[-60:], label='SMA 50', color='orange', alpha=0.8)
        
        # S/R lines
        support, resistance = find_support_resistance(df)
        for level in support:
            plt.axhline(level, color='green', linestyle='--', alpha=0.7, label='Support' if support.index(level) == 0 else "")
        for level in resistance:
            plt.axhline(level, color='red', linestyle='--', alpha=0.7, label='Resistance' if resistance.index(level) == 0 else "")
        
        plt.title(f"{pair_name} - Last 60 Days with S/R", color='white', fontsize=16)
        plt.xlabel('Date', color='white')
        plt.ylabel('Price', color='white')
        plt.legend()
        plt.grid(alpha=0.3)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='black')
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        print("Chart error:", e)
        return None

# Signal with S/R
def generate_signal(df, pair_name):
    if df.empty or len(df) < 50:
        return "Not enough data 😕", 0
    
    df['sma_20'] = ta.sma(df['close'], length=20)
    df['sma_50'] = ta.sma(df['close'], length=50)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    strength = 0
    reasons = []
    
    if last['sma_20'] > last['sma_50'] and prev['sma_20'] <= prev['sma_50']:
        reasons.append("🟢 Golden Cross")
        strength += 3
    elif last['sma_20'] < last['sma_50'] and prev['sma_20'] >= prev['sma_50']:
        reasons.append("🔴 Death Cross")
        strength -= 3
    
    # S/R
    support, resistance = find_support_resistance(df)
    current = last['close']
    sr_text = ""
    if support and abs(current - max(support)) < last['atr']:
        sr_text += f"\n🟢 Near Support ({max(support):.5f}) - Strong Buy Zone"
        strength += 2
    if resistance and abs(current - min(resistance)) < last['atr']:
        sr_text += f"\n🔴 Near Resistance ({min(resistance):.5f}) - Caution"
        strength -= 2
    
    base, quote = PAIRS[pair_name]
    live_rate = get_live_rate(base, quote)
    if live_rate is None:
        live_rate = get_live_rate(quote, base)
        if live_rate is not None:
            live_rate = 1 / live_rate if base != 'USD' else live_rate
    
    live_str = f"{live_rate:.5f}" if live_rate else "N/A"
    
    atr = last['atr'] if pd.notna(last['atr']) else 0.001
    risk_amount = user_balance * (max_risk_percent / 100)
    position_size = risk_amount / (atr * 10000) if atr > 0 else 0.01
    
    sl = tp = "N/A"
    if strength > 0 and live_rate:
        sl = f"{live_rate - atr:.5f}"
        tp = f"{live_rate + (reward_risk_ratio * atr):.5f}"
    elif strength < 0 and live_rate:
        sl = f"{live_rate + atr:.5f}"
        tp = f"{live_rate - (reward_risk_ratio * atr):.5f}"
    
    risk_text = (
        f"\n\n**Risk Management**\n"
        f"• Balance: ${user_balance:,.0f}\n"
        f"• Risk %: {max_risk_percent}%\n"
        f"• Lots: {position_size:.2f}\n"
        f"• Stop-Loss: {sl}\n"
        f"• Take-Profit: {tp}\n"
        f"• R:R = {reward_risk_ratio}:1"
    )
    
    if strength >= 4:
        signal = f"**STRONG BUY** 📈\n" + "\n".join(reasons) + sr_text + f"\n\nLive Rate: {live_str}" + risk_text
    elif strength <= -4:
        signal = f"**STRONG SELL** 📉\n" + "\n".join(reasons) + sr_text + f"\n\nLive Rate: {live_str}" + risk_text
    else:
        signal = f"**HOLD** ⚖️\nStrength: {strength}{sr_text}\nLive Rate: {live_str}\n\nWait for stronger signal."
    
    return signal, strength

# Commands & Handlers (same as before, no change needed)

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setrisk", set_risk))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.job_queue.run_repeating(auto_alert, interval=1800, first=30)
    
    print("Bot with Support/Resistance & Chart - Final Version!")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
