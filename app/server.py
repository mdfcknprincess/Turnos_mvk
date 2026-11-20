"""Mesa de Soporte TI - VERSION 1 (hito "Servicio en linea": servidor propio + Docker).

Toda la aplicacion en UN solo proceso, pensado para correr en un contenedor:

    pieza de esta version               ->  en la version final (iac/main.yaml)
    ----------------------------------      -----------------------------------
    servidor web (pagina + API)         ->  S3 + API Gateway + Lambdas
    cola EN MEMORIA + hilo trabajador   ->  SQS (durable) + Lambda worker
    base de datos SQLite en un volumen  ->  DynamoDB
    hilo que revisa el SLA              ->  EventBridge + Lambda sla
    "correos" escritos en el log        ->  SNS

Expone la MISMA API y sirve la MISMA pagina que la version final.
Solo usa la biblioteca estandar de Python: no hay nada que instalar.

    python3 app/server.py                 # local, http://localhost:8080
    docker build -f app/Dockerfile -t soporte-ti . && docker run -p 8080:8080 soporte-ti
"""
import json
import os
import queue
import signal
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
PUERTO = int(os.environ.get('PUERTO', '8080'))
DATOS = os.environ.get('DATOS', os.path.join(AQUI, 'tickets.db'))
SLA_HORAS = float(os.environ.get('SLA_HORAS', '24'))
SLA_CADA_SEG = int(os.environ.get('SLA_CADA_SEG', '3600'))
# En la imagen Docker la pagina queda en ./web; en local se usa ../frontend
WEB = os.path.join(AQUI, 'web') if os.path.isdir(os.path.join(AQUI, 'web')) else os.path.join(AQUI, '..', 'frontend')

CATEGORIAS = {'HARDWARE', 'SOFTWARE', 'RED', 'ACCESOS', 'OTRO'}
PRIORIDADES = {'BAJA', 'MEDIA', 'ALTA'}
TEXTO_ESTADO = {'PENDIENTE': 'fue recibido: ya se encuentra en la cola de pendientes',
                'EN_PROCESO': 'fue tomado por un agente: ahora se encuentra EN PROCESO',
                'RESUELTO': 'fue RESUELTO'}

cola = queue.Queue()          # la cola de ingreso: vive en memoria (se pierde si el proceso muere)
candado = threading.Lock()    # SQLite se comparte entre hilos: un solo escritor a la vez
db = None


def log(*partes):
    print(*partes, flush=True)


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def horas(desde, hasta):
    return (datetime.fromisoformat(hasta) - datetime.fromisoformat(desde)).total_seconds() / 3600


# ----------------------------------------------------------------- base de datos
def abrir_bd():
    os.makedirs(os.path.dirname(DATOS) or '.', exist_ok=True)
    con = sqlite3.connect(DATOS, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS tickets (
        ticketId TEXT PRIMARY KEY, email TEXT, nombre TEXT, titulo TEXT, descripcion TEXT,
        categoria TEXT, prioridad TEXT, creadoEn TEXT, estado TEXT, agente TEXT,
        tomadoEn TEXT, resueltoEn TEXT, solucion TEXT, slaAlertado INTEGER DEFAULT 0)""")
    con.execute('CREATE INDEX IF NOT EXISTS porEstado ON tickets (estado, creadoEn)')
    con.execute('CREATE INDEX IF NOT EXISTS porEmail ON tickets (email, creadoEn)')
    con.commit()
    return con


def fila(r):
    d = {k: r[k] for k in r.keys() if r[k] is not None}
    d['slaAlertado'] = bool(d.get('slaAlertado'))
    return d


def consultar(sql, args=()):
    with candado:
        return [fila(r) for r in db.execute(sql, args).fetchall()]


def ejecutar(sql, args=()):
    """Ejecuta una escritura y devuelve cuantas filas cambio."""
    with candado:
        cur = db.execute(sql, args)
        db.commit()
        return cur.rowcount


def buscar(ticket_id):
    filas = consultar('SELECT * FROM tickets WHERE ticketId = ?', (ticket_id,))
    return filas[0] if filas else None


# ------------------------------------------------------------- datos de prueba
# (titulo, categoria, prioridad, usuario, creado hace h, tomado tras h, resuelto tras h, agente)
SEMILLA = [
    ('No enciende el computador', 'HARDWARE', 'ALTA', 'ana.gomez', 96, 1, 6, 'carlos'),
    ('Clave de correo bloqueada', 'ACCESOS', 'MEDIA', 'luis.perez', 90, 0.5, 1, 'diana'),
    ('Impresora piso 2 atascada', 'HARDWARE', 'BAJA', 'marta.ruiz', 80, 3, 8, 'carlos'),
    ('VPN no conecta desde casa', 'RED', 'ALTA', 'jorge.diaz', 72, 0.2, 2, 'diana'),
    ('Instalar Office en equipo nuevo', 'SOFTWARE', 'MEDIA', 'sofia.leon', 60, 4, 10, 'andres'),
    ('Pantalla parpadea', 'HARDWARE', 'BAJA', 'ana.gomez', 50, 2, 20, 'andres'),
    ('Sin acceso a carpeta compartida', 'ACCESOS', 'ALTA', 'pedro.mora', 40, 0.5, 1.5, 'carlos'),
    ('Wifi lento en sala de juntas', 'RED', 'MEDIA', 'luis.perez', 30, 1, None, 'diana'),
    ('Error al abrir el ERP', 'SOFTWARE', 'ALTA', 'marta.ruiz', 20, 0.3, None, 'carlos'),
    ('Teclado con teclas pegadas', 'HARDWARE', 'BAJA', 'sofia.leon', 36, None, None, None),
    ('Solicitud de segundo monitor', 'HARDWARE', 'BAJA', 'jorge.diaz', 28, None, None, None),
    ('Antivirus vencido', 'SOFTWARE', 'MEDIA', 'pedro.mora', 5, None, None, None),
    ('Crear usuario a nuevo empleado', 'ACCESOS', 'ALTA', 'rrhh', 2, None, None, None),
    ('Videollamadas con cortes', 'RED', 'MEDIA', 'ana.gomez', 1, None, None, None),
]


def sembrar():
    if consultar('SELECT ticketId FROM tickets LIMIT 1'):
        return
    base = datetime.now(timezone.utc)
    hace = lambda h: (base - timedelta(hours=h)).isoformat(timespec='seconds')
    for n, (titulo, cat, prio, usuario, creado, tomado, resuelto, agente) in enumerate(SEMILLA, 1):
        estado = 'RESUELTO' if resuelto is not None else 'EN_PROCESO' if tomado is not None else 'PENDIENTE'
        ejecutar('INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)', (
            f'T-SEED{n:03d}', usuario + '@example.com', usuario, titulo, 'Dato de prueba: ' + titulo, cat, prio,
            hace(creado), estado, agente if tomado is not None else None,
            hace(creado - tomado) if tomado is not None else None,
            hace(creado - resuelto) if resuelto is not None else None,
            'Resuelto (dato de prueba)' if resuelto is not None else None))
    log(f'[SEMILLA] {len(SEMILLA)} tickets de prueba cargados')


# ------------------------------------------------- cola de ingreso y notificaciones
def notificar(ticket_id):
    """En esta version el 'correo' solo se escribe en el log del contenedor."""
    t = buscar(ticket_id)
    if t:
        extra = f" | agente: {t['agente']}" if t.get('agente') else ''
        extra += f" | respuesta del agente: {t['solucion']}" if t.get('solucion') else ''
        log(f"[CORREO] para {t['email']}: tu ticket {t['ticketId']} \"{t['titulo']}\" "
            f"{TEXTO_ESTADO.get(t['estado'], t['estado'])}{extra}")


def trabajador():
    """Consume la cola y guarda cada ticket. INSERT OR IGNORE = idempotente."""
    while True:
        t = cola.get()
        try:
            nuevas = ejecutar(
                'INSERT OR IGNORE INTO tickets (ticketId, email, nombre, titulo, descripcion, categoria, prioridad, '
                "creadoEn, estado) VALUES (?,?,?,?,?,?,?,?,'PENDIENTE')",
                (t['ticketId'], t['email'], t['nombre'], t['titulo'], t['descripcion'], t['categoria'],
                 t['prioridad'], t['creadoEn']))
            if nuevas:
                notificar(t['ticketId'])
        except Exception as e:  # un ticket malo no puede tumbar al trabajador
            log('[ERROR] no se pudo guardar el ticket', t.get('ticketId'), e)
        finally:
            cola.task_done()


def revisar_sla():
    limite = (datetime.now(timezone.utc) - timedelta(hours=SLA_HORAS)).isoformat(timespec='seconds')
    vencidos = consultar("SELECT * FROM tickets WHERE estado = 'PENDIENTE' AND creadoEn < ? AND slaAlertado = 0 "
                         'ORDER BY creadoEn', (limite,))
    if vencidos:
        log(f'[ALERTA SLA] {len(vencidos)} ticket(s) superan {SLA_HORAS:g}h sin ser atendidos: '
            + ', '.join(t['ticketId'] for t in vencidos))
        for t in vencidos:
            ejecutar('UPDATE tickets SET slaAlertado = 1 WHERE ticketId = ?', (t['ticketId'],))
    return len(vencidos)


def reloj_sla():
    while True:
        try:
            revisar_sla()
        except Exception as e:
            log('[ERROR] revision de SLA', e)
        time.sleep(SLA_CADA_SEG)


# ------------------------------------------------------------------- metricas
def promedio(valores):
    return round(sum(valores) / len(valores), 2) if valores else None


def metricas():
    tickets = consultar('SELECT * FROM tickets')
    momento = ahora()
    espera, resolucion, agentes, estados, vencidos = [], [], {}, {}, []
    for t in tickets:
        estados[t['estado']] = estados.get(t['estado'], 0) + 1
        if t.get('tomadoEn'):
            espera.append(horas(t['creadoEn'], t['tomadoEn']))
        if t.get('resueltoEn'):
            resolucion.append(horas(t['creadoEn'], t['resueltoEn']))
        if t.get('agente'):
            a = agentes.setdefault(t['agente'], {'agente': t['agente'], 'asignados': 0, 'resueltos': 0, 'h': []})
            a['asignados'] += 1
            if t.get('resueltoEn'):
                a['resueltos'] += 1
                a['h'].append(horas(t['tomadoEn'], t['resueltoEn']))
        if t['estado'] == 'PENDIENTE' and horas(t['creadoEn'], momento) > SLA_HORAS:
            vencidos.append({k: t[k] for k in ('ticketId', 'titulo', 'prioridad', 'creadoEn')})
    for a in agentes.values():
        a['horasPromResolucion'] = promedio(a.pop('h'))
    vencidos.sort(key=lambda t: t['creadoEn'])
    return {'total': len(tickets), 'porEstado': estados, 'horasPromEspera': promedio(espera),
            'horasPromResolucion': promedio(resolucion), 'slaHoras': SLA_HORAS, 'slaVencidos': vencidos,
            'porAgente': sorted(agentes.values(), key=lambda a: -a['asignados'])}


# ------------------------------------------------------------------ servidor web
class Manejador(BaseHTTPRequestHandler):
    server_version = 'SoporteTI/1'

    def log_message(self, formato, *args):
        log('[HTTP]', formato % args)

    def _responder(self, codigo, cuerpo, tipo='application/json'):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(datos)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(datos)

    def _cuerpo(self):
        largo = int(self.headers.get('Content-Length') or 0)
        if largo > 65536:
            raise ValueError('cuerpo demasiado grande')
        cuerpo = json.loads(self.rfile.read(largo) or b'{}')
        if not isinstance(cuerpo, dict):
            raise ValueError('se esperaba un objeto JSON')
        return cuerpo

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in ('/', '/index.html'):
            with open(os.path.join(WEB, 'index.html'), 'rb') as f:
                return self._responder(200, f.read(), 'text/html; charset=utf-8')
        if url.path == '/config.js':  # la pagina y la API viven en el mismo servidor
            return self._responder(200, b'window.APP_CONFIG = { apiUrl: location.origin };', 'application/javascript')
        if url.path == '/salud':
            return self._responder(200, {'estado': 'ok', 'version': 1, 'enCola': cola.qsize()})
        if url.path == '/metricas':
            return self._responder(200, metricas())
        if url.path == '/tickets':
            if q.get('estado'):   # cola de atencion: el mas antiguo primero
                lista = consultar('SELECT * FROM tickets WHERE estado = ? ORDER BY creadoEn', (q['estado'].upper(),))
            elif q.get('email'):
                lista = consultar('SELECT * FROM tickets WHERE email = ? ORDER BY creadoEn DESC', (q['email'].lower(),))
            else:
                lista = consultar('SELECT * FROM tickets ORDER BY creadoEn')
            if q.get('agente'):
                lista = [t for t in lista if t.get('agente') == q['agente']]
            return self._responder(200, lista)
        if url.path.startswith('/tickets/'):
            t = buscar(unquote(url.path[len('/tickets/'):]))
            return self._responder(200, t) if t else self._responder(404, {'error': 'No existe'})
        self._responder(404, {'error': 'Ruta no soportada'})

    def do_POST(self):
        if urlparse(self.path).path != '/tickets':
            return self._responder(404, {'error': 'Ruta no soportada'})
        try:
            b = self._cuerpo()
        except ValueError:
            return self._responder(400, {'error': 'El cuerpo debe ser un objeto JSON'})
        texto = lambda campo: str(b.get(campo) or '').strip()
        email, titulo, descripcion = texto('email').lower(), texto('titulo'), texto('descripcion')
        if '@' not in email or not titulo or not descripcion:
            return self._responder(400, {'error': 'email, titulo y descripcion son obligatorios'})
        ticket = {
            'ticketId': 'T-' + uuid.uuid4().hex[:8].upper(), 'email': email[:120],
            'nombre': texto('nombre')[:80], 'titulo': titulo[:120], 'descripcion': descripcion[:2000],
            'categoria': texto('categoria') if texto('categoria') in CATEGORIAS else 'OTRO',
            'prioridad': texto('prioridad') if texto('prioridad') in PRIORIDADES else 'MEDIA',
            'creadoEn': ahora()}
        cola.put(ticket)   # no se guarda aqui: lo hace el trabajador (asincronico)
        self._responder(202, {'mensaje': 'Ticket recibido y en cola', 'ticketId': ticket['ticketId']})

    def do_PATCH(self):
        ruta = urlparse(self.path).path
        if not ruta.startswith('/tickets/'):
            return self._responder(404, {'error': 'Ruta no soportada'})
        ticket_id = unquote(ruta[len('/tickets/'):])
        try:
            b = self._cuerpo()
        except ValueError:
            return self._responder(400, {'error': 'El cuerpo debe ser un objeto JSON'})
        agente = str(b.get('agente') or '').strip().lower()
        if not agente:
            return self._responder(400, {'error': 'agente es obligatorio'})
        # El WHERE hace de "escritura condicional": dos agentes no toman el mismo ticket
        if b.get('accion') == 'tomar':
            cambios = ejecutar("UPDATE tickets SET estado = 'EN_PROCESO', agente = ?, tomadoEn = ? "
                               "WHERE ticketId = ? AND estado = 'PENDIENTE'", (agente, ahora(), ticket_id))
        elif b.get('accion') == 'resolver':
            cambios = ejecutar("UPDATE tickets SET estado = 'RESUELTO', resueltoEn = ?, solucion = ? "
                               "WHERE ticketId = ? AND estado = 'EN_PROCESO' AND agente = ?",
                               (ahora(), str(b.get('solucion') or 'Sin detalle')[:1000], ticket_id, agente))
        else:
            return self._responder(400, {'error': "accion debe ser 'tomar' o 'resolver'"})
        if not cambios:
            return self._responder(409, {'error': 'No se pudo: el ticket ya fue tomado por otro agente, no es tuyo o no existe'})
        notificar(ticket_id)
        self._responder(200, buscar(ticket_id))


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128   # conexiones en espera; el valor por defecto (5) rechaza picos pequenos


def main():
    global db
    db = abrir_bd()
    sembrar()
    threading.Thread(target=trabajador, daemon=True).start()
    threading.Thread(target=reloj_sla, daemon=True).start()
    servidor = Servidor(('0.0.0.0', PUERTO), Manejador)
    # "docker stop" envia SIGTERM: se apaga con orden en vez de esperar a que lo maten
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=servidor.shutdown).start())
    log(f'Mesa de Soporte TI v1 en http://0.0.0.0:{PUERTO} (datos en {DATOS})')
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    if cola.qsize():
        log(f'[AVISO] {cola.qsize()} ticket(s) seguian en la cola en memoria y se perdieron')
    log('Servidor detenido')


if __name__ == '__main__':
    main()
