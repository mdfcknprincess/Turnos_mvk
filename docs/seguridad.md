# Auditoría de permisos y seguridad

**Resultado:** cada función tiene su propio rol con los permisos mínimos, ninguna política usa `*` como acción ni como recurso completo, y nadie puede borrar tickets. Quedan **dos riesgos aceptados** para el laboratorio, con plan de corrección: la API no tiene autenticación y la página se sirve por HTTP.

## 1. Alcance y método

| Qué se revisó | Cómo |
|---|---|
| Roles y políticas IAM de las 7 funciones | Lectura de `iac/main.yaml` y pruebas automáticas (`tests/test_plantilla.py`, clase `AuditoriaDePermisos`) |
| Políticas de recursos (bucket, permisos de invocación) | Lectura de la plantilla |
| Exposición a internet | Qué URL responde sin credenciales |
| Datos (cifrado, datos personales, retención) | Configuración de cada servicio |
| Credenciales del pipeline | `.github/workflows/cd.yml` |
| Servidor de la versión 1 | `iac/servidor.yaml` y `app/Dockerfile` |

## 2. Matriz de permisos (quién puede hacer qué)

Todos los roles solo pueden ser asumidos por el servicio Lambda. Además de lo que muestra la tabla, cada rol puede escribir sus registros en CloudWatch (política administrada `AWSLambdaBasicExecutionRole`).

| Rol | Función | Puede | Sobre | No puede (ejemplos) |
|---|---|---|---|---|
| `RolCrearTicket` | `crear-ticket` | `sqs:SendMessage` | La cola de tickets | Leer o escribir la tabla, enviar correos |
| `RolWorker` | `worker` | `sqs:ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes` · `dynamodb:PutItem` · `sns:Subscribe` | La cola, la tabla, el tema de usuarios | Leer, modificar o borrar tickets; publicar correos |
| `RolConsultas` | `consultas` | `dynamodb:GetItem`, `Query`, `Scan` | La tabla y sus índices | Cualquier escritura |
| `RolEstado` | `cambiar-estado` | `dynamodb:UpdateItem` | La tabla | Crear, listar o borrar tickets |
| `RolNotificar` | `notificar` | Leer el stream (`GetRecords`, `GetShardIterator`, `DescribeStream`, `ListStreams`) · `sns:Publish` | Los streams de la tabla de tickets, el tema de usuarios | Tocar la tabla; escribirle al jefe |
| `RolSla` | `sla` | `dynamodb:Query` · `dynamodb:UpdateItem` · `sns:Publish` | El índice `porEstado`, la tabla, el tema del jefe | Escribirles a los usuarios |
| `RolSemilla` | `semilla` | `dynamodb:BatchWriteItem` | La tabla | Todo lo demás (corre una sola vez) |

Ninguna función tiene `dynamodb:DeleteItem`: **el sistema no puede borrar un ticket**, ni por error ni por un fallo de seguridad.

Los únicos comodines están acotados a la tabla de tickets: `…/index/*` (sus índices) y `…/stream/*` (sus streams, porque el identificador de un stream cambia cada vez que se recrea).

## 3. Hallazgos

| # | Hallazgo | Riesgo | Estado | Qué se hizo o se propone |
|---|---|---|---|---|
| H1 | **Roles compartidos.** La primera versión de la plantilla tenía 4 roles: `consultas` y `cambiar-estado` compartían uno, y `notificar`, `sla` y `semilla` otro. Cada función tenía permisos que no usaba (la de consultas podía modificar tickets). | Medio | **Corregido** | Un rol por función (7 roles). Una prueba falla si dos funciones vuelven a compartir rol. |
| H2 | **API sin autenticación.** Cualquiera con la URL puede listar tickets (incluyen correos) y cambiar estados; el nombre del agente lo escribe quien usa la página. | Alto en producción | **Aceptado en el laboratorio** | Mitigado con límite de 10 peticiones por segundo, validación de transiciones y datos de prueba ficticios. Corrección: Amazon Cognito con grupos (usuarios, agentes, jefes) y un autorizador JWT en la API. |
| H3 | **La página se sirve por HTTP.** El sitio web de S3 no ofrece HTTPS. La API sí usa HTTPS. | Medio | **Aceptado en el laboratorio** | Corrección: CloudFront delante del bucket, con certificado de ACM. Además es requisito para usar Cognito. |
| H4 | **Bucket con lectura pública.** | Bajo | Esperado | Es un sitio estático: solo permite `s3:GetObject`, solo en ese bucket, y no guarda datos de tickets. Con CloudFront el bucket pasaría a ser privado. |
| H5 | **Registros con recurso amplio.** La política administrada de Lambda permite escribir en cualquier grupo de registros de la cuenta. | Bajo | Aceptado | Es la política estándar de AWS. Mejora: política propia limitada al grupo de cada función. |
| H6 | **Credenciales del pipeline.** El despliegue usa claves guardadas como secretos de GitHub. | Medio | Mitigado | Secretos cifrados, el flujo solo tiene permiso de lectura del repo y solo despliega desde `main`. Corrección: federación OIDC, para que GitHub asuma un rol sin guardar claves. |
| H7 | **Servidor de la versión 1.** Puerto 80 abierto a internet, sin TLS. | Medio | Aceptado para el hito | Sin puerto SSH, contenedor sin privilegios de root, disco cifrado. El servidor se apaga cuando no se usa. |
| H8 | **Datos personales.** Los tickets guardan correo y nombre, sin fecha de borrado. | Medio | Parcial | Los datos de prueba usan el dominio reservado `example.com`. Los registros se borran a los 14 días. Mejora: TTL en DynamoDB para tickets resueltos antiguos. |
| H9 | **Modo AWS Academy.** Con `CrearRolesIam=false` todas las funciones usan `LabRole`, que tiene permisos muy amplios. | Medio | Limitación del entorno | Esas cuentas no permiten crear roles. El mínimo privilegio solo aplica con `CrearRolesIam=true`. |
| H10 | **Cualquiera puede hacer que se envíe un correo de confirmación.** El formulario acepta cualquier dirección y, al guardarse el ticket, SNS le envía a esa dirección el correo de confirmación de la suscripción. Alguien podría usarlo para molestar a terceros. | Medio | Mitigado en parte | El límite de 10 peticiones por segundo acota el abuso y las direcciones `@example.com` nunca se suscriben. Corrección: con Cognito el correo sale del usuario autenticado; como alternativa, aceptar solo el dominio de la empresa. |

## 4. Otras capas de protección

- **Cifrado en tránsito:** la API solo responde por HTTPS.
- **Cifrado en reposo:** DynamoDB cifra por defecto con una clave propiedad de AWS; las dos colas usan cifrado administrado por SQS; el disco del servidor v1 está cifrado.
- **Entrada validada:** la API exige correo, título y descripción, limita tamaños (título 120 caracteres, descripción 2.000) y normaliza categoría y prioridad.
- **Página a prueba de inyección:** todo texto que viene de la API se escapa antes de mostrarse, así un título con HTML no se ejecuta.
- **Transiciones controladas:** un ticket solo se toma si está `PENDIENTE` y solo lo resuelve el agente asignado. Lo garantiza la base de datos con una escritura condicional.
- **Tope de abuso y de costo:** 10 peticiones por segundo, con ráfaga de 20.
- **Sin superficie de red propia:** la arquitectura final no tiene VPC, servidores ni puertos abiertos que administrar.

## 5. Qué es visible desde internet

| Recurso | ¿Responde sin credenciales? | Comentario |
|---|---|---|
| API (`https://…execute-api…`) | Sí | Riesgo H2 |
| Página (`http://…s3-website…`) | Sí, solo lectura | Riesgos H3 y H4 |
| DynamoDB, SQS, SNS, Lambda | No | Exigen credenciales de AWS firmadas |
| Servidor v1 (si está encendido) | Sí, puerto 80 | Riesgo H7 |

## 6. Cómo comprobarlo en la cuenta

```bash
# Los 7 roles del stack
aws iam list-roles --query "Roles[?starts_with(RoleName, 'gtn-<equipo>-')].RoleName" --output table

# La política de un rol (por ejemplo, el de consultas)
ROL=$(aws iam list-roles --query "Roles[?contains(RoleName, 'RolConsultas')].RoleName" --output text)
aws iam get-role-policy --role-name "$ROL" --policy-name leer-tickets

# Prueba negativa: ¿el rol de consultas puede modificar o borrar tickets? Debe decir implicitDeny
TABLA=$(aws dynamodb describe-table --table-name gtn-<equipo>-tickets --query Table.TableArn --output text)
aws iam simulate-principal-policy \
  --policy-source-arn "$(aws iam get-role --role-name "$ROL" --query Role.Arn --output text)" \
  --action-names dynamodb:UpdateItem dynamodb:DeleteItem --resource-arns "$TABLA" \
  --query "EvaluationResults[].[EvalActionName, EvalDecision]" --output table
```

En la consola, **IAM → Access Analyzer** debe reportar como acceso público únicamente el bucket de la página.

## 7. Controles automáticos

Estas pruebas corren en cada pull request y fallan si alguien debilita la seguridad de la plantilla:

| Prueba (`tests/test_plantilla.py`) | Qué impide |
|---|---|
| `test_cada_funcion_tiene_su_propio_rol` | Volver a compartir roles (H1) |
| `test_ninguna_politica_usa_comodines` | Acciones con `*` o un recurso `*` completo |
| `test_permisos_esperados_por_rol` | Agregar un permiso sin actualizar esta auditoría |
| `test_nadie_puede_borrar_tickets` | Dar permiso de borrado sobre la tabla |
| `test_los_roles_solo_los_asume_lambda` | Que otra cuenta o servicio asuma los roles |
| `test_lo_unico_publico_es_la_lectura_del_sitio_web` | Abrir algo más al público |
| `test_el_servidor_solo_abre_el_puerto_80` | Abrir SSH a internet en el servidor v1 |
| `test_colas_cifradas_y_con_cola_de_fallidos` | Quitar el cifrado o la DLQ |
