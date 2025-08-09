import os
import tkinter as tk
from tkinter import ttk
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import datetime
import threading
import requests
import time
from dotenv import load_dotenv

# Load .env file
load_dotenv()
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
    print("WARNING: PushOver keys not set in .env")

def send_pushover_message(message, title=None):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("PushOver disabled:", message)
        return
    try:
        data = {"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "message": message}
        if title:
            data["title"] = title
        requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
    except Exception as e:
        print("PushOver error:", e)

BG_COLOR = "#121212"
BUY_COLOR = "#00ff00"
SELL_COLOR = "#ff4444"
TEXT_COLOR = "#ffffff"

ASSETS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "NZD/USD": "NZDUSD=X",
    "AUD/JPY": "AUDJPY=X",
    "USD/CHF": "USDCHF=X",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "WTI Oil": "CL=F",
    "Brent Oil": "BZ=F",
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "DAX": "^GDAXI",
}

COOLDOWN_SECONDS = 5 * 60
VOLATILITY_THRESHOLD = 0.0005

last_notified_ts = {asset: 0 for asset in ASSETS}
signal_history = []

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_signal(symbol):
    try:
        data_1m = yf.download(symbol, interval="1m", period="1d", progress=False, threads=False)
        data_5m = yf.download(symbol, interval="5m", period="5d", progress=False, threads=False)
    except Exception as e:
        print("yfinance error:", e)
        return None, None

    if len(data_1m) < 20 or len(data_5m) < 20:
        return None, data_1m

    data_1m["EMA5"] = data_1m["Close"].ewm(span=5, adjust=False).mean()
    data_1m["EMA20"] = data_1m["Close"].ewm(span=20, adjust=False).mean()
    data_1m["RSI"] = rsi(data_1m["Close"])

    data_5m["EMA5"] = data_5m["Close"].ewm(span=5, adjust=False).mean()
    data_5m["EMA20"] = data_5m["Close"].ewm(span=20, adjust=False).mean()

    close_now = float(data_1m["Close"].iloc[-1])
    close_prev = float(data_1m["Close"].iloc[-2])
    vol = abs(close_now - close_prev) / close_prev if close_prev != 0 else 0
    if vol < VOLATILITY_THRESHOLD:
        return None, data_1m

    avg_vol = data_1m["Volume"].tail(20).mean()
    if float(data_1m["Volume"].iloc[-1]) < avg_vol:
        return None, data_1m

    if data_1m["RSI"].iloc[-1] > 70 or data_1m["RSI"].iloc[-1] < 30:
        return None, data_1m

    ema5_1m, ema20_1m = data_1m["EMA5"].iloc[-1], data_1m["EMA20"].iloc[-1]
    ema5_5m, ema20_5m = data_5m["EMA5"].iloc[-1], data_5m["EMA20"].iloc[-1]

    if ema5_1m > ema20_1m and close_now > close_prev and ema5_5m > ema20_5m:
        return "BUY", data_1m
    elif ema5_1m < ema20_1m and close_now < close_prev and ema5_5m < ema20_5m:
        return "SELL", data_1m
    return None, data_1m

def handle_signal(asset, signal, data):
    now_ts = time.time()
    if now_ts - last_notified_ts[asset] < COOLDOWN_SECONDS:
        return
    pre = f"{asset} - {signal} incoming in 20 seconds (1m trade)"
    send_pushover_message(pre, title=f"{asset} PREPARE")
    time.sleep(20)
    now_msg = f"{asset} - {signal} NOW (enter 1m trade)"
    send_pushover_message(now_msg, title=f"{asset} SIGNAL")
    last_notified_ts[asset] = time.time()
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    signal_history.insert(0, f"{ts} - {asset} - {signal} - 1m")
    while len(signal_history) > 500:
        signal_history.pop()
    try:
        history_box.delete(0, tk.END)
        for h in signal_history[:100]:
            history_box.insert(tk.END, h)
    except:
        pass

def monitor_all():
    while True:
        start = time.time()
        for asset, symbol in ASSETS.items():
            signal, data = get_signal(symbol)
            if signal:
                threading.Thread(target=handle_signal, args=(asset, signal, data), daemon=True).start()
            time.sleep(0.9)
        time.sleep(max(1, 60 - (time.time() - start)))

root = tk.Tk()
root.title("Binary Options Bot")
root.configure(bg=BG_COLOR)
root.geometry("900x600")

style = ttk.Style()
style.configure("TButton", background=BG_COLOR, foreground=TEXT_COLOR)

current_asset = list(ASSETS.keys())[0]

btn_frame = tk.Frame(root, bg=BG_COLOR)
btn_frame.pack(pady=5)
for asset in ASSETS:
    ttk.Button(btn_frame, text=asset, command=lambda a=asset: change_asset(a)).pack(side=tk.LEFT, padx=5)

asset_label = tk.Label(root, text=f"Asset: {current_asset}", font=("Arial", 14), fg=TEXT_COLOR, bg=BG_COLOR)
asset_label.pack()

signal_label = tk.Label(root, text="---", font=("Arial", 32, "bold"), bg=BG_COLOR)
signal_label.pack(pady=10)

timer_label = tk.Label(root, text="", font=("Arial", 14), fg=TEXT_COLOR, bg=BG_COLOR)
timer_label.pack()

fig, ax = plt.subplots(figsize=(7, 4))
fig.patch.set_facecolor(BG_COLOR)
canvas = FigureCanvasTkAgg(fig, master=root)
canvas.get_tk_widget().pack()

tk.Label(root, text="Signal history:", font=("Arial", 12), fg=TEXT_COLOR, bg=BG_COLOR).pack()
history_box = tk.Listbox(root, height=8, width=80, bg=BG_COLOR, fg=TEXT_COLOR)
history_box.pack(pady=5)

def change_asset(asset):
    global current_asset
    current_asset = asset
    asset_label.config(text=f"Asset: {asset}")

def update_chart():
    symbol = ASSETS.get(current_asset)
    signal, data = get_signal(symbol)
    if signal == "BUY":
        signal_label.config(text="BUY", fg=BUY_COLOR)
    elif signal == "SELL":
        signal_label.config(text="SELL", fg=SELL_COLOR)
    else:
        signal_label.config(text="---", fg=TEXT_COLOR)
    try:
        ax.clear()
        if data is not None:
            ax.plot(data.index, data['Close'], label='Price')
            ax.plot(data.index, data['EMA5'], label='EMA5')
            ax.plot(data.index, data['EMA20'], label='EMA20')
        ax.set_facecolor(BG_COLOR)
        ax.legend(facecolor=BG_COLOR, labelcolor=TEXT_COLOR)
        canvas.draw()
    except Exception as e:
        print("Chart error:", e)
    now = datetime.datetime.now()
    seconds_left = 60 - now.second
    timer_label.config(text=f"Time to next candle: {seconds_left} sec.")
    root.after(1000, update_chart)

threading.Thread(target=monitor_all, daemon=True).start()
threading.Thread(target=update_chart, daemon=True).start()
root.mainloop()

