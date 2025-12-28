import os
import requests
import mplfinance as mpf
import pandas as pd
import asyncio
import nest_asyncio
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')  # Cloud ke liye zaroori
import matplotlib.pyplot as plt
import io

nest_asyncio.apply()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== ENV VARIABLES (Fly.io ke secrets se lenge) =====
# ===== ENV VARIABLES (Fly.io ke secrets se lenge) =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_CHAT_ID_STR = os.getenv("YOUR_CHAT_ID")  # String me milega, jaise "12345" ya "12345,67890"

if not TELEGRAM_TOKEN:
    print("ERROR: TELEGRAM_TOKEN not set in secrets!")
    exit()

# Chat IDs ko list mein convert karo
def get_chat_ids():
    if not YOUR_CHAT_ID_STR:
        return []
    return [int(cid.strip()) for cid in YOUR_CHAT_ID_STR.split(",") if cid.strip().isdigit()]

# Risk Settings
user_balance = 10000.0
max_risk_percent = 1.0

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

# ================= API Functions =================
def get_live_rate(base_curr, quote_curr):
    url = f"https://api.frankfurter.app/latest?from={base_curr}&to={quote_curr}"
    try:
        data = requests.get(url).json()
        return data.get('rates', {}).get(quote_curr)
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
    except Exception as e:
        print("Historical data error:", e)
        return pd.DataFrame()

# ================= Chart =================
def generate_chart(df, pair_name):
    if df.empty or len(df) < 20:
        return None
    try:
        data = df.copy()[-60:]
        data = data[['date', 'open', 'high', 'low', 'close']].set_index('date')
        data.columns = ['Open', 'High', 'Low', 'Close']

        fig, ax = plt.subplots(figsize=(12, 7))
        plt.style.use('dark_background')

        mpf.plot(data, type='candle', ax=ax, style='charles', show_nontrading=False)

        support = data['Low'].min()
        resistance = data['High'].max()
        ax.axhline(support, color='green', linestyle='--', alpha=0.7, label=f'Support: {support:.5f}')
        ax.axhline(resistance, color='red', linestyle='--', alpha=0.7, label=f'Resistance: {resistance:.5f}')

        ax.set_title(f"{pair_name} - Last 60 Days", color='white', fontsize=16)
        ax.legend()
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='black', bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print("Chart error:", e)
        return None

# ================= Signal =================
def generate_signal(df, pair_name):
    if df.empty or len(df) < 60:
        return f"{pair_name}: Not enough data.", "HOLD"

    last = df.iloc[-1]
    close_price = last['close']
    open_price = last['open']
    high_price = last['high']
    low_price = last['low']

    df['ma20'] = df['close'].rolling(20).mean()
    ma20 = df['ma20'].iloc[-1]

    strength = "HOLD"
    if close_price > ma20 and close_price > open_price:
        strength = "STRONG BUY"
    elif close_price < ma20 and close_price < open_price:
        strength = "STRONG SELL"

    # SL/TP
    sl_price = tp_price = rr_ratio = None
    if strength == "STRONG BUY":
        sl_price = low_price * 0.995
        tp_price = close_price * 1.010
    elif strength == "STRONG SELL":
        sl_price = high_price * 1.005
        tp_price = close_price * 0.990

    if sl_price and tp_price:
        risk = abs(close_price - sl_price)
        reward = abs(tp_price - close_price)
        rr_ratio = round(reward / risk, 2) if risk != 0 else 0

    recent = df[-60:]
    support = recent['low'].min()
    resistance = recent['high'].max()

    risk_text = f"\n\n**Risk Management**\n• SL: {sl_price:.5f}\n• TP: {tp_price:.5f}\n• RR: {rr_ratio}" if sl_price else "\n\n**Risk Management**\n• No clear signal."
    sr_text = f"\n\n**Support / Resistance**\n• Support: {support:.5f}\n• Resistance: {resistance:.5f}"

    if strength == "STRONG BUY":
        message = f"📈 {pair_name} - STRONG BUY\n• Price: {close_price:.5f}\n• MA20: {ma20:.5f}\n• Bullish Candle{risk_text}{sr_text}"
    elif strength == "STRONG SELL":
        message = f"📉 {pair_name} - STRONG SELL\n• Price: {close_price:.5f}\n• MA20: {ma20:.5f}\n• Bearish Candle{risk_text}{sr_text}"
    else:
        message = f"⚖ {pair_name} - HOLD\n• Price: {close_price:.5f}\n• MA20: {ma20:.5f}\n• Range market{risk_text}{sr_text}"

    return message, strength

# ================= Commands =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("💱 Live Rates", callback_data="live_menu"),
                 InlineKeyboardButton("📊 Chart + Signal", callback_data="chart_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🤖 **Forex Bot Live!**\nChart, Signal & Alerts ready!", reply_markup=reply_markup, parse_mode="Markdown")

async def set_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) == 2:
        try:
            global user_balance, max_risk_percent
            user_balance = float(args[0])
            max_risk_percent = float(args[1])
            await update.message.reply_text(f"✅ Updated!\nBalance: ${user_balance:,.0f}\nRisk: {max_risk_percent}%")
        except:
            await update.message.reply_text("❌ Wrong format. Use: /setrisk 10000 1")
    else:
        await update.message.reply_text("Usage: /setrisk balance risk_percent\nExample: /setrisk 10000 1")

# ================= Button Handler =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.endswith("_menu"):
        keyboard = [[InlineKeyboardButton(name, callback_data=f"{data[:-5]}_{name}")] for name in PAIRS]
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main")])
        await query.edit_message_text("Select Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "main":
        keyboard = [[InlineKeyboardButton("💱 Live Rates", callback_data="live_menu"),
                     InlineKeyboardButton("📊 Chart + Signal", callback_data="chart_menu")]]
        await query.edit_message_text("Main Menu", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    action, pair_name = data.split("_", 1)
    base, quote = PAIRS[pair_name]

    if action == "live":
        rate = get_live_rate(base, quote) or (1 / get_live_rate(quote, base) if get_live_rate(quote, base) else None)
        rate_str = f"{rate:.5f}" if rate else "Error"
        await query.edit_message_text(f"**{pair_name} Live Rate**\n\n{rate_str}", parse_mode="Markdown")
        return

    # Chart + Signal
    await query.edit_message_text("Generating chart & signal...")
    df = get_historical_data(base, quote)
    signal_text, strength = generate_signal(df, pair_name)
    chart = generate_chart(df, pair_name)

    if chart:
        await context.bot.send_photo(query.message.chat_id, chart, caption=f"**{pair_name}**\n\n{signal_text}", parse_mode="Markdown")
        await query.delete_message()
    else:
        await query.edit_message_text(f"**{pair_name}**\n\n{signal_text}\n\nChart not available", parse_mode="Markdown")

# ================= Auto Alert =================
async def auto_alert(context: ContextTypes.DEFAULT_TYPE):
    chat_ids = get_chat_ids()
    if not chat_ids:
        return

    for pair_name in PAIRS:
        base, quote = PAIRS[pair_name]
        df = get_historical_data(base, quote)
        if df.empty:
            continue
        message, strength = generate_signal(df, pair_name)
        chart = generate_chart(df, pair_name)

        if strength in ["STRONG BUY", "STRONG SELL"]:
            caption = f"🔔 **STRONG SIGNAL**\n\n{message}"
            for chat_id in chat_ids:
                try:
                    if chart:
                        await context.bot.send_photo(chat_id, chart, caption=caption, parse_mode="Markdown")
                    else:
                        await context.bot.send_message(chat_id, caption, parse_mode="Markdown")
                except Exception as e:
                    print(f"Alert send error to {chat_id}: {e}")

# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setrisk", set_risk))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_alert, interval=1800, first=30)  # Every 30 min

    print("Forex Bot Running Successfully!")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
