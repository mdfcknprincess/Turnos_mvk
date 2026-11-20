# Historias de usuario

Las cinco épicas del enunciado (HU-01 a HU-05) se descomponen aquí en historias pequeñas. Cada una se convierte en un **issue** (título `HU-XX`), tiene criterios de aceptación en formato *Dado / Cuando / Entonces* y se cierra con el pull request que la implementa.

- Los requisitos **no funcionales** (costo, picos de carga, seguridad…) también son historias: cada una justifica una decisión de [decisiones.md](decisiones.md).
- Cada criterio tiene una **prueba automática** que lo comprueba en cada cambio (`python3 -m unittest discover -s tests`).
- `python3 scripts/crear_issues.py` crea en GitHub los hitos y un issue por historia a partir de este archivo.

| Hito | Historias |
|---|---|
| Servicio en línea (sem 6–7) | HU-01.1 · HU-02.1 · HU-02.2 · HU-03.1 · HU-04.1 · HU-NF-08 |
| Arquitectura (sem 9–10) | HU-NF-01 · HU-NF-02 · HU-NF-03 |
| Automatización (sem 11–12) | HU-01.2 · HU-05.1 · HU-NF-04 · HU-NF-07 · HU-NF-09 |
| Seguridad y costos (sem 13–14) | HU-NF-05 · HU-NF-06 · HU-NF-10 |
| Sustentación (sem 16) | HU-EX-01 |

---

## Épica HU-01 · Crear ticket

### HU-01.1 · Crear ticket desde la web
Hito: Servicio en línea (sem 6–7) · Épica: HU-01 · Prueba: `tests/test_lambdas.py` (HU01CrearTicket)

**Como** usuario, **quiero** llenar un formulario con correo, título, descripción, categoría y prioridad, **para** reportar mi problema sin depender del correo.

- **Dado** que abro la URL del sistema, **cuando** envío el formulario con los campos obligatorios, **entonces** veo el código del ticket (`T-XXXXXXXX`) y el mensaje «en cola».
- **Dado** que dejo vacío el correo, el título o la descripción, **cuando** envío, **entonces** recibo un error 400 y no se crea nada.
- **Dado** que no instalé ningún programa, **cuando** uso el sistema desde cualquier navegador, **entonces** funciona.

### HU-01.2 · Ingreso asincrónico por cola
Hito: Automatización (sem 11–12) · Épica: HU-01 · Prueba: `tests/test_lambdas.py` (HU01IngresoPorCola) · Decisión: ADR-02

**Como** agente, **quiero** que los tickets entren por una cola, **para** que ninguno se pierda aunque haya un pico de reportes o falle la base de datos.

- **Dado** un ticket válido, **cuando** la API lo recibe, **entonces** responde `202` y el mensaje queda en SQS, sin escribir todavía en la base de datos.
- **Dado** un mensaje en la cola, **cuando** el worker lo procesa, **entonces** el ticket queda en DynamoDB con estado `PENDIENTE`.
- **Dado** que SQS entrega el mismo mensaje dos veces, **cuando** el worker lo procesa, **entonces** el ticket no se duplica.
- **Dado** un mensaje corrupto en un lote, **cuando** el worker lo procesa, **entonces** solo ese mensaje se reintenta y, tras 3 fallos, queda en la cola de mensajes fallidos (DLQ).

## Épica HU-02 · Cola de pendientes

### HU-02.1 · Ver la cola de pendientes
Hito: Servicio en línea (sem 6–7) · Épica: HU-02 · Prueba: `tests/test_lambdas.py` (HU02ColaDePendientes)

**Como** agente, **quiero** ver los tickets pendientes ordenados del más antiguo al más reciente, **para** atender en orden de llegada.

- **Dado** que hay tickets `PENDIENTE`, **cuando** abro la vista Agente, **entonces** los veo con prioridad, usuario y tiempo de espera, el más antiguo primero.
- **Dado** que tengo tickets en proceso, **cuando** abro la vista Agente, **entonces** veo aparte solo los míos.

### HU-02.2 · Tomar un ticket
Hito: Servicio en línea (sem 6–7) · Épica: HU-02 · Prueba: `tests/test_lambdas.py` (HU02ColaDePendientes) · Decisión: ADR-04

**Como** agente, **quiero** tomar un ticket de la cola, **para** que quede claro quién lo lleva.

- **Dado** un ticket `PENDIENTE`, **cuando** pulso *Tomar*, **entonces** pasa a `EN_PROCESO` con mi nombre y la hora.
- **Dado** que otro agente ya lo tomó, **cuando** intento tomarlo, **entonces** recibo `409` y el ticket conserva su agente original.

## Épica HU-03 · Cambiar estado

### HU-03.1 · Resolver un ticket
Hito: Servicio en línea (sem 6–7) · Épica: HU-03 · Prueba: `tests/test_lambdas.py` (HU03CambiarEstado)

**Como** agente, **quiero** marcar un ticket como resuelto indicando la solución, **para** que el usuario sepa qué se hizo.

- **Dado** un ticket `EN_PROCESO` asignado a mí, **cuando** pulso *Resolver*, **entonces** pasa a `RESUELTO` con la hora y la solución.
- **Dado** un ticket asignado a otro agente, **cuando** intento resolverlo, **entonces** recibo `409`.
- **Dado** un ticket que nadie ha tomado, **cuando** intento resolverlo, **entonces** recibo `409` y sigue `PENDIENTE`.

## Épica HU-04 · Métricas

### HU-04.1 · Dashboard del jefe
Hito: Servicio en línea (sem 6–7) · Épica: HU-04 · Prueba: `tests/test_lambdas.py` (HU04Metricas)

**Como** jefe, **quiero** ver tiempos promedio de atención y tickets por agente, **para** medir el servicio.

- **Dado** que existen tickets, **cuando** abro la vista Jefe, **entonces** veo el total y el conteo por estado, las horas promedio de espera y de resolución, y por agente: asignados, resueltos y promedio de resolución.
- **Dado** que se resuelve un ticket, **cuando** actualizo, **entonces** las métricas cambian.
- **Dado** que todavía no hay tickets, **cuando** abro la vista Jefe, **entonces** veo ceros y no un error.

## Épica HU-05 · Notificaciones

### HU-05.1 · Correo por cambio de estado
Hito: Automatización (sem 11–12) · Épica: HU-05 · Prueba: `tests/test_lambdas.py` (HU05Notificaciones) · Decisión: ADR-05

**Como** usuario, **quiero** recibir un correo cuando mi ticket cambia de estado, **para** hacer seguimiento.

- **Dado** que creé mi primer ticket, **cuando** el worker lo procesa, **entonces** recibo un correo de AWS para confirmar la suscripción.
- **Dado** que confirmé, **cuando** mi ticket pasa a `EN_PROCESO` o `RESUELTO`, **entonces** recibo un correo con el estado, el agente y la solución.
- **Dado** que otro usuario tiene tickets, **cuando** cambian de estado, **entonces** yo no recibo esos correos (filtro por correo).
- **Dado** un cambio que no es de estado, **cuando** se guarda, **entonces** no se envía ningún correo.

## Reto extra

### HU-EX-01 · Alerta de SLA
Hito: Sustentación (sem 16) · Épica: reto extra · Prueba: `tests/test_lambdas.py` (RetoSLA) · Decisión: ADR-09

**Como** jefe, **quiero** recibir una alerta si un ticket supera 24 h sin atención, **para** reaccionar antes de que el usuario se queje.

- **Dado** un ticket `PENDIENTE` creado hace más de 24 h, **cuando** corre la revisión horaria, **entonces** recibo un correo con su código, prioridad y título.
- **Dado** que ya fui alertado por ese ticket, **cuando** vuelve a correr la revisión, **entonces** no recibo un correo repetido.
- **Dado** un ticket antiguo que ya fue tomado, **cuando** corre la revisión, **entonces** no genera alerta.

## Requisitos no funcionales

### HU-NF-01 · Costo máximo de 10 USD al mes
Hito: Arquitectura (sem 9–10) · Épica: restricción del enunciado · Evidencia: [costos.md](costos.md) · Decisión: ADR-01 y ADR-03

**Como** jefe, **quiero** que el sistema cueste máximo 10 USD al mes, **para** que sea sostenible para la oficina.

- **Dado** el escenario de 2.000 tickets al mes, **cuando** se calcula el costo con precios de lista, **entonces** el total es menor que 10 USD.
- **Dado** que nadie usa el sistema, **cuando** pasa un mes, **entonces** el costo es prácticamente cero.

### HU-NF-02 · Soportar picos sin perder tickets
Hito: Arquitectura (sem 9–10) · Épica: restricción del enunciado · Evidencia: `scripts/prueba-carga.sh` · Decisión: ADR-02

**Como** usuario, **quiero** que mi reporte no se pierda cuando muchos reportan a la vez, **para** confiar en el sistema.

- **Dado** un pico de reportes, **cuando** la API los acepta, **entonces** todos terminan guardados aunque el worker tarde en procesarlos.
- **Dado** que el worker o la base de datos fallan, **cuando** se recuperan, **entonces** los tickets encolados se procesan sin intervención manual.

### HU-NF-03 · Un ticket, un solo agente
Hito: Arquitectura (sem 9–10) · Épica: HU-02 · Prueba: `tests/test_lambdas.py` (HU02ColaDePendientes) · Decisión: ADR-04

**Como** agente, **quiero** que dos agentes no puedan tomar el mismo ticket, **para** no duplicar trabajo.

- **Dado** dos agentes que pulsan *Tomar* a la vez, **cuando** llegan las dos peticiones, **entonces** solo una tiene éxito y la otra recibe `409`.

### HU-NF-04 · Entorno reproducible con un comando
Hito: Automatización (sem 11–12) · Épica: requisito del curso · Prueba: `tests/test_plantilla.py` (RequisitosDelCurso) · Decisión: ADR-06

**Como** equipo, **quiero** recrear todo el entorno con un solo comando, **para** reproducirlo desde cero en cualquier cuenta.

- **Dado** una cuenta vacía, **cuando** ejecuto `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-<equipo> --capabilities CAPABILITY_NAMED_IAM`, **entonces** quedan creados todos los recursos.
- **Dado** cualquier recurso que admita tags, **cuando** se crea, **entonces** lleva `Curso`, `Equipo`, `Proyecto` y `Ambiente`.

### HU-NF-05 · Mínimo privilegio
Hito: Seguridad y costos (sem 13–14) · Épica: requisito del curso · Prueba: `tests/test_plantilla.py` (AuditoriaDePermisos) · Evidencia: [seguridad.md](seguridad.md) · Decisión: ADR-07

**Como** equipo, **quiero** que cada función tenga solo los permisos que necesita, **para** limitar el daño si una falla o es vulnerada.

- **Dado** las siete funciones, **cuando** se revisan sus roles, **entonces** cada una tiene su propio rol y ninguna política usa comodines.
- **Dado** cualquier rol, **cuando** se revisan sus acciones, **entonces** ninguno puede borrar tickets.

### HU-NF-06 · Enterarse de los fallos técnicos
Hito: Seguridad y costos (sem 13–14) · Épica: operación · Evidencia: tablero y alarma de CloudWatch · Decisión: ADR-08

**Como** jefe, **quiero** enterarme si hay tickets que el sistema no pudo procesar, **para** actuar a tiempo.

- **Dado** un mensaje que falló 3 veces, **cuando** llega a la DLQ, **entonces** recibo un correo de alarma.
- **Dado** el sistema en operación, **cuando** abro el tablero, **entonces** veo mensajes en cola, errores y peticiones a la API.

### HU-NF-07 · Datos de prueba cargados
Hito: Automatización (sem 11–12) · Épica: restricción del enunciado · Prueba: `tests/test_lambdas.py` (DatosDePrueba)

**Como** evaluador, **quiero** encontrar datos de prueba al abrir el sistema, **para** verlo funcionando sin preparar nada.

- **Dado** un entorno recién creado, **cuando** abro la vista Jefe, **entonces** veo 14 tickets en los tres estados y 2 fuera de SLA.

### HU-NF-08 · Servicio en línea en servidor propio con Docker
Hito: Servicio en línea (sem 6–7) · Épica: requisito del curso · Prueba: `tests/test_app.py` · Decisión: ADR-11

**Como** equipo, **quiero** una primera versión corriendo en un servidor propio y empaquetada en Docker, **para** validar el caso de punta a punta antes de diseñar la arquitectura final.

- **Dado** el repo, **cuando** ejecuto `docker build -f app/Dockerfile -t soporte-ti .` y `docker run -p 8080:8080 soporte-ti`, **entonces** la mesa de ayuda responde en el puerto 8080.
- **Dado** el template `iac/servidor.yaml`, **cuando** lo despliego, **entonces** un servidor EC2 construye la imagen y publica la página en el puerto 80.

### HU-NF-09 · Pipeline CI/CD
Hito: Automatización (sem 11–12) · Épica: requisito del curso · Evidencia: `.github/workflows/`

**Como** equipo, **quiero** que cada cambio se valide y se despliegue solo, **para** no depender de pasos manuales.

- **Dado** un pull request, **cuando** se abre, **entonces** corren `cfn-lint`, las pruebas automáticas y la construcción de la imagen Docker.
- **Dado** un cambio fusionado en `main`, **cuando** están configuradas las credenciales, **entonces** se despliega la infraestructura y la página.

### HU-NF-10 · Informe de costos optimizado
Hito: Seguridad y costos (sem 13–14) · Épica: requisito del curso · Evidencia: [costos.md](costos.md)

**Como** jefe, **quiero** un informe con el costo mensual y las optimizaciones aplicadas, **para** decidir con cifras.

- **Dado** el entorno desplegado, **cuando** leo el informe, **entonces** veo el costo por servicio, la comparación con las alternativas y el costo real en Cost Explorer.
