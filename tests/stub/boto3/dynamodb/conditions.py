"""Doble de boto3.dynamodb.conditions.Key (solo eq, lt y &)."""


class _Cond:
    def __init__(self, f): self.f = f
    def __call__(self, item): return self.f(item)
    def __and__(self, otra): return _Cond(lambda item: self(item) and otra(item))


class Key:
    def __init__(self, nombre): self.nombre = nombre
    def eq(self, valor): return _Cond(lambda item: item.get(self.nombre) == valor)
    def lt(self, valor): return _Cond(lambda item: item.get(self.nombre) is not None and item.get(self.nombre) < valor)
