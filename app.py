import streamlit as st
import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Configuración de la página
st.set_page_config(
    page_title="Trading Quant Dashboard",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Panel de Control Cuantitativo: Trading System")
st.markdown("Ajusta los parámetros del modelo, selecciona activos (acciones o crypto) y analiza el rendimiento en tiempo real.")

# Inicializar estado de sesión
if 'backtest_corredor' not in st.session_state:
    st.session_state['backtest_corredor'] = False

# ---------------------------------------------------------
# SIDEBAR: PARÁMETROS Y CONFIGURACIÓN
# ---------------------------------------------------------
st.sidebar.header("⚙️ Configuración del Algoritmo")

# 1. Selección de Activos Sugeridos
tickers_sugeridos = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD', 'NFLX', 'QCOM', 'BTC-USD', 'ETH-USD']
tickers_multiselect = st.sidebar.multiselect(
    "Selección Rápida de Activos:",
    options=tickers_sugeridos,
    default=['AAPL', 'MSFT', 'NVDA', 'GOOGL']
)

# 2. Buscador / Entrada Manual de Tickers Adicionales
tickers_custom_input = st.sidebar.text_input(
    "🔍 Agregar otros Tickers (separados por coma):",
    placeholder="Ej: AMD, NFLX, QCOM, BTC-USD"
)

# Procesar y combinar los tickers seleccionados
custom_list = [t.strip().upper() for t in tickers_custom_input.split(',') if t.strip()]
tickers_seleccionados = list(dict.fromkeys(tickers_multiselect + custom_list))

if tickers_seleccionados:
    st.sidebar.info(f"Activos activos ({len(tickers_seleccionados)}): {', '.join(tickers_seleccionados)}")

st.sidebar.subheader("📊 Indicadores Técnicos")
ema_corta = st.sidebar.slider("EMA Corta (Rápida)", min_value=5, max_value=25, value=16, step=1)
ema_larga = st.sidebar.slider("EMA Larga (Lenta)", min_value=20, max_value=50, value=35, step=1)
adx_min = st.sidebar.slider("ADX Mínimo (Fuerza de Tendencia)", min_value=10, max_value=35, value=20, step=1)

st.sidebar.subheader("🛡️ Gestión de Riesgo")
trailing_stop_pct = st.sidebar.slider("Trailing Stop Dynamic (%)", min_value=1.0, max_value=10.0, value=5.0, step=0.5) / 100.0

st.sidebar.subheader("📅 Período de Tiempo")
fecha_inicio = st.sidebar.date_input("Fecha Inicio", pd.to_datetime('2024-01-01'))
fecha_fin = st.sidebar.date_input("Fecha Fin", pd.to_datetime('2026-10-29'))

# ---------------------------------------------------------
# LÓGICA DE ESTRATEGIA Y BACKTESTING (BACKTRADER)
# ---------------------------------------------------------
class EstrategiaPro(bt.Strategy):
    params = (
        ('ema_corta', 16),
        ('ema_larga', 35),
        ('adx_period', 14),
        ('adx_min', 20),
        ('trailing_stop', 0.05)
    )

    def __init__(self):
        self.spy = self.datas[0]
        self.spy_sma200 = bt.indicators.SMA(self.spy.close, period=200)

        self.inds = {}
        for d in self.datas[1:]:
            self.inds[d] = {}
            self.inds[d]['ema_corta'] = bt.indicators.EMA(d.close, period=self.p.ema_corta)
            self.inds[d]['ema_larga'] = bt.indicators.EMA(d.close, period=self.p.ema_larga)
            self.inds[d]['cruce'] = bt.indicators.CrossOver(
                self.inds[d]['ema_corta'], self.inds[d]['ema_larga']
            )
            self.inds[d]['adx'] = bt.indicators.ADX(d, period=self.p.adx_period)
            self.inds[d]['max_price'] = 0.0

    def next(self):
        mercado_alcista = self.spy.close[0] > self.spy_sma200[0]

        for d in self.datas[1:]:
            pos = self.getposition(d)
            if not pos:
                if mercado_alcista and self.inds[d]['cruce'] > 0 and self.inds[d]['adx'][0] > self.p.adx_min:
                    precio = d.close[0]
                    monto = self.broker.getvalue() * 0.20
                    tamano = int(monto / precio) if precio > 1 else round(monto / precio, 4)
                    if tamano > 0:
                        self.buy(data=d, size=tamano)
                        self.inds[d]['max_price'] = precio
            else:
                precio_actual = d.close[0]
                if precio_actual > self.inds[d]['max_price']:
                    self.inds[d]['max_price'] = precio_actual
                
                max_alcanzado = self.inds[d]['max_price']
                stop_dinamico = max_alcanzado * (1.0 - self.p.trailing_stop)
                
                if precio_actual <= stop_dinamico or self.inds[d]['cruce'] < 0:
                    self.close(data=d)
                    self.inds[d]['max_price'] = 0.0

class CustomTradeRecorder(bt.Analyzer):
    def __init__(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            tamano_original = trade.history[0].event.size if trade.history else 1
            precio_salida = trade.price + (trade.pnl / tamano_original) if tamano_original != 0 else trade.price
            self.trades.append({
                'Activo': trade.data._name,
                'Fecha Entrada': bt.num2date(trade.dtopen).strftime('%Y-%m-%d'),
                'Fecha Salida': bt.num2date(trade.dtclose).strftime('%Y-%m-%d'),
                'Duración (Días)': trade.barlen,
                'Cantidad': tamano_original,
                'Precio Entrada ($)': round(trade.price, 2),
                'Precio Salida ($)': round(precio_salida, 2),
                'PnL Neto ($)': round(trade.pnlcomm, 2)
            })

    def get_analysis(self):
        return self.trades

# ---------------------------------------------------------
# ACCIÓN DEL BOTÓN
# ---------------------------------------------------------
if st.button("🚀 Ejecutar Backtest con Parámetros Seleccionados"):
    if not tickers_seleccionados:
        st.warning("Por favor, selecciona al menos un activo para ejecutar la simulación.")
    else:
        with st.spinner("Descargando datos y procesando estrategia..."):
            tickers_totales = ['SPY'] + [t for t in tickers_seleccionados if t != 'SPY']
            
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(10000.0)

            for ticker in tickers_totales:
                df = yf.download(ticker, start=fecha_inicio, end=fecha_fin, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df = df.resample('D').ffill().dropna()
                data = bt.feeds.PandasData(dataname=df, name=ticker)
                cerebro.adddata(data)

            cerebro.addstrategy(
                EstrategiaPro,
                ema_corta=ema_corta,
                ema_larga=ema_larga,
                adx_min=adx_min,
                trailing_stop=trailing_stop_pct
            )

            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252)
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(CustomTradeRecorder, _name='trade_recorder')

            resultados = cerebro.run()
            strat = resultados[0]

            val_final = strat.broker.getvalue()
            sharpe_info = strat.analyzers.sharpe.get_analysis()
            drawdown_info = strat.analyzers.drawdown.get_analysis()
            trades_info = strat.analyzers.trade_recorder.get_analysis()

            retorno_pct = ((val_final - 10000.0) / 10000.0) * 100.0
            max_dd = drawdown_info['max']['drawdown'] if 'max' in drawdown_info and 'drawdown' in drawdown_info['max'] else 0.0
            sharpe_val = sharpe_info.get('sharperatio', 0.0) if sharpe_info.get('sharperatio') is not None else 0.0

            # Guardar en Session State
            st.session_state['val_final'] = val_final
            st.session_state['retorno_pct'] = retorno_pct
            st.session_state['max_dd'] = max_dd
            st.session_state['sharpe_val'] = sharpe_val
            st.session_state['trades_info'] = trades_info
            st.session_state['backtest_corredor'] = True

# ---------------------------------------------------------
# DESPLIEGUE DE RESULTADOS Y GRÁFICOS
# ---------------------------------------------------------
if st.session_state.get('backtest_corredor'):
    # METRICS
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Capital Final", f"${st.session_state['val_final']:,.2f}", f"{st.session_state['retorno_pct']:.2f}%")
    col2.metric("Máximo Drawdown", f"{st.session_state['max_dd']:.2f}%")
    col3.metric("Sharpe Ratio", f"{st.session_state['sharpe_val']:.2f}")
    col4.metric("Operaciones Cerradas", f"{len(st.session_state['trades_info'])}")

    st.markdown("---")

    # TABLA DE OPERACIONES
    st.subheader("📋 Registro de Operaciones Ejecutadas")
    if st.session_state['trades_info']:
        df_trades = pd.DataFrame(st.session_state['trades_info'])
        st.dataframe(df_trades, use_container_width=True)

        csv = df_trades.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Reporte CSV",
            data=csv,
            file_name="reporte_backtest_dashboard.csv",
            mime="text/csv"
        )
    else:
        st.info("No se generaron operaciones en el período seleccionado con estos parámetros.")

    # GRÁFICO INTERACTIVO
    st.markdown("---")
    st.subheader("📊 Gráfico Técnico Interactivo")
    activo_graficar = st.selectbox("Selecciona un activo para visualizar sus velas e indicadores:", options=tickers_seleccionados)

    if activo_graficar:
        df_chart = yf.download(activo_graficar, start=fecha_inicio, end=fecha_fin, progress=False)
        if isinstance(df_chart.columns, pd.MultiIndex):
            df_chart.columns = df_chart.columns.get_level_values(0)

        df_chart['EMA_Corta'] = df_chart['Close'].ewm(span=ema_corta, adjust=False).mean()
        df_chart['EMA_Larga'] = df_chart['Close'].ewm(span=ema_larga, adjust=False).mean()

        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
        fig.add_trace(go.Candlestick(
            x=df_chart.index,
            open=df_chart['Open'],
            high=df_chart['High'],
            low=df_chart['Low'],
            close=df_chart['Close'],
            name="Precio"
        ))

        fig.add_trace(go.Scatter(
            x=df_chart.index,
            y=df_chart['EMA_Corta'],
            mode='lines',
            name=f'EMA {ema_corta}',
            line=dict(color='orange', width=1.5)
        ))

        fig.add_trace(go.Scatter(
            x=df_chart.index,
            y=df_chart['EMA_Larga'],
            mode='lines',
            name=f'EMA {ema_larga}',
            line=dict(color='blue', width=1.5)
        ))

        fig.update_layout(
            title=f"Análisis Técnico - {activo_graficar}",
            yaxis_title="Precio (USD)",
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=500
        )

        st.plotly_chart(fig, use_container_width=True)