"""新高値ブレイク スクリーナー（Streamlit）。
data/rows.json を読み、フィルタ表示。銘柄を選ぶとチャートを yfinance からライブ取得して描画。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

HERE = Path(__file__).parent
DATA = HERE / "data" / "rows.json"

st.set_page_config(page_title="新高値ブレイク スクリーナー", layout="wide")


@st.cache_data(ttl=3600)
def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


@st.cache_data(ttl=1800)
def history(sym, period):
    df = yf.Ticker(sym).history(period=period, auto_adjust=True)
    return df.dropna(subset=["Close"]) if df is not None else None


def sma(s, n):
    return s.rolling(n).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def chart(sym, name, tf):
    period = {"日足": "1y", "週足": "3y", "月足": "10y"}[tf]
    interval = {"日足": "1d", "週足": "1wk", "月足": "1mo"}[tf]
    df = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=True)
    if df is None or df.empty:
        st.info("チャートデータを取得できませんでした。")
        return
    df = df.dropna(subset=["Close"])
    c = df["Close"]
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.16, 0.18, 0.16], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                 low=df["Low"], close=c, name="株価",
                                 increasing_line_color="#d33", decreasing_line_color="#39c"), 1, 1)
    for n, col in [(25, "#c99a16"), (50, "#c4382d"), (100, "#2e8b57"), (200, "#2e6fa7")]:
        fig.add_trace(go.Scatter(x=df.index, y=sma(c, n), name=f"SMA{n}",
                                 line=dict(width=1, color=col)), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=mid + 2 * sd, name="BB+", line=dict(width=1, color="rgba(140,143,163,.6)")), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=mid - 2 * sd, name="BB-", line=dict(width=1, color="rgba(140,143,163,.6)")), 1, 1)
    vol_col = np.where(c >= df["Open"], "#d33", "#39c")
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="出来高", marker_color=vol_col), 2, 1)
    fig.add_trace(go.Bar(x=df.index, y=macd - signal, name="MACD Hist", marker_color="#888"), 3, 1)
    fig.add_trace(go.Scatter(x=df.index, y=macd, name="MACD", line=dict(width=1, color="#2e6fa7")), 3, 1)
    fig.add_trace(go.Scatter(x=df.index, y=signal, name="Signal", line=dict(width=1, color="#c4382d")), 3, 1)
    fig.add_trace(go.Scatter(x=df.index, y=rsi(c), name="RSI", line=dict(width=1, color="#2e8b57")), 4, 1)
    fig.add_hline(y=70, line=dict(width=0.6, dash="dot", color="#888"), row=4, col=1)
    fig.add_hline(y=30, line=dict(width=0.6, dash="dot", color="#888"), row=4, col=1)
    fig.update_layout(height=760, template="plotly_dark", xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      title=f"{sym}  {name}  ({tf})")
    st.plotly_chart(fig, use_container_width=True)


data = load()
df = pd.DataFrame(data["rows"])

st.title("新高値ブレイク スクリーナー")
st.caption(f"必須条件：52週高値更新 × 売上+10% × 営業利益率20%(通期) × ROE10%　"
           f"｜ データ日 {data['date']}　｜ 母集団 {data['universe']:,} 中 {data['qualified']} 銘柄が条件通過")

with st.sidebar:
    st.header("絞り込み")
    since_opt = {"当日": 0, "5日以内": 5, "10日以内": 10, "1ヶ月以内": 21,
                 "3ヶ月以内": 63, "6ヶ月以内": 126, "52週以内": 252}
    since_lbl = st.radio("ブレイクからの経過", list(since_opt), index=3)
    vol_lbl = st.radio("出来高倍率", ["指定なし", "1.5〜5倍", "1.5倍以上", "5倍超"], index=0)
    caps = st.multiselect("時価総額（億円）", ["〜50", "50〜300", "300〜1000", "1000〜"], [])
    secs = st.multiselect("業種", sorted(df["sec"].unique()), [])
    capital = st.number_input("総資金（円）", value=5_000_000, step=500_000)

m = df["since"] <= since_opt[since_lbl]
if vol_lbl == "1.5〜5倍":
    m &= df["vol"].between(1.5, 5, inclusive="left")
elif vol_lbl == "1.5倍以上":
    m &= df["vol"] >= 1.5
elif vol_lbl == "5倍超":
    m &= df["vol"] >= 5
if caps:
    rng = {"〜50": (0, 50), "50〜300": (50, 300), "300〜1000": (300, 1000), "1000〜": (1000, 9e9)}
    cm = pd.Series(False, index=df.index)
    for c in caps:
        lo, hi = rng[c]
        cm |= df["cap"].between(lo, hi, inclusive="left")
    m &= cm
if secs:
    m &= df["sec"].isin(secs)

view = df[m].copy().sort_values("cap", ascending=False)
lim = capital * 0.25
view["買える"] = np.where(view["unit"] <= lim, "○", "×(25%超)")

st.subheader(f"該当 {len(view)} 銘柄")
show = view[["sym", "name", "sec", "since", "cap", "price", "unit", "買える",
             "fromHigh", "vol", "revG", "opmA", "roe", "ma200"]].rename(columns={
    "sym": "コード", "name": "銘柄", "sec": "業種", "since": "経過日", "cap": "時価総額(億)",
    "price": "株価", "unit": "単元(円)", "fromHigh": "高値差%", "vol": "出来高倍",
    "revG": "売上%", "opmA": "営業益率%", "roe": "ROE%", "ma200": "200日線%"})
st.dataframe(show, use_container_width=True, hide_index=True, height=460)

st.subheader("チャート")
col1, col2 = st.columns([3, 1])
pick = col1.selectbox("銘柄を選択", view["sym"] + "  " + view["name"] if len(view) else [""])
tf = col2.radio("足", ["日足", "週足", "月足"], horizontal=True)
if len(view) and pick:
    sym = pick.split("  ")[0]
    name = view[view["sym"] == sym]["name"].iloc[0]
    chart(sym, name, tf)

st.caption("スクリーニング結果であり推奨銘柄ではありません。営業利益率は通期（Yahooは日本株の四半期営業利益をほぼ提供しないため）。")
