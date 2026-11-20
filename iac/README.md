# Infraestructura como código (CloudFormation)

Hay dos plantillas. Cada una crea un stack independiente.

| Plantilla | Qué crea | Stack | Costo encendido todo el mes |
|---|---|---|---|
| [`main.yaml`](main.yaml) | **La versión final**, sin servidores: API, 7 funciones, cola, tabla, notificaciones, página, tablero y alarma | `gtn-<equipo>` | ≈ 0,9 USD |
| [`servidor.yaml`](servidor.yaml) | La versión 1 (hito «Servicio en línea»): un servidor EC2 que construye y ejecuta la imagen Docker de `app/` | `gtn-<equipo>-servidor` | ≈ 11,9 USD |

`main.yaml` está organizado por capas, cada una en su sección: **datos** (DynamoDB), **mensajería** (SQS y SNS), **seguridad** (roles IAM), **cómputo** (Lambda), **API** (API Gateway), **frontend** (S3) y **observabilidad** (registros, alarma y tablero). No hay capa de red porque la versión final no usa VPC.

> **¿Por qué un solo archivo y no stacks anidados?** Los stacks anidados obligan a subir antes las plantillas hijas a S3 (`aws cloudformation package`). El curso exige recrear todo con un solo `aws cloudformation deploy --template-file iac/main.yaml`, sin pasos previos. Por la misma razón el código de las funciones va dentro de la plantilla. Detalle en la decisión ADR-06 de [`docs/decisiones.md`](../docs/decisiones.md).

## Parámetros de `main.yaml`

Todos tienen valor por defecto, así que el comando del curso funciona sin `--parameter-overrides`.

| Parámetro | Por defecto | Para qué |
|---|---|---|
| `Equipo` | `equipo` | Tag obligatorio. En minúsculas y sin espacios |
| `Proyecto` | `10` | Tag obligatorio |
| `Ambiente` | `lab` | Tag obligatorio |
| `EmailJefe` | `jefe@example.com` | Correo que recibe las alertas de SLA y de mensajes fallidos. Con el valor por defecto no se suscribe a nadie: **cámbienlo** |
| `SlaHoras` | `24` | Horas máximas que un ticket puede estar `PENDIENTE` |
| `CrearRolesIam` | `true` | `true`: un rol de mínimo privilegio por función. `false`: todas usan `RolExistente` |
| `RolExistente` | `LabRole` | Nombre del rol cuando `CrearRolesIam=false` (cuentas AWS Academy) |
| `CrearSitioWeb` | `true` | `false` si la cuenta bloquea los buckets públicos |

**Salidas:** `ApiUrl`, `SitioWebUrl`, `BucketSitio`, `ColaUrl`, `DlqUrl`, `TablaTickets`, `TopicUsuarios`, `DashboardUrl`.

**Tags:** todo recurso que los admite declara `Curso: GTN-2026-2`, `Equipo`, `Proyecto` y `Ambiente`. Una prueba automática lo comprueba. Los recursos que no admiten tags en la plantilla (rutas, permisos, la regla programada) los heredan del stack cuando se despliega con `--tags`, como hace `scripts/deploy.sh`.

## Desplegar

Con el script, que además publica la página:

```bash
./scripts/deploy.sh <equipo> <correo-del-jefe>            # cuenta normal
./scripts/deploy.sh <equipo> <correo-del-jefe> LabRole    # AWS Academy
```

A mano, en dos pasos:

```bash
# 1. Infraestructura
aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-<equipo> \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Equipo=<equipo> EmailJefe=<correo-del-jefe> \
  --tags Curso=GTN-2026-2 Equipo=<equipo> Proyecto=10 Ambiente=lab
# En AWS Academy se agrega a --parameter-overrides:  CrearRolesIam=false RolExistente=LabRole

# 2. Página
API=$(aws cloudformation describe-stacks --stack-name gtn-<equipo> --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --stack-name gtn-<equipo> --query "Stacks[0].Outputs[?OutputKey=='BucketSitio'].OutputValue" --output text)
aws s3 cp frontend/index.html s3://$BUCKET/index.html --content-type "text/html; charset=utf-8"
echo "window.APP_CONFIG = { apiUrl: '$API' };" | aws s3 cp - s3://$BUCKET/config.js --content-type application/javascript
```

La creación tarda unos minutos. Al terminar:

1. El jefe recibe el correo *AWS Notification - Subscription Confirmation* y debe **confirmarlo**.
2. Cada usuario recibe uno igual la primera vez que crea un ticket.
3. Los 14 tickets de prueba ya están cargados: se ven en la vista Jefe.

## Versión 1: el servidor propio

```bash
aws cloudformation deploy --template-file iac/servidor.yaml --stack-name gtn-<equipo>-servidor \
  --parameter-overrides Equipo=<equipo> RepoUrl=https://github.com/<usuario>/<repo>.git
# En AWS Academy se agrega:  PerfilInstancia=LabInstanceProfile   (permite entrar por Session Manager)
```

El servidor clona el repo, construye la imagen y arranca el contenedor. La salida `Url` empieza a responder unos minutos después, cuando termina de construirse la imagen. El repositorio debe ser **público** para que el servidor pueda clonarlo. Pasos manuales y diagnóstico: [`app/README.md`](../app/README.md).

## Detener (pausar sin borrar)

La versión final no tiene nada encendido: sin uso cuesta prácticamente cero. Lo único que corre solo es la revisión de SLA de cada hora.

```bash
# Pausar la revisión de SLA
REGLA=$(aws events list-rules --name-prefix gtn-<equipo> --query 'Rules[0].Name' --output text)
aws events disable-rule --name "$REGLA"          # reanudar: enable-rule

# Pausar el consumo de la cola: los tickets nuevos esperan en SQS hasta 4 días
UUID=$(aws lambda list-event-source-mappings --function-name gtn-<equipo>-worker --query 'EventSourceMappings[0].UUID' --output text)
aws lambda update-event-source-mapping --uuid "$UUID" --no-enabled     # reanudar: --enabled

# Apagar el servidor de la versión 1 (deja de cobrar cómputo y dirección IP; el disco sigue costando 0,64 USD al mes)
aws ec2 stop-instances --instance-ids <InstanciaId>
```

## Destruir

```bash
./scripts/destroy.sh <equipo>
```

Vacía el bucket de la página y elimina los dos stacks. **Borra también los tickets.** A mano:

```bash
aws s3 rm s3://<BucketSitio> --recursive
aws cloudformation delete-stack --stack-name gtn-<equipo>
aws cloudformation delete-stack --stack-name gtn-<equipo>-servidor
```

## Validar antes de desplegar

```bash
pip install cfn-lint pyyaml
cfn-lint iac/*.yaml                                # lo mismo que corre el CI en cada pull request
python3 tests/test_plantilla.py                    # tags, permisos, tamaño y referencias
aws cloudformation validate-template --template-body file://iac/main.yaml
```

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El stack falla al crear un rol (`iam:CreateRole`) | La cuenta es de AWS Academy | Desplegar con `CrearRolesIam=false` (tercer argumento `LabRole` en `deploy.sh`) |
| Falla al crear la política del bucket | La cuenta bloquea el acceso público a S3 | Desplegar con `CrearSitioWeb=false` y abrir `frontend/index.html?api=<ApiUrl>` desde el computador |
| El stack queda en `ROLLBACK_COMPLETE` | Falló la primera creación | Borrarlo (`delete-stack`) y volver a desplegar: un stack en ese estado no se puede actualizar |
| La página carga pero dice «Configura la URL de la API» | No se subió `config.js` | Repetir el paso 2 o pegar la URL de la API en el campo de arriba a la derecha |
| No llegan correos | La suscripción no está confirmada | Buscar el correo de AWS (revisar correo no deseado) y confirmar |
| El ticket no aparece tras crearlo | El worker falló | Revisar la cola de fallidos en el tablero y los registros de la función `gtn-<equipo>-worker` (consola de Lambda → Monitorear → Ver registros de CloudWatch) |
| El pipeline falla con `ExpiredToken` | Las credenciales de AWS Academy duran pocas horas | Actualizar los tres secretos en GitHub al iniciar cada sesión del laboratorio |

## Costo estimado

Cerca de **0,9 USD al mes** para 2.000 tickets y 50.000 llamadas a la API, a precios de lista. Dentro de la capa gratuita permanente el costo esperado es cercano a cero. Desglose, comparación con las alternativas y sensibilidad en [`docs/costos.md`](../docs/costos.md).
