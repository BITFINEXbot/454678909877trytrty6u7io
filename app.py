
import os
import io
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests

ASSETS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CHF": "CHFUSD=X",
    "NZD/USD": "NZDUSD=X",
}

FETCH_INTERVAL_SECONDS = 60
CONFIRM_BARS = 2
MIN_ATR = 0.0001
COOLDOWN_SECONDS = 120

# Вградените Pushover ключове
PUSHOVER_USER = "u7eqmqc9ksxfpv4tca4xghe3qii8w9"
PUSHOVER_TOKEN = "a4ebyf72knqhz4b6obzh8idyrcdr1u"

latest_signal = {}
signal_history = []
last_signal_time = {}

app = Flask(__name__, static_folder="static", template_folder="templates")

def atr(series_high, series_low, series_close, n=14):
    prev_close = series_close.shift(1)
    tr1 = series_high - series_low
    tr2 = (series_high - prev_close).abs()
    tr3 = (series_low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]

def compute_signal(symbol):
    try:
        data = yf.download(symbol, interval="1m", period="2d", progress=False)
    except Exception:
        return None, None
    if data is None or len(data) < 30:
        return None, data

    data["EMA5"] = data["Close"].ewm(span=5, adjust=False).mean()
    data["EMA20"] = data["Close"].ewm(span=20, adjust=False).mean()
    data["EMA5_diff"] = data["EMA5"].diff()
    data["EMA20_diff"] = data["EMA20"].diff()

    recent = data.tail(CONFIRM_BARS)
    buy_confirm = (recent["EMA5"] > recent["EMA20"]).all()
    sell_confirm = (recent["EMA5"] < recent["EMA20"]).all()

    try:
        recent_atr = atr(data["High"], data["Low"], data["Close"], n=14)
    except Exception:
        recent_atr = 0
    if recent_atr < MIN_ATR:
        return None, data

    ema5_slope = data["EMA5_diff"].iloc[-1]
    price = data["Close"].iloc[-1]
    ema20_now = data["EMA20"].iloc[-1]
    price_gap = abs(price - ema20_now) / (ema20_now if ema20_now != 0 else 1)

    if buy_confirm and ema5_slope > 0 and price > ema20_now and price_gap > 0.0002:
        return "BUY", data
    elif sell_confirm and ema5_slope < 0 and price < ema20_now and price_gap > 0.0002:
        return "SELL", data
    else:
        return None, data

def maybe_send_pushover(title, message):
    try:
        r = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "title": title,
            "message": message,
            "priority": 0
        }, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def polling_loop():
    while True:
        for asset_name, symbol in ASSETS.items():
            sig, data = compute_signal(symbol)
            now = datetime.utcnow()
            last_time = last_signal_time.get(asset_name)
            if sig and (last_time is None or (now - last_time).total_seconds() > COOLDOWN_SECONDS):
                prev = latest_signal.get(asset_name)
                if prev != sig:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    entry = {"time": ts, "asset": asset_name, "signal": sig}
                    signal_history.insert(0, entry)
                    latest_signal[asset_name] = sig
                    last_signal_time[asset_name] = now
                    maybe_send_pushover(f"{asset_name} - {sig}", f"Сигнал: {sig} за {asset_name} @ {ts}")
        time.sleep(FETCH_INTERVAL_SECONDS)

@app.route("/")
def index():
    selected = request.args.get("asset", list(ASSETS.keys())[0])
    snapshot = {k: latest_signal.get(k, "---") for k in ASSETS.keys()}
    history = signal_history[:50]
    return render_template("index.html", assets=list(ASSETS.keys()), selected=selected, snapshot=snapshot, history=history)

@app.route("/chart.png")
def chart_png():
    asset = request.args.get("asset", list(ASSETS.keys())[0])
    symbol = ASSETS.get(asset)
    sig, data = compute_signal(symbol)
    if data is None:
        fig, ax = plt.subplots(figsize=(8,4))
        ax.text(0.5,0.5,"No data", ha="center")
    else:
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data.index, data["Close"], label="Close")
        ax.plot(data.index, data["EMA5"], label="EMA5")
        ax.plot(data.index, data["EMA20"], label="EMA20")
        ax.set_title(f"{asset} - {symbol}")
        ax.legend()
        ax.grid(True)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/send_test_push")
def send_test():
    ok = maybe_send_pushover("Test", "Тестово уведомление от бота")
    return ("OK" if ok else "FAILED"), (200 if ok else 500)

@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    t = threading.Thread(target=polling_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
