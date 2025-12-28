import os
import requests
import pandas as pd
import pandas_ta as ta
import asyncio
import nest_asyncio
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')  # Render ke liye zaroori
import matplotlib.pyplot as plt
import io

nest_asyncio.apply()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== DETAILS (ENV VARIABLES) =====
# Render / .env me set karo:
# TELEGRAM_TOKEN, YOUR_CHAT_ID

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID", "123456"))

# Risk Settings (global default)
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

# ================= API Functions =================

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

        # OHLC approx
        df['open'] = df['close'].shift(1)
        df['high'] = df['close'].rolling(window=5).max()
        df['low'] = df['close'].rolling(window=5).min()
        df = df.dropna().reset_index(drop=True)

        return df
    except:
        return pd.DataFrame()

# ================= Chart (with Support/Resistance) =================

def generate_chart(df, pair_name):
    if df.empty or len(df) < 20:
        return None

    try:
        plt.figure(figsize=(12, 7))
        plt.style.use('dark_background')

        recent = df[-60:]

        # Price
        plt.plot(recent['date'], recent['close'], label='Price', color='cyan', linewidth=2)

        # SMAs
        sma_20 = ta.sma(df['close'], length=20)
        sma_50 = ta.sma(df['close'], length=50)
        plt.plot(recent['date'], sma_20[-60:], label='SMA 20', color='yellow', alpha=0.8)
        plt.plot(recent['date'], sma_50[-60:], label='SMA 50', color='orange', alpha=0.8)

        # Simple Support / Resistance from last 60 candles
        support = recent['low'].min()
        resistance = recent['high'].max()
        plt.axhline(support, color='green', linestyle='--', alpha=0.7, label='Support')
        plt.axhline(resistance, color='red', linestyle='--', alpha=0.7, label='Resistance')

        plt.title(f"{pair_name} - Last 60 Days", color='white', fontsize=16)
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
    except:
        return None

# ================= Signal (with SL/TP always) =================

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

    # SMA cross logic
    if last['sma_20'] > last['sma_50'] and prev['sma_20'] <= prev['sma_50']:
        reasons.append("🟢 Golden Cross")
        strength += 3
    elif last['sma_20'] < last['sma_50'] and prev['sma_20'] >= prev['sma_50']:
        reasons.append("🔴 Death Cross")
        strength -= 3

    # Live rate
    base, quote = PAIRS[pair_name]
    live_rate = get_live_rate(base, quote)
    if live_rate is None:
        live_rate = get_live_rate(quote, base)
        if live_rate is not None:
            live_rate = 1 / live_rate
    live_str = f"{live_rate:.5f}" if live_rate else "N/A"

    # ATR & risk
    atr = last['atr'] if pd.notna(last['atr']) else 0.001
    risk_amount = user_balance * (max_risk_percent / 100)
    position_size = risk_amount / (atr * 10000) if atr > 0 else 0.01

    sl = tp = "N/A"
    if live_rate:
        if strength > 0:
            sl = f"{live_rate - atr:.5f}"
            tp = f"{live_rate + (reward_risk_ratio * atr):.5f}"
        elif strength < 0:
            sl = f"{live_rate + atr:.5f}"
            tp = f"{live_rate - (reward_risk_ratio * atr):.5f}"
        else:
            # HOLD ke case me bhi neutral SL/TP (assume buy side)
            sl = f"{live_rate - atr:.5f}"
            tp = f"{live_rate + (reward_risk_ratio * atr):.5f}"

    risk_text = (
        f"

**Risk Management**
"
        f"• Balance: ${user_balance:,.0f}
"
        f"• Risk %: {max_risk_percent}%
"
        f"• Lots: {position_size:.2f}
"
        f"• Stop-Loss: {sl}
"
        f"• Take-Profit: {tp}
"
        f"• R:R = {reward_risk_ratio}:1"
    )

    if strength >= 3:
        signal = (
            f"**STRONG BUY** 📈
"
            + "
".join(reasons)
            + f"

Live Rate: {live_str}"
            + risk_text
        )
    elif strength <= -3:
        signal = (
            f"**STRONG SELL** 📉
"
            + "
".join(reasons)
            + f"

Live Rate: {live_str}"
            + risk_text
        )
    else:
        signal = (
            f"**HOLD** ⚖️
"
            f"Strength: {strength}
"
            f"Live Rate: {live_str}"
            + risk_text
            + "

No strong signal."
        )

    return signal, strength

# ================= Commands =================

async def set_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_balance, max_risk_percent
    args = context.args

    if len(args) == 2:
        try:
            user_balance = float(args[0])
            max_risk_percent = float(args[1])
            await update.message.reply_text(
                f"✅ Updated!
Balance: ${user_balance:,.0f}
Risk: {max_risk_percent}%"
            )
        except:
            await update.message.reply_text("❌ Wrong format. Use: /setrisk 10000 1")
    else:
        await update.message.reply_text(
            "Usage: /setrisk balance risk_percent
Example: /setrisk 10000 1"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("💱 Live Rates", callback_data="live_menu"),
            InlineKeyboardButton("📊 Chart + Signal", callback_data="chart_menu"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 **Forex Bot Live & Working!**

"
        "Chart + Signal & Risk Management ready!",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

# ================= Button Handler =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Menu selection
    if data.endswith("_menu"):
        keyboard = []
        for name in PAIRS.keys():
            keyboard.append(
                [InlineKeyboardButton(name, callback_data=f"{data[:-5]}_{name}")]
            )
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select Pair:", reply_markup=reply_markup)
        return

    # Back to main
    if data == "main":
        keyboard = [
            [
                InlineKeyboardButton("💱 Live Rates", callback_data="live_menu"),
                InlineKeyboardButton("📊 Chart + Signal", callback_data="chart_menu"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Main Menu", reply_markup=reply_markup)
        return

    action = data.split("_")[0]
    pair_name = data.split("_", 1)[1]
    base, quote = PAIRS[pair_name]

    # Live rate
    if action == "live":
        rate = get_live_rate(base, quote)
        if rate is None:
            rate = get_live_rate(quote, base)
            if rate is not None:
                rate = 1 / rate
        rate_str = f"{rate:.5f}" if rate else "Error"
        msg = f"**{pair_name} Live Rate**

{rate_str}"
        await query.edit_message_text(msg, parse_mode="Markdown")
        return

    # Chart + Signal
    await query.edit_message_text("Generating chart & signal...")
    df = get_historical_data(base, quote)
    signal_text, _ = generate_signal(df, pair_name)
    chart = generate_chart(df, pair_name)

    if chart:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=chart,
            caption=f"**{pair_name}**

{signal_text}",
            parse_mode="Markdown",
        )
        await query.delete_message()
    else:
        await query.edit_message_text(
            f"**{pair_name}**

{signal_text}

Chart not available",
            parse_mode="Markdown",
        )

# ================= Auto Alert =================

async def auto_alert(context: ContextTypes.DEFAULT_TYPE):
    for pair_name in PAIRS:
        base, quote = PAIRS[pair_name]
        df = get_historical_data(base, quote)
        if df.empty:
            continue

        text, strength = generate_signal(df, pair_name)
        if abs(strength) >= 3:
            chart = generate_chart(df, pair_name)
            caption = f"🔔 **STRONG ALERT**

{text}"

            if chart:
                await context.bot.send_photo(
                    YOUR_CHAT_ID, chart, caption=caption, parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    YOUR_CHAT_ID, text=caption, parse_mode="Markdown"
                )

# ================= MAIN =================

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setrisk", set_risk))
    app.add_handler(CallbackQueryHandler(button_handler))

    # 30 min auto alerts
    app.job_queue.run_repeating(auto_alert, interval=1800, first=30)

    print("Forex Bot Running Successfully!")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())

