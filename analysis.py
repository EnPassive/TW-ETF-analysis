import yfinance as yf
import pandas as pd
import json
from datetime import datetime

# 1. 標的清單分三類
STOCKS_DIVIDEND = ['0056.TW', '00878.TW', '00919.TW', '00918.TW', '00939.TW', '00940.TW']
STOCKS_MARKET = ['0050.TW', '006208.TW']
STOCKS_STRATEGY = ['00981A.TW', '00982A.TW', '009816.TW', '00988A.TW']
ALL_STOCKS = STOCKS_DIVIDEND + STOCKS_MARKET + STOCKS_STRATEGY

# 2. 獲取大盤狀態 (市場濾網)
def get_market_regime():
    try:
        twii = yf.Ticker("^TWII").history(period="6mo")
        if twii.empty: return "unknown"
        
        twii['MA20'] = twii['Close'].rolling(window=20).mean()
        twii['MA60'] = twii['Close'].rolling(window=60).mean()
        latest = twii.iloc[-1]
        
        if latest['Close'] > latest['MA60'] and latest['Close'] > latest['MA20']:
            return "bull"  # 多頭：站上月季線
        elif latest['Close'] < latest['MA60']:
            return "bear"  # 空頭：跌破季線
        else:
            return "consolidation" # 盤整
    except:
        return "unknown"

# 3. 動態抓取近四季配息總和
def get_trailing_12m_dividend(ticker_obj):
    try:
        divs = ticker_obj.dividends
        if divs.empty: return 0.0
        last_year_divs = divs[divs.index > (pd.Timestamp.now(tz=divs.index.tz) - pd.DateOffset(years=1))]
        return float(last_year_divs.sum())
    except:
        return 0.0

# 4. 核心決策引擎
def get_disciplined_advice(symbol, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div):
    is_dividend_etf = (symbol + '.TW') in STOCKS_DIVIDEND
    yield_rate = 0.0
    
    # --- 風控第一層：空頭市場強制防禦 ---
    if market_regime == "bear":
        extreme_buy = period_high * 0.85
        if current_price <= extreme_buy:
            return "🟡 空頭極端超跌，僅限動用小資金摸底", "warning", [extreme_buy, extreme_buy*0.95], [ma20], 0.0
        else:
            return "🔴 大盤空頭確認，嚴禁攤平加碼，滿手現金觀望", "warning", [], [ma20, period_high*0.9], 0.0

    # --- 風控第二層：多頭/盤整市場的買賣邏輯 ---
    buys = []
    sells = []
    advice = ""
    status = "neutral"

    if is_dividend_etf and trailing_div > 0:
        yield_rate = (trailing_div / current_price) * 100
        cheap = trailing_div / 0.07   
        fair = trailing_div / 0.055   
        expensive = trailing_div / 0.045 

        if yield_rate >= 7.0 and rsi < 60:
            advice = f"🟢 殖利率達 {yield_rate:.1f}% (超值價)，大盤安全，可正常建倉"
            status = "safe"
            buys = [cheap, cheap - atr]
        elif yield_rate <= 4.5 or rsi > 70:
            advice = f"🔴 殖利率僅 {yield_rate:.1f}% 或短線過熱，禁止買進，建議減碼"
            status = "warning"
            sells = [current_price * 1.05, expensive]
        else:
            advice = f"🟡 殖利率 {yield_rate:.1f}% (合理區)，耐心等待更低網格"
            status = "neutral"
            buys = [fair, cheap]

    else:
        drop_from_high = ((period_high - current_price) / period_high) * 100
        
        if rsi < 40 or drop_from_high > 8:
            advice = f"🟢 價格回檔達 {drop_from_high:.1f}%，大盤安全，可分批承接"
            status = "safe"
            buys = [current_price, current_price - atr*1.5]
        elif rsi > 75:
            advice = "🔴 RSI 嚴重過熱 (>75)，嚴禁追高，準備停利"
            status = "warning"
            sells = [current_price, current_price + atr*2]
        else:
            advice = "🟡 價格於均線附近震盪，小量低掛或觀望"
            status = "neutral"
            buys = [ma20 * 0.98, period_high * 0.9]

    # --- 風控微調：盤整盤的資金控管 ---
    if market_regime == "consolidation" and status == "safe":
        advice = advice.replace("可正常建倉", "建議資金減半建倉").replace("可分批承接", "建議縮小部位承接")
        status = "neutral"

    if not sells: sells = [period_high, period_high * 1.05]
    if not buys: buys = [current_price * 0.9]

    return advice, status, buys, sells, yield_rate

def main():
    results = {}
    market_regime = get_market_regime()
    print(f"目前大盤狀態: {market_regime}")

    market_text = "🟢 多頭市場 (適合佈局)" if market_regime == "bull" else ("🔴 空頭市場 (防禦優先)" if market_regime == "bear" else "🟡 盤整震盪 (縮小部位)")

    for symbol in ALL_STOCKS:
        try:
            short_name = symbol.replace('.TW', '')
            
            # 定義該 ETF 屬於哪一個分類
            if symbol in STOCKS_DIVIDEND:
                category = "dividend"
            elif symbol in STOCKS_MARKET:
                category = "market"
            else:
                category = "strategy"

            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
