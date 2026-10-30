import streamlit as st
import yfinance as yf
import backtrader as bt
import pandas as pd
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# Configuración inicial de la página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Cuantitativo",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Dashboard Cuantitativo de Trading")

# -----------------------------------------------------------------------------
# Estrategia Backtrader (EMA 16/35 + ADX + Filtro SPY > SMA200)
# -----------------------------------------------------------------------------
class EmaAdxStrategy(bt.Strategy):
    params = (
        ('ema_fast', 16),
        ('ema_slow', 35),
        ('adx_period', 14),
        ('adx_threshold', 20.0),
        ('spy_sma_period', 200),
        ('trail_percent', 0.05),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data0.close, period=self.params.ema_fast)
        self.ema_slow = bt.indicators.EMA(self.data0.close, period=self.params.ema_slow)
        self.adx = bt.indicators.ADX(self.data0, period=self.params.adx_period)

        if len(self.datas) > 1:
            self.spy_close = self.data1.close
            self.spy_sma = bt.indicators.SMA(self.data1.close, period=self.params.spy_sma_period)
        else:
            self.spy_close = None
            self.spy_sma = None

        self.order = None

    def next(self):
        if self.order:
            return

        market_bullish = True
        if self.spy_close is not None and self.spy_sma is not None:
            market_bullish = self.spy_close[0] > self.spy_sma[0]

        crossover = self.ema_fast[0] > self.ema_slow[0] and self.ema_fast[-1] <= self.ema_slow[-1]
        adx_strong = self.adx[0] > self.params.adx_threshold

        if not self.position:
            if crossover and adx_strong and market_bullish:
                self.order = self.buy()
                self.sell(exectype=bt.Order.StopTrail, trailpercent=self.params.trail_percent)

# -----------------------------------------------------------------------------
# Función de descarga de datos
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_data(ticker, start_date=None, end_date=None):
    try:
        if start_date and end_date:
            df = yf.download(ticker, start=start_date, end=end_date, interval="1d", progress=False)
        else:
            df = yf.download(ticker, period="max", interval="1d", progress=False)
            
        if df.empty:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.dropna(inplace=True)
        return df
    except Exception as e:
        st.error(f"Error al descargar datos para {ticker}: {e}")
        return None

# -----------------------------------------------------------------------------
# Barra lateral de parámetros
# -----------------------------------------------------------------------------
st.sidebar.header("Parámetros de la Estrategia")

# Catálogo amplio de símbolos predefinidos (incluye índices, ETFs y acciones líderes)
catalog_symbols = [
    "SPY", "^GSPC", "^NDX", "QQQ", "^IXIC", "^DJI", "BTC-USD", "ETH-USD",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD"
]

# Campo de texto para agregar dinámicamente un ticker personalizado
custom_symbol = st.sidebar.text_input("Agregar ticker personalizado (ej: IWM, DIA):", "").strip().upper()

# Si el usuario escribe un ticker personalizado, se suma a las opciones disponibles
available_options = catalog_symbols.copy()
if custom_symbol and custom_symbol not in available_options:
    available_options.append(custom_symbol)

# Multiselect con la lista de opciones enriquecida
default_selections = ["SPY", "QQQ"]
if custom_symbol and custom_symbol not in default_selections:
    default_selections.append(custom_symbol)

selected_symbols = st.sidebar.multiselect(
    "Selecciona los activos a evaluar:",
    options=available_options,
    default=default_selections
)

# Configuración de fechas
st.sidebar.subheader("Rango Temporal")
date_mode = st.sidebar.radio("Modo de Fechas", ["Histórico Máximo", "Rango Personalizado"])

if date_mode == "Rango Personalizado":
    start_input = st.sidebar.date_input("Fecha Inicio", pd.to_datetime("2000-01-01"))
    end_input = st.sidebar.date_input("Fecha Fin", pd.to_datetime("today"))
    start_str = start_input.strftime('%Y-%m-%d')
    end_str = end_input.strftime('%Y-%m-%d')
else:
    start_str, end_str = None, None

initial_capital = st.sidebar.number_input("Capital Inicial ($)", value=10000, step=1000)

st.sidebar.subheader("Indicadores")
ema_fast = st.sidebar.slider("EMA Rápida", 5, 50, 16)
ema_slow = st.sidebar.slider("EMA Lenta", 20, 100, 35)
adx_threshold = st.sidebar.slider("Umbral ADX Mínimo", 10.0, 40.0, 20.0, step=1.0)
trail_percent = st.sidebar.slider("Trailing Stop (%)", 1.0, 15.0, 5.0, step=0.5) / 100.0

run_button = st.sidebar.button("Ejecutar Backtest")

# Persistencia de ejecución en session_state
if "executed" not in st.session_state:
    st.session_state.executed = False

if run_button:
    st.session_state.executed = True

# -----------------------------------------------------------------------------
# Ejecución del Algoritmo y Renderizado
# -----------------------------------------------------------------------------
if st.session_state.executed:
    if not selected_symbols:
        st.warning("Por favor selecciona al menos un activo en la barra lateral.")
    else:
        with st.spinner("Descargando datos y procesando historial..."):
            loaded_data = {}
            start_dates = {}

            for sym in selected_symbols:
                df = fetch_data(sym, start_str, end_str)
                if df is not None and not df.empty:
                    loaded_data[sym] = df
                    start_dates[sym] = df.index[0]

            data_spy = fetch_data("SPY", start_str, end_str)

            if not loaded_data:
                st.error("No se pudieron cargar datos para los activos seleccionados.")
            else:
                latest_start_symbol = max(start_dates, key=start_dates.get)
                common_start_date = start_dates[latest_start_symbol]
                common_start_str = common_start_date.strftime('%Y-%m-%d')
                latest_year = common_start_date.year

                # -------------------------------------------------------------
                # 1. GRÁFICO COMPARATIVO DESDE LA FECHA MÁS RECIENTE
                # -------------------------------------------------------------
                if len(loaded_data) > 1:
                    st.warning(
                        f"⚠️ **Aviso de Alineación:** La fecha de inicio común para la comparativa está limitada por **{latest_start_symbol}**, "
                        f"cuyos datos inician el **{common_start_str}** (año {latest_year})."
                    )
                    st.subheader(f"🔄 Comparativa de Rendimiento (%) Normalizada desde {common_start_str}")
                    
                    fig_comp = go.Figure()

                    for sym, df_asset in loaded_data.items():
                        df_trimmed = df_asset.loc[df_asset.index >= common_start_date]
                        
                        if not df_trimmed.empty:
                            base_price = df_trimmed['Close'].iloc[0]
                            pct_change = ((df_trimmed['Close'] - base_price) / base_price) * 100

                            fig_comp.add_trace(go.Scatter(
                                x=df_trimmed.index,
                                y=pct_change,
                                mode='lines',
                                name=f"{sym} (%)"
                            ))

                    fig_comp.update_layout(
                        title=f"Rendimiento Porcentual Acumulado (Base 0% en {common_start_str})",
                        xaxis_title="Fecha",
                        yaxis_title="Retorno (%)",
                        template="plotly_dark",
                        height=480,
                        margin=dict(l=20, r=20, t=40, b=20),
                        hovermode="x unified"
                    )

                    st.plotly_chart(fig_comp, use_container_width=True)
                else:
                    st.info(f"📅 **Rango Histórico de {selected_symbols[0]}:** Datos disponibles desde **{common_start_str}**.")

                # -------------------------------------------------------------
                # 2. GRÁFICOS E INFORMES INDIVIDUALES PARA CADA ACTIVO
                # -------------------------------------------------------------
                st.markdown("---")
                st.header("📋 Backtest y Gráficos Individuales por Activo")

                for sym, data_asset in loaded_data.items():
                    st.subheader(f"📊 Análisis de {sym}")

                    cerebro = bt.Cerebro()
                    cerebro.broker.setcash(initial_capital)

                    data0 = bt.feeds.PandasData(dataname=data_asset)
                    cerebro.adddata(data0, name=sym)

                    if data_spy is not None and not data_spy.empty:
                        data1 = bt.feeds.PandasData(dataname=data_spy)
                        cerebro.adddata(data1, name="SPY_Filter")

                    cerebro.addstrategy(
                        EmaAdxStrategy,
                        ema_fast=ema_fast,
                        ema_slow=ema_slow,
                        adx_threshold=adx_threshold,
                        trail_percent=trail_percent
                    )
                    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
                    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

                    results = cerebro.run()
                    strat = results[0]

                    final_val = cerebro.broker.getvalue()
                    pnl = final_val - initial_capital
                    ret_pct = (pnl / initial_capital) * 100

                    dd_info = strat.analyzers.drawdown.get_analysis()
                    max_dd = dd_info.get('max', {}).get('drawdown', 0.0)

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Capital Final", f"${final_val:,.2f}")
                    col2.metric("Ganancia / Pérdida", f"${pnl:,.2f}", f"{ret_pct:.2f}%")
                    col3.metric("Max Drawdown", f"{max_dd:.2f}%")
                    col4.metric("Años Evaluados", f"{(len(data_asset) / 252):.1f} años")

                    fig_ind = go.Figure()
                    fig_ind.add_trace(go.Candlestick(
                        x=data_asset.index,
                        open=data_asset['Open'],
                        high=data_asset['High'],
                        low=data_asset['Low'],
                        close=data_asset['Close'],
                        name="Precio"
                    ))

                    ema16 = data_asset['Close'].ewm(span=ema_fast, adjust=False).mean()
                    ema35 = data_asset['Close'].ewm(span=ema_slow, adjust=False).mean()

                    fig_ind.add_trace(go.Scatter(x=data_asset.index, y=ema16, line=dict(color='orange', width=1.5), name=f'EMA {ema_fast}'))
                    fig_ind.add_trace(go.Scatter(x=data_asset.index, y=ema35, line=dict(color='blue', width=1.5), name=f'EMA {ema_slow}'))

                    fig_ind.update_layout(
                        title=f"Evolución de Precio e Indicadores - {sym} (Histórico Completo)",
                        xaxis_rangeslider_visible=False,
                        template="plotly_dark",
                        height=450,
                        margin=dict(l=20, r=20, t=40, b=20)
                    )

                    st.plotly_chart(fig_ind, use_container_width=True)
                    st.markdown("---")
else:
    st.info("Selecciona los activos en la barra lateral y presiona **Ejecutar Backtest**.")