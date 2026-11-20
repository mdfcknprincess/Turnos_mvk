# Informe FinOps

**Presupuesto objetivo:** máximo 10 USD al mes · **Estimado de la arquitectura final:** cerca de **0,9 USD al mes** a precio de lista, y prácticamente 0 dentro de la capa gratuita · **Región:** us-east-1

> Los precios son de lista, en us-east-1, consultados en noviembre de 2026. Los de EC2, la dirección IPv4, Lambda, API Gateway, SQS, SNS y DynamoDB se contrastaron con las páginas de AWS y con fuentes secundarias coincidentes. Los de CloudWatch, el balanceador, Fargate, RDS y NAT Gateway son los habituales de lista y **deben validarse**. **Antes de entregar:** repetir el cálculo en la [calculadora de AWS](https://calculator.aws/), pegar aquí el enlace, y comparar con el gasto real en **Cost Explorer** filtrando por el tag `Equipo`.

## 1. Escenario

Una oficina mediana: **2.000 tickets al mes** (unos 100 por día hábil), 5 agentes y 1 jefe.

| Supuesto | Cantidad al mes |
|---|---|
| Llamadas a la API (crear, ver la cola, métricas, cambios de estado) | 50.000 |
| Cambios guardados (crear, tomar, resolver) | 6.000 |
| Correos enviados a usuarios y al jefe | 6.000 |
| Revisiones de SLA (una por hora) | 730 |

## 2. Costo por servicio (versión final)

| Servicio | Cálculo | USD al mes |
|---|---|---|
| API Gateway (HTTP API) | 50.000 peticiones × 1,00 USD por millón | 0,05 |
| Lambda, invocaciones | unas 60.000 × 0,20 USD por millón | 0,01 |
| Lambda, cómputo | unos 3.500 GB-segundo × 0,0000166667 USD | 0,06 |
| SQS | unas 650.000 consultas del worker a la cola + 6.000 operaciones de mensajes, a 0,40 USD por millón | 0,26 |
| DynamoDB, escrituras | unas 22.000 unidades (cada escritura actualiza también los 2 índices) × 0,625 USD por millón | 0,01 |
| DynamoDB, lecturas | unos 2 millones de unidades (cola y métricas) × 0,125 USD por millón | 0,25 |
| DynamoDB, almacenamiento | menos de 10 MB × 0,25 USD por GB | 0,00 |
| DynamoDB Streams | leído por Lambda: sin costo | 0,00 |
| SNS, correos | (6.000 − 1.000 gratis) × 2,00 USD por cada 100.000 | 0,10 |
| EventBridge | regla programada: sin costo | 0,00 |
| S3 (página) | 13 KB y unas 50.000 descargas | 0,02 |
| CloudWatch, registros | unos 30 MB × 0,50 USD por GB, con retención de 14 días | 0,02 |
| CloudWatch, alarma | 1 alarma estándar | 0,10 |
| CloudWatch, tablero | dentro de los 3 gratuitos de la cuenta | 0,00 |
| **Total** | | **≈ 0,88** |

La **capa gratuita permanente** cubre casi todo: 1 millón de peticiones y 400.000 GB-segundo de Lambda, 1 millón de peticiones de SQS, 25 GB de DynamoDB, 1.000 correos de SNS, 10 alarmas y 5 GB de registros. En el laboratorio el costo real esperado es cercano a 0.

El rubro más grande es curioso: **SQS cobra por las consultas que hace el worker para ver si hay mensajes**, aunque la cola esté vacía. Con espera larga de 20 segundos son unas 650.000 al mes; sin ella serían muchas más.

## 3. Comparación con las alternativas

| Arquitectura | Componentes | USD al mes |
|---|---|---|
| **Versión final (serverless)** | Tabla anterior | **≈ 0,9** |
| Versión 1 (servidor propio con Docker) | EC2 t3.micro 7,59 + disco de 8 GB 0,64 + dirección IPv4 pública 3,65 | ≈ 11,9 |
| Versión 1 encendida solo en horario laboral (unas 217 h) | 2,26 + 0,64 + 1,09 | ≈ 4,0, pero sin servicio de noche ni fines de semana |
| Contenedores administrados | Balanceador 16,43 + Fargate (0,25 vCPU, 0,5 GB) 9,01 + RDS db.t4g.micro con 20 GB 13,98 + 2 direcciones IPv4 7,30 | ≈ 47 |
| Lo anterior en subredes privadas | + NAT Gateway 32,85 | ≈ 80 |

Para esta carga, la versión final cuesta unas **13 veces menos** que el servidor propio y unas **50 veces menos** que la opción con contenedores. La razón es una sola: no paga por capacidad ociosa. De noche y los fines de semana el sistema cuesta cero.

## 4. Optimizaciones aplicadas

| # | Optimización | Efecto |
|---|---|---|
| 1 | Sin red privada (VPC) ni NAT Gateway | Evita unos 33 USD al mes |
| 2 | Sin balanceador: API Gateway cobra por petición | Evita unos 16 USD al mes |
| 3 | HTTP API en lugar de REST API | 1,00 contra 3,50 USD por millón de peticiones |
| 4 | DynamoDB bajo demanda en lugar de RDS encendida | Evita unos 14 USD al mes |
| 5 | Espera larga de 20 s en la cola | Menos consultas vacías a SQS |
| 6 | Funciones de 128 MB (256 MB solo la de métricas) | El cómputo se cobra por memoria asignada |
| 7 | Límite de 10 peticiones por segundo en la API | Tope de gasto ante abuso o un error en bucle |
| 8 | Registros con retención de 14 días | No se acumula almacenamiento |
| 9 | Cifrado de DynamoDB con la clave propiedad de AWS | Sin cargos de KMS |
| 10 | SNS para correos en lugar de SES | 1.000 correos gratis y sin trámite de salida del modo de prueba |
| 11 | Tags obligatorios en todos los recursos | El gasto se puede atribuir por equipo en Cost Explorer |
| 12 | `scripts/destroy.sh` | Costo cero al terminar el semestre |

## 5. Qué haría subir el costo

| Si… | Impacto |
|---|---|
| Los tickets se multiplican por 10 (20.000 al mes) | Entre 5 y 6 USD al mes: sigue dentro del presupuesto. Lo que más crece es la lectura para métricas, porque recorre toda la tabla |
| Alguien abusa de la API (no tiene autenticación) | Acotado por el límite de 10 peticiones por segundo: como máximo unos 26 millones al mes, cerca de 26 USD solo en API Gateway. Por eso se recomienda autenticación y una alerta de presupuesto |
| La cuenta ya tiene más de 3 tableros de CloudWatch | El cuarto en adelante se cobra por mes |
| Se deja encendido el servidor de la versión 1 | Unos 12 USD al mes: apagarlo o destruir su stack al terminar la demo |
| Se activan copias de seguridad continuas de la tabla | Despreciable con pocos MB |

## 6. Control del gasto

Crear una alerta de presupuesto de 10 USD que avise al 80 %:

```bash
aws budgets create-budget --account-id <cuenta> \
  --budget '{"BudgetName":"gtn-<equipo>","BudgetLimit":{"Amount":"10","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<correo>"}]}]'
```

## 7. Costo real medido

Completar después de tener el entorno desplegado unos días (Cost Explorer → agrupar por servicio → filtrar por el tag `Equipo`):

| Periodo | Costo real (USD) | Servicio más costoso | Observación |
|---|---|---|---|
| _por completar_ | | | |

## Fuentes de precios

- API Gateway: https://aws.amazon.com/api-gateway/pricing/
- SNS: https://aws.amazon.com/sns/faqs
- Dirección IPv4 pública: https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights
- EC2, Lambda, SQS, DynamoDB, CloudWatch, Fargate, RDS y NAT Gateway: página de precios de cada servicio, a validar en https://calculator.aws/
