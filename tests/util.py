"""Carga iac/main.yaml y ejecuta el codigo inline de cada Lambda contra los dobles de prueba."""
import os
import sys
import types

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
PLANTILLA = os.path.join(RAIZ, 'iac', 'main.yaml')
sys.path.insert(0, os.path.join(AQUI, 'stub'))

os.environ.update(TABLE='tickets', QUEUE_URL='https://cola', TOPIC_USUARIOS='arn:usuarios',
                  TOPIC_JEFE='arn:jefe', SLA_HORAS='24')


class _Cargador(yaml.SafeLoader):
    """Entiende las funciones cortas de CloudFormation (!Ref, !Sub, !GetAtt, !If...)."""


def _funcion_cfn(loader, sufijo, nodo):
    if isinstance(nodo, yaml.ScalarNode):
        valor = loader.construct_scalar(nodo)
    elif isinstance(nodo, yaml.SequenceNode):
        valor = loader.construct_sequence(nodo, deep=True)
    else:
        valor = loader.construct_mapping(nodo, deep=True)
    return {'!' + sufijo: valor}


_Cargador.add_multi_constructor('!', _funcion_cfn)


def cargar_plantilla(ruta=PLANTILLA):
    with open(ruta, encoding='utf-8') as f:
        return yaml.load(f, Loader=_Cargador)


def cargar_funcion(nombre_logico):
    """Devuelve un modulo con el codigo inline (ZipFile) de la Lambda indicada."""
    codigo = cargar_plantilla()['Resources'][nombre_logico]['Properties']['Code']['ZipFile']
    modulo = types.ModuleType(nombre_logico)
    exec(compile(codigo, nombre_logico + '.py', 'exec'), modulo.__dict__)
    return modulo
