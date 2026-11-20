# Decisiones de arquitectura

Cada decisión responde a una historia de [historias.md](historias.md) y sigue el mismo formato: contexto, decisión, alternativa descartada y consecuencias. Al final está la revisión contra los 6 pilares del marco Well-Architected.

| # | Decisión | Historia que la origina |
|---|---|---|
| ADR-01 | Cómputo sin servidor (Lambda) | HU-NF-01 |
| ADR-02 | Ingreso asincrónico con SQS y cola de fallidos | HU-01.2, HU-NF-02 |
| ADR-03 | DynamoDB bajo demanda en lugar de RDS | HU-NF-01 |
| ADR-04 | Concurrencia con escritura condicional | HU-02.2, HU-NF-03 |
| ADR-05 | Notificaciones con Streams y SNS filtrado | HU-05.1 |
| ADR-06 | Un solo template con código embebido | HU-NF-04 |
| ADR-07 | Un rol IAM por función | HU-NF-05 |
| ADR-08 | Observabilidad: tablero, alarma y registros con retención | HU-NF-06 |
| ADR-09 | SLA con una regla programada | HU-EX-01 |
| ADR-10 | Sin autenticación en esta versión (riesgo aceptado) | — |
| ADR-11 | De un servidor con Docker a serverless | HU-NF-08, HU-NF-01 |

---

## ADR-01 · Cómputo sin servidor (Lambda) en lugar de contenedores o servidores

- **Contexto:** la carga es baja e intermitente (una oficina, en horario laboral) y el presupuesto es de máximo 10 USD al mes. El enunciado permite «Lambda o ECS».
- **Decisión:** API Gateway (HTTP API) con siete funciones Lambda en Python 3.12.
- **Descartado:** ECS Fargate detrás de un balanceador. Solo el balanceador cuesta unos 16 USD al mes y una tarea mínima encendida todo el mes unos 9 USD: se rompe el presupuesto sin atender un ticket. Un servidor EC2 propio cuesta unos 12 USD al mes (ver ADR-11).
- **Consecuencias:** costo casi nulo en reposo, escalado automático y sin sistema operativo que parchar. A cambio, la primera llamada tras un rato inactivo tarda unos cientos de milisegundos más (arranque en frío), algo aceptable en una mesa de ayuda.

## ADR-02 · Ingreso asincrónico con SQS y cola de mensajes fallidos

- **Contexto:** restricción del enunciado («los tickets entran por cola asincrónica») y riesgo de picos (lunes a primera hora).
- **Decisión:** `POST /tickets` solo valida y publica en SQS, y responde `202`. Una función *worker* consume en lotes de hasta 10 y guarda.
- **Detalles:** si un mensaje falla 3 veces pasa a una cola de fallidos (DLQ) que lo conserva 14 días; solo se reintenta el mensaje que falló y no todo el lote; como máximo corren 2 workers en paralelo, para que la base de datos reciba un ritmo controlado. Explicación completa en [patron-cola.md](patron-cola.md).
- **Descartado:** escribir directo en la base de datos (se pierden tickets si falla) y SQS FIFO (más costosa y con menor capacidad; el orden de atención lo da el índice de la tabla, no la cola de ingreso).
- **Consecuencias:** el ticket aparece unos segundos después de crearlo (consistencia eventual). La página lo maneja consultando hasta que aparece.

## ADR-03 · DynamoDB bajo demanda en lugar de RDS

- **Decisión:** una tabla `tickets` con clave `ticketId` y dos índices: `porEstado` (estado + fecha, la cola que ve el agente) y `porEmail` (correo + fecha, «mis tickets»).
- **Descartado:** RDS. La instancia más pequeña cuesta entre 12 y 15 USD al mes con su disco, está siempre encendida y exige una red privada (VPC).
- **Consecuencias:** se paga por operación y no hay servidor que administrar. Las métricas leen la tabla completa (`Scan`): correcto para miles de tickets; con cientos de miles habría que precalcular los totales (trabajo futuro).

## ADR-04 · Concurrencia con escritura condicional

- **Problema:** dos agentes pulsan *Tomar* sobre el mismo ticket al mismo tiempo.
- **Decisión:** la actualización lleva una condición (`estado = PENDIENTE`). DynamoDB garantiza que solo una gana; la otra recibe `409 Conflict`. Lo mismo al resolver: solo el agente asignado y solo si está `EN_PROCESO`.
- **Descartado:** leer el ticket y luego escribirlo. Entre la lectura y la escritura otro agente puede adelantarse (condición de carrera).

## ADR-05 · Notificaciones con DynamoDB Streams y SNS filtrado

- **Decisión:** cada cambio en la tabla genera un evento en el Stream. La función `notificar` publica en un tema de SNS con el atributo `email`. Cada usuario queda suscrito, al crear su primer ticket, con un **filtro** por su correo: solo recibe lo suyo.
- **Por qué Streams:** las funciones de la API no saben nada de correos (bajo acoplamiento). Cualquier cambio de estado futuro notifica sin tocar código.
- **Descartado:** SES. En modo de prueba exige verificar cada destinatario y salir de ese modo requiere una solicitud a AWS. SNS funciona de inmediato; a cambio, cada usuario confirma su suscripción una vez.
- **Detalle:** los correos del dominio reservado `example.com` (datos y pruebas de carga) nunca se suscriben.

## ADR-06 · Un solo template de CloudFormation con el código embebido

- **Contexto:** el curso exige recrear todo con `aws cloudformation deploy --template-file iac/main.yaml …` y sugiere, idealmente, stacks anidados o por capa.
- **Decisión:** un único `iac/main.yaml`, organizado por capas (datos, mensajería, seguridad, cómputo, API, frontend, observabilidad), con parámetros y salidas. El código de las funciones va dentro del template.
- **Por qué no anidado:** los stacks anidados obligan a subir antes los templates hijos a S3 (`aws cloudformation package`). Ese paso previo rompe el «un solo comando desde cero». Las capas quedan separadas por secciones del mismo archivo.
- **Límites que se vigilan con pruebas:** cada función debe caber en 4.096 caracteres y el template completo en 51.200 bytes; por encima de eso el comando exigiría un bucket (`--s3-bucket`).
- **Consecuencia:** si el sistema crece, el siguiente paso es dividir en stacks por capa y empaquetar el código desde el pipeline.

## ADR-07 · Un rol IAM por función (mínimo privilegio)

- **Decisión:** siete funciones, siete roles. Cada rol lista acciones exactas sobre los recursos de este proyecto; ninguna política usa `*` como acción ni como recurso completo, y ningún rol puede borrar tickets.
- **Origen:** la auditoría encontró que la primera versión compartía roles entre funciones (hallazgo H1 de [seguridad.md](seguridad.md)).
- **Excepción:** las cuentas de AWS Academy no dejan crear roles. Con `CrearRolesIam=false` las funciones usan el rol existente (`LabRole`) y el mínimo privilegio no aplica.

## ADR-08 · Observabilidad: tablero, alarma y registros con retención

- **Métricas de negocio** (tiempos, tickets por agente, SLA): en la vista Jefe de la página.
- **Métricas técnicas:** un tablero de CloudWatch creado por el template (mensajes en cola, mensajes fallidos, peticiones y errores).
- **Alarma:** si un mensaje llega a la cola de fallidos, el jefe recibe un correo. No depende de que alguien mire el tablero.
- **Registros:** cada función tiene su grupo de registros declarado en el template, con retención de 14 días, para que no crezcan sin límite ni queden huérfanos al destruir el entorno.

## ADR-09 · SLA con una regla programada de EventBridge

- **Decisión:** una regla dispara cada hora la función `sla`. Esta consulta los `PENDIENTE` creados hace más de 24 horas, alerta al jefe por SNS y marca el ticket para no repetir.
- **Consecuencia:** la alerta llega, como máximo, una hora después de vencer el plazo. Se puede bajar a 15 minutos sin costo relevante.

## ADR-10 · Sin autenticación en esta versión (riesgo aceptado)

- **Riesgo:** cualquiera con la URL puede usar la API y escribir cualquier nombre de agente.
- **Mitigación actual:** límite de 10 peticiones por segundo, validación de transiciones y datos ficticios.
- **Corrección propuesta:** Amazon Cognito con grupos y un autorizador JWT en la API; el agente saldría del token y no del formulario. Requiere servir la página por HTTPS (CloudFront), porque Cognito no acepta direcciones de retorno HTTP.

## ADR-11 · De un servidor con Docker (versión 1) a serverless (versión 2)

- **Versión 1 (hito «Servicio en línea»):** toda la aplicación en un contenedor Docker (`app/`) sobre un servidor EC2 propio (`iac/servidor.yaml`). Misma página y misma API; cola en memoria y base de datos SQLite.
- **Qué mostró la revisión de esa versión:**

| Pilar | Problema de la versión 1 |
|---|---|
| Costo | Unos 12 USD al mes encendida todo el día: supera el presupuesto sin atender un ticket |
| Fiabilidad | Un solo servidor: si se cae, no hay servicio. La cola vive en memoria: un reinicio pierde lo que no se había guardado |
| Operación | Hay que parchar el sistema operativo y Docker, y vigilar el disco |
| Rendimiento | Capacidad fija: un pico grande rechaza conexiones |
| Seguridad | Un puerto abierto a internet que administrar |

- **Decisión:** la versión final reemplaza cada pieza por un servicio administrado (la tabla de equivalencias está en [`app/README.md`](../app/README.md)): el servidor web por S3 y API Gateway, la cola en memoria por SQS, SQLite por DynamoDB, el hilo de SLA por EventBridge y el registro de «correos» por SNS.
- **Qué se conserva:** el contrato de la API y la página no cambiaron; por eso las mismas pruebas (`scripts/demo.sh`) corren contra las dos versiones. La imagen Docker sigue sirviendo para desarrollo local y como plan B de la demo.

---

# Revisión contra los 6 pilares

| Pilar | Cómo se cumple | Riesgo pendiente |
|---|---|---|
| **Excelencia operativa** | Todo en CloudFormation, pipeline CI/CD, 56 pruebas automáticas, tablero, alarma de mensajes fallidos y registros con retención. | No hay alarmas de errores por función. |
| **Seguridad** | Un rol por función sin comodines, cifrado en reposo, API por HTTPS, entrada validada, límite de peticiones. | API sin autenticación y página por HTTP (ADR-10). |
| **Fiabilidad** | Cola con reintentos y DLQ, worker idempotente, escritura condicional, servicios administrados que operan en varias zonas de disponibilidad. | Sin copias de seguridad de la tabla (activar recuperación a un punto en el tiempo en producción). |
| **Eficiencia de rendimiento** | Funciones de 128 a 256 MB, índices para las consultas frecuentes, procesamiento por lotes. | Las métricas leen toda la tabla (ADR-03). |
| **Optimización de costos** | Pago por uso, sin red privada ni balanceador, HTTP API en lugar de REST, tope de peticiones, registros con vencimiento. Cerca de 1 USD al mes. | El tablero es gratuito solo dentro de los 3 primeros de la cuenta. |
| **Sostenibilidad** | Sin servidores ociosos: los recursos solo consumen cuando llega trabajo. | — |
