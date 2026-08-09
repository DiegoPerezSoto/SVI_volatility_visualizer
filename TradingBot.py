import os
import time
import numpy as np
import pandas as pd
from datetime import datetime
from ib_insync import IB, Stock

# 🎯 IMPORTAMOS TUS COMPONENTES LOCALES
from GestorSuscripciones import GestorSuscripciones
from PortfolioManager import PortfolioManager
from GestorVolatilidad import GestorVolatilidad

#This file coordinates the interfazed and the main loop trading bot
class TerminalUI:
    def __init__(self, symbol):
        self.symbol = symbol

    def limpiar_pantalla(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def dibujar(self, current_price, open_price, fecha_apertura, vencimientos, df_radar, bot):
        self.limpiar_pantalla()
        diff     = current_price - open_price
        diff_pct = (diff / open_price * 100) if open_price > 0 else 0

        print("=" * 124)
        print(f"    QUANT LAB | TERMINAL IBKR  |  RELOJ: {datetime.now().strftime('%H:%M:%S.%f')[:-4]}")
        print("=" * 124)
        print(f" [ ASSET TRACKER: {self.symbol} ]")
        print(f" CURRENT: ${current_price:,.2f} ({diff_pct:+.2f}%)   |   OPEN: ${open_price:,.2f} ({fecha_apertura})")
        print("-" * 124)
        print(" [ PORTFOLIO RISK INFO ]")
        print(f" TOTAL EQUITY: ${bot.portfoliomanager.capital_total:,.2f} | "
              f"AVAILABLE: ${bot.portfoliomanager.disponible:,.2f} | "
              f"EXCESS LIQ: ${bot.portfoliomanager.exceso_liq:,.2f}")
        print(f" SUSCRIPCIONES ACTIVAS: {bot.suscripciones.total_suscripciones()}/100")
        print()

        if bot.portfoliomanager.analisis:
            print(f" {'SÍMBOLO':<12} | {'TIPO':<4} | {'VENCIM.':<10} | {'CANT':^6} | {'PRECIO':>8} | {'COSTE':>8} | {'PnL $':>10} | {'PnL %':>8}")
            for pos in bot.portfoliomanager.analisis:
                flecha = "▲" if pos['pnl'] >= 0 else "▼"
                print(f" {flecha} {pos['simbolo']:<10} | {pos['tipo']:<4} | {pos['venc']:<10} | {pos['cantidad']:^6.1f} | "
                      f"${pos['actual']:>7.2f} | ${pos['coste']:>7.2f} | "
                      f"${pos['pnl']:>9.2f} | {pos['pct']:>+7.2f}%")
        else:
            print(" [ No hay posiciones abiertas ]")

        print(" Δ Delta: 0.52   Γ Gamma: 0.12   σ Vol: 28.1%")
        print("-" * 124)
        
        if df_radar:
            for fecha, df in df_radar.items():
                print(f"\n [ OPTION RADAR | VENCIMIENTO: {fecha} ]")
                print("═" * 124)
                
                # 1. Hacemos una copia y duplicamos la columna de IV para el lado de las Calls
                df_copia = df.copy()
                if "IV-SVI" in df_copia.columns:
                    df_copia["IV-SVI-C"] = df_copia["IV-SVI"]  # Creamos el clon para la izquierda
                
                # 2. Ahora sí, la lista tiene 15 columnas simétricas
                columnas_espejo = [
                    "C-Z", "C-OBI", "C-Sprd", "C-IVR", "IV-SVI-C", "C-Bid", "C-Ask", 
                    "STRIKE", 
                    "P-Bid", "P-Ask", "P-IVR", "IV-SVI", "P-Sprd", "P-OBI", "P-Z"
                ]
                
                df_ordenado = df_copia[[col for col in columnas_espejo if col in df_copia.columns]].copy()
                
                # 3. Mapeamos los 15 títulos exactos (¡aquí estaba el descuadre!)
                df_ordenado.columns = [
                    "  C-Z ", " C-OBI", "C-Sprd", " C-IVR", "IV-SVI", " C-Bid", "  CALLS │", 
                    "STRIKE", 
                    "│ PUTS  ", " P-Ask", " P-IVR", "IV-SVI", "P-Sprd", " P-OBI", "  P-Z "
                ]
                
                # 4. Redondeamos de forma segura
                for col in df_ordenado.columns:
                    try:
                        df_ordenado[col] = df_ordenado[col].round(2)
                    except:
                        pass
                
                # 5. Imprimimos el espejo perfecto
                print(df_ordenado.to_string(index=False))
                print("═" * 124)
        else:
            print(" Esperando apertura de mercado o datos iniciales...")

        print("=" * 124)
        print(f" [ SYSTEM LOG ] -> STREAMING MODE ACTIVO")


class TradingBot:
    def __init__(self, host, puerto, client_id, symbol, r_interes, div_yield):
        self.host      = host
        self.puerto    = puerto
        self.client_id = client_id
        self.symbol    = symbol
        self.r_interes = r_interes
        self.div_yield = div_yield

        self.apertura       = 0
        self.fecha_apertura = 'N/A'
        self.subyacente     = None

        self.ib          = IB()
        self.ui          = TerminalUI(symbol)

    def conectar(self):
        print("Iniciando conexión con IBKR...")
        try:
            self.ib.connect(self.host, self.puerto, self.client_id, timeout=15)
            self.suscripciones   = GestorSuscripciones(self.ib)
            self.portfoliomanager = PortfolioManager(self.ib, self.suscripciones)
            self.volatilidad     = GestorVolatilidad(
                self.symbol, self.ib, self.suscripciones, self.r_interes, self.div_yield
            )
            print("Conectado.")
        except Exception as e:
            print(f"Error conectando a IBKR: {e}")

    def inicializar(self):
        self.portfoliomanager.actualizar_portfolio()
        stock = Stock(self.symbol, 'SMART', 'USD')
        self.ib.qualifyContracts(stock)

        try:
            bars = self.ib.reqHistoricalData(stock, '', '1 D', '1 day', 'TRADES', True)
            if bars:
                self.apertura       = float(bars[-1].open)
                self.fecha_apertura = bars[-1].date.strftime('%d-%m-%Y')
        except:
            pass

        self.subyacente = self.suscripciones.suscribir(stock, 'subyacente')
        self.ib.sleep(2)

    def ejecucion(self):
        try:
            while True:
                self.ib.sleep(0.5)
                self.portfoliomanager.actualizar_portfolio()
                self.volatilidad.crear_radar(self.subyacente)

                last = self.subyacente.last
                close = self.subyacente.close
                current_price = float(last if last and not np.isnan(last) else close)

                self.ui.dibujar(
                    current_price,
                    self.apertura,
                    self.fecha_apertura,
                    self.volatilidad.fecha_vencimientos,
                    self.volatilidad.df_radar,
                    self,
                )
        except KeyboardInterrupt:
            print("\nApagando terminal de forma segura...")
            self.ib.disconnect()
        except Exception as e:
            print(f"\n[!] Error: {e}")
            self.ib.sleep(1)

    def iniciar(self):
        self.conectar()
        self.inicializar()
        self.ejecucion()