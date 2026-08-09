class GestorSuscripciones:
    def __init__(self, ib_instancia):
        self.ib = ib_instancia
        self._suscripciones = {} #diccionario doble ponemos el id luego tenemos dos posibilidades owners o ticker, en ticker esta el objeto de datos y owners es un conjunto

    def suscribir(self, contract, owner):
        cid = contract.conId
        if cid in self._suscripciones:
            self._suscripciones[cid]['owners'].add(owner)
            return self._suscripciones[cid]['ticker']
            
        ticker = self.ib.reqMktData(contract, '', False, False)
        self._suscripciones[cid] = {'ticker': ticker, 'owners': {owner}}
        return ticker

    def cancelar(self, contract):
        cid = contract.conId
        if cid in self._suscripciones:
            self.ib.cancelMktData(contract)
            del self._suscripciones[cid]

    def cancelar_por_owner(self, owner):
        cids_a_borrar = []
        for cid, v in self._suscripciones.items():
            if owner in v['owners']:
                v['owners'].remove(owner)
                if not v['owners']:
                    cids_a_borrar.append(cid)
        
        for cid in cids_a_borrar:
            ticker = self._suscripciones[cid]['ticker']
            self.ib.cancelMktData(ticker.contract)
            del self._suscripciones[cid]

    def get_ticker(self, contract):
        return self._suscripciones.get(contract.conId, {}).get('ticker', None)

    def total_suscripciones(self):
        return len(self._suscripciones)