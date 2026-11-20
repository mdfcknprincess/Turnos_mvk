# Versión 1: servidor propio con Docker

Esta carpeta es el entregable del hito **«Servicio en línea»** (semanas 6–7): la mesa de ayuda completa empaquetada en una imagen Docker y corriendo en un servidor propio de AWS (EC2).

Es la primera versión del sistema. La versión final, sin servidores, está en [`iac/main.yaml`](../iac/main.yaml). Las dos exponen **la misma API y la misma página**; cambia lo que hay debajo.

| Pieza | Versión 1 (esta carpeta) | Versión final |
|---|---|---|
| Página y API | Un proceso de Python en un contenedor | S3 + API Gateway + Lambda |
| Cola de ingreso | En memoria, con un hilo trabajador | SQS + Lambda *worker* |
| Base de datos | SQLite en un volumen de Docker | DynamoDB |
| Revisión de SLA | Un hilo que revisa cada hora | EventBridge + Lambda |
| Correos | Se escriben en el registro del contenedor | SNS |

`server.py` solo usa la biblioteca estándar de Python: la imagen no instala nada más.

## 1. Probar en el computador

```bash
python3 app/server.py                    # sin Docker: abre http://localhost:8080
```

Con Docker (se construye desde la raíz del repo, porque la imagen incluye `frontend/index.html`):

```bash
docker build -f app/Dockerfile -t soporte-ti .
docker run -d --name soporte-ti -p 8080:8080 -v soporte-datos:/data soporte-ti
docker logs -f soporte-ti                # aquí se ven los «correos» y las alertas de SLA
```

La página queda en `http://localhost:8080`, con 14 tickets de prueba. Para comprobarla de extremo a extremo: `./scripts/demo.sh http://localhost:8080`.

## 2. Publicarla en un servidor de AWS

### Opción A: con CloudFormation (un comando)

```bash
aws cloudformation deploy --template-file iac/servidor.yaml --stack-name gtn-<equipo>-servidor \
  --parameter-overrides Equipo=<equipo> RepoUrl=https://github.com/<usuario>/<repo>.git
aws cloudformation describe-stacks --stack-name gtn-<equipo>-servidor --query "Stacks[0].Outputs" --output table
```

El servidor instala Docker, clona el repo, construye la imagen y arranca el contenedor en el puerto 80. La salida `Url` responde unos minutos después.

- El repositorio debe ser **público** (el servidor lo clona sin credenciales).
- En AWS Academy conviene agregar `PerfilInstancia=LabInstanceProfile` para poder entrar al servidor con Session Manager.
- Si la página no responde, el motivo está en el registro de arranque: `aws ec2 get-console-output --instance-id <InstanciaId> --latest --output text | tail -40`.

### Opción B: a mano, desde la consola

1. **EC2 → Lanzar instancia.** Imagen *Amazon Linux 2023*, tipo `t3.micro`, disco de 8 GB.
2. **Red:** crear un grupo de seguridad que permita solo **HTTP (puerto 80)** desde cualquier lugar. No abrir SSH.
3. **Detalles avanzados → Datos de usuario:** pegar este script (cambiando la URL del repo):

   ```bash
   #!/bin/bash
   dnf install -y docker git
   systemctl enable --now docker
   git clone --depth 1 https://github.com/<usuario>/<repo>.git /opt/soporte-ti
   cd /opt/soporte-ti
   docker build -f app/Dockerfile -t soporte-ti .
   docker run -d --name soporte-ti --restart unless-stopped -p 80:8080 -v soporte-datos:/data soporte-ti
   ```

4. **Etiquetas:** `Curso=GTN-2026-2`, `Equipo=<equipo>`, `Proyecto=10`, `Ambiente=lab`.
5. Lanzar y abrir `http://<DNS público de la instancia>` unos minutos después.

## 3. Evidencia para el hito

| Evidencia | Cómo obtenerla |
|---|---|
| La página responde desde internet | Captura de pantalla de `http://<DNS público>` con la vista Jefe |
| La aplicación corre en Docker | `docker ps` en el servidor, o el registro de arranque |
| El recorrido completo funciona | Salida de `./scripts/demo.sh http://<DNS público>` |
| El servidor está etiquetado | Captura de la pestaña *Etiquetas* de la instancia |

## 4. Apagar o borrar

El servidor cuesta mientras esté encendido: cerca de 11,9 USD al mes entre cómputo, dirección IP pública y disco.

```bash
aws ec2 stop-instances --instance-ids <InstanciaId>                      # apagar (el disco sigue costando 0,64 USD al mes)
aws ec2 start-instances --instance-ids <InstanciaId>                     # encender: cambia la dirección pública
aws cloudformation delete-stack --stack-name gtn-<equipo>-servidor       # borrar todo
```

## 5. Qué se aprendió de esta versión

La versión 1 funciona, pero al revisarla contra los pilares aparecen cinco problemas. Son los que justifican la arquitectura final (decisión ADR-11 en [`docs/decisiones.md`](../docs/decisiones.md)).

| Problema | Consecuencia | Cómo lo resuelve la versión final |
|---|---|---|
| Cuesta cerca de 12 USD al mes aunque nadie la use | Supera el presupuesto de 10 USD | Pago por uso: cerca de 0,9 USD |
| La cola vive en memoria | Si el contenedor se reinicia, los tickets que no se habían guardado se pierden | SQS guarda los mensajes hasta 4 días |
| Es un solo servidor | Si se cae, no hay servicio | Servicios administrados en varias zonas de disponibilidad |
| Hay que mantener el sistema operativo y Docker | Trabajo de operación y riesgo de seguridad | No hay servidor que mantener |
| Los correos no se envían | El usuario no se entera de los cambios | SNS envía un correo en cada cambio de estado |

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `PUERTO` | `8080` | Puerto en el que escucha |
| `DATOS` | `/data/tickets.db` en la imagen | Archivo de la base de datos |
| `SLA_HORAS` | `24` | Horas máximas de un ticket pendiente |
| `SLA_CADA_SEG` | `3600` | Cada cuántos segundos se revisa el SLA |
