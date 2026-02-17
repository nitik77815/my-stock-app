import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from SmartApi import SmartConnect
import pyotp
from datetime import datetime, timedelta

st.set_page_config(page_title="Pro Trader Dashboard", layout="wide")

# ==========================================
# ### SECURE CONFIGURATION (CLOUD) ###
# ==========================================
# This looks for keys in the Streamlit "Secrets" vault
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]  # This is your MPIN
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"] # For the login screen
except FileNotFoundError:
    st.error("⚠️ Secrets not found! If running locally, you need a .streamlit/secrets.toml file. If on Cloud, add them to App Settings.")
    st.stop()
except KeyError as e:
    st.error(f"⚠️ Missing Secret: {e}. Please add it to your Secrets.")
    st.stop()

# ==========================================
# ### SECURITY LOCK ###
# ==========================================
check_password = st.sidebar.text_input("🔑 Enter App Password", type="password")
if check_password != APP_PASSWORD:
    st.warning("🔒 Please enter the correct password to access the trading dashboard.")
    st.stop()

# --- 1. LOGIN ---
@st.cache_resource
def login():
    try:
        smartApi = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = smartApi.generateSession(CLIENT_CODE, PASSWORD, totp)
        if data['status']:
            return smartApi
        else:
            st.error(f"Login Failed: {data['message']}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

# --- 2. LOAD TOKENS ---
# We use a built-in list or fetch it if needed. 
# For Cloud, it's safer to fetch it live or use a smaller static list if the file is missing.
@st.cache_data
def load_tokens():
    try:
        # Try to read local file first
        return pd.read_csv("angel_tokens.csv")
    except:
        # If file missing (common in cloud), return empty or handle download
        st.warning("⚠️ Token file not found. Please upload 'angel_tokens.csv' to GitHub or add code to download it.")
        return pd.DataFrame()

api = login()
tokens_df = load_tokens()

# --- 3. DATA ENGINE ---
def fetch_data(token, interval, days):
    try:
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": interval,
            "fromdate": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M"), 
            "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        data = api.getCandleData(params)
        df = pd.DataFrame(data['data'], columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        return df.astype(float)
    except:
        return None

# --- 4. INDICATOR CALCULATION (ROBUST) ---
def add_indicators(df, is_intraday=False):
    # Trend
    df['SMA_50'] = ta.sma(df['Close'], length=50)
    df['EMA_50'] = ta.ema(df['Close'], length=50)
    
    # Supertrend (Auto-Find)
    st_data = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=3)
    if st_data is not None:
        st_col = [col for col in st_data.columns if col.startswith('SUPERT_')][0]
        df['Supertrend'] = st_data[st_col]
    
    # Momentum
    df['RSI'] = ta.rsi(df['Close'], length=14)
    macd = ta.macd(df['Close'])
    if macd is not None:
        macd_col = [col for col in macd.columns if col.startswith('MACD_')][0]
        signal_col = [col for col in macd.columns if col.startswith('MACDs_')][0]
        df['MACD'] = macd[macd_col]
        df['MACD_Signal'] = macd[signal_col]

    # Volatility (Bollinger Bands Auto-Find)
    bb = ta.bbands(df['Close'], length=20)
    if bb is not None:
        bb_upper_col = [col for col in bb.columns if col.startswith('BBU_')][0]
        bb_lower_col = [col for col in bb.columns if col.startswith('BBL_')][0]
        df['BB_Upper'] = bb[bb_upper_col]
        df['BB_Lower'] = bb[bb_lower_col]
    
    # Volume
    df['Vol_SMA_5'] = ta.sma(df['Volume'], length=5)

    # VWAP (Only valid for Intraday)
    if is_intraday:
        df['VWAP'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])

    return df

# --- 5. DASHBOARD LAYOUT ---
st.sidebar.header("🔍 Stock Selector")

if tokens_df.empty:
    st.error("⚠️ Stock list is empty. Please check 'angel_tokens.csv'.")
    st.stop()
else:
    stock_name = st.sidebar.selectbox("Select Stock", tokens_df['name'].unique())
    row = tokens_df[tokens_df['name'] == stock_name].iloc[0]
    token = str(row['token'])
    symbol = row['symbol']

if st.sidebar.button("Analyze (Rule of 3)"):
    with st.spinner("Fetching Multi-Timeframe Data..."):
        # 1. Fetch Daily Data
        df_daily = fetch_data(token, "ONE_DAY", 365)
        
        # 2. Fetch 15-Min Data
        df_intra = fetch_data(token, "FIFTEEN_MINUTE", 10)

        if df_daily is not None and not df_daily.empty and df_intra is not None and not df_intra.empty:
            
            # Add Indicators
            df_daily = add_indicators(df_daily, is_intraday=False)
            df_intra = add_indicators(df_intra, is_intraday=True)

            last_day = df_daily.iloc[-1]
            last_15 = df_intra.iloc[-1]
            
            st.title(f"📊 {stock_name} Professional Analysis")
            
# --- THE RULE OF THREE LOGIC ---
            score = 0
            
            # CATEGORY 1: TREND (Daily Chart)
            trend_bullish = last_day['Close'] > last_day['EMA_50']
            trend_msg = "BULLISH" if trend_bullish else "BEARISH"
            trend_color = "green" if trend_bullish else "red"
            if trend_bullish: score += 1

            # CATEGORY 2: MOMENTUM (Daily RSI)
            rsi_val = last_day['RSI']
            mom_bullish = 50 < rsi_val < 70
            mom_msg = f"RSI {rsi_val:.1f}"
            mom_color = "green" if mom_bullish else "orange"
            if mom_bullish: score += 1

            # CATEGORY 3: VOLUME
            vol_bullish = last_day['Volume'] > last_day['Vol_SMA_5']
            vol_msg = "High Vol" if vol_bullish else "Low Vol"
            vol_color = "green" if vol_bullish else "red"
            if vol_bullish: score += 1
            
            # Intraday Check
            intra_bullish = last_15['Close'] > last_15['VWAP']
            intra_msg = "Price > VWAP" if intra_bullish else "Price < VWAP"
            intra_color = "green" if intra_bullish else "red"

            # --- DISPLAY SUMMARY ---
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Current Price", f"₹{last_day['Close']}")
            col2.metric("Daily Trend", trend_msg)
            col3.metric("RSI Momentum", f"{rsi_val:.1f}")
            col4.metric("Intraday Signal", intra_msg)

            st.divider()

            # --- THE RULE OF THREE CHECKLIST ---
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**1. Trend (EMA 50):** :{trend_color}[{trend_msg}]")
            c2.markdown(f"**2. Momentum (RSI):** :{mom_color}[{mom_msg}]")
            c3.markdown(f"**3. Volume:** :{vol_color}[{vol_msg}]")

            if score == 3 and intra_bullish:
                st.success("🚀 **STRONG BUY SIGNAL** (All Systems Go!)")
            elif score <= 1:
                st.error("🛑 **NO TRADE** (Waiting for setup)")
            else:
                st.warning("⚠️ **Watchlist** (Mixed Signals)")

            # --- ADVANCED CHARTS ---
            tab1, tab2 = st.tabs(["Daily Chart (Trend)", "15-Min Chart (Entry)"])

            with tab1:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                fig.add_trace(go.Candlestick(x=df_daily.index, open=df_daily['Open'], high=df_daily['High'], low=df_daily['Low'], close=df_daily['Close'], name="Price"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['EMA_50'], line=dict(color='orange'), name="50 EMA"), row=1, col=1)
                if 'Supertrend' in df_daily.columns:
                    fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['Supertrend'], line=dict(color='green', dash='dot'), name="Supertrend"), row=1, col=1)
                fig.add_trace(go.Bar(x=df_daily.index, y=df_daily['MACD'] - df_daily['MACD_Signal'], name="MACD Hist"), row=2, col=1)
                fig.update_layout(height=600, template="plotly_dark", title_text="Daily Trend Analysis")
                st.plotly_chart(fig, use_container_width=True)

            with tab2:
                fig2 = go.Figure()
                fig2.add_trace(go.Candlestick(x=df_intra.index, open=df_intra['Open'], high=df_intra['High'], low=df_intra['Low'], close=df_intra['Close'], name="Intraday Price"))
                if 'VWAP' in df_intra.columns:
                    fig2.add_trace(go.Scatter(x=df_intra.index, y=df_intra['VWAP'], line=dict(color='cyan'), name="VWAP"))
                fig2.update_layout(height=500, template="plotly_dark", title_text="15-Minute Entry Chart (VWAP)")
                st.plotly_chart(fig2, use_container_width=True)

        else:
            st.error("Could not fetch data. Market closed or invalid symbol.")
