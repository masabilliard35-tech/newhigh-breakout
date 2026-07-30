"""スクリーニングの実行本体（全市場・毎日方式）。
必須条件: 52週高値更新 × 売上+10%(前年同期比) × 営業利益率20%(通期) × ROE10%

毎日の流れ:
  1. 全銘柄の株価を取得 → 当日52週高値を更新した銘柄を抽出（数十銘柄）
  2. その当日新高値だけ業績(ROE・売上成長・営業利益率)をライブ取得
  3. 4条件を満たすものを通知
株価の一括取得はレート制限を受けにくく、重い業績取得は当日新高値の数十銘柄だけで済む。

使い方:
  python scan.py            … 上記の毎日処理（GitHub Actions想定）
  python scan.py --full     … 全銘柄の業績も取り直す（表の網羅性向上・ローカル想定）
出力: data/rows.json（画面用）, data/funda.json, data/margins.json, data/universe.json
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
NEAR = 252          # 表に載せる「高値からの経過日」の上限
FRESH_NEW = 3       # 当日〜数日以内を「新規」とみなし業績をライブ取得


def pc(x):
    return None if x is None else round(x * 100)


def load_json(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


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


def fetch_fundamentals(sym):
    """[ROE%, 売上成長%, 営業利益率(通期)%] をライブ取得。"""
    roe = revg = None
    try:
        info = yf.Ticker(sym).info
        roe = pc(info.get("returnOnEquity"))
        revg = pc(info.get("revenueGrowth"))
    except Exception:
        pass
    return roe, revg, opm_annual(sym)


def passes(roe, revg, opm):
    return (roe is not None and roe >= 10 and revg is not None and revg >= 10
            and opm is not None and opm >= 20)


def download_all(syms, period="15mo", chunk=150):
    """全銘柄の株価をまとめて取得（レート制限に備え小分け＋リトライ）。"""
    frames = {}
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        for attempt in range(3):
            try:
                h = yf.download(part, period=period, progress=False,
                                group_by="ticker", threads=True, auto_adjust=True)
            except Exception:
                h = None
            got = 0
            if h is not None:
                for s in part:
                    try:
                        d = h[s].dropna(subset=["Close", "Volume"])
                        if len(d) >= W52:
                            frames[s] = d
                            got += 1
                    except Exception:
                        pass
            if got >= max(1, len(part) // 3):
                break
            time.sleep(5 * (attempt + 1))
        print(f"\r株価 {min(i + chunk, len(syms))}/{len(syms)}  取得 {len(frames)}", end="")
    print()
    return frames


def run_full():
    """全銘柄の業績を取り直してキャッシュを厚くする（ローカル想定・任意）。"""
    print("universe取得...")
    uni = fetch_universe()
    (DATA / "universe.json").write_text(json.dumps(uni, ensure_ascii=False), encoding="utf-8")
    syms = sorted(uni)
    print(f"  {len(syms)} 銘柄 / 業績取得...")
    funda = load_json("funda.json", {})
    margins = load_json("margins.json", {})
    for i, s in enumerate(syms, 1):
        roe, revg, opm = fetch_fundamentals(s)
        funda[s] = [roe, revg]
        if opm is not None:
            margins[s] = opm
        if i % 200 == 0:
            print(f"  {i}/{len(syms)}")
            (DATA / "funda.json").write_text(json.dumps(funda), encoding="utf-8")
            (DATA / "margins.json").write_text(json.dumps(margins), encoding="utf-8")
        time.sleep(0.03)
    (DATA / "funda.json").write_text(json.dumps(funda), encoding="utf-8")
    (DATA / "margins.json").write_text(json.dumps(margins), encoding="utf-8")
    print("full完了")


def run_daily():
    uni = load_json("universe.json", None)
    if uni is None:
        print("universe.json が無いので取得します")
        uni = fetch_universe()
        (DATA / "universe.json").write_text(json.dumps(uni, ensure_ascii=False), encoding="utf-8")
    syms = sorted(uni)
    print(f"全 {len(syms)} 銘柄の株価取得...")
    frames = download_all(syms)

    funda = load_json("funda.json", {})
    margins = load_json("margins.json", {})

    metrics = {}
    today_high = []
    for s, d in frames.items():
        close = d["Close"].to_numpy(dtype=float)
        vol = d["Volume"].to_numpy(dtype=float)
        if float(np.max(close[1:] / close[:-1])) > 1.6:      # 分割未調整等の異常
            continue
        w = close[-W52:]
        hi = float(w.max())
        since = (W52 - 1) - int(np.argmax(w))
        last = float(close[-1])
        v50 = float(np.mean(vol[-50:]))
        v5 = float(np.max(vol[-5:]))
        metrics[s] = {
            "since": since, "price": round(last), "unit": round(last * 100),
            "fromHigh": round((last / hi - 1) * 100, 1),
            "vol": round(v5 / v50, 1) if v50 else None,
            "ma25": round((last / float(np.mean(close[-25:])) - 1) * 100, 1),
            "ma200": round((last / float(np.mean(close[-200:])) - 1) * 100, 1),
        }
        if since <= FRESH_NEW:
            today_high.append(s)

    print(f"直近{FRESH_NEW}日以内に52週高値: {len(today_high)} 銘柄 → 業績をライブ取得...")
    for s in today_high:
        roe, revg, opm = fetch_fundamentals(s)
        old = funda.get(s, [None, None])
        # ライブ取得が失敗(None)したらキャッシュ値を残す＝GitHubで制限されても後退しない
        funda[s] = [roe if roe is not None else old[0],
                    revg if revg is not None else old[1]]
        if opm is not None:
            margins[s] = opm
        time.sleep(0.05)
    (DATA / "funda.json").write_text(json.dumps(funda), encoding="utf-8")
    (DATA / "margins.json").write_text(json.dumps(margins), encoding="utf-8")

    # 表用: 高値圏 かつ 4条件クリア（業績はキャッシュ＋本日取得分）
    rows, latest = [], ""
    alerts = []
    for s, m in metrics.items():
        f = funda.get(s, [None, None])
        opm = margins.get(s)
        if not passes(f[0], f[1], opm):
            continue
        if m["since"] > NEAR:
            continue
        row = {"sym": s, "name": uni.get(s, {}).get("name", s),
               "sec": uni.get(s, {}).get("sector", ""),
               "cap": round((uni.get(s, {}).get("cap") or 0) / 1e8),
               **m, "revG": f[1], "roe": f[0], "opmA": opm}
        rows.append(row)
        if m["since"] == 0:
            alerts.append(row)

    for s, d in frames.items():
        latest = max(latest, str(d.index[-1].date()))
    out = {"date": latest, "universe": len(syms), "qualified": len(rows), "rows": rows}
    (DATA / "rows.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"rows.json 保存: {len(rows)} 銘柄 / 最新 {latest} / 当日新高値かつ条件クリア {len(alerts)}")

    notify_alerts(alerts, latest)


def notify_alerts(rows, date):
    if not rows:
        send(f"【新高値ブレイク】{date}\n"
             f"本日52週高値を更新し4条件（売上+10%・営業利益率20%・ROE10%）を"
             f"満たす銘柄はありませんでした。")
        return
    rows = sorted(rows, key=lambda r: -(r["cap"] or 0))
    lines = [f"【新高値ブレイク】{date}",
             f"本日52週高値を更新かつ4条件クリア: {len(rows)}銘柄", ""]
    for r in rows[:25]:
        vol = f"{r['vol']}x" if r["vol"] is not None else "—"
        lines.append(f"{r['sym']} {r['name'][:14]}  {r['price']:,}円  "
                     f"出来高{vol}  営業益率{r['opmA']}%  ROE{r['roe']}%  売上+{r['revG']}%")
    if len(rows) > 25:
        lines.append(f"…ほか {len(rows) - 25} 銘柄")
    send("\n".join(lines))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="全銘柄の業績も取り直す（ローカル想定）")
    args = p.parse_args()
    if args.full:
        run_full()
    run_daily()
