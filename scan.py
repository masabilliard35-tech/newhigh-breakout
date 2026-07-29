"""スクリーニングの実行本体。
必須条件: 52週高値更新 × 売上+10%(前年同期比) × 営業利益率20%(通期) × ROE10%

使い方:
  python scan.py --full   … 業種リスト取得＋全銘柄の業績取得（重い・週1想定）
  python scan.py          … 業績キャッシュを使い株価だけ最新化＋当日新高値を通知（毎日17:30想定）
出力: data/rows.json（画面用）, data/funda.json, data/margins.json, data/universe.json（キャッシュ）
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yfinance as yf

from universe import fetch_universe
from notify import send

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)
W52 = 252


def pc(x):
    return None if x is None else round(x * 100)


def opm_annual(sym):
    """通期の営業利益率(%) = 営業利益 ÷ 売上高。取れなければ None。"""
    try:
        df = yf.Ticker(sym).income_stmt
    except Exception:
        return None
    if df is None or df.empty or "Total Revenue" not in df.index or "Operating Income" not in df.index:
        return None
    rev = df.loc["Total Revenue"].dropna().sort_index(ascending=False)
    oi = df.loc["Operating Income"].dropna().sort_index(ascending=False)
    if not len(rev) or not len(oi):
        return None
    r = float(rev.iloc[0])
    return None if r <= 0 else round(float(oi.iloc[0]) / r * 100, 1)


def run_full():
    print("universe取得...")
    uni = fetch_universe()
    (DATA / "universe.json").write_text(json.dumps(uni, ensure_ascii=False), encoding="utf-8")
    syms = sorted(uni)
    print(f"  {len(syms)} 銘柄")

    print("業績(.info)取得...")
    funda = {}
    for i, s in enumerate(syms, 1):
        d = [None, None]
        try:
            info = yf.Ticker(s).info
            d = [pc(info.get("returnOnEquity")), pc(info.get("revenueGrowth"))]  # [ROE, 売上成長]
        except Exception:
            pass
        funda[s] = d
        if i % 200 == 0:
            print(f"  {i}/{len(syms)}")
        time.sleep(0.03)
    (DATA / "funda.json").write_text(json.dumps(funda), encoding="utf-8")

    cand = [s for s, v in funda.items()
            if v[0] is not None and v[0] >= 10 and v[1] is not None and v[1] >= 10]
    print(f"営業利益率取得（売上+ROE通過 {len(cand)} 銘柄）...")
    margins = {}
    for i, s in enumerate(cand, 1):
        margins[s] = opm_annual(s)
        if i % 100 == 0:
            print(f"  {i}/{len(cand)}")
        time.sleep(0.05)
    (DATA / "margins.json").write_text(json.dumps(margins), encoding="utf-8")
    print("full完了")


def qualified_symbols():
    funda = json.loads((DATA / "funda.json").read_text(encoding="utf-8"))
    margins = json.loads((DATA / "margins.json").read_text(encoding="utf-8"))
    out = []
    for s, v in funda.items():
        if v[0] is None or v[0] < 10 or v[1] is None or v[1] < 10:
            continue
        m = margins.get(s)
        if m is None or m < 20:
            continue
        out.append(s)
    return out, funda, margins


def run_daily():
    if not (DATA / "funda.json").exists():
        print("業績キャッシュが無いので --full を先に実行します")
        run_full()
    uni = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    syms, funda, margins = qualified_symbols()
    print(f"4条件の候補 {len(syms)} 銘柄の株価取得...")

    hist = yf.download(syms, period="2y", progress=False, group_by="ticker",
                       threads=True, auto_adjust=True)
    rows, new_today, latest = [], [], ""
    for s in syms:
        try:
            d = hist[s].dropna(subset=["Close", "Volume"])
        except Exception:
            continue
        if len(d) < W52 + 1:
            continue
        close = d["Close"].to_numpy(dtype=float)
        vol = d["Volume"].to_numpy(dtype=float)
        # 分割未調整等の異常は除外
        if float(np.max(close[1:] / close[:-1])) > 1.6:
            continue
        w = close[-W52:]
        hi = float(w.max())
        since = (W52 - 1) - int(np.argmax(w))
        last = float(close[-1])
        v50 = float(np.mean(vol[-50:]))
        v5 = float(np.max(vol[-5:]))
        row = {
            "sym": s, "name": uni.get(s, {}).get("name", s),
            "sec": uni.get(s, {}).get("sector", ""),
            "cap": round((uni.get(s, {}).get("cap") or 0) / 1e8),
            "price": round(last), "unit": round(last * 100),
            "since": since, "fromHigh": round((last / hi - 1) * 100, 1),
            "vol": round(v5 / v50, 1) if v50 else None,
            "ma25": round((last / float(np.mean(close[-25:])) - 1) * 100, 1),
            "ma200": round((last / float(np.mean(close[-200:])) - 1) * 100, 1),
            "revG": funda[s][1], "roe": funda[s][0], "opmA": margins[s],
        }
        rows.append(row)
        latest = max(latest, str(d.index[-1].date()))
        if since == 0:
            new_today.append(row)

    out = {"date": latest, "universe": len(funda), "qualified": len(syms), "rows": rows}
    (DATA / "rows.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"rows.json 保存: {len(rows)} 銘柄 / 最新 {latest} / 当日新高値 {len(new_today)}")

    notify_new_highs(new_today, latest)


def notify_new_highs(rows, date):
    if not rows:
        send(f"【新高値ブレイク】{date}\n本日52週高値を更新した該当銘柄はありません。")
        return
    rows = sorted(rows, key=lambda r: -(r["cap"] or 0))
    lines = [f"【新高値ブレイク】{date}",
             f"本日52週高値を更新（4条件クリア）: {len(rows)}銘柄", ""]
    for r in rows[:25]:
        vol = f"{r['vol']}x" if r["vol"] is not None else "—"
        lines.append(f"{r['sym']} {r['name'][:14]}  {r['price']:,}円  "
                     f"出来高{vol}  営業益率{r['opmA']}%  ROE{r['roe']}%")
    if len(rows) > 25:
        lines.append(f"…ほか {len(rows) - 25} 銘柄")
    send("\n".join(lines))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="業種リスト＋全銘柄業績を取り直す")
    args = p.parse_args()
    if args.full:
        run_full()
    run_daily()
