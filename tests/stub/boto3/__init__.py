"""Doble de prueba de boto3: simula DynamoDB, SQS y SNS en memoria.

Permite ejecutar el codigo real de las Lambdas (el que esta dentro de
iac/main.yaml) sin cuenta de AWS, sin red y sin costo. Solo implementa
las operaciones que usa el proyecto.
"""
DB = {}      # tabla de tickets: ticketId -> item
ENVIADOS = []  # mensajes enviados a SQS
PUBLICADOS = []  # mensajes publicados en SNS
SUSCRIPCIONES = []  # suscripciones creadas en SNS


def reiniciar():
    DB.clear(); ENVIADOS.clear(); PUBLICADOS.clear(); SUSCRIPCIONES.clear()


class ConditionalCheckFailedException(Exception):
    pass


class _Excepciones:
    ConditionalCheckFailedException = ConditionalCheckFailedException


class _Meta:
    class client:
        exceptions = _Excepciones


class _LoteEscritura:
    def __init__(self, tabla): self.tabla = tabla
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def put_item(self, Item): self.tabla.items[Item['ticketId']] = dict(Item)


class Table:
    meta = _Meta

    def __init__(self, nombre):
        self.items = DB

    def put_item(self, Item, ConditionExpression=None):
        if 'ticketId' not in Item:
            raise ValueError('ValidationException: falta la clave ticketId')
        if ConditionExpression and Item['ticketId'] in self.items:
            raise ConditionalCheckFailedException()
        self.items[Item['ticketId']] = dict(Item)

    def get_item(self, Key):
        item = self.items.get(Key['ticketId'])
        return {'Item': dict(item)} if item else {}

    def scan(self, **kw):
        return {'Items': [dict(v) for v in self.items.values()]}

    def query(self, IndexName, KeyConditionExpression, ScanIndexForward=True):
        res = [dict(v) for v in self.items.values() if KeyConditionExpression(v)]
        res.sort(key=lambda x: x['creadoEn'], reverse=not ScanIndexForward)
        return {'Items': res}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues,
                    ConditionExpression=None, ReturnValues=None):
        item = self.items.get(Key['ticketId'])
        v = ExpressionAttributeValues
        if ConditionExpression:
            if item is None:
                raise ConditionalCheckFailedException()
            for cond in ConditionExpression.split(' AND '):
                attr, marcador = [x.strip() for x in cond.split('=')]
                if item.get(attr) != v[marcador]:
                    raise ConditionalCheckFailedException()
        if item is None:
            item = self.items.setdefault(Key['ticketId'], dict(Key))
        for parte in UpdateExpression.replace('SET', '').split(','):
            attr, marcador = [x.strip() for x in parte.split('=')]
            item[attr] = v[marcador]
        return {'Attributes': dict(item)}

    def batch_writer(self):
        return _LoteEscritura(self)


class _Recurso:
    def Table(self, nombre): return Table(nombre)


class _Cliente:
    def send_message(self, **kw): ENVIADOS.append(kw)
    def publish(self, **kw): PUBLICADOS.append(kw)
    def subscribe(self, **kw): SUSCRIPCIONES.append(kw)


def resource(nombre): return _Recurso()
def client(nombre): return _Cliente()
