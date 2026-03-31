import yfinance as yf
import pandas as pd
import json
from datetime import datetime

# 1. 標的清單
STOCKS_DIVIDEND = ['0056.TW', '00878.TW', '00919.TW', '00918.TW', '00939.TW', '00940.TW']
STOCKS_MARKET = ['0050.TW', '006208.TW']
STOCKS_STRATEGY = ['00981A.TW', '00982A.TW', '009816.TW', '00988A.TW']
ALL_STOCKS = STOCKS_DIVIDEND + STOCKS_MARKET + STOCKS_STRATEGY

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

def get_trailing_12m_dividend(ticker_obj):
    try:
        divs = ticker_obj.dividends
        if divs.empty: return 0.0
        last_year_divs = divs[divs.index > (pd.Timestamp.now(tz=divs.index.tz) - pd.DateOffset(years=1))]
        return float(last_year_divs.sum())
    except:
        return 0.0

# --- 核心決策引擎 (修正版) ---
def get_disciplined_advice(symbol, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div):
    is_dividend_etf = (symbol + '.TW') in STOCKS_DIVIDEND
    yield_rate = 0.0
    
    # A. 處理空頭市場
    if market_regime == "bear":
        extreme_buy = min(current_price * 0.95, period_high * 0.82)
        return "🔴 大盤空頭確認，嚴禁一般加碼，僅限極小量避險佈局", "warning", [extreme_buy, extreme_buy - atr], [ma20, period_high*0.9], 0.0

    buys = []
    sells = []
    advice = ""
    status = "neutral"

    # B. 高股息邏輯 (殖利率修正版)
    if is_dividend_etf and trailing_div > 0:
        yield_rate = (trailing_div / current_price) * 100
        # 修正：買點計算以 現價 與 殖利率估價 的較小值為準
        cheap_by_yield = trailing_div / 0.08    # 8% 殖利率
        fair_by_yield = trailing_div / 0.065    # 6.5% 殖利率
        expensive_by_yield = trailing_div / 0.05 # 5% 殖利率

        if yield_rate >= 7.5: # 殖利率非常誘人
            advice = f"🟢 殖利率達 {yield_rate:.1f}% (超值價)，大盤安全，建議分批建倉"
            status = "safe"
            # 買點不能高於現價
            buys = [min(current_price, cheap_by_yield) * 0.98, current_price - atr]
            sells = [max(current_price * 1.08, fair_by_yield), expensive_by_yield]
        elif yield_rate <= 5.0 or rsi > 70:
            advice = f"🔴 殖利率僅 {yield_rate:.1f}% 或短線過熱，建議減碼或觀望"
            status = "warning"
            buys = [fair_by_yield, cheap_by_yield]
            sells = [current_price * 1.02, current_price + atr]
        else:
            advice = f"🟡 殖利率 {yield_rate:.1f}% (合理區)，耐心等待更低網格"
            status = "neutral"
            buys = [min(current_price * 0.97, fair_by_yield), cheap_by_yield]
            sells = [max(current_price * 1.1, expensive_by_yield)]

    # C. 市值型/策略型邏輯
    else:
        drop_from_high = ((period_high - current_price) / period_high) * 100
        if rsi < 40 or drop_from_high > 10:
            advice = f"🟢 價格回檔達 {drop_from_high:.1f}%，大盤安全，建議縮小部位承接"
            status = "safe"
            buys = [current_price, current_price - atr*1.2]
            sells = [current_price * 1.1, period_high]
        elif rsi > 75:
            advice = "🔴 RSI 嚴重過熱 (>75)，嚴禁追高，建議部分停利"
            status = "warning"
            buys = [ma20 * 0.95, ma20 * 0.9]
            sells = [current_price, current_price + atr]
        else:
            advice = "🟡 價格於均線附近震盪，小量低掛或觀望"
            status = "neutral"
            buys = [min(current_price * 0.98, ma20), current_price - atr*1.5]
            sells = [max(current_price * 1.1, period_high)]

    # 風控微調：盤整盤
    if market_regime == "consolidation" and status == "safe":
        advice = advice.replace("建議分批建倉", "建議資金減半建倉").replace("建議縮小部位承接", "建議資金減半承接")
        status = "neutral"

    # 最終防呆：確保買價 < 現價 < 賣價
    buys = [round(b, 2) for b in buys if b < current_price]
    sells = [round(s, 2) for s in sells if s > current_price]
    
    # 如果列表空了，補上基本的
    if not buys: buys = [round(current_price * 0.96, 2)]
    if not sells: sells = [round(current_price * 1.08, 2)]

    return advice, status, buys, sells, yield_rate

def main():
    results = {}
    market_regime = get_market_regime()
    market_text = "🟢 多頭市場 (適合佈局)" if market_regime == "bull" else ("🔴 空頭市場 (防禦優先)" if market_regime == "bear" else "🟡 盤整震盪 (縮小部位)")

    for symbol in ALL_STOCKS:
        try:
            short_name = symbol.replace('.TW', '')
            category = "dividend" if symbol in STOCKS_DIVIDEND else ("market" if symbol in STOCKS_MARKET else "strategy")
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
            if df.empty: continue
            
            trailing_div = get_trailing_12m_dividend(ticker)
            close = df['Close']
            current_price = float(close.iloc[-1])
            period_high = float(df['High'].max())
            ma20 = float(close.rolling(20).mean().iloc[-1])
            atr = float(close.diff().abs().rolling(14).mean().iloc[-1])
            if pd.isna(atr): atr = current_price * 0.02
            
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = float(100 - (100 / (1 + (gain / (loss + 1e-9)).iloc[-1])))
            
            advice, status, buys, sells, yield_rate = get_disciplined_advice(
                short_name, current_price, rsi, ma20, period_high, atr, market_regime, trailing_div
            )
            
            results[short_name] = {
                'name': short_name, 'category': category, 'price': round(current_price, 2),
                'rsi': round(rsi, 1), 'ma20': round(ma20, 2), 'high': round(period_high, 2),
                'trailing_div': round(trailing_div, 2), 'yield_rate': round(yield_rate, 1) if yield_rate > 0 else "-",
                'advice': advice, 'status_type': status, 'buy_grids': buys, 'sell_grids': sells,
                'market_regime': market_text, 'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        except Exception as e:
            print(f"[{symbol}] 錯誤: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
