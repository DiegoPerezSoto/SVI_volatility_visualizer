import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy.stats import norm
from collections import deque, defaultdict
from ib_insync import Option
import yfinance as yf
from arch import arch_model

# 🎯 IMPORTAMOS TU MODULO MATEMÁTICO
from OpcionesPricer import OpcionesPricer

class GestorVolatilidad:
    def __init__(self, symbol, ib_instancia, gestor_suscripciones, r_interes, div_yield):
        self.symbol              = symbol
        self.ib                  = ib_instancia
        self.suscripciones       = gestor_suscripciones
        self.r_interes           = r_interes
        self.div_yield           = div_yield

        self.memoria_residuos = defaultdict(lambda: deque(maxlen=4000)) #diccionario con clave triples y dentro array deque 
        self.periodo_calentamiento = 30

        self.__valor_cache       = 0.333
        self.__timestamp_cache   = 0
        self.cached_contracts    = {} # clave fecha ->  tengo una lista de contratos por cada fecha
        self.last_chain_update   = 0
        self.df_radar            = {} # clave fecha -> un pandas date frame por cada una de las fechas del diccionario 
        self.fecha_vencimientos  = [] # array de las fechas 

    def obtener_vol_garch(self):
        ahora = time.time()
        if ahora - self.__timestamp_cache > 900:
            try:
                df = yf.download(self.symbol, period="1mo", interval="5m", progress=False)
                if not df.empty:
                    retornos = 100 * np.log(df['Close'] / df['Close'].shift(1)).dropna()
                    var = (
                        arch_model(retornos, vol='Garch', p=1, q=1, dist='t')
                        .fit(disp='off')
                        .forecast(horizon=1)
                        .variance.values[-1, 0]
                    )
                    self.__valor_cache    = np.sqrt(var * 12 * 6.5 * 252) / 100
                    self.__timestamp_cache = ahora
            except:
                pass
        return self.__valor_cache

    def _actualizar_contratos_radar(self, ticker_stock, current_price):
        self.suscripciones.cancelar_por_owner('radar')
        c = ticker_stock.contract
        chains = self.ib.reqSecDefOptParams(c.symbol, '', c.secType, c.conId)
        chain  = next((ch for ch in chains if ch.exchange == 'SMART'), None)

        if not chain:
            return

        objetivo = datetime.now() + timedelta(days=6)
        while objetivo.weekday() != 4:
            objetivo += timedelta(days=1)
        target = objetivo.strftime('%Y%m%d')

        exps_validas           = [e for e in sorted(chain.expirations) if e >= target]
        self.fecha_vencimientos = exps_validas[:4] if exps_validas else sorted(chain.expirations)[-4:] #aqui tendria que poner para que fuese los 5 ultimos en el else ya puesto

        # limpiamos el diccionario de los self 
        self.cached_contracts = {}
        strikes_atm            = sorted(chain.strikes, key=lambda x: abs(x - current_price))[:35]
        strikes_ordenados      = sorted(strikes_atm)

        for exp in self.fecha_vencimientos:
            # Creamos candidatos para AMBOS lados (Call y Put) para todos los strikes de la red grande
            candidatos_call = [Option(self.symbol, exp, s, 'C', 'SMART') for s in strikes_ordenados] 
            candidatos_put = [Option(self.symbol, exp, s, 'P', 'SMART') for s in strikes_ordenados]
            candidatos = candidatos_call + candidatos_put 
            
        
            contratos_validos = self.ib.qualifyContracts(*candidatos)
            
    
            contratos_ordenados = sorted(contratos_validos, key=lambda x: abs(x.strike - current_price))
            
            # Pongo esta logica para que se vayan añadiendo pero siempre maximo 10 strikes
            strikes_finales = []
            for cont in contratos_ordenados:
                if cont.strike not in strikes_finales:
                    strikes_finales.append(cont.strike)
                if len(strikes_finales) == 10: # Ya tenemos los 10 strikes más cercanos y líquidos
                    break
            
            # Guardamos únicamente las parejas  cally put
            top_20_contratos = [c for c in contratos_validos if c.strike in strikes_finales]
            
            # Los ordenamos por strike de menor a mayor para q kla tabla quede bien, doble clave primero strike luego el tipo asi interacalmos calls y puts 
            self.cached_contracts[exp] = sorted(top_20_contratos, key=lambda x: (x.strike, x.right))

  
            for cont in self.cached_contracts[exp]:
                self.suscripciones.suscribir(cont, 'radar')


    def _procesar_calculos_radar(self, current_price):
        if not self.fecha_vencimientos or not self.cached_contracts:
            return
        
        # Inicializamos el diccionario de DataFrames
        self.df_radar = {} 

        # Bucle principal por cada fecha de vencimiento
        for exp in self.fecha_vencimientos:
            contracts_esa_fecha = self.cached_contracts.get(exp, [])
            if not contracts_esa_fecha: 
                continue

            t_val = OpcionesPricer.calcular_t(exp)
            
            strikes_validos = []
            ivs_validas = []
            dicc_strikes = defaultdict(dict) # organiza por strike y tipo tenemos aqui un triple dcionari anidado 

            for contract in contracts_esa_fecha:
                ticker = self.suscripciones.get_ticker(contract)
                if ticker is None:
                    continue

                bid = float(ticker.bid) if ticker.bid and not np.isnan(ticker.bid) else 0.0
                ask = float(ticker.ask) if ticker.ask and not np.isnan(ticker.ask) else 0.0
                
                if bid <= 0 and ask <= 0:
                    continue

                op_price = (bid + ask) / 2
                strike = contract.strike
                tipo = contract.right

                bid_size = float(ticker.bidSize) if ticker.bidSize and not np.isnan(ticker.bidSize) else 0.0
                ask_size = float(ticker.askSize) if ticker.askSize and not np.isnan(ticker.askSize) else 0.0

                total_size = bid_size + ask_size
                obi = (bid_size - ask_size) / total_size if total_size > 0 else 0
               

                iv_dec = max(
                    OpcionesPricer.hallar_iv_biseccion(
                        op_price, current_price, strike, t_val, self.r_interes, self.div_yield, tipo
                    ), 0.0001
                )
                
             
                sprd_pct = (ask - bid) / bid * 100 if bid > 0 else 0.0
                
                dicc_strikes[strike][tipo] = {
                    "bid": bid, "ask": ask, "iv_real": iv_dec, "obi": obi, "sprd_pct": sprd_pct
                }

                # el svi solo usa opciones out of the money
                if (tipo == 'C' and strike >= current_price) or (tipo == 'P' and strike < current_price):
                    if strike not in strikes_validos:
                        strikes_validos.append(strike)
                        ivs_validas.append(iv_dec)

            if len(strikes_validos) < 5: 
                continue 

            # Ordenamos e indexación de los arrays antes de la calibración
            indices_ordenados = np.argsort(strikes_validos) #nos da la lista de las posiciones ordenadas
            strikes_svi_ord = [strikes_validos[i] for i in indices_ordenados]
            ivs_svi_ord = [ivs_validas[i] for i in indices_ordenados]
            #con eto conseguimos ordenar strikes sin perder el orden respecto a la iv 

            
            _, params_svi = OpcionesPricer.calibrar_svi(strikes_svi_ord, ivs_svi_ord, current_price, t_val)
            
            # Recorremos el diccionario creado para montar la tabla de straddle
            datos_finales = []
            for strike in sorted(dicc_strikes.keys()):
                info_strike = dicc_strikes[strike]  #esto seria como un doble diccionario 
                
                
                if params_svi is not None:
                    k_val = np.log(strike / current_price)
                    a_opt, b_opt, rho_opt, m_opt, sigma_opt = params_svi
                    w_teorica = OpcionesPricer.formula_svi(k_val, a_opt, b_opt, rho_opt, m_opt, sigma_opt)
                    iv_teorica = np.sqrt(max(w_teorica, 0) / t_val)

                # --- PROCESAMOS LADO CALL ---
                call_z, call_alerta, call_str_obi, call_str_sprd = 0.0, "", "0.00 ⚪", "0.0%"
                if "C" in info_strike:
                    c_data = info_strike["C"]
                    residuo_c = c_data["iv_real"] - iv_teorica
                    
                    #clave triple con una tupla 
                    clave_mem = (exp, strike, "C")
                    self.memoria_residuos[clave_mem].append(residuo_c)
                    
                    if len(self.memoria_residuos[clave_mem]) >= self.periodo_calentamiento:
                        serie_res = pd.Series(list(self.memoria_residuos[clave_mem]))
                        ewm = serie_res.ewm(span=900) #usamso una media ewma exponential weighted movin average, priorizamos 600 ultimos ticks 
                        media_ewm = ewm.mean().iloc[-1]
                        std_ewm = ewm.std().iloc[-1]
                        
                        call_z = 0.0 if std_ewm == 0 else (residuo_c - media_ewm) / std_ewm
                        if call_z > 2.0 and c_data['sprd_pct'] < 15.0 and abs(residuo_c) > 0.015: call_alerta = "🔥"
                        elif call_z < -2.0 and c_data['sprd_pct'] < 15.0 and abs(residuo_c) > 0.015: call_alerta = "💎"
                    else:
                        call_alerta = "⏳"
                    
                    call_str_sprd = f"{c_data['sprd_pct']:.1f}%"
                    call_str_obi = f"+{c_data['obi']:.2f}" if c_data['obi'] > 0.4 else (f"{c_data['obi']:.2f}" if c_data['obi'] < -0.4 else f"{c_data['obi']:+.2f}")
                    #poenmos asi para que salga el mas pero que nunca salgan en 0 o en negativos 

                # --- PROCESAMOS LADO PUT ---
                put_z, put_alerta, put_str_obi, put_str_sprd = 0.0, "", "0.00 ⚪", "0.0%"
                if "P" in info_strike:
                    p_data = info_strike["P"]
                    residuo_p = p_data["iv_real"] - iv_teorica
                    
                    clave_mem = (exp, strike, "P")
                    self.memoria_residuos[clave_mem].append(residuo_p)
                    
                    if len(self.memoria_residuos[clave_mem]) >= self.periodo_calentamiento:
                        serie_res = pd.Series(list(self.memoria_residuos[clave_mem]))
                        ewm = serie_res.ewm(span=900) 
                        media_ewm = ewm.mean().iloc[-1] #la ultima media o desviacion
                        std_ewm = ewm.std().iloc[-1]
                        
                        put_z = 0.0 if std_ewm == 0 else (residuo_p - media_ewm) / std_ewm
                        if put_z > 2.0 and p_data['sprd_pct'] < 15.0 and abs(residuo_p) > 0.015: put_alerta = "🔥"
                        elif put_z < -2.0 and p_data['sprd_pct'] < 15.0 and abs(residuo_p) > 0.015: put_alerta = "💎"
                    else:
                        put_alerta = "⏳"
                    
                    put_str_sprd = f"{p_data['sprd_pct']:.1f}%"
                    put_str_obi = f"+{p_data['obi']:.2f}" if p_data['obi'] > 0.4 else (f"{p_data['obi']:.2f}" if p_data['obi'] < -0.4 else f"{p_data['obi']:+.2f}")

          
                datos_finales.append({
                    "C-Z":      f"{call_z:+.1f}{call_alerta}",
                    "C-OBI":    call_str_obi,
                    "C-Sprd":   call_str_sprd,
                    "C-IVR":    f"{info_strike['C']['iv_real']*100:.1f}%" if "C" in info_strike else "N/A",
                    "C-Bid":    f"{info_strike['C']['bid']:.2f}" if "C" in info_strike else "0.00",
                    "C-Ask":    f"{info_strike['C']['ask']:.2f}" if "C" in info_strike else "0.00",
                    "STRIKE":   f"{strike:.1f}", 
                    "P-Bid":    f"{info_strike['P']['bid']:.2f}" if "P" in info_strike else "0.00",
                    "P-Ask":    f"{info_strike['P']['ask']:.2f}" if "P" in info_strike else "0.00",
                    "P-IVR":    f"{info_strike['P']['iv_real']*100:.1f}%" if "P" in info_strike else "N/A",
                    "IV-SVI":   f"{iv_teorica*100:.1f}%", 
                    "P-Sprd":   put_str_sprd,
                    "P-OBI":    put_str_obi,
                    "P-Z":      f"{put_z:+.1f}{put_alerta}"
                })

            if datos_finales:
                self.df_radar[exp] = pd.DataFrame(datos_finales)


    def crear_radar(self, ticker_stock):
        ahora = time.time()
        if not ticker_stock or np.isnan(ticker_stock.marketPrice()):
            return

        current_price = ticker_stock.marketPrice()
        if np.isnan(current_price) or current_price <= 0:
            return

        if ahora - self.last_chain_update > 600 or not self.cached_contracts:
            self._actualizar_contratos_radar(ticker_stock, current_price)
            self.last_chain_update = ahora

        self._procesar_calculos_radar(current_price)