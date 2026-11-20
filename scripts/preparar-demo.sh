#!/usr/bin/env bash
# Deja el entorno listo para ensayar o sustentar:
#   1. restaura los 14 tickets de prueba a su estado original
#   2. dispara la revision de SLA ahora, sin esperar a la proxima hora (le llega el correo al jefe)
#   3. muestra las URL del entorno
# Los tickets creados en ensayos anteriores NO se borran.
#
# Uso: ./scripts/preparar-demo.sh <equipo>
set -euo pipefail
EQUIPO="${1:?Uso: preparar-demo.sh <equipo>}"
STACK="gtn-${EQUIPO}"
TMP=$(mktemp)

invocar() {  # invocar <funcion>: ejecuta la Lambda y muestra lo que devolvio
  aws lambda invoke --function-name "${STACK}-$1" --cli-binary-format raw-in-base64-out \
    --payload '{}' "$TMP" >/dev/null
  cat "$TMP"; echo
}
salida() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "== Datos de prueba restaurados:"
invocar semilla
sleep 3   # el indice por estado tarda un instante en reflejar los cambios
echo "== Revision de SLA (alertados = tickets incluidos en el correo al jefe):"
invocar sla
echo
echo "Pagina:  $(salida SitioWebUrl)"
echo "API:     $(salida ApiUrl)"
echo "Tablero: $(salida DashboardUrl)"
rm -f "$TMP"
