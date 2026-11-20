"""Revision automatica de las plantillas de CloudFormation (iac/*.yaml).

Comprueba lo que exige el curso y lo que promete docs/seguridad.md:
tags obligatorios, parametros con valor por defecto, un rol por funcion,
politicas IAM sin comodines y codigo inline valido.

    python3 tests/test_plantilla.py -v
"""
import ast
import os
import re
import unittest

import util

IAC = os.path.join(util.RAIZ, 'iac')
PRINCIPAL = util.cargar_plantilla(os.path.join(IAC, 'main.yaml'))
SERVIDOR = util.cargar_plantilla(os.path.join(IAC, 'servidor.yaml'))
PLANTILLAS = {'main.yaml': PRINCIPAL, 'servidor.yaml': SERVIDOR}

TAGS_OBLIGATORIOS = {'Curso', 'Equipo', 'Proyecto', 'Ambiente'}
# Tipos que declaran sus tags en la plantilla. El resto (rutas, permisos, reglas...) no admite
# tags o los recibe del stack con "aws cloudformation deploy --tags".
TIPOS_CON_TAGS = {'AWS::DynamoDB::Table', 'AWS::SQS::Queue', 'AWS::SNS::Topic', 'AWS::IAM::Role',
                  'AWS::Lambda::Function', 'AWS::ApiGatewayV2::Api', 'AWS::ApiGatewayV2::Stage',
                  'AWS::S3::Bucket', 'AWS::Logs::LogGroup', 'AWS::EC2::Instance', 'AWS::EC2::SecurityGroup'}
PSEUDO = {'AWS::StackName', 'AWS::Region', 'AWS::AccountId', 'AWS::Partition', 'AWS::NoValue'}


def recursos(plantilla, tipo=None):
    return {n: r for n, r in plantilla['Resources'].items() if tipo is None or r['Type'] == tipo}


def claves_de_tags(tags):
    return set(tags) if isinstance(tags, dict) else {t['Key'] for t in tags}


def recorrer(nodo):
    """Recorre toda la plantilla devolviendo cada diccionario que encuentre."""
    if isinstance(nodo, dict):
        yield nodo
        for v in nodo.values():
            yield from recorrer(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from recorrer(v)


def como_lista(x):
    return x if isinstance(x, list) else [x]


class RequisitosDelCurso(unittest.TestCase):
    def test_tags_obligatorios_en_todos_los_recursos_que_los_admiten(self):
        for archivo, plantilla in PLANTILLAS.items():
            for nombre, r in recursos(plantilla).items():
                if r['Type'] in TIPOS_CON_TAGS:
                    with self.subTest(archivo=archivo, recurso=nombre):
                        tags = r['Properties'].get('Tags')
                        self.assertIsNotNone(tags, 'no declara Tags')
                        self.assertTrue(TAGS_OBLIGATORIOS <= claves_de_tags(tags))

    def test_los_valores_de_los_tags_son_los_del_curso(self):
        """Curso es fijo (GTN-2026-2); Equipo, Proyecto y Ambiente salen de los parametros."""
        esperado = {'Curso': 'GTN-2026-2', 'Equipo': {'!Ref': 'Equipo'},
                    'Proyecto': {'!Ref': 'Proyecto'}, 'Ambiente': {'!Ref': 'Ambiente'}}
        for archivo, plantilla in PLANTILLAS.items():
            self.assertEqual(plantilla['Parameters']['Ambiente']['Default'], 'lab')
            self.assertEqual(plantilla['Parameters']['Proyecto']['Default'], '10')
            for nombre, r in recursos(plantilla).items():
                tags = r.get('Properties', {}).get('Tags')
                if tags is None:
                    continue
                valores = tags if isinstance(tags, dict) else {t['Key']: t['Value'] for t in tags}
                for clave, valor in esperado.items():
                    self.assertEqual(valores[clave], valor, f'{archivo}: {nombre}.{clave}')

    def test_el_template_principal_se_despliega_sin_parametros(self):
        """El comando del curso no pasa --parameter-overrides: todo debe tener valor por defecto."""
        for nombre, p in PRINCIPAL['Parameters'].items():
            self.assertIn('Default', p, f'el parametro {nombre} no tiene valor por defecto')

    def test_el_template_cabe_en_el_comando_del_curso(self):
        """'aws cloudformation deploy --template-file' solo acepta hasta 51.200 bytes sin --s3-bucket."""
        tamano = os.path.getsize(os.path.join(IAC, 'main.yaml'))
        self.assertLess(tamano, 51200, f'main.yaml pesa {tamano} bytes: el comando exigiria --s3-bucket')

    def test_las_plantillas_son_ascii_puro(self):
        """En Windows, la CLI de AWS puede fallar o danar una plantilla con tildes o enes."""
        for archivo in PLANTILLAS:
            with open(os.path.join(IAC, archivo), 'rb') as f:
                contenido = f.read()
            raros = sorted({chr(b) for b in contenido if b > 127})
            self.assertEqual(raros, [], f'{archivo} tiene caracteres que no son ASCII')
            self.assertNotIn(b'\r\n', contenido, f'{archivo} debe usar saltos de linea de Unix')

    def test_el_tablero_de_cloudwatch_es_json_valido(self):
        import json
        (tablero,) = recursos(PRINCIPAL, 'AWS::CloudWatch::Dashboard').values()
        cuerpo = re.sub(r'\$\{[^}]+\}', 'x', tablero['Properties']['DashboardBody']['!Sub'])
        self.assertEqual(len(json.loads(cuerpo)['widgets']), 4)

    def test_tiene_parametros_y_outputs(self):
        self.assertGreaterEqual(len(PRINCIPAL['Parameters']), 3)
        self.assertTrue({'ApiUrl', 'SitioWebUrl', 'ColaUrl', 'TablaTickets'} <= set(PRINCIPAL['Outputs']))
        self.assertIn('Url', SERVIDOR['Outputs'])

    def test_las_referencias_apuntan_a_algo_que_existe(self):
        for archivo, plantilla in PLANTILLAS.items():
            nombres = set(plantilla['Resources']) | set(plantilla.get('Parameters', {})) | PSEUDO
            for nodo in recorrer(plantilla):
                for clave, valor in nodo.items():
                    with self.subTest(archivo=archivo, funcion=clave, valor=str(valor)[:60]):
                        if clave == '!Ref':
                            self.assertIn(valor, nombres)
                        elif clave == '!GetAtt':
                            self.assertIn(valor.split('.')[0], nombres)
                        elif clave == '!Sub' and isinstance(valor, str):
                            for var in re.findall(r'\$\{([^}!]+)\}', valor):
                                self.assertIn(var.split('.')[0], nombres)
                        elif clave in ('Condition',) and isinstance(valor, str) and valor[0].isupper():
                            self.assertIn(valor, plantilla.get('Conditions', {}))


class CodigoDeLasLambdas(unittest.TestCase):
    def test_el_codigo_inline_compila_y_cabe_en_el_limite(self):
        funciones = recursos(PRINCIPAL, 'AWS::Lambda::Function')
        self.assertEqual(len(funciones), 7)
        for nombre, r in funciones.items():
            with self.subTest(funcion=nombre):
                codigo = r['Properties']['Code']['ZipFile']
                ast.parse(codigo)
                self.assertLessEqual(len(codigo), 4096, 'CloudFormation limita el codigo inline a 4096 caracteres')
                self.assertEqual(r['Properties']['Handler'], 'index.handler')

    def test_cada_funcion_tiene_su_grupo_de_logs_con_retencion(self):
        grupos = recursos(PRINCIPAL, 'AWS::Logs::LogGroup')
        usados = []
        for nombre, f in recursos(PRINCIPAL, 'AWS::Lambda::Function').items():
            grupo = f['Properties']['LoggingConfig']['LogGroup']['!Ref']
            usados.append(grupo)
            self.assertEqual(grupos[grupo]['Properties']['RetentionInDays'], 14, nombre)
            self.assertNotIn('LogGroupName', grupos[grupo]['Properties'],
                             'con nombre fijo, un grupo viejo con el mismo nombre haria fallar el despliegue')
        self.assertEqual(sorted(usados), sorted(grupos), 'cada funcion escribe en su propio grupo')


class AuditoriaDePermisos(unittest.TestCase):
    """Lo que afirma docs/seguridad.md, comprobado en cada cambio."""

    def sentencias(self):
        for nombre, rol in recursos(PRINCIPAL, 'AWS::IAM::Role').items():
            for politica in rol['Properties'].get('Policies', []):
                for s in politica['PolicyDocument']['Statement']:
                    yield nombre, s

    def test_cada_funcion_tiene_su_propio_rol(self):
        roles = []
        for nombre, f in recursos(PRINCIPAL, 'AWS::Lambda::Function').items():
            condicion, propio, existente = f['Properties']['Role']['!If']
            self.assertEqual(condicion, 'CrearRoles')
            roles.append(propio['!GetAtt'].split('.')[0])
        self.assertEqual(len(set(roles)), 7, 'dos funciones comparten rol')
        self.assertEqual(set(roles), set(recursos(PRINCIPAL, 'AWS::IAM::Role')), 'hay roles que nadie usa')

    def test_ninguna_politica_usa_comodines(self):
        for rol, s in self.sentencias():
            with self.subTest(rol=rol):
                self.assertEqual(s['Effect'], 'Allow')
                for accion in como_lista(s['Action']):
                    self.assertNotIn('*', accion, 'accion con comodin')
                for recurso in como_lista(s['Resource']):
                    self.assertNotEqual(recurso, '*', 'recurso con comodin total')

    def test_los_roles_solo_los_asume_lambda(self):
        for nombre, rol in recursos(PRINCIPAL, 'AWS::IAM::Role').items():
            s = rol['Properties']['AssumeRolePolicyDocument']['Statement']
            self.assertEqual([x['Principal'] for x in s], [{'Service': 'lambda.amazonaws.com'}], nombre)

    def test_nadie_puede_borrar_tickets(self):
        acciones = {a for _, s in self.sentencias() for a in como_lista(s['Action'])}
        self.assertFalse({a for a in acciones if 'Delete' in a and a.startswith('dynamodb:')})

    def test_permisos_esperados_por_rol(self):
        esperado = {
            'RolCrearTicket': {'sqs:SendMessage'},
            'RolWorker': {'sqs:ReceiveMessage', 'sqs:DeleteMessage', 'sqs:GetQueueAttributes',
                          'dynamodb:PutItem', 'sns:Subscribe'},
            'RolConsultas': {'dynamodb:GetItem', 'dynamodb:Query', 'dynamodb:Scan'},
            'RolEstado': {'dynamodb:UpdateItem'},
            'RolNotificar': {'dynamodb:GetRecords', 'dynamodb:GetShardIterator', 'dynamodb:DescribeStream',
                             'dynamodb:ListStreams', 'sns:Publish'},
            'RolSla': {'dynamodb:Query', 'dynamodb:UpdateItem', 'sns:Publish'},
            'RolSemilla': {'dynamodb:BatchWriteItem'},
        }
        real = {}
        for rol, s in self.sentencias():
            real.setdefault(rol, set()).update(como_lista(s['Action']))
        self.assertEqual(real, esperado)

    def test_lo_unico_publico_es_la_lectura_del_sitio_web(self):
        politicas = recursos(PRINCIPAL, 'AWS::S3::BucketPolicy')
        self.assertEqual(len(politicas), 1)
        (s,) = next(iter(politicas.values()))['Properties']['PolicyDocument']['Statement']
        self.assertEqual((s['Principal'], s['Action']), ('*', 's3:GetObject'))

    def test_el_servidor_solo_abre_el_puerto_80(self):
        (grupo,) = recursos(SERVIDOR, 'AWS::EC2::SecurityGroup').values()
        puertos = [(r['FromPort'], r['ToPort']) for r in grupo['Properties']['SecurityGroupIngress']]
        self.assertEqual(puertos, [(80, 80)], 'no debe haber SSH (22) abierto a internet')

    def test_colas_cifradas_y_con_cola_de_fallidos(self):
        colas = recursos(PRINCIPAL, 'AWS::SQS::Queue')
        self.assertEqual(len(colas), 2)
        for nombre, c in colas.items():
            self.assertTrue(c['Properties']['SqsManagedSseEnabled'], nombre)
        self.assertEqual(colas['ColaTickets']['Properties']['RedrivePolicy']['maxReceiveCount'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
