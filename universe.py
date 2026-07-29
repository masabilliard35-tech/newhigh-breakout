"""東証の対象銘柄リストを yfinance の screener で取得する。"""
import yfinance as yf
from yfinance import EquityQuery

SECTORS = ["Financial Services", "Healthcare", "Consumer Defensive", "Industrials",
           "Real Estate", "Energy", "Basic Materials", "Utilities",
           "Consumer Cyclical", "Communication Services", "Technology"]

SEC_JA = {"Financial Services": "金融", "Healthcare": "ヘルスケア",
          "Consumer Defensive": "生活必需品", "Industrials": "資本財",
          "Real Estate": "不動産", "Energy": "エネルギー",
          "Basic Materials": "素材", "Utilities": "公益",
          "Consumer Cyclical": "一般消費財", "Communication Services": "通信",
          "Technology": "テクノロジー"}

MIN_VOLUME = 10000


def fetch_universe():
    """{symbol: {"name","sector","cap"}} を返す（東証・出来高1万株/日以上）。"""
    seen = {}
    for sec in SECTORS:
        offset = 0
        while offset < 1000:
            try:
                r = yf.screen(EquityQuery("and", [
                    EquityQuery("eq", ["region", "jp"]),
                    EquityQuery("eq", ["sector", sec]),
                    EquityQuery("gte", ["avgdailyvol3m", MIN_VOLUME])]),
                    offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
            except Exception:
                break
            page = r.get("quotes", [])
            if not page:
                break
            for q in page:
                seen[q["symbol"]] = {"name": q.get("shortName") or q["symbol"],
                                     "sector": SEC_JA.get(sec, sec),
                                     "cap": q.get("marketCap")}
            offset += len(page)
            if offset >= r.get("total", 0):
                break
    return seen
