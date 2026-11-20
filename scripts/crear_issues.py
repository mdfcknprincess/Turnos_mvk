#!/usr/bin/env python3
"""Crea en GitHub los hitos y un issue por cada historia de docs/historias.md.

Requisitos: GitHub CLI instalado y autenticado (gh auth login), y ejecutarlo dentro del repo.

    python3 scripts/crear_issues.py --simular   # solo muestra lo que crearia
    python3 scripts/crear_issues.py             # crea hitos, etiquetas e issues

Es seguro repetirlo: si ya existe un issue cuyo titulo empieza por el mismo codigo
(por ejemplo "HU-01.1"), no lo vuelve a crear.
"""
import json
import os
import re
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORIAS = os.path.join(RAIZ, 'docs', 'historias.md')
ETIQUETAS = {
    'historia de usuario': ('1D76DB', 'Historia funcional con criterios de aceptacion'),
    'requisito no funcional': ('5319E7', 'Costo, carga, seguridad, operacion'),
    'reto extra': ('D93F0B', 'Reto extra del enunciado'),
}


def leer_historias():
    """Devuelve una lista de historias: codigo, titulo, hito, etiqueta y cuerpo del issue."""
    texto = open(HISTORIAS, encoding='utf-8').read()
    historias = []
    for bloque in re.split(r'\n(?=### HU-)', texto)[1:]:
        lineas = bloque.strip().split('\n')
        titulo = lineas[0][4:].strip()                      # "HU-01.1 · Crear ticket desde la web"
        codigo = titulo.split(' ')[0]
        meta = lineas[1].strip()                            # "Hito: ... · Epica: ... · Prueba: ..."
        hito = re.match(r'Hito: (.+?)(?: · |$)', meta).group(1)
        resto = '\n'.join(lineas[2:]).split('\n## ')[0].strip()   # corta donde empieza otra seccion
        partes = [p.strip() for p in resto.split('\n\n') if p.strip()]
        historia = partes[0]
        criterios = [c.replace('- ', '- [ ] ', 1) for c in '\n'.join(partes[1:]).split('\n') if c.startswith('- ')]
        etiqueta = ('requisito no funcional' if codigo.startswith('HU-NF') else
                    'reto extra' if codigo.startswith('HU-EX') else 'historia de usuario')
        cuerpo = (f'## Historia\n\n{historia}\n\n## Criterios de aceptación\n\n' + '\n'.join(criterios) +
                  f'\n\n## Trazabilidad\n\n{meta}\n\nDetalle en `docs/historias.md`. '
                  'Se cierra con el pull request que la implementa.')
        historias.append({'codigo': codigo, 'titulo': titulo, 'hito': hito, 'etiqueta': etiqueta, 'cuerpo': cuerpo})
    return historias


def gh(*args, entrada=None):
    r = subprocess.run(['gh', *args], input=entrada, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}... fallo: {r.stderr.strip()}")
    return r.stdout


def main():
    simular = '--simular' in sys.argv
    historias = leer_historias()
    # sin repetir y en orden cronologico: "Servicio en linea (sem 6-7)" va antes que "(sem 9-10)"
    hitos = sorted(dict.fromkeys(h['hito'] for h in historias), key=lambda t: int(re.search(r'\d+', t).group()))
    print(f'{len(historias)} historias en {len(hitos)} hitos')

    if simular:
        for hito in hitos:
            print(f'\nHito: {hito}')
            for h in (x for x in historias if x['hito'] == hito):
                print(f"  [{h['etiqueta']}] {h['titulo']}  ({h['cuerpo'].count('- [ ]')} criterios)")
        print('\nEjemplo del cuerpo de un issue:\n' + '-' * 60 + '\n' + historias[0]['cuerpo'])
        return

    for nombre, (color, descripcion) in ETIQUETAS.items():
        gh('label', 'create', nombre, '--color', color, '--description', descripcion, '--force')
    existentes = {m['title'] for m in json.loads(gh('api', 'repos/{owner}/{repo}/milestones?state=all&per_page=100'))}
    for hito in hitos:
        if hito not in existentes:
            gh('api', 'repos/{owner}/{repo}/milestones', '-f', f'title={hito}')
            print('hito creado:', hito)
    titulos = [i['title'] for i in json.loads(gh('issue', 'list', '--state', 'all', '--limit', '500', '--json', 'title'))]
    for h in historias:
        if any(t.startswith(h['codigo'] + ' ') or t == h['codigo'] for t in titulos):
            print('ya existe:', h['codigo'])
            continue
        url = gh('issue', 'create', '--title', h['titulo'], '--body', h['cuerpo'],
                 '--label', h['etiqueta'], '--milestone', h['hito']).strip()
        print('creado:', h['codigo'], url)


if __name__ == '__main__':
    main()
