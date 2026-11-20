"""Pruebas de la version 1 (app/server.py), la que corre en Docker sobre el servidor propio.

Levantan el servidor real en un puerto libre de esta maquina y lo usan por HTTP,
igual que lo haria el navegador. No necesitan Docker ni cuenta de AWS.

    python3 tests/test_app.py -v
"""
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['DATOS'] = os.path.join(tempfile.mkdtemp(), 'tickets.db')

spec = importlib.util.spec_from_file_location('server', os.path.join(RAIZ, 'app', 'server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
server.log = lambda *a: None   # sin ruido en la salida de las pruebas

SIN_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TICKET = {'email': 'Ana@Empresa.com', 'titulo': 'PC lento', 'descripcion': 'Tarda mucho', 'prioridad': 'ALTA'}


class AppV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.db = server.abrir_bd()
        server.sembrar()
        threading.Thread(target=server.trabajador, daemon=True).start()
        cls.srv = server.Servidor(('127.0.0.1', 0), server.Manejador)
        cls.base = f'http://127.0.0.1:{cls.srv.server_address[1]}'
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def llamar(self, metodo, ruta, cuerpo=None):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo,
                                     headers={'content-type': 'application/json'})
        try:
            with SIN_PROXY.open(req, timeout=5) as r:
                texto, codigo, tipo = r.read().decode(), r.status, r.headers.get('Content-Type', '')
        except urllib.error.HTTPError as e:
            texto, codigo, tipo = e.read().decode(), e.code, e.headers.get('Content-Type', '')
        return codigo, json.loads(texto) if 'json' in tipo else texto

    def crear_y_esperar(self, **cambios):
        codigo, r = self.llamar('POST', '/tickets', {**TICKET, **cambios})
        self.assertEqual(codigo, 202)
        for _ in range(100):   # el guardado es asincronico: lo hace el hilo trabajador
            if self.llamar('GET', '/tickets/' + r['ticketId'])[0] == 200:
                return r['ticketId']
            time.sleep(0.02)
        self.fail('el trabajador no guardo el ticket')

    def test_sirve_la_pagina_y_su_configuracion(self):
        codigo, html = self.llamar('GET', '/')
        self.assertEqual(codigo, 200)
        self.assertIn('Mesa de Soporte TI', html)
        self.assertIn('location.origin', self.llamar('GET', '/config.js')[1])
        self.assertEqual(self.llamar('GET', '/salud')[1]['estado'], 'ok')

    def test_datos_de_prueba_y_metricas(self):
        codigo, m = self.llamar('GET', '/metricas')
        self.assertEqual(codigo, 200)
        self.assertGreaterEqual(m['total'], 14)
        self.assertEqual({a['agente'] for a in m['porAgente']} & {'carlos', 'diana', 'andres'},
                         {'carlos', 'diana', 'andres'})
        self.assertEqual([t['ticketId'] for t in m['slaVencidos']], ['T-SEED010', 'T-SEED011'])

    def test_la_cola_sale_en_orden_de_llegada(self):
        _, cola = self.llamar('GET', '/tickets?estado=pendiente')
        fechas = [t['creadoEn'] for t in cola]
        self.assertEqual(fechas, sorted(fechas))
        self.assertEqual(cola[0]['ticketId'], 'T-SEED010')

    def test_flujo_completo_crear_tomar_resolver(self):
        tid = self.crear_y_esperar()
        self.assertEqual(self.llamar('GET', '/tickets/' + tid)[1]['estado'], 'PENDIENTE')
        tomar = {'accion': 'tomar', 'agente': 'Diana'}
        codigo, t = self.llamar('PATCH', '/tickets/' + tid, tomar)
        self.assertEqual((codigo, t['estado'], t['agente']), (200, 'EN_PROCESO', 'diana'))
        self.assertEqual(self.llamar('PATCH', '/tickets/' + tid, {'accion': 'tomar', 'agente': 'carlos'})[0], 409)
        self.assertEqual(self.llamar('PATCH', '/tickets/' + tid, {'accion': 'resolver', 'agente': 'carlos'})[0], 409)
        codigo, t = self.llamar('PATCH', '/tickets/' + tid,
                                {'accion': 'resolver', 'agente': 'diana', 'solucion': 'Mas memoria'})
        self.assertEqual((codigo, t['estado'], t['solucion']), (200, 'RESUELTO', 'Mas memoria'))
        _, mios = self.llamar('GET', '/tickets?email=ANA@empresa.com')
        self.assertIn(tid, [x['ticketId'] for x in mios])

    def test_validaciones(self):
        self.assertEqual(self.llamar('POST', '/tickets', {})[0], 400)
        self.assertEqual(self.llamar('POST', '/tickets', {**TICKET, 'email': 'sin-arroba'})[0], 400)
        self.assertEqual(self.llamar('POST', '/tickets', ['no', 'es', 'un', 'objeto'])[0], 400)
        self.assertEqual(self.llamar('POST', '/tickets', {**TICKET, 'categoria': ['HARDWARE']})[0], 202)
        server.cola.join()   # deja la cola vacia para no interferir con las demas pruebas
        tid = self.crear_y_esperar(titulo='Validaciones')
        self.assertEqual(self.llamar('PATCH', '/tickets/' + tid, {'accion': 'borrar', 'agente': 'x'})[0], 400)
        self.assertEqual(self.llamar('PATCH', '/tickets/' + tid, {'accion': 'tomar'})[0], 400)
        self.assertEqual(self.llamar('PATCH', '/tickets/T-NOEXISTE', {'accion': 'tomar', 'agente': 'x'})[0], 409)
        self.assertEqual(self.llamar('GET', '/tickets/T-NOEXISTE')[0], 404)
        self.assertEqual(self.llamar('GET', '/ruta-rara')[0], 404)

    def test_muchos_tickets_a_la_vez_no_se_pierden(self):
        antes = self.llamar('GET', '/metricas')[1]['total']
        codigos = []
        enviar = lambda i: codigos.append(self.llamar('POST', '/tickets', {**TICKET, 'titulo': f'Pico {i}'})[0])
        hilos = [threading.Thread(target=enviar, args=(i,)) for i in range(40)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(codigos, [202] * 40, 'las 40 peticiones simultaneas deben ser aceptadas')
        server.cola.join()   # espera a que el trabajador vacie la cola
        self.assertEqual(self.llamar('GET', '/metricas')[1]['total'], antes + 40)

    def test_sla_alerta_una_sola_vez(self):
        self.assertEqual(server.revisar_sla(), 2)
        self.assertEqual(server.revisar_sla(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
