"""Doble del modulo cfnresponse que AWS incluye en las Lambdas con codigo inline."""
SUCCESS = 'SUCCESS'
FAILED = 'FAILED'
RESPUESTAS = []


def send(event, context, estado, datos):
    RESPUESTAS.append(estado)
