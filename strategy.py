import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time, timezone, timedelta
import json
import os
import requests

# ========== INDIAN TIMEZONE ==========
IST = timezone(timedelta(hours=5, minutes=30))

def ist_now():
    return datetime.now(IST)

# ========== LOAD CONFIG ==========
def load_config():
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
        return config.get("trade_mode", "BOTH")
    except:
        return "BOTH"

TRADE_MODE = load_config()

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

# ========== TELEGRAM SETTINGS ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
    """Telegram पर मैसेज भेजें, अगर टोकन और चैट आईडी सेट हैं।"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")

# ========== STATE MANAGEMENT ==========
STATE_FILE = "state.json"
DEFAULT_STATE = {'trade_taken': False, 'position': None, 'entry_price': 0}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    state = json.loads(content)
                    for key in DEFAULT_STATE:
                        if key not in state:
                            state[key] = DEFAULT_STATE[key]
                    print(f"📁 Loaded state: {state}")
                    return state
        except:
            pass
    print("📁 Using default state")
    return DEFAULT_STATE.copy()

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
        print(f"💾 Saved state: {state}")
    except Exception as e:
        print(f"⚠️ Could not save state: {e}")

# ========== DATA FETCH ==========
def fetch_latest_data():
    try:
        data = {}
        bnf = yf.download(BNF_SYMBOL, period="1d", interval="1m", progress=False)
        if len(bnf) < 2:
            return None
        bnf = bnf[~bnf.index.duplicated(keep='last')]
        data['bnf'] = bnf
        
        for sym in SYMBOLS:
            stock = yf.download(sym, period="1d", interval="1m", progress=False)
            if len(stock) < 2:
                return None
            stock = stock[~stock.index.duplicated(keep='last')]
            data[sym] = stock
        return data
    except Exception as e:
        print(f"Data fetch error: {e}")
        return None

# ========== SAFE SCALAR EXTRACTION ==========
def safe_iloc(df, col, idx):
    try:
        val = df[col].iloc[idx]
        if isinstance(val, pd.Series):
            val = val.item()
        return val
    except:
        return None

# ========== CALCULATION ==========
def calculate_contribution(data):
    bnf_curr = safe_iloc(data['bnf'], 'Close', -1)
    bnf_prev = safe_iloc(data['bnf'], 'Close', -2)
    bnf_open = safe_iloc(data['bnf'], 'Open', -2)
    bnf_high = safe_iloc(data['bnf'], 'High', -2)
    bnf_low  = safe_iloc(data['bnf'], 'Low', -2)
    
    if any(v is None for v in [bnf_curr, bnf_prev, bnf_open, bnf_high, bnf_low]):
        print("❌ Missing BNF data")
        return None
    
    impacts = []
    for i, sym in enumerate(SYMBOLS):
        stock_curr = safe_iloc(data[sym], 'Close', -1)
        stock_prev = safe_iloc(data[sym], 'Close', -2)
        
        if stock_curr is None or stock_prev is None:
            impacts.append(0.0)
            continue
        
        if stock_prev != 0:
            pct_change = (stock_curr - stock_prev) / stock_prev * 100
        else:
            pct_change = 0.0
        
        impact = bnf_curr * (WEIGHTS[i] / 100.0) * (pct_change / 100.0)
        impacts.append(impact)
    
    pull_sum = sum(max(imp, 0) for imp in impacts)
    drag_sum_abs = abs(sum(min(imp, 0) for imp in impacts))
    bnf_move = abs(bnf_curr - bnf_prev)
    bnf_up = bnf_prev > bnf_open
    bnf_down = bnf_prev < bnf_open
    bnf_mid = (bnf_high + bnf_low) / 2.0
    
    body = abs(bnf_prev - bnf_open)
    upper_wick = bnf_high - max(bnf_prev, bnf_open)
    lower_wick = min(bnf_prev, bnf_open) - bnf_low
    total_range = bnf_high - bnf_low
    
    is_doji = total_range > 0 and body < total_range * 0.1
    is_hammer = lower_wick > body * 2 and upper_wick < body * 0.5
    is_shooting = upper_wick > body * 2 and lower_wick < body * 0.5
    
    return {
        'pull_sum': pull_sum, 'drag_sum_abs': drag_sum_abs,
        'bnf_move': bnf_move, 'bnf_up': bnf_up, 'bnf_down': bnf_down,
        'bnf_mid': bnf_mid, 'bnf_high': bnf_high, 'bnf_low': bnf_low,
        'bnf_curr': bnf_curr,
        'ce_pattern': is_hammer or is_doji,
        'pe_pattern': is_shooting or is_doji
    }

def check_signals(calc, current_price):
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

# ========== MAIN ==========
if __name__ == "__main__":
    now = ist_now()
    print(f"🕐 Run time (IST): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔄 Trade Mode: {TRADE_MODE}")
    
    if not (time(9, 16) <= now.time() <= time(15, 19)):
        print("⏰ Outside market hours")
        print(f"🔑 TELEGRAM_TOKEN: {'SET' if TELEGRAM_TOKEN else 'NOT SET'}")
print(f"📱 TELEGRAM_CHAT_ID: {'SET' if TELEGRAM_CHAT_ID else 'NOT SET'}")

if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    print("📤 Attempting to send Telegram message...")
    send_telegram("✅ GitHub Actions Telegram test successful!")
    print("📤 Test message sent (check Telegram)")
else:
    print("❌ Telegram credentials not found. Check GitHub Secrets.")
        exit()
    
    state = load_state()
    
    if now.hour == 9 and now.minute == 15:
        state = DEFAULT_STATE.copy()
        save_state(state)
        print("🔄 New day, flags reset")
        exit()
    
    if now.time() >= time(15, 19) and state.get('position'):
        msg = f"🔴 EOD EXIT {state['position']} at {state.get('entry_price', 'N/A')}"
        print(msg)
        send_telegram(msg)
        state['position'] = None
        state['entry_price'] = 0
        save_state(state)
        exit()
    
    data = fetch_latest_data()
    if data is None:
        print("❌ Data fetch failed")
        exit()
    
    calc = calculate_contribution(data)
    if calc is None:
        print("❌ Calculation failed")
        exit()
    
    current_price = calc['bnf_curr']
    
    print(f"📊 BNF: {current_price:.2f} | Pull: {calc['pull_sum']:.2f} | Drag: {calc['drag_sum_abs']:.2f}")
    
    # Exit check
    if state.get('position') and state.get('entry_price', 0) > 0:
        move = current_price - state['entry_price']
        
        if state['position'] == 'CE':
            if move >= TARGET_PTS:
                msg = f"🎯 CE TARGET HIT! Profit: {move:.0f} pts, Entry: {state['entry_price']:.2f}, Exit: {current_price:.2f}"
                print(msg)
                send_telegram(msg)
                state['position'] = None
                state['entry_price'] = 0
                save_state(state)
                exit()
            elif move <= -STOP_PTS:
                msg = f"🛑 CE STOP LOSS! Loss: {move:.0f} pts, Entry: {state['entry_price']:.2f}, Exit: {current_price:.2f}"
                print(msg)
                send_telegram(msg)
                state['position'] = None
                state['entry_price'] = 0
                save_state(state)
                exit()
        
        elif state['position'] == 'PE':
            if move <= -TARGET_PTS:
                msg = f"🎯 PE TARGET HIT! Profit: {-move:.0f} pts, Entry: {state['entry_price']:.2f}, Exit: {current_price:.2f}"
                print(msg)
                send_telegram(msg)
                state['position'] = None
                state['entry_price'] = 0
                save_state(state)
                exit()
            elif move >= STOP_PTS:
                msg = f"🛑 PE STOP LOSS! Loss: {move:.0f} pts, Entry: {state['entry_price']:.2f}, Exit: {current_price:.2f}"
                print(msg)
                send_telegram(msg)
                state['position'] = None
                state['entry_price'] = 0
                save_state(state)
                exit()
    
    # Entry check
    if not state.get('trade_taken', False) and not state.get('position'):
        ce_signal, pe_signal = check_signals(calc, current_price)
        
        if ce_signal and TRADE_MODE in ["BOTH", "BUY_ONLY"]:
            msg = f"🟢 BUY CE at {current_price:.2f}"
            print(msg)
            send_telegram(msg)
            state['position'] = 'CE'
            state['entry_price'] = current_price
            state['trade_taken'] = True
            save_state(state)
        
        elif pe_signal and TRADE_MODE in ["BOTH", "SELL_ONLY"]:
            msg = f"🔴 BUY PE at {current_price:.2f}"
            print(msg)
            send_telegram(msg)
            state['position'] = 'PE'
            state['entry_price'] = current_price
            state['trade_taken'] = True
            save_state(state)
            # ========== TEST TELEGRAM ==========
print("📤 Sending test message to Telegram...")
send_telegram("✅ GitHub Actions Telegram test successful!")
print("📤 Test message sent (check Telegram)")

            
