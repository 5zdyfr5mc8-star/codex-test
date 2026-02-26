import pandas as pd
import streamlit as st

PIP_VALUE_PER_LOT = 1000  # JPY pairs rough estimate for 1 lot (100k units), simplified for MVP


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def load_data(file) -> pd.DataFrame:
    df = pd.read_csv(file)
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["rsi14"] = calc_rsi(out["close"], 14)
    out["atr14"] = calc_atr(out, 14)
    return out


def trend_label(row: pd.Series) -> str:
    if row["ema20"] > row["ema50"] and row["close"] > row["ema20"]:
        return "上昇トレンド寄り"
    if row["ema20"] < row["ema50"] and row["close"] < row["ema20"]:
        return "下降トレンド寄り"
    return "レンジ/遷移"


st.set_page_config(page_title="FX 裁量支援ツール", layout="wide")
st.title("FX 裁量売買支援ツール (MVP)")
st.caption("自動売買ではなく、裁量トレードの意思決定を補助するツール")

uploaded = st.sidebar.file_uploader("OHLCV CSV をアップロード", type=["csv"])

if not uploaded:
    st.info("左サイドバーからCSVをアップロードしてください。")
    st.stop()

try:
    raw = load_data(uploaded)
    data = add_indicators(raw)
except Exception as e:
    st.error(f"データ読み込みエラー: {e}")
    st.stop()

latest = data.iloc[-1]

col1, col2, col3, col4 = st.columns(4)
col1.metric("現在価格", f"{latest['close']:.5f}")
col2.metric("EMA20", f"{latest['ema20']:.5f}")
col3.metric("EMA50", f"{latest['ema50']:.5f}")
col4.metric("RSI14", f"{latest['rsi14']:.2f}")

st.subheader("相場コンディション")
st.write(f"**トレンド判定:** {trend_label(latest)}")
st.write(f"**ATR14:** {latest['atr14']:.5f}")

st.subheader("価格とEMA")
chart_df = data.set_index("time")[["close", "ema20", "ema50"]]
st.line_chart(chart_df)

st.subheader("裁量トレード用 リスク計算")
r1, r2, r3 = st.columns(3)
with r1:
    balance = st.number_input("口座残高 (JPY)", min_value=10000.0, value=300000.0, step=10000.0)
    risk_pct = st.number_input("1トレード許容リスク (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
with r2:
    entry = st.number_input("Entry価格", value=float(latest["close"]))
    stop = st.number_input("Stop価格", value=float(latest["close"] - 0.005))
with r3:
    take = st.number_input("Take価格", value=float(latest["close"] + 0.01))

risk_amount = balance * (risk_pct / 100.0)
stop_pips = abs(entry - stop) * 100  # simplified JPY pip calc
reward_pips = abs(take - entry) * 100
rr = (reward_pips / stop_pips) if stop_pips > 0 else 0

estimated_lot = (risk_amount / (stop_pips * PIP_VALUE_PER_LOT)) if stop_pips > 0 else 0

st.write(f"- 許容損失額: **{risk_amount:,.0f} JPY**")
st.write(f"- 損切り幅: **{stop_pips:.1f} pips**")
st.write(f"- 利確幅: **{reward_pips:.1f} pips**")
st.write(f"- RR比: **{rr:.2f}**")
st.write(f"- 推奨ロット（概算）: **{estimated_lot:.3f} lot**")

st.subheader("取引前チェックリスト")
check1 = st.checkbox("経済指標・要人発言の直前ではない")
check2 = st.checkbox("損切り位置に客観的根拠がある（高安・ATR等）")
check3 = st.checkbox("エントリー理由を1行で説明できる")
check4 = st.checkbox("連敗中の感情トレードではない")

if check1 and check2 and check3 and check4:
    st.success("チェック完了: ルール準拠で執行可能")
else:
    st.warning("未チェック項目があります。執行前に再確認してください。")
