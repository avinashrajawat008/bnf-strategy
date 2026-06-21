import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta

print("=" * 60)
print("📊 BANK NIFTY CONTRIBUTION STRATEGY - BACKTEST")
print("=" * 60)

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

# ========== DATE RANGE ==========
START_DATE = "2026-06-01"
END_DATE = "2026-06-20"

print(f"📅 Period: {START_DATE} to {END_DATE}")
print(f"🎯 Target: {TARGET_PTS} pts | 🛑 SL: {STOP_PTS} pts")
print("=" * 60)

# ========== FETCH HISTORICAL DATA ==========
print("📥 Fetching BNF data...")
bnf_data = yf.download(BNF_SYMBOL, start=START_DATE, end=END_DATE, interval="1m", progress=False)

print("📥 Fetching stock data...")
stock_data = {}
for sym in SYMBOLS:
    stock_data[sym] = yf.download(sym, start=START_DATE, end=END_DATE, interval="1m", progress=False)

print(f"✅ Data fetched: {len(bnf_data)} BNF candles")
print("=" * 60)

# ========== STRATEGY LOGIC ==========
trades = []
position = None
entry_price = 0
entry_time = None
trade_taken_today = False
last_date = None

# Iterate through each candle
for i in range(2, len(bnf_data)):
    try:
        now = bnf_data.index[i]
        current_date = now.date()
        
        # Reset daily flag
        if last_date != current_date:
            trade_taken_today = False
            last_date = current_date
        
        # Market hours filter
        if now.time() < time(9, 16) or now.time() > time(15, 19):
            continue
        
        # Get current and previous data
        bnf_curr = bnf_data['Close'].iloc[i]
        bnf_prev = bnf_data['Close'].iloc[i-1]
        bnf_open = bnf_data['Open'].iloc[i-1]
        bnf_high = bnf_data['High'].iloc[i-1]
        bnf_low = bnf_data['Low'].iloc[i-1]
        
        # Calculate impacts
        impacts = []
        for j, sym in enumerate(SYMBOLS):
            stock_curr = stock_data[sym]['Close'].iloc[i]
            stock_prev = stock_data[sym]['Close'].iloc[i-1]
            
            if stock_prev != 0:
                pct_change = (stock_curr - stock_prev) / stock_prev * 100
            else:
                pct_change = 0
            
            impact = bnf_curr * (WEIGHTS[j]/100) * (pct_change/100)
            impacts.append(impact)
        
        pull_sum = sum(max(imp, 0) for imp in impacts)
        drag_sum_abs = abs(sum(min(imp, 0) for imp in impacts))
        
        bnf_move = abs(bnf_curr - bnf_prev)
        bnf_up = bnf_prev > bnf_open
        bnf_down = bnf_prev < bnf_open
        bnf_mid = (bnf_high + bnf_low) / 2
        
        # Candlestick patterns
        body = abs(bnf_prev - bnf_open)
        upper_wick = bnf_high - max(bnf_prev, bnf_open)
        lower_wick = min(bnf_prev, bnf_open) - bnf_low
        total_range = bnf_high - bnf_low
        
        is_doji = total_range > 0 and body < total_range * 0.1
        is_hammer = lower_wick > body * 2 and upper_wick < body * 0.5
        is_shooting = upper_wick > body * 2 and lower_wick < body * 0.5
        
        ce_pattern = is_hammer or is_doji
        pe_pattern = is_shooting or is_doji
        
        # EXIT LOGIC
        if position and entry_price > 0:
            move = bnf_curr - entry_price
            exit_reason = None
            
            if position == 'CE':
                if move >= TARGET_PTS:
                    exit_reason = "TARGET"
                elif move <= -STOP_PTS:
                    exit_reason = "STOP LOSS"
            
            elif position == 'PE':
                if move <= -TARGET_PTS:
                    exit_reason = "TARGET"
                elif move >= STOP_PTS:
                    exit_reason = "STOP LOSS"
            
            # EOD Exit
            if now.time() >= time(15, 19):
                exit_reason = "EOD"
            
            if exit_reason:
                trades[-1]['exit_time'] = now
                trades[-1]['exit_price'] = bnf_curr
                trades[-1]['exit_reason'] = exit_reason
                trades[-1]['pnl'] = move if position == 'CE' else -move
                position = None
                entry_price = 0
        
        # ENTRY LOGIC
        if not trade_taken_today and not position:
            ce_signal = False
            pe_signal = False
            
            ce_cond1 = drag_sum_abs > pull_sum and bnf_down and (bnf_move > drag_sum_abs)
            ce_cond2 = pull_sum > drag_sum_abs and ce_pattern
            ce_cond3 = pull_sum > drag_sum_abs and bnf_up and (bnf_move > pull_sum)
            
            if ce_cond1 and bnf_curr > bnf_mid:
                ce_signal = True
            elif (ce_cond2 or ce_cond3) and bnf_curr > bnf_high:
                ce_signal = True
            
            pe_cond1 = pull_sum > drag_sum_abs and bnf_up and (bnf_move > pull_sum)
            pe_cond2 = drag_sum_abs > pull_sum and pe_pattern
            pe_cond3 = drag_sum_abs > pull_sum and bnf_down and (bnf_move > drag_sum_abs)
            
            if pe_cond1 and bnf_curr < bnf_mid:
                pe_signal = True
            elif (pe_cond2 or pe_cond3) and bnf_curr < bnf_low:
                pe_signal = True
            
            if ce_signal:
                position = 'CE'
                entry_price = bnf_curr
                entry_time = now
                trade_taken_today = True
                trades.append({
                    'entry_time': now,
                    'entry_price': bnf_curr,
                    'type': 'CE',
                    'exit_time': None,
                    'exit_price': None,
                    'exit_reason': None,
                    'pnl': None
                })
            
            elif pe_signal:
                position = 'PE'
                entry_price = bnf_curr
                entry_time = now
                trade_taken_today = True
                trades.append({
                    'entry_time': now,
                    'entry_price': bnf_curr,
                    'type': 'PE',
                    'exit_time': None,
                    'exit_price': None,
                    'exit_reason': None,
                    'pnl': None
                })
    
    except Exception as e:
        continue

# ========== RESULTS ==========
print("\n" + "=" * 60)
print("📊 BACKTEST RESULTS")
print("=" * 60)

completed_trades = [t for t in trades if t['exit_price'] is not None]

if len(completed_trades) > 0:
    total_pnl = sum(t['pnl'] for t in completed_trades)
    winning_trades = [t for t in completed_trades if t['pnl'] > 0]
    losing_trades = [t for t in completed_trades if t['pnl'] <= 0]
    win_rate = len(winning_trades) / len(completed_trades) * 100 if completed_trades else 0
    
    print(f"\n📈 Total Trades: {len(completed_trades)}")
    print(f"✅ Winning: {len(winning_trades)} | ❌ Losing: {len(losing_trades)}")
    print(f"🎯 Win Rate: {win_rate:.1f}%")
    print(f"💰 Total P&L: {total_pnl:.1f} pts")
    
    if winning_trades:
        avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades)
        print(f"📈 Avg Win: {avg_win:.1f} pts")
    if losing_trades:
        avg_loss = sum(t['pnl'] for t in losing_trades) / len(losing_trades)
        print(f"📉 Avg Loss: {avg_loss:.1f} pts")
    
    print(f"\n📋 TRADE LIST:")
    print("-" * 80)
    for i, t in enumerate(completed_trades, 1):
        print(f"{i:2d}. {t['type']} | Entry: {t['entry_time']} @ {t['entry_price']:.1f} | "
              f"Exit: {t['exit_time']} @ {t['exit_price']:.1f} | "
              f"P&L: {t['pnl']:+.1f} | {t['exit_reason']}")
else:
    print("\n❌ No trades found in this period")
