"""Pruebas automaticas de las historias de usuario.

Ejecutan el codigo REAL de las Lambdas (el que esta dentro de iac/main.yaml)
contra dobles en memoria de DynamoDB, SQS y SNS. No necesitan cuenta de AWS.

    python3 tests/test_lambdas.py -v

Cada prueba corresponde a un criterio de aceptacion de docs/historias.md.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone

import util  # noqa: F401  (configura rutas y variables de entorno)
import boto3
import cfnresponse

crear = util.cargar_funcion('FnCrearTicket')
worker = util.cargar_funcion('FnWorker')
consultas = util.cargar_funcion('FnConsultas')
estado = util.cargar_funcion('FnEstado')
notificar = util.cargar_funcion('FnNotificar')
sla = util.cargar_funcion('FnSla')
semilla = util.cargar_funcion('FnSemilla')

TICKET = {'email': 'Ana@Empresa.com', 'nombre': 'Ana', 'titulo': 'PC lento',
          'descripcion': 'Tarda 10 minutos en encender', 'categoria': 'HARDWARE', 'prioridad': 'ALTA'}


def post_ticket(cuerpo):
    return crear.handler({'body': json.dumps(cuerpo) if isinstance(cuerpo, dict) else cuerpo}, None)


def procesar_cola():
    """Simula a SQS entregando al worker todo lo que hay en la cola."""
    registros = [{'messageId': f'm{i}', 'body': m['MessageBody']} for i, m in enumerate(boto3.ENVIADOS)]
    return worker.handler({'Records': registros}, None)


def get(ruta, query=None, ident=None):
    r = consultas.handler({'routeKey': ruta, 'queryStringParameters': query,
                           'pathParameters': {'id': ident} if ident else None}, None)
    return r['statusCode'], json.loads(r['body'])


def patch(ident, cuerpo):
    r = estado.handler({'pathParameters': {'id': ident}, 'body': json.dumps(cuerpo)}, None)
    return r['statusCode'], json.loads(r['body'])


def crear_y_guardar(**cambios):
    """Crea un ticket por la API, lo pasa por la cola y devuelve su codigo."""
    boto3.ENVIADOS.clear()
    tid = json.loads(post_ticket({**TICKET, **cambios})['body'])['ticketId']
    procesar_cola()
    return tid


EVENTO_CFN = {'ResponseURL': 'https://respuesta-de-cloudformation'}   # asi llega al crear o borrar el stack


def cargar_semilla():
    semilla.handler({'RequestType': 'Create', **EVENTO_CFN}, None)


def imagen(**campos):
    """Arma un registro con el formato de DynamoDB Streams."""
    return {k: {'S': v} for k, v in campos.items()}


class Base(unittest.TestCase):
    def setUp(self):
        boto3.reiniciar()
        cfnresponse.RESPUESTAS.clear()


class HU01CrearTicket(Base):
    def test_ticket_valido_responde_202_y_queda_en_la_cola(self):
        r = post_ticket(TICKET)
        self.assertEqual(r['statusCode'], 202)
        self.assertRegex(json.loads(r['body'])['ticketId'], r'^T-[0-9A-F]{8}$')
        self.assertEqual(len(boto3.ENVIADOS), 1, 'debe haber un mensaje en SQS')
        self.assertEqual(boto3.DB, {}, 'la API no escribe en la base de datos: es asincronico')

    def test_faltan_campos_obligatorios_responde_400_y_no_encola(self):
        for cuerpo in ({}, {**TICKET, 'email': 'sin-arroba'}, {**TICKET, 'titulo': ' '}, {**TICKET, 'descripcion': ''}):
            self.assertEqual(post_ticket(cuerpo)['statusCode'], 400)
        self.assertEqual(post_ticket('esto no es json')['statusCode'], 400)
        self.assertEqual(boto3.ENVIADOS, [])

    def test_cuerpos_con_tipos_inesperados_responden_400_y_no_un_error_interno(self):
        for cuerpo in ('[]', '"texto"', '123', 'null'):
            self.assertIn(post_ticket(cuerpo)['statusCode'], (400,), cuerpo)
        self.assertEqual(post_ticket({**TICKET, 'email': 12345})['statusCode'], 400)
        r = post_ticket({**TICKET, 'categoria': ['HARDWARE'], 'prioridad': {'x': 1}, 'nombre': 7})
        self.assertEqual(r['statusCode'], 202, 'categoria y prioridad invalidas se normalizan')
        t = json.loads(boto3.ENVIADOS[0]['MessageBody'])
        self.assertEqual((t['categoria'], t['prioridad'], t['nombre']), ('OTRO', 'MEDIA', '7'))

    def test_normaliza_correo_categoria_y_prioridad(self):
        post_ticket({**TICKET, 'categoria': 'INVENTADA', 'prioridad': 'URGENTISIMA'})
        t = json.loads(boto3.ENVIADOS[0]['MessageBody'])
        self.assertEqual((t['email'], t['categoria'], t['prioridad']), ('ana@empresa.com', 'OTRO', 'MEDIA'))


class HU01IngresoPorCola(Base):
    def test_el_worker_guarda_el_ticket_como_pendiente(self):
        tid = crear_y_guardar()
        self.assertEqual(boto3.DB[tid]['estado'], 'PENDIENTE')
        self.assertFalse(boto3.DB[tid]['slaAlertado'])

    def test_mensaje_duplicado_no_duplica_el_ticket(self):
        post_ticket(TICKET)
        boto3.ENVIADOS.append(boto3.ENVIADOS[0])  # SQS entrega "al menos una vez"
        self.assertEqual(procesar_cola(), {'batchItemFailures': []})
        self.assertEqual(len(boto3.DB), 1)

    def test_mensaje_corrupto_se_reintenta_sin_bloquear_a_los_demas(self):
        post_ticket(TICKET)
        boto3.ENVIADOS.append({'MessageBody': '{"esto": "no es un ticket"}'})
        boto3.ENVIADOS.append({'MessageBody': 'ni siquiera es json'})
        r = procesar_cola()
        self.assertEqual(r, {'batchItemFailures': [{'itemIdentifier': 'm1'}, {'itemIdentifier': 'm2'}]})
        self.assertEqual(len(boto3.DB), 1, 'el ticket valido si se guardo')


class HU02ColaDePendientes(Base):
    def test_la_cola_sale_en_orden_de_llegada(self):
        cargar_semilla()
        codigo, cola = get('GET /tickets', {'estado': 'pendiente'})
        self.assertEqual(codigo, 200)
        self.assertEqual([t['ticketId'] for t in cola],
                         ['T-SEED010', 'T-SEED011', 'T-SEED012', 'T-SEED013', 'T-SEED014'])
        fechas = [t['creadoEn'] for t in cola]
        self.assertEqual(fechas, sorted(fechas), 'el mas antiguo va primero')

    def test_tomar_pasa_a_en_proceso_con_agente_y_hora(self):
        tid = crear_y_guardar()
        codigo, t = patch(tid, {'accion': 'tomar', 'agente': 'Diana'})
        self.assertEqual(codigo, 200)
        self.assertEqual((t['estado'], t['agente']), ('EN_PROCESO', 'diana'))
        self.assertIn('tomadoEn', t)

    def test_dos_agentes_no_pueden_tomar_el_mismo_ticket(self):
        tid = crear_y_guardar()
        self.assertEqual(patch(tid, {'accion': 'tomar', 'agente': 'diana'})[0], 200)
        self.assertEqual(patch(tid, {'accion': 'tomar', 'agente': 'carlos'})[0], 409)
        self.assertEqual(boto3.DB[tid]['agente'], 'diana', 'conserva al primer agente')

    def test_un_agente_ve_solo_sus_tickets_en_proceso(self):
        cargar_semilla()
        _, mios = get('GET /tickets', {'estado': 'EN_PROCESO', 'agente': 'diana'})
        self.assertEqual([t['ticketId'] for t in mios], ['T-SEED008'])


class HU03CambiarEstado(Base):
    def test_solo_el_agente_asignado_puede_resolver(self):
        tid = crear_y_guardar()
        patch(tid, {'accion': 'tomar', 'agente': 'diana'})
        self.assertEqual(patch(tid, {'accion': 'resolver', 'agente': 'carlos'})[0], 409)
        codigo, t = patch(tid, {'accion': 'resolver', 'agente': 'diana', 'solucion': 'Se amplio la memoria'})
        self.assertEqual(codigo, 200)
        self.assertEqual((t['estado'], t['solucion']), ('RESUELTO', 'Se amplio la memoria'))
        self.assertIn('resueltoEn', t)

    def test_no_se_puede_resolver_un_ticket_que_nadie_ha_tomado(self):
        tid = crear_y_guardar()
        self.assertEqual(patch(tid, {'accion': 'resolver', 'agente': 'diana'})[0], 409)
        self.assertEqual(boto3.DB[tid]['estado'], 'PENDIENTE')

    def test_ticket_inexistente_responde_409(self):
        self.assertEqual(patch('T-NOEXISTE', {'accion': 'tomar', 'agente': 'diana'})[0], 409)
        self.assertNotIn('T-NOEXISTE', boto3.DB, 'no debe crear un ticket fantasma')

    def test_peticiones_invalidas_responden_400(self):
        tid = crear_y_guardar()
        self.assertEqual(patch(tid, {'accion': 'borrar', 'agente': 'diana'})[0], 400)
        self.assertEqual(patch(tid, {'accion': 'tomar', 'agente': '  '})[0], 400)


class HU04Metricas(Base):
    def test_metricas_con_los_datos_de_prueba(self):
        cargar_semilla()
        codigo, m = get('GET /metricas')
        self.assertEqual(codigo, 200)
        self.assertEqual(m['total'], 14)
        self.assertEqual(m['porEstado'], {'RESUELTO': 7, 'EN_PROCESO': 2, 'PENDIENTE': 5})
        self.assertAlmostEqual(m['horasPromEspera'], 12.5 / 9, places=2)
        self.assertAlmostEqual(m['horasPromResolucion'], 48.5 / 7, places=2)
        self.assertEqual([t['ticketId'] for t in m['slaVencidos']], ['T-SEED010', 'T-SEED011'])
        agentes = {a['agente']: (a['asignados'], a['resueltos']) for a in m['porAgente']}
        self.assertEqual(agentes, {'carlos': (4, 3), 'diana': (3, 2), 'andres': (2, 2)})

    def test_las_metricas_cambian_al_resolver_un_ticket(self):
        cargar_semilla()
        patch('T-SEED008', {'accion': 'resolver', 'agente': 'diana', 'solucion': 'Cambio de canal wifi'})
        _, m = get('GET /metricas')
        self.assertEqual(m['porEstado'], {'RESUELTO': 8, 'EN_PROCESO': 1, 'PENDIENTE': 5})

    def test_metricas_sin_tickets_no_fallan(self):
        _, m = get('GET /metricas')
        self.assertEqual((m['total'], m['horasPromEspera'], m['porAgente']), (0, None, []))

    def test_detalle_de_un_ticket_y_ticket_inexistente(self):
        tid = crear_y_guardar()
        self.assertEqual(get('GET /tickets/{id}', ident=tid)[1]['titulo'], 'PC lento')
        self.assertEqual(get('GET /tickets/{id}', ident='T-NOEXISTE')[0], 404)


class HU05Notificaciones(Base):
    def test_el_usuario_queda_suscrito_solo_a_sus_tickets(self):
        crear_y_guardar()
        s = boto3.SUSCRIPCIONES[0]
        self.assertEqual((s['Protocol'], s['Endpoint']), ('email', 'ana@empresa.com'))
        self.assertEqual(json.loads(s['Attributes']['FilterPolicy']), {'email': ['ana@empresa.com']})

    def test_los_correos_de_prueba_no_se_suscriben(self):
        crear_y_guardar(email='carga-1@example.com')
        self.assertEqual(boto3.SUSCRIPCIONES, [])

    def test_mis_tickets_muestra_solo_los_mios(self):
        mio = crear_y_guardar()
        crear_y_guardar(email='otro@empresa.com')
        _, lista = get('GET /tickets', {'email': 'ANA@empresa.com'})
        self.assertEqual([t['ticketId'] for t in lista], [mio])

    def test_cambio_de_estado_envia_correo_al_dueno_del_ticket(self):
        nuevo = imagen(ticketId='T-1', titulo='PC lento', email='ana@empresa.com',
                       estado='EN_PROCESO', agente='diana')
        notificar.handler({'Records': [{'eventName': 'MODIFY', 'dynamodb': {
            'OldImage': imagen(estado='PENDIENTE'), 'NewImage': nuevo}}]}, None)
        p = boto3.PUBLICADOS[0]
        self.assertEqual(p['TopicArn'], 'arn:usuarios')
        self.assertIn('T-1', p['Subject'])
        self.assertIn('EN_PROCESO', p['Subject'])
        self.assertIn('diana', p['Message'])
        self.assertEqual(p['MessageAttributes']['email']['StringValue'], 'ana@empresa.com',
                         'el atributo email es el que usa el filtro de cada suscripcion')

    def test_ticket_nuevo_tambien_notifica(self):
        notificar.handler({'Records': [{'eventName': 'INSERT', 'dynamodb': {'NewImage': imagen(
            ticketId='T-2', titulo='x', email='ana@empresa.com', estado='PENDIENTE')}}]}, None)
        self.assertIn('PENDIENTE', boto3.PUBLICADOS[0]['Subject'])

    def test_un_registro_sin_correo_no_tumba_el_lote(self):
        notificar.handler({'Records': [
            {'eventName': 'INSERT', 'dynamodb': {'NewImage': imagen(ticketId='T-9', titulo='x', estado='PENDIENTE')}},
            {'eventName': 'INSERT', 'dynamodb': {'NewImage': imagen(
                ticketId='T-10', titulo='y', email='ana@empresa.com', estado='PENDIENTE')}}]}, None)
        self.assertEqual([p['MessageAttributes']['email']['StringValue'] for p in boto3.PUBLICADOS],
                         ['ana@empresa.com'])

    def test_un_cambio_que_no_es_de_estado_no_envia_correo(self):
        igual = imagen(ticketId='T-3', titulo='x', email='ana@empresa.com', estado='PENDIENTE')
        notificar.handler({'Records': [
            {'eventName': 'MODIFY', 'dynamodb': {'OldImage': igual, 'NewImage': igual}},
            {'eventName': 'REMOVE', 'dynamodb': {'OldImage': igual}}]}, None)
        self.assertEqual(boto3.PUBLICADOS, [])


class RetoSLA(Base):
    def test_alerta_al_jefe_una_sola_vez_por_ticket(self):
        cargar_semilla()
        self.assertEqual(sla.handler({}, None), {'alertados': 2})
        p = boto3.PUBLICADOS[0]
        self.assertEqual(p['TopicArn'], 'arn:jefe')
        self.assertIn('2 ticket(s) superan 24h', p['Subject'])
        self.assertIn('T-SEED010', p['Message'])
        self.assertIn('T-SEED011', p['Message'])
        self.assertEqual(sla.handler({}, None), {'alertados': 0}, 'la segunda revision no repite')
        self.assertEqual(len(boto3.PUBLICADOS), 1)

    def test_tickets_recientes_o_ya_tomados_no_generan_alerta(self):
        crear_y_guardar()                                   # recien creado
        viejo = crear_y_guardar(titulo='Viejo pero atendido')
        hace_30h = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec='seconds')
        boto3.DB[viejo]['creadoEn'] = hace_30h
        patch(viejo, {'accion': 'tomar', 'agente': 'diana'})   # ya no esta PENDIENTE
        self.assertEqual(sla.handler({}, None), {'alertados': 0})
        self.assertEqual(boto3.PUBLICADOS, [])


class DatosDePrueba(Base):
    def test_la_semilla_carga_14_tickets_al_crear_el_stack(self):
        cargar_semilla()
        self.assertEqual(cfnresponse.RESPUESTAS, ['SUCCESS'])
        self.assertEqual(len(boto3.DB), 14)
        self.assertTrue(all(t['email'].endswith('@example.com') for t in boto3.DB.values()))

    def test_al_borrar_el_stack_la_semilla_no_escribe_nada(self):
        semilla.handler({'RequestType': 'Delete', **EVENTO_CFN}, None)
        self.assertEqual((cfnresponse.RESPUESTAS, boto3.DB), (['SUCCESS'], {}))

    def test_invocada_a_mano_restaura_los_datos_de_prueba(self):
        """Antes de una demo: aws lambda invoke --function-name <stack>-semilla ..."""
        cargar_semilla()
        patch('T-SEED010', {'accion': 'tomar', 'agente': 'diana'})      # un ensayo cambio los datos
        sla.handler({}, None)                                           # y ya se envio la alerta de SLA
        cfnresponse.RESPUESTAS.clear()
        self.assertEqual(semilla.handler({}, None), {'cargados': 14})
        self.assertEqual(cfnresponse.RESPUESTAS, [], 'a mano no hay CloudFormation a quien responder')
        self.assertEqual(boto3.DB['T-SEED010']['estado'], 'PENDIENTE')
        self.assertNotIn('agente', boto3.DB['T-SEED010'])
        self.assertFalse(boto3.DB['T-SEED011']['slaAlertado'], 'la alerta de SLA puede volver a mostrarse')


if __name__ == '__main__':
    unittest.main(verbosity=2)
