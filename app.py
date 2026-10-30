import streamlit as st
import yfinance as yf
import backtrader as bt
import pandas as pd
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# Configuración inicial de la página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Cuantitativo & Prop Firm Simulator",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Dashboard Cuantitativo & Simulador Prop Firm (LucidFlex)")

# -----------------------------------------------------------------------------
# Estrategia Backtrader (EMA 16/35 + ADX + Filtro SPY + Risk Management)
# -----------------------------------------------------------------------------
class EmaAdxStrategy(bt.Strategy):
    params = (
        ('ema_fast', 16),
        ('ema_slow', 35),
        ('adx_period', 14),
        ('adx_threshold', 20.0),
        ('spy_sma_period', 200),
        ('stop_points', 50.0),      # Stop loss en puntos
        ('target_points', 150.0),   # Take profit en puntos
        ('contracts', 1),
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
            return  # Esperar orden pendiente

        market_bullish = True
        if self.spy_close is not None and self.spy_sma is not None:
            market_bullish = self.spy_close[0] > self.spy_sma[0]

        crossover = self.ema_fast[0] > self.ema_slow[0] and self.ema_fast[-1] <= self.ema_slow[-1]
        adx_strong = self.adx[0] > self.params.adx_threshold

        if not self.position:
            if crossover and adx_strong and market_bullish:
                price = self.data0.close[0]
                stop_price = price - self.params.stop_points
                target_price = price + self.params.target_points

                # Entrar comprando con OCO (Stop Loss y Take Profit fijos)
                self.order = self.buy(size=self.params.contracts)
                self.sell(size=self.params.contracts, price=stop_price, exectype=bt.Order.Stop, oco=self.order)
                self.sell(size=self.params.contracts, price=target_price, exectype=bt.Order.Limit, oco=self.order)

# -----------------------------------------------------------------------------
# Analizador de Reglas de Fondeo (LucidFlex $50K)
# -----------------------------------------------------------------------------
class LucidFlexAnalyzer(bt.Analyzer):
    params = (
        ('initial_cash', 50000.0),
        ('max_drawdown_limit', 2000.0),
        ('target_profit', 3000.0),
        ('consistency_limit_pct', 0.50),
    )

    def __init__(self):
        self.start_cash = self.params.initial_cash
        self.max_dd_limit = self.params.max_drawdown_limit
        self.target = self.params.target_profit
        self.consistency_pct = self.params.consistency_limit_pct

        self.peak_value = self.start_cash
        self.max_eod_drawdown = 0.0
        self.failed_drawdown = False
        self.passed_target = False
        self.daily_pnls = []
        self.prev_value = self.start_cash

    def next(self):
        current_val = self.strategy.broker.getvalue()
        
        daily_pnl = current_val - self.prev_value
        self.daily_pnls.append(daily_pnl)
        self.prev_value = current_val

        if current_val > self.peak_value:
            self.peak_value = current_val
        
        current_dd = self.peak_value - current_val
        if current_dd > self.max_eod_drawdown:
            self.max_eod_drawdown = current_dd

        if current_dd >= self.max_dd_limit:
            self.failed_drawdown = True

        if (current_val - self.start_cash) >= self.target:
            self.passed_target = True

    def get_analysis(self):
        total_pnl = self.strategy.broker.getvalue() - self.start_cash
        max_single_day = max(self.daily_pnls) if self.daily_pnls else 0.0
        
        consistency_violated = False
        if total_pnl > 0 and max_single_day > 0:
            if (max_single_day / total_pnl) > self.consistency_pct:
                consistency_violated = True

        return {
            'failed_drawdown': self.failed_drawdown,
            'passed_target': self.passed_target,
            'max_eod_drawdown': self.max_eod_drawdown,
            'max_single_day_pnl': max_single_day,
            'consistency_violated': consistency_violated,
            'total_pnl': total_pnl
        }

# -----------------------------------------------------------------------------
# Función de Descarga de Datos
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
# Barra Lateral
# -----------------------------------------------------------------------------
st.sidebar.header("Parámetros del Sistema")

catalog_symbols = [
    "MNQ=F", "NQ=F", "MES=F", "ES=F", "SPY", "QQQ", "^NDX", "^GSPC"
]

custom_symbol = st.sidebar.text_input("Ticker personalizado (ej: MNQ=F):", "").strip().upper()
available_options = catalog_symbols.copy()
if custom_symbol and custom_symbol not in available_options:
    available_options.append(custom_symbol)

default_selections = ["MNQ=F"]
if custom_symbol and custom_symbol not in default_selections:
    default_selections.append(custom_symbol)

selected_symbols = st.sidebar.multiselect(
    "Selecciona los activos a evaluar:",
    options=available_options,
    default=default_selections
)

st.sidebar.subheader("Modo Prop Firm (LucidFlex $50K)")
enable_prop_sim = st.sidebar.checkbox("Simular Reglas LucidFlex $50K", value=True)

if enable_prop_sim:
    prop_capital = 50000.0
else:
    prop_capital = st.sidebar.number_input("Capital Inicial ($)", value=10000, step=1000)

num_contracts = st.sidebar.number_input("Número de Contratos Futuros", min_value=1, max_value=10, value=2, step=1)

st.sidebar.subheader("Gestión de Riesgo (Puntos)")
stop_points = st.sidebar.number_input("Stop Loss (en puntos NQ)", min_value=10, max_value=300, value=50, step=5)
target_points = st.sidebar.number_input("Take Profit (en puntos NQ)", min_value=20, max_value=600, value=150, step=10)

st.sidebar.subheader("Indicadores")
ema_fast = st.sidebar.slider("EMA Rápida", 5, 50, 16)
ema_slow = st.sidebar.slider("EMA Lenta", 20, 100, 35)
adx_threshold = st.sidebar.slider("Umbral ADX Mínimo", 10.0, 40.0, 20.0, step=1.0)

run_button = st.sidebar.button("Ejecutar Simulación")

if "executed" not in st.session_state:
    st.session_state.executed = False

if run_button:
    st.session_state.executed = True

# -----------------------------------------------------------------------------
# Renderizado de Resultados
# -----------------------------------------------------------------------------
if st.session_state.executed:
    if not selected_symbols:
        st.warning("Selecciona al menos un activo en la barra lateral.")
    else:
        with st.spinner("Procesando simulación cuantitativa y auditoría de reglas..."):
            loaded_data = {}
            start_dates = {}

            for sym in selected_symbols:
                df = fetch_data(sym)
                if df is not None and not df.empty:
                    loaded_data[sym] = df
                    start_dates[sym] = df.index[0]

            data_spy = fetch_data("SPY")

            if not loaded_data:
                st.error("No se pudieron cargar los datos del activo seleccionado.")
            else:
                latest_start_symbol = max(start_dates, key=start_dates.get)
                common_start_date = start_dates[latest_start_symbol]
                common_start_str = common_start_date.strftime('%Y-%m-%d')

                if len(loaded_data) > 1:
                    st.subheader(f"🔄 Comparativa de Rendimiento (%) desde {common_start_str}")
                    fig_comp = go.Figure()

                    for sym, df_asset in loaded_data.items():
                        df_trimmed = df_asset.loc[df_asset.index >= common_start_date]
                        if not df_trimmed.empty:
                            base_price = df_trimmed['Close'].iloc[0]
                            pct_change = ((df_trimmed['Close'] - base_price) / base_price) * 100
                            fig_comp.add_trace(go.Scatter(x=df_trimmed.index, y=pct_change, mode='lines', name=f"{sym} (%)"))

                    fig_comp.update_layout(
                        template="plotly_dark",
                        height=450,
                        margin=dict(l=20, r=20, t=40, b=20),
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_comp, use_container_width=True)

                st.markdown("---")
                st.header("📋 Auditoría de Reglas de Fondeo e Informes Individuales")

                for sym, data_asset in loaded_data.items():
                    st.subheader(f"📊 Resultado para {sym}")

                    try:
                        cerebro = bt.Cerebro()
                        cerebro.broker.setcash(prop_capital)
                        cerebro.broker.set_coc(True)

                        if "MNQ=F" in sym:
                            contract_mult = 2.0
                        elif "NQ=F" in sym:
                            contract_mult = 20.0
                        elif "MES=F" in sym:
                            contract_mult = 5.0
                        elif "ES=F" in sym:
                            contract_mult = 50.0
                        else:
                            contract_mult = 1.0

                        cerebro.broker.setcommission(
                            commission=2.50,
                            mult=contract_mult,
                            margin=1000.0
                        )

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
                            stop_points=stop_points,
                            target_points=target_points,
                            contracts=num_contracts
                        )

                        if enable_prop_sim:
                            cerebro.addanalyzer(LucidFlexAnalyzer, _name='lucid')

                        results = cerebro.run()
                        strat = results[0]

                        final_val = cerebro.broker.getvalue()
                        pnl = final_val - prop_capital
                        ret_pct = (pnl / prop_capital) * 100

                        if enable_prop_sim:
                            lucid_res = strat.analyzers.lucid.get_analysis()

                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Capital Final", f"${final_val:,.2f}")
                            c2.metric("P&L Total", f"${pnl:,.2f}", f"{ret_pct:.2f}%")
                            c3.metric("Max Drawdown EOD", f"${lucid_res['max_eod_drawdown']:,.2f}")
                            c4.metric("Máx. Ganancia en 1 Día", f"${lucid_res['max_single_day_pnl']:,.2f}")

                            if lucid_res['failed_drawdown']:
                                st.error(f"❌ **REGLA VIOLADA:** La estrategia superó el límite de Drawdown EOD de $2,000 (Pérdida máxima registrada: ${lucid_res['max_eod_drawdown']:,.2f}).")
                            else:
                                st.success("✅ **DRAWDOWN EOD RESPETADO:** La estrategia nunca superó la pérdida permitida de $2,000.")

                            if lucid_res['consistency_violated']:
                                st.warning("⚠️ **INCONSISTENCIA DE GANANCIAS:** Un solo día de trading representó más del 50% de las ganancias totales acumuladas.")
                            else:
                                st.info("✅ **REGLA DE CONSISTENCIA CUMPLIDA:** La distribución de ganancias diarias respeta el límite del 50%.")

                            if lucid_res['passed_target']:
                                st.balloons()
                                st.success("🎉 **OBJETIVO ALCANZADO:** El algoritmo logró superar el Profit Target de $3,000 requeridos por LucidFlex.")
                        else:
                            c1, c2 = st.columns(2)
                            c1.metric("Capital Final", f"${final_val:,.2f}")
                            c2.metric("P&L Total", f"${pnl:,.2f}", f"{ret_pct:.2f}%")

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
                            title=f"Evolución de Precio e Indicadores - {sym}",
                            xaxis_rangeslider_visible=False,
                            template="plotly_dark",
                            height=420,
                            margin=dict(l=20, r=20, t=40, b=20)
                        )

                        st.plotly_chart(fig_ind, use_container_width=True)

                    except Exception as err:
                        st.error(f"Error al ejecutar el backtest para {sym}: {err}")

                    st.markdown("---")
else:
    st.info("Configura las opciones en la barra lateral y presiona **Ejecutar Simulación**.")