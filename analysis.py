import yfinance as yf
import pandas as pd
import json
from datetime import datetime, timedelta, timezone

# 1. 標的清單
STOCKS_DIVIDEND = ['0056.TW', '00878.TW', '00919.TW', '00918.TW']
STOCKS_MARKET = ['0050.TW']
STOCKS_STRATEGY = ['00993A.TW', '00981A.TW', '00982A.TW', '009816.TW', '00988A.TW']
ALL_STOCKS = STOCKS_DIVIDEND + STOCKS_MARKET + STOCKS_STRATEGY

# 2. 備援配息資料庫 (僅在 YF 完全抓不到資料時使用)
DIVIDEND_FALLBACK = {
    '0050': 6.00,
    '00981A': 0.82,
    '00982A': 0.76
}

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
        if latest['Close'] > latest['MA60'] and latest['Close'] > latest['MA20']: return "bull"
        elif latest['Close'] < latest['MA60']: return "bear"
        else: return "consolidation"
    except: return "unknown"

# --- 吸收 ChatGPT 精華：三級防護網配息系統 ---
def get_dividend_smart(ticker_obj, short_name):
    """
    回傳: (年化配息金額, 資料來源標籤, 穩定度因子)
    """
    try:
        divs = ticker_obj.dividends
        if divs is None or divs.empty:
            if short_name in DIVIDEND_FALLBACK:
                return float(DIVIDEND_FALLBACK[short_name]), "手動備援", 1.0
            return 0.0, "無資料", 0.0

        divs.index = pd.to_datetime(divs.index, utc=True)
        one_year_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
        last_year_divs = divs[divs.index > one_year_ago]

        # Level 1: 過去一年有穩定配息 (大於等於3次，代表是季配或月配且資料完整)
        if len(last_year_divs) >= 3:
            # 計算穩定度 (標準差越小，穩定度越高，越接近 1)
            mean_div = last_year_divs.mean()
            std_div = last_year_divs.std()
            stability = 1.0
            if mean_div > 0 and not pd.isna(std_div):
                stability = max(0.5, 1 - (std_div / (mean_div + 1e-6))) # 最低給 0.5 權重
            return float(last_year_divs.sum()), "近四季真實", round(stability, 2)

        # Level 2: 新上市或資料不全，用最近一次推估年化 (假設為季配，乘以4)
        recent = divs.tail(1)
        if not recent.empty and len(last_year_divs) < 3:
            last_div = float(recent.iloc[-1])
            annualized = last_div * 4
            return annualized, "單季推估年化", 0.7 # 推估的穩定度打 7 折

        # Level 3: 退回手動備援
        if short_name in DIVIDEND_FALLBACK:
            return float(DIVIDEND_FALLBACK[short_name]), "手動備援", 1.0

        return 0.0, "無資料", 0.0
    except Exception as e:
        print(f"配息抓取錯誤: {e}")
        return 0.0, "錯誤", 0.0

def get_disciplined_advice(symbol, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div, stability):
    is_dividend_etf = (symbol + '.TW') in STOCKS_DIVIDEND
    yield_rate = (trailing_div / current_price * 100) if (trailing_div > 0) else 0.0
    
    buys, sells, advice, status = [], [], "", "neutral"

    if market_regime == "bear":
        ex_buy = current_price * 0.94
        advice, status = "🔴 大盤空頭，嚴禁一般加碼，僅限極小量避險佈局", "warning"
        buys, sells = [round(ex_buy, 2), round(ex_buy - atr, 2)], [round(ma20, 2), round(period_high*0.9, 2)]
        buys = sorted(list(set([round(b, 2) for b in buys if b < current_price])), reverse=True)
        sells = sorted(list(set([round(s, 2) for s in sells if s > current_price])))
        if not buys: buys = [round(current_price * 0.95, 2)]
        if not sells: sells = [round(current_price * 1.05, 2)]
        return advice, status, buys, sells, yield_rate

    if is_dividend_etf and trailing_div > 0:
        # 吸收 ChatGPT 精華：加入穩定度因子調整真實殖利率
        adj_yield_rate = yield_rate * stability
        
        cheap_val, fair_val, expensive_val = trailing_div / 0.08, trailing_div / 0.065, trailing_div / 0.05
        
        if adj_yield_rate >= 7.0: # 經過穩定度打折後還有 7% 以上，代表非常優質
            advice, status = f"🟢 經風險調整殖利率達 {adj_yield_rate:.1f}% (超值)，建議分批建倉", "safe"
            buys, sells = [min(current_price * 0.98, cheap_val), current_price - atr], [max(current_price * 1.08, fair_val), expensive_val]
        elif adj_yield_rate <= 5.0 or rsi > 70:
            advice, status = f"🔴 調整後殖利率僅 {adj_yield_rate:.1f}% 或過熱，建議減碼或觀望", "warning"
            buys, sells = [fair_val, cheap_val], [current_price * 1.02, current_price + atr]
        else:
            advice, status = f"🟡 調整後殖利率 {adj_yield_rate:.1f}% (合理區)，耐心等待低點", "neutral"
            buys, sells = [min(current_price * 0.97, fair_val), cheap_val], [max(current_price * 1.1, expensive_val)]
    else:
        drop_from_high = ((period_high - current_price) / period_high) * 100
        if rsi < 40 or drop_from_high > 10:
            advice, status = f"🟢 價格回檔達 {drop_from_high:.1f}%，大盤安全，建議縮小部位承接", "safe"
            buys, sells = [current_price, current_price - atr*1.2], [current_price * 1.1, period_high]
        elif rsi > 75:
            advice, status = "🔴 RSI 嚴重過熱 (>75)，嚴禁追高，建議部分停利", "warning"
            buys, sells = [ma20 * 0.95, ma20 * 0.9], [current_price, current_price + atr]
        else:
            advice, status = "🟡 價格於均線附近震盪，小量低掛或觀望", "neutral"
            buys, sells = [min(current_price * 0.98, ma20), current_price - atr*1.5], [max(current_price * 1.1, period_high)]

    if market_regime == "consolidation" and status == "safe":
        advice = advice.replace("建議分批建倉", "建議資金減半建倉").replace("建議縮小部位承接", "建議資金減半承接")
        status = "neutral"

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
            df = ticker.history(period="1y")
            if df.empty: continue
            
            current_price = getattr(ticker.fast_info, 'last_price', None)
            if current_price is None or current_price == 0:
                current_price = float(df['Close'].iloc[-1])
            
            short_name = symbol.replace('.TW', '')
            
            # 使用全新的智能配息系統
            trailing_div, div_source, stability = get_dividend_smart(ticker, short_name)
            
            df_6mo = df.tail(120)
            close, high_val = df_6mo['Close'], df_6mo['High'].max()
            ma20 = float(close.rolling(20).mean().iloc[-1])
            atr = float(close.diff().abs().rolling(14).mean().iloc[-1]) or (current_price * 0.02)
            
            delta = close.diff()
            gain, loss = delta.where(delta > 0, 0).rolling(14).mean(), -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = float(100 - (100 / (1 + (gain / (loss + 1e-9)).iloc[-1])))
            
            # 傳入 stability 因子
            advice, status, buys, sells, y_rate = get_disciplined_advice(
                short_name, current_price, rsi, ma20, high_val, atr, market_regime, trailing_div, stability
            )
            
            category = "dividend" if symbol in STOCKS_DIVIDEND else ("market" if symbol in STOCKS_MARKET else "strategy")
            
            # 保持輸出格式與前端 index.html 完全相容，並加入隱藏的除錯資訊
            results[short_name] = {
                'name': short_name, 'category': category, 'price': round(current_price, 2),
                'rsi': round(rsi, 1), 'ma20': round(ma20, 2), 'high': round(high_val, 2),
                'trailing_div': round(trailing_div, 2), 'yield_rate': round(y_rate, 1) if y_rate > 0 else "-",
                'advice': advice, 'status_type': status, 'buy_grids': buys, 'sell_grids': sells,
                'market_regime': market_text, 'updated_at': now_str,
                # 以下為內部除錯用，前端網頁不會報錯
                '_div_source': div_source, '_stability': stability
            }
            print(f"[{short_name}] 分析完成 | 配息: {trailing_div} ({div_source})")
        except Exception as e:
            print(f"[{symbol}] 處理失敗: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
