import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import requests
from alpha_vantage.forex import Forex
import pandas as pd
import pandas_ta as ta
import schedule
import time
import threading

# Your secrets
TELEGRAM_TOKEN = '8377055187:AAGinbhefXUOk9vj2miXAcfI1B-1_Hgr-cw'  # From BotFather
ALPHA_VANTAGE_KEY = 'DWR5U401WFQXY2CY'

# Forex API setup
forex = Forex(key=ALPHA_VANTAGE_KEY)

def get_forex_data(pair='EURUSD', interval='1min'):
    data, _ = forex.get_currency_exchange_intraday(pair, interval=interval, outputsize='compact')
    df = pd.DataFrame(data).T.astype(float)
    df.columns = ['open', 'high', 'low', 'close']
    return df

def generate_signal(df):
    df['sma_20'] = ta.sma(df['close'], length=20)
    df['sma_50'] = ta.sma(df['close'], length=50)
    df['rsi'] = ta.rsi(df['close'], length=14)
    if df['sma_20'].iloc[-1] > df['sma_50'].iloc[-1] and df['rsi'].iloc[-1] < 70:
        return "Buy Signal!"
    elif df['sma_20'].iloc[-1] < df['sma_50'].iloc[-1] and df['rsi'].iloc[-1] > 30:
        return "Sell Signal!"
    return "Hold"

# Telegram commands
def start(update, context):
    update.message.reply_text('Welcome to Forex Trading 24X7! Use /rates for current rates, /signal for advice.')

def rates(update, context):
    df = get_forex_data()
    latest = df.iloc[-1]
    msg = f"EUR/USD: Open {latest['open']}, High {latest['high']}, Low {latest['low']}, Close {latest['close']}"
    update.message.reply_text(msg)

def signal(update, context):
    df = get_forex_data()
    sig = generate_signal(df)
    update.message.reply_text(sig)

# Auto scheduler
def auto_signal(bot):
    df = get_forex_data()
    sig = generate_signal(df)
    # Send to a specific chat or group (replace with your chat_id)
    bot.send_message(chat_id='YOUR_CHAT_ID', text=f"Auto Signal: {sig}")

def scheduler_thread(updater):
    bot = updater.bot
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('rates', rates))
    dp.add_handler(CommandHandler('signal', signal))

    # Scheduler for auto
    schedule.every(30).minutes.do(auto_signal, bot=updater.bot)

    # Run scheduler in thread
    threading.Thread(target=scheduler_thread, args=(updater,)).start()

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
