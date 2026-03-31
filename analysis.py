import yfinance as yf
import pandas as pd
import json
from datetime import datetime, timedelta, timezone

# 1. 標的清單 (依分類排序)
STOCKS_DIVIDEND = ['0056.TW', '00878.TW', '00919.TW', '00918.TW']
STOCKS_MARKET = ['0050.TW']
STOCKS_STRATEGY = ['00993A.TW', '00981A.TW', '00982A.TW', '009816.TW', '00988A.TW']
ALL_STOCKS = STOCKS_DIVIDEND + STOCKS_MARKET + STOCKS_STRATEGY

def get_taipei_now():
    """獲取台北時間 (UTC+8) 字串"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")

def get_market_regime():
    """判斷大盤多空趨勢 (依據加權指數 ^TWII)"""
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

def get_trailing_12m_dividend(ticker_obj):
    """獲取近四季真實配息總和 (修正時區比較 Bug)"""
    try:
        divs = ticker_obj.dividends
        if divs.empty: return 0.0
        # 取得台北時間一年前的標記，並移除時區資訊以便與 divs.index 比較
        tz = timezone(timedelta(hours=8))
        one_year_ago = (pd.Timestamp.now(tz=tz) - pd.DateOffset(years=1)).tz_localize(None)
        last_year_divs = divs[divs.index > one_year_ago]
        return float(last_year_divs.sum())
    except:
        return 0.0

def get_disciplined_advice(symbol, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div):
    """資產配置與紀律執行邏輯"""
    is_dividend_etf = (symbol + '.TW') in STOCKS_DIVIDEND
    yield_rate = (trailing_div / current_price * 100) if (trailing_div > 0) else 0
    
    # --- 風控第一層：空頭市場強制防禦 ---
    if market_regime == "bear":
        ex_buy = current_price * 0.94
        return "🔴 大盤空頭，嚴禁一般加碼，僅限極小量避險佈局", "warning", [round(ex_buy, 2), round(ex_buy - atr, 2)], [round(ma20, 2)], yield_rate

    buys, sells, advice, status = [], [], "", "neutral"
    
    # --- 風控第二層：高股息與市值/策略型分流 ---
    if is_dividend_etf and trailing_div > 0:
        # 2026 最新門檻：8% (便宜) / 6.5% (合理) / 5% (昂貴)
        cheap_val = trailing_div / 0.08
        fair_val = trailing_div / 0.065
        expensive_val = trailing_div / 0.05
        
        if yield_rate >= 8.0:
            advice, status = f"🟢 殖利率達 {yield_rate:.1f}% (超值價)，建議分批建倉", "safe"
            buys = [current_price * 0.98, current_price - atr]
            sells = [max(current_price * 1.08, fair_val)]
        elif yield_rate <= 5.5 or rsi > 70:
            advice, status = f"🔴 殖利率僅 {yield_rate:.1f}% 或過熱，建議減碼觀望", "warning"
            buys, sells = [fair_val, cheap_val], [current_price * 1.02, current_price + atr]
        else:
            advice, status = f"🟡 殖利率 {yield_rate:.1f}% (合理區)，建議分批低掛", "neutral"
            buys, sells = [min(current_price * 0.97, fair_val), cheap_val], [expensive_val]
    else:
        # 市值型/策略型 (如 0050, 00981A)
        drop = (period_high - current_price) / period_high * 100
        if rsi < 38 or drop > 10:
            advice, status = f"🟢 價格回檔 {drop:.1f}%，大盤安全，建議分批承接", "safe"
            buys, sells = [current_price * 0.98, current_price - atr*1.2], [period_high]
        elif rsi > 72:
            advice, status = "🔴 RSI 短線過熱，建議部分停利減碼", "warning"
            buys, sells = [ma20], [current_price * 1.05]
        else:
            advice, status = "🟡 價格區間震盪，建議維持網格紀律", "neutral"
            buys, sells = [current_price * 0.96, ma20 * 0.95], [period_high * 1.05]

    # --- 最終防呆：確保買價 < 現價 < 賣價，並去重排序 ---
    buys = sorted(list(set([round(b, 2) for b in buys if b < current_price])), reverse=True)
    sells = sorted(list(set([round(s, 2) for s in sells if s > current_price])))
    
    if not buys: buys = [round(current_price * 0.95, 2)]
    if not sells: sells = [round(current_price * 1.1, 2)]
    
    return advice, status, buys, sells, yield_rate

def main():
    results = {}
    market_regime = get_market_regime()
    now_str = get_taipei_now()
    market_text = {"bull": "🟢 多頭市場 (適合佈局)", "bear": "🔴 空頭市場 (防禦優先)", "consolidation": "🟡 盤整震盪 (縮小部位)"}.get(market_regime, "未知")

    for symbol in ALL_STOCKS:
        try:
            ticker = yf.Ticker(symbol)
            
            # 安全抓取最新成交價 (優化備援邏輯)
            current_price = getattr(ticker.fast_info, 'last_price', None)
            
            df = ticker.history(period="6mo")
            if df.empty: continue
            
            # 若 fast_info 失效，退回使用歷史數據末尾
            if current_price is None or current_price == 0:
                current_price = float(df['Close'].iloc[-1])
            
            # 獲取自動配息數據
            trailing_div = get_trailing_12m_dividend(ticker)

            close, high_val = df['Close'], df['High'].max()
            ma20 = float(close.rolling(20).mean().iloc[-1])
            atr = float(close.diff().abs().rolling(14).mean().iloc[-1]) or (current_price * 0.02)
            
            # RSI 計算 (加入 1e-9 防止除以 0)
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
            print(f"[{symbol}] 分析完成: {current_price}")
        except Exception as e:
            print(f"[{symbol}] 處理失敗: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
