#!/usr/bin/env bash
# Destruye el entorno completo. Despues de esto el costo es cero. BORRA TAMBIEN LOS TICKETS.
#
# Uso: ./scripts/destroy.sh <equipo>
set -euo pipefail
EQUIPO="${1:?Uso: destroy.sh <equipo>}"
STACK="gtn-${EQUIPO}"

BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketSitio'].OutputValue" --output text 2>/dev/null || true)
if [[ -n "$BUCKET" && "$BUCKET" != "None" ]]; then
  echo "Vaciando el bucket de la pagina (un bucket con archivos no se puede borrar)"
  aws s3 rm "s3://${BUCKET}" --recursive
fi

for S in "$STACK" "${STACK}-servidor"; do
  if aws cloudformation describe-stacks --stack-name "$S" >/dev/null 2>&1; then
    echo "Eliminando el stack $S"
    aws cloudformation delete-stack --stack-name "$S"
    aws cloudformation wait stack-delete-complete --stack-name "$S"
  fi
done
echo "Listo: no queda ningun recurso del proyecto en la cuenta."
