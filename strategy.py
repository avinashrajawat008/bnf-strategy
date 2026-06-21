import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
import time as tm
import schedule
import requests

# ========== CONFIGURATION ==========
SYMBOLS = [
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "SBIN.NS", "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS",
    "IDFCFIRSTB.NS", "AUBANK.NS"
]
WEIGHTS = [29, 24, 10, 9, 9, 5, 4, 3, 3, 2]
BNF_SYMBOL = "^NSEBANK"

TARGET_PTS = 100
STOP_PTS = 70
TRADE_MODE = "BOTH"

# Global variables
trade_taken = False
position = None
entry_price = 0
entry_time_str = ""

# ========== DATA FETCH ==========
def fetch_latest_data():
    """Fetch latest 1-minute data for all symbols"""
    try:
        data = {}
        bnf = yf.download(BNF_SYMBOL, period="3m", interval="1m", progress=False)
        if len(bnf) < 2:
            return None
        data['bnf'] = bnf
        
        for sym in SYMBOLS:
            stock = yf.download(sym, period="3m", interval="1m", progress=False)
            if len(stock) < 2:
                return None
            data[sym] = stock
        
        return data
    except Exception as e:
        print(f"Data fetch error: {e}")
        return None

# ========== CALCULATION ==========
def calculate_contribution(data):
    """Calculate pull_sum and drag_sum_abs"""
    bnf_curr = data['bnf']['Close'].iloc[-1]
    bnf_prev = data['bnf']['Close'].iloc[-2]
    
    bnf_open = data['bnf']['Open'].iloc[-2]
    bnf_high = data['bnf']['High'].iloc[-2]
    bnf_low = data['bnf']['Low'].iloc[-2]
    
    impacts = []
    for i, sym in enumerate(SYMBOLS):
        stock_curr = data[sym]['Close'].iloc[-1]
        stock_prev = data[sym]['Close'].iloc[-2]
        
        if stock_prev != 0:
            pct_change = (stock_curr - stock_prev) / stock_prev * 100
        else:
            pct_change = 0
        
        impact = bnf_curr * (WEIGHTS[i]/100) * (pct_change/100)
        impacts.append(impact)
    
    pull_sum = sum(max(imp, 0) for imp in impacts)
    drag_sum_abs = abs(sum(min(imp, 0) for imp in impacts))
    
    bnf_move = abs(bnf_curr - bnf_prev)
    bnf_up = bnf_prev > bnf_open
    bnf_down = bnf_prev < bnf_open
    bnf_mid = (bnf_high + bnf_low) / 2
    
    body = abs(bnf_prev - bnf_open)
    upper_wick = bnf_high - max(bnf_prev, bnf_open)
    lower_wick = min(bnf_prev, bnf_open) - bnf_low
    total_range = bnf_high - bnf_low
    
    is_doji = total_range > 0 and body < total_range * 0.1
    is_hammer = lower_wick > body * 2 and upper_wick < body * 0.5
    is_shooting = upper_wick > body * 2 and lower_wick < body * 0.5
    
    ce_pattern = is_hammer or is_doji
    pe_pattern = is_shooting or is_doji
    
    return {
        'pull_sum': pull_sum,
        'drag_sum_abs': drag_sum_abs,
        'bnf_move': bnf_move,
        'bnf_up': bnf_up,
        'bnf_down': bnf_down,
        'bnf_mid': bnf_mid,
        'bnf_high': bnf_high,
        'bnf_low': bnf_low,
        'bnf_curr': bnf_curr,
        'ce_pattern': ce_pattern,
        'pe_pattern': pe_pattern
    }

# ========== ENTRY/EXIT LOGIC ==========
def check_signals(calc, current_price):
    """Check entry conditions"""
    ce_signal = False
    pe_signal = False
    
    ce_cond1 = calc['drag_sum_abs'] > calc['pull_sum'] and calc['bnf_down'] and (calc['bnf_move'] > calc['drag_sum_abs'])
    ce_cond2 = calc['pull_sum'] > calc['drag_sum_abs'] and calc['ce_pattern']
    ce_cond3 = calc['pull_sum'] > calc['drag_sum_abs'] and calc['bnf_up'] and (calc['bnf_move'] > calc['pull_sum'])
    
    if ce_cond1 and current_price > calc['bnf_mid']:
        ce_signal = True
    elif (ce_cond2 or ce_cond3) and current_price > calc['bnf_high']:
        ce_signal = True
    
    pe_cond1 = calc['pull_sum'] > calc['drag_sum_abs'] and calc['bnf_up'] and (calc['bnf_move'] > calc['pull_sum'])
    pe_cond2 = calc['drag_sum_abs'] > calc['pull_sum'] and calc['pe_pattern']
    pe_cond3 = calc['drag_sum_abs'] > calc['pull_sum'] and calc['bnf_down'] and (calc['bnf_move'] > calc['drag_sum_abs'])
    
    if pe_cond1 and current_price < calc['bnf_mid']:
        pe_signal = True
    elif (pe_cond2 or pe_cond3) and current_price < calc['bnf_low']:
        pe_signal = True
    
    return ce_signal, pe_signal

# ========== TELEGRAM NOTIFICATION ==========
def send_telegram(message):
    """Send notification via Telegram (optional)"""
    try:
        # Replace with your bot token and chat ID
        BOT_TOKEN = "YOUR_BOT_TOKEN"
        CHAT_ID = "YOUR_CHAT_ID"
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": message}
        requests.post(url, data=data)
    except:
        pass

# ========== MAIN LOGIC ==========
def run_strategy():
    global trade_taken, position, entry_price, entry_time_str
    
    now = datetime.now()
    
    # Reset at 9:15 AM
    if now.hour == 9 and now.minute == 15 and now.second < 10:
        trade_taken = False
        position = None
        entry_price = 0
        print("🔄 New day started, flags reset")
    
    # Check market hours (9:16 AM to 3:19 PM)
    if not (time(9, 16) <= now.time() <= time(15, 19)):
        return
    
    # After 3:19 PM, exit all positions
    if now.time() >= time(15, 19) and position:
        print(f"🔴 EOD EXIT {position}")
        send_telegram(f"🔴 EOD EXIT {position}")
        position = None
        entry_price = 0
        return
    
    # Fetch data
    data = fetch_latest_data()
    if data is None:
        print("❌ Data fetch failed, retrying...")
        return
    
    # Calculate
    calc = calculate_contribution(data)
    current_price = calc['bnf_curr']
    current_time = now.strftime("%H:%M:%S")
    
    print(f"📊 {current_time} | BNF: {current_price:.2f} | Pull: {calc['pull_sum']:.2f} | Drag: {calc['drag_sum_abs']:.2f}")
    
    # Exit check
    if position and entry_price > 0:
        move = current_price - entry_price
        
        if position == 'CE':
            if move >= TARGET_PTS:
                print(f"🎯 CE TARGET HIT! Profit: {move:.2f} pts")
                send_telegram(f"🎯 CE TARGET HIT! Profit: {move:.2f} pts, Entry: {entry_time_str}")
                position = None
                entry_price = 0
                return
            elif move <= -STOP_PTS:
                print(f"🛑 CE STOP LOSS! Loss: {move:.2f} pts")
                send_telegram(f"🛑 CE STOP LOSS! Loss: {move:.2f} pts, Entry: {entry_time_str}")
                position = None
                entry_price = 0
                return
        
        elif position == 'PE':
            if move <= -TARGET_PTS:
                print(f"🎯 PE TARGET HIT! Profit: {-move:.2f} pts")
                send_telegram(f"🎯 PE TARGET HIT! Profit: {-move:.2f} pts, Entry: {entry_time_str}")
                position = None
                entry_price = 0
                return
            elif move >= STOP_PTS:
                print(f"🛑 PE STOP LOSS! Loss: {move:.2f} pts")
                send_telegram(f"🛑 PE STOP LOSS! Loss: {move:.2f} pts, Entry: {entry_time_str}")
                position = None
                entry_price = 0
                return
    
    # Entry check
    if not trade_taken and not position:
        ce_signal, pe_signal = check_signals(calc, current_price)
        
        if ce_signal and TRADE_MODE in ["BOTH", "BUY_ONLY"]:
            print(f"🟢 BUY CE at {current_price:.2f}")
            send_telegram(f"🟢 BUY CE at {current_price:.2f}")
            position = 'CE'
            entry_price = current_price
            trade_taken = True
            entry_time_str = current_time
        
        elif pe_signal and TRADE_MODE in ["BOTH", "SELL_ONLY"]:
            print(f"🔴 BUY PE at {current_price:.2f}")
            send_telegram(f"🔴 BUY PE at {current_price:.2f}")
            position = 'PE'
            entry_price = current_price
            trade_taken = True
            entry_time_str = current_time

# ========== SCHEDULER ==========
print("🚀 Bank Nifty Contribution Strategy Started!")
print(f"📋 Config: Target={TARGET_PTS}pts, SL={STOP_PTS}pts, Mode={TRADE_MODE}")
print("⏰ Waiting for market hours (9:16 AM - 3:19 PM)...")

# Run every 30 seconds
schedule.every(30).seconds.do(run_strategy)

# Also run immediately
run_strategy()

while True:
    schedule.run_pending()
    tm.sleep(1)
