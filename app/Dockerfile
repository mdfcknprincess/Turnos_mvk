# Mesa de Soporte TI - version 1: toda la aplicacion en un contenedor.
# Se construye desde la RAIZ del repo (necesita app/ y frontend/):
#   docker build -f app/Dockerfile -t soporte-ti .
#   docker run -d --name soporte-ti -p 8080:8080 -v soporte-datos:/data soporte-ti
# Imagen oficial de Python tomada del registro publico de AWS (ECR Public): es la misma de
# Docker Hub, pero sin su limite de descargas anonimas, que suele afectar a los servidores en la nube.
FROM public.ecr.aws/docker/library/python:3.12-slim

# Usuario sin privilegios: la app no corre como root dentro del contenedor
RUN useradd --system --uid 10001 --no-create-home app \
 && mkdir /data && chown app /data

WORKDIR /srv
COPY app/server.py ./server.py
COPY frontend/index.html ./web/index.html

# La base de datos vive en /data: se monta un volumen para que sobreviva al contenedor
ENV PUERTO=8080 \
    DATOS=/data/tickets.db \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
VOLUME /data

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/salud' % os.environ.get('PUERTO', '8080'), timeout=2)"

CMD ["python", "server.py"]
