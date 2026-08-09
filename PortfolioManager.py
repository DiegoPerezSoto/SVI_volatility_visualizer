import numpy as np

class PortfolioManager:
    """Gestiona balance y posiciones abiertas."""

    def __init__(self, ib_instancia, gestor_suscripciones):
        self.ib              = ib_instancia
        self.suscripciones   = gestor_suscripciones
        self.capital_total   = 0
        self.disponible      = 0
        self.exceso_liq      = 0
        self.analisis        = []

    def actualizar_balance(self):
        try:
            etiquetas = ['NetLiquidation', 'AvailableFunds', 'ExcessLiquidity']
            resumen   = self.ib.accountSummary()
            datos     = {item.tag: item.value for item in resumen if item.tag in etiquetas}

            self.capital_total = float(datos.get('NetLiquidation', 0))
            self.disponible    = float(datos.get('AvailableFunds', 0))
            self.exceso_liq    = float(datos.get('ExcessLiquidity', 0))
        except Exception as e:
            print(f"Error actualizando balance: {e}")

    def analizar_posiciones(self):
        """Descarga posiciones, gestiona suscripciones y calcula métricas."""
        try:
            raw_posiciones = self.ib.positions()
            
            contratos_pos = []
            for p in raw_posiciones:
                p.contract.exchange = 'SMART'
                contratos_pos.append(p.contract)
            
            if contratos_pos:
                self.ib.qualifyContracts(*contratos_pos)

            ids_actuales = {p.contract.conId for p in raw_posiciones}
            subs_portfolio = {
                cid for cid, v in self.suscripciones._suscripciones.items()
                if 'portfolio' in v['owners']
            }
            
            for cid in subs_portfolio - ids_actuales:
                carpeta = self.suscripciones._suscripciones.get(cid)
                if carpeta and 'portfolio' in carpeta['owners']:
                    carpeta['owners'].remove('portfolio')
                    if not carpeta['owners']:
                        self.ib.cancelMktData(carpeta['ticker'].contract)
                        del self.suscripciones._suscripciones[cid]

            self.analisis = []

            for p in raw_posiciones:
                ticker = self.suscripciones.suscribir(p.contract, 'portfolio')

                precio_actual = ticker.last
                if np.isnan(precio_actual) or precio_actual <= 0:
                    precio_actual = ticker.close
                
                aviso = ""
                if np.isnan(precio_actual) or precio_actual <= 0:
                    precio_actual = p.avgCost
                    aviso = "*"

                if p.contract.multiplier and p.contract.multiplier.isdigit():
                    multiplicador = float(p.contract.multiplier)
                else:
                    multiplicador = 1.0

                valor_mercado = precio_actual * p.position * multiplicador
                coste_total   = p.avgCost * p.position * multiplicador
                pnl           = valor_mercado - coste_total
                porcentaje    = (pnl / coste_total * 100) if coste_total > 0 else 0

                if p.contract.secType == 'OPT':
                    tipo = "CALL" if p.contract.right == 'C' else "PUT"
                    v = p.contract.lastTradeDateOrContractMonth
                    vencimiento = f"{v[:4]}-{v[4:6]}-{v[6:]}" if len(v) == 8 else v
                    simbolo_limpio = f"{p.contract.symbol} {p.contract.strike}"
                else:
                    tipo = "STK"
                    vencimiento = "N/A"
                    simbolo_limpio = p.contract.symbol

                self.analisis.append({
                    'simbolo':  simbolo_limpio + aviso,
                    'tipo':     tipo,
                    'venc':     vencimiento,
                    'cantidad': p.position,
                    'coste':    p.avgCost,
                    'actual':   precio_actual,
                    'pnl':      pnl,
                    'pct':      porcentaje,
                })
        except Exception as e:
            print(f"Error al procesar posiciones: {e}")
            
    def actualizar_portfolio(self):
        self.actualizar_balance()
        self.analizar_posiciones()