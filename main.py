import nest_asyncio
import pandas as pd
from TradingBot import TradingBot

"""
Pequeño resumen para el githuib

git add GestorVolatilidad.py  // git add .

git commit -m "lo que quiera que ponga en el commit"

git push 

esos 3 comandos y ya
"""

# Configuraciones globales de entorno
nest_asyncio.apply()
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.colheader_justify', 'center')

if __name__ == '__main__':
    bot = TradingBot(
        host='127.0.0.1',
        puerto=7497, # Cambiar a 4002 para IB Gateway en producción
        client_id=20,
        symbol='NVDA',
        r_interes=0.043,
        div_yield=0.0,
    )
    bot.iniciar()