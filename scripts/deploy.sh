#!/usr/bin/env bash
# Despliega (o actualiza) el entorno completo y publica la pagina web.
#
# Uso: ./scripts/deploy.sh <equipo> <correo-del-jefe> [rol-existente]
#   rol-existente: solo para cuentas AWS Academy, que no dejan crear roles (pasar LabRole).
set -euo pipefail
cd "$(dirname "$0")/.."

EQUIPO="${1:?Uso: deploy.sh <equipo> <correo-del-jefe> [rol-existente]}"
EMAIL_JEFE="${2:?Falta el correo del jefe de soporte}"
ROL="${3:-}"
STACK="gtn-${EQUIPO}"

PARAMETROS=(Equipo="$EQUIPO" EmailJefe="$EMAIL_JEFE")
if [[ -n "$ROL" ]]; then
  PARAMETROS+=(CrearRolesIam=false RolExistente="$ROL")
fi

echo "== 1/2 Infraestructura (stack $STACK)"
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name "$STACK" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${PARAMETROS[@]}" \
  --tags Curso=GTN-2026-2 Equipo="$EQUIPO" Proyecto=10 Ambiente=lab \
  --no-fail-on-empty-changeset

salida() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
API_URL=$(salida ApiUrl)
BUCKET=$(salida BucketSitio)

echo "== 2/2 Pagina web"
if [[ -n "$BUCKET" && "$BUCKET" != "None" ]]; then
  aws s3 cp frontend/index.html "s3://${BUCKET}/index.html" \
    --content-type "text/html; charset=utf-8" --cache-control no-cache
  # config.js le dice a la pagina cual es la API de ESTE despliegue (no se guarda en el repo)
  echo "window.APP_CONFIG = { apiUrl: '${API_URL}' };" | aws s3 cp - "s3://${BUCKET}/config.js" \
    --content-type application/javascript --cache-control no-cache
  echo "Pagina:    $(salida SitioWebUrl)"
else
  echo "Sin sitio en S3 (CrearSitioWeb=false). Abre frontend/index.html?api=${API_URL}"
fi
echo "API:       ${API_URL}"
echo "Tablero:   $(salida DashboardUrl)"
echo
echo "Pendiente: el jefe debe confirmar el correo 'AWS Notification - Subscription Confirmation'."
