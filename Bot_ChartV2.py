import os
import requests
import mplfinance as mpf
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
YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID"))

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
        # Index ko datetime bana ke set karna (mplfinance requirement)
        data = df.copy()
        data = data[-60:]  # last 60 candles
        data = data[['date', 'open', 'high', 'low', 'close']].set_index('date')

        # Simple Support / Resistance from last 60 candles
        support = data['Low'].min() if 'Low' in data.columns else data['low'].min()
        resistance = data['High'].max() if 'High' in data.columns else data['high'].max()

        # Columns ko mplfinance ke standard naam par rename karo
        data.columns = ['Open', 'High', 'Low', 'Close']

        # Figure + Axes create karo
        fig, ax = plt.subplots(figsize=(12, 7))
        plt.style.use('dark_background')

        # Candlestick plot
        mpf.plot(
            data,
            type='candle',
            ax=ax,
            style='charles',
            show_nontrading=False
        )

        # Support / Resistance lines overlay
        ax.axhline(support, color='green', linestyle='--', alpha=0.7, label=f'Support: {support:.5f}')
        ax.axhline(resistance, color='red', linestyle='--', alpha=0.7, label=f'Resistance: {resistance:.5f}')

        # Title & labels
        ax.set_title(f"{pair_name} - Last 60 Candles", color='white', fontsize=16)
        ax.set_xlabel('Date', color='white')
        ax.set_ylabel('Price', color='white')

        ax.legend()
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='black')
        buf.seek(0)
        plt.close(fig)

        return buf
    except Exception as e:
        print("Chart error:", e)
        return None

# ================= Signal (with SL/TP always) =================

def generate_signal(df, pair_name):
    # Data check
    if df is None or df.empty or len(df) < 60:
        return f"{pair_name}: Data not enough for analysis."

    # Last candle / basic values
    last = df.iloc[-1]
    close_price = last['close']
    open_price = last['open']
    high_price = last['high']
    low_price = last['low']

    # Example indicators (agar tum indicators already calculate kar rahe ho,
    # to unka code yahan use karo)
    # Yahan ek simple moving average ka example:
    df['ma20'] = df['close'].rolling(window=20).mean()
    ma20 = df['ma20'].iloc[-1]

    # Price action ke basis par dummy signal (tum apni logic rakh sakte ho)
    signal_type = "HOLD"
    if close_price > ma20 and close_price > open_price:
        signal_type = "STRONG BUY"
    elif close_price < ma20 and close_price < open_price:
        signal_type = "STRONG SELL"

    # SL / TP example (simple percentage logic, tum apni strategy use karo)
    if signal_type == "STRONG BUY":
        sl_price = low_price * 0.995
        tp_price = close_price * 1.010
    elif signal_type == "STRONG SELL":
        sl_price = high_price * 1.005
        tp_price = close_price * 0.990
    else:
        sl_price = None
        tp_price = None

    # Risk/Reward ratio example
    if sl_price and tp_price:
        risk = abs(close_price - sl_price)
        reward = abs(tp_price - close_price)
        rr_ratio = reward / risk if risk != 0 else 0
    else:
        rr_ratio = None

    # ---------- Support / Resistance calculation ----------
    recent = df[-60:]  # last 60 candles
    support = recent['low'].min()
    resistance = recent['high'].max()

    # ---------- Text blocks ready ----------
    # Risk text
    if sl_price and tp_price and rr_ratio is not None:
        risk_text = (
            f"\n\n**Risk Management**\n"
            f"• SL: {sl_price:.5f}\n"
            f"• TP: {tp_price:.5f}\n"
            f"• RR: {rr_ratio:.2f}"
        )
    else:
        risk_text = "\n\n**Risk Management**\n• No clear SL/TP suggested in HOLD condition."

    # Support / Resistance text
    sr_text = (
        f"\n\n**Support / Resistance**\n"
        f"• Support: {support:.5f}\n"
        f"• Resistance: {resistance:.5f}"
    )

    # Dono ko ek sath jodna
    full_extra = risk_text + sr_text

    # ---------- Final message per signal ----------
    if signal_type == "STRONG BUY":
        message = (
            f"📈 {pair_name} - STRONG BUY\n"
            f"• Price: {close_price:.5f}\n"
            f"• Above MA20: {ma20:.5f}\n"
            f"• Candle: Bullish\n"
            f"{full_extra}"
        )
    elif signal_type == "STRONG SELL":
        message = (
            f"📉 {pair_name} - STRONG SELL\n"
            f"• Price: {close_price:.5f}\n"
            f"• Below MA20: {ma20:.5f}\n"
            f"• Candle: Bearish\n"
            f"{full_extra}"
        )
    else:
        message = (
            f"⚖ {pair_name} - HOLD\n"
            f"• Price: {close_price:.5f}\n"
            f"• Near MA20: {ma20:.5f}\n"
            f"• Market in range.\n"
            f"{full_extra}"
        )

    return message

# ================= Commands =================

async def set_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_balance, max_risk_percent
    args = context.args

    if len(args) == 2:
        try:
            user_balance = float(args[0])
            max_risk_percent = float(args[1])
            await update.message.reply_text(
                f"✅ Updated!\nBalance: ${user_balance:,.0f}\nRisk: {max_risk_percent}%"
            )
        except:
            await update.message.reply_text("❌ Wrong format. Use: /setrisk 10000 1")
    else:
        await update.message.reply_text(
            "Usage: /setrisk balance risk_percent\nExample: /setrisk 10000 1"
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
        "🤖 **Forex Bot Live & Working!**\n\n"
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
        msg = f"**{pair_name} Live Rate**\n\n{rate_str}"
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
            caption=f"**{pair_name}**\n\n{signal_text}",
            parse_mode="Markdown",
        )
        await query.delete_message()
    else:
        await query.edit_message_text(
            f"**{pair_name}**\n\n{signal_text}\n\nChart not available",
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
            caption = f"🔔 **STRONG ALERT**\n\n{text}"

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

