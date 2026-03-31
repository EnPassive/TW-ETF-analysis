import yfinance as yf
import pandas as pd
import json
from datetime import datetime, timedelta, timezone

# 1. 標的清單
STOCKS_DIVIDEND = ['0056.TW', '00878.TW', '00919.TW', '00918.TW']
STOCKS_MARKET = ['0050.TW']
STOCKS_STRATEGY = ['00993A.TW', '00981A.TW', '00982A.TW', '009816.TW', '00988A.TW']
ALL_STOCKS = STOCKS_DIVIDEND + STOCKS_MARKET + STOCKS_STRATEGY

def get_taipei_now():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")

def get_market_regime():
    try:
        twii = yf.Ticker("^TWII").history(period="6mo")
        if twii.empty: return "unknown"
        twii['MA20'] = twii['Close'].rolling(window=20).mean()
        twii['MA60'] = twii['Close'].rolling(window=60).mean()
        latest = twii.iloc[-1]
        if latest['Close'] > latest['MA60'] and latest['Close'] > latest['MA20']:
            return "bull"
        elif latest['Close'] < latest['MA60']:
            return "bear"
        else:
            return "consolidation"
    except:
        return "unknown"

# --- 強化版：配息抓取函數 ---
def get_trailing_12m_dividend(ticker_obj):
    try:
        # 強制呼叫 action，有時候這能喚醒 yfinance 的緩存
        actions = ticker_obj.actions
        divs = ticker_obj.dividends
        
        if divs is None or divs.empty: 
            return 0.0
            
        # 將 divs 的 index 統一轉換格式，避免時區比對錯誤
        divs.index = pd.to_datetime(divs.index, utc=True)
        
        # 設定一年前的 UTC 時間
        one_year_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
        
        # 篩選過去一年的配息並加總
        last_year_divs = divs[divs.index > one_year_ago]
        total_div = float(last_year_divs.sum())
        
        return total_div
    except Exception as e:
        print(f"配息抓取錯誤: {e}")
        return 0.0

def get_disciplined_advice(symbol, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div):
    is_dividend_etf = (symbol + '.TW') in STOCKS_DIVIDEND
    yield_rate = (trailing_div / current_price * 100) if (trailing_div > 0) else 0.0
    
    buys, sells, advice, status = [], [], "", "neutral"

    # --- 修正：空頭市場時，也要保留殖利率顯示 ---
    if market_regime == "bear":
        ex_buy = current_price * 0.94
        advice = "🔴 大盤空頭，嚴禁一般加碼，僅限極小量避險佈局"
        status = "warning"
        buys = [round(ex_buy, 2), round(ex_buy - atr, 2)]
        sells = [round(ma20, 2), round(period_high*0.9, 2)]
        
        # 即使空頭，確保過濾掉不合理的買賣點
        buys = sorted(list(set([round(b, 2) for b in buys if b < current_price])), reverse=True)
        sells = sorted(list(set([round(s, 2) for s in sells if s > current_price])))
        if not buys: buys = [round(current_price * 0.95, 2)]
        if not sells: sells = [round(current_price * 1.05, 2)]
        
        return advice, status, buys, sells, yield_rate

    # --- 風控第二層：買賣邏輯 ---
    if is_dividend_etf and trailing_div > 0:
        cheap_val = trailing_div / 0.08      
        fair_val = trailing_div / 0.065     
        expensive_val = trailing_div / 0.05  

        if yield_rate >= 8.0:
            advice, status = f"🟢 殖利率達 {yield_rate:.1f}% (超值價)，大盤安全，建議分批建倉", "safe"
            buys = [min(current_price * 0.98, cheap_val), current_price - atr]
            sells = [max(current_price * 1.08, fair_val), expensive_val]
        elif yield_rate <= 5.5 or rsi > 70:
            advice, status = f"🔴 殖利率僅 {yield_rate:.1f}% 或短線過熱，建議減碼或觀望", "warning"
            buys, sells = [fair_val, cheap_val], [current_price * 1.02, current_price + atr]
        else:
            advice, status = f"🟡 殖利率 {yield_rate:.1f}% (合理區)，耐心等待更低網格", "neutral"
            buys, sells = [min(current_price * 0.97, fair_val), cheap_val], [max(current_price * 1.1, expensive_val)]
    else:
        drop_from_high = ((period_high - current_price) / period_high) * 100
        if rsi < 40 or drop_from_high > 10:
            advice, status = f"🟢 價格回檔達 {drop_from_high:.1f}%，大盤安全，建議縮小部位承接", "safe"
            buys = [current_price, current_price - atr*1.2]
            sells = [current_price * 1.1, period_high]
        elif rsi > 75:
            advice, status = "🔴 RSI 嚴重過熱 (>75)，嚴禁追高，建議部分停利", "warning"
            buys = [ma20 * 0.95, ma20 * 0.9]
            sells = [current_price, current_price + atr]
        else:
            advice, status = "🟡 價格於均線附近震盪，小量低掛或觀望", "neutral"
            buys = [min(current_price * 0.98, ma20), current_price - atr*1.5]
            sells = [max(current_price * 1.1, period_high)]

    if market_regime == "consolidation" and status == "safe":
        advice = advice.replace("建議分批建倉", "建議資金減半建倉").replace("建議縮小部位承接", "建議資金減半承接")
        status = "neutral"

    # 最終濾網
    buys = sorted(list(set([round(b, 2) for b in buys if b < current_price])), reverse=True)
    sells = sorted(list(set([round(s, 2) for s in sells if s > current_price])))
    
    if not buys: buys = [round(current_price * 0.96, 2)]
    if not sells: sells = [round(current_price * 1.08, 2)]

    return advice, status, buys, sells, yield_rate

def main():
    results = {}
    market_regime = get_market_regime()
    now_str = get_taipei_now()
    market_text = {"bull": "🟢 多頭市場 (適合佈局)", "bear": "🔴 空頭市場 (防禦優先)", "consolidation": "🟡 盤整震盪 (縮小部位)"}.get(market_regime, "未知")

    for symbol in ALL_STOCKS:
        try:
            ticker = yf.Ticker(symbol)
            
            # 確保獲取完整的歷史數據，這有助於緩存配息資料
            df = ticker.history(period="1y")
            if df.empty: continue
            
            current_price = getattr(ticker.fast_info, 'last_price', None)
            if current_price is None or current_price == 0:
                current_price = float(df['Close'].iloc[-1])
            
            trailing_div = get_trailing_12m_dividend(ticker)
            
            # 計算技術指標只看近半年
            df_6mo = df.tail(120)
            close, high_val = df_6mo['Close'], df_6mo['High'].max()
            ma20 = float(close.rolling(20).mean().iloc[-1])
            atr = float(close.diff().abs().rolling(14).mean().iloc[-1]) or (current_price * 0.02)
            
            delta = close.diff()
            gain, loss = delta.where(delta > 0, 0).rolling(14).mean(), -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = float(100 - (100 / (1 + (gain / (loss + 1e-9)).iloc[-1])))
            
            advice, status, buys, sells, y_rate = get_disciplined_advice(
                symbol.replace('.TW',''), current_price, rsi, ma20, high_val, atr, market_regime, trailing_div
            )
            
            results[symbol.replace('.TW','')] = {
                'name': symbol.replace('.TW',''),
                'category': "dividend" if symbol in STOCKS_DIVIDEND else ("market" if symbol in STOCKS_MARKET else "strategy"),
                'price': round(current_price, 2),
                'rsi': round(rsi, 1), 'ma20': round(ma20, 2), 'high': round(high_val, 2),
                'trailing_div': round(trailing_div, 2), 'yield_rate': round(y_rate, 1) if y_rate > 0 else "-",
                'advice': advice, 'status_type': status, 'buy_grids': buys, 'sell_grids': sells,
                'market_regime': market_text, 'updated_at': now_str
            }
            print(f"[{symbol}] 分析完成 | 配息: {trailing_div}")
        except Exception as e:
            print(f"[{symbol}] 處理失敗: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
