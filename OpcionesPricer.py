import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize
from datetime import datetime

class OpcionesPricer:
    """Clase estática: Solo recibe datos, calcula y devuelve resultados. No guarda estado."""

    @staticmethod
    def calcular_d1(S, E, t, r, sigma, D):
        sigma, t = max(sigma, 0.0001), max(t, 0.000001)
        return (np.log(S / E) + (r - D + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))

    @staticmethod
    def calcular_d2(d1, sigma, t):
        return d1 - max(sigma, 0.0001) * np.sqrt(max(t, 0.000001))

    @staticmethod
    def theorical_price_call(S, E, t, r, sigma, D):
        d1 = OpcionesPricer.calcular_d1(S, E, t, r, sigma, D)
        d2 = OpcionesPricer.calcular_d2(d1, sigma, t)
        return S * np.exp(-D * t) * norm.cdf(d1) - (E * np.exp(-r * t) * norm.cdf(d2))

    @staticmethod
    def theorical_price_put(S, E, t, r, sigma, D):
        d1 = OpcionesPricer.calcular_d1(S, E, t, r, sigma, D)
        d2 = OpcionesPricer.calcular_d2(d1, sigma, t)
        return (E * np.exp(-r * t) * norm.cdf(-d2)) - (S * np.exp(-D * t) * norm.cdf(-d1))

    @staticmethod
    def calcular_vega(S, E, t, r, sigma, D):
        d1 = OpcionesPricer.calcular_d1(S, E, t, r, sigma, D)
        return S * np.sqrt(max(t, 0.000001)) * np.exp(-D * t) * norm.pdf(d1)

    @staticmethod
    def calcular_gamma(S, E, t, r, sigma, D):
        d1 = OpcionesPricer.calcular_d1(S, E, t, r, sigma, D)
        return norm.pdf(d1) / (S * max(sigma, 0.0001) * np.sqrt(max(t, 0.000001)))

    @staticmethod
    def hallar_iv_biseccion(precio_mercado, S, E, T, r, D, right): 
        valor_minimo = max(0, S - E) if right == 'C' else max(0, E - S)
        if precio_mercado <= valor_minimo or np.isnan(precio_mercado):
            return 0.001
            
        bajo, alto = 0.001, 4.0
        for _ in range(30):
            mid = (bajo + alto) / 2
            if right == 'C':
                p_teorico = OpcionesPricer.theorical_price_call(S, E, T, r, mid, D)
            else:
                p_teorico = OpcionesPricer.theorical_price_put(S, E, T, r, mid, D)
                
            if p_teorico > precio_mercado:
                alto = mid
            else:
                bajo = mid
            if (alto - bajo) < 1e-5:
                break
        return mid

    @staticmethod
    def calcular_t(fecha_str):
        fecha = datetime.strptime(fecha_str, '%Y%m%d')
        dias  = (fecha - datetime.now()).days + ((fecha - datetime.now()).seconds / 86400)
        return max(dias / 365, 0.000001)

    @staticmethod
    def formula_svi(k, a, b, rho, m, sigma):
        return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))
    
    @staticmethod
    def _error_svi_objetivo(params, k_arr, w_real):
        a, b, rho, m, sigma = params
        w_teorica = OpcionesPricer.formula_svi(k_arr, a, b, rho, m, sigma)
        return np.sum((w_real - w_teorica) ** 2)

    @staticmethod
    def calibrar_svi(strikes, ivs, S, T):
        strikes_arr = np.array(strikes)
        ivs_arr = np.array(ivs)
        k_arr = np.log(strikes_arr / S)
        w_real = (ivs_arr**2) * T

        x0 = [0.1 * T, 0.1, 0.0, 0.0, 0.1]
        bounds = [(1e-5, None), (0.0, 5.0), (-0.99, 0.99), (-2.0, 2.0), (1e-5, 1.0)]

        resultado = minimize(
            OpcionesPricer._error_svi_objetivo, 
            x0, 
            args=(k_arr, w_real), 
            method='L-BFGS-B', 
            bounds=bounds
        )
        
        if resultado.success:
            a_opt, b_opt, rho_opt, m_opt, sigma_opt = resultado.x
            w_opt = OpcionesPricer.formula_svi(k_arr, a_opt, b_opt, rho_opt, m_opt, sigma_opt)
            iv_teorica = np.sqrt(np.maximum(w_opt, 0) / T)
            return iv_teorica, resultado.x
        else:
            coeficientes = np.polyfit(strikes_arr, ivs_arr, 2)
            return np.polyval(coeficientes, strikes_arr), None