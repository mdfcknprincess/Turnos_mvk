#!/usr/bin/env bash
# Prueba del patron cola: envia muchos tickets seguidos y mide cuanto tarda
# la API en aceptarlos y cuanto tarda el worker en dejarlos guardados.
#
# Uso: ./scripts/prueba-carga.sh <url-de-la-api> [cantidad=60] [en-paralelo=5]
#   Los tickets usan un correo @example.com: no se envia ningun correo.
#   La API limita a 10 peticiones por segundo (rafaga de 20): con mas paralelismo
#   veras respuestas 429, que es el limite funcionando.
set -uo pipefail
API="${1:?Uso: prueba-carga.sh <url-de-la-api> [cantidad] [en-paralelo]}"; API="${API%/}"
N="${2:-60}"
PARALELO="${3:-5}"
EMAIL="carga-$(date +%s)@example.com"

echo "Enviando $N tickets ($PARALELO a la vez) como $EMAIL"
INICIO=$(date +%s.%N)
seq 1 "$N" | xargs -P "$PARALELO" -I{} curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API/tickets" \
  -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"titulo\":\"Carga {}\",\"descripcion\":\"Prueba de carga\"}" > /tmp/carga-codigos.txt
FIN_ENVIO=$(date +%s.%N)
echo "Respuestas de la API (cantidad y codigo HTTP):"
sort /tmp/carga-codigos.txt | uniq -c | sed 's/^/   /'
ACEPTADOS=$(grep -c '^202$' /tmp/carga-codigos.txt || true)
python3 -c "print(f'La API acepto $ACEPTADOS tickets en {$FIN_ENVIO - $INICIO:.1f} s')"

echo "Esperando a que el worker los guarde todos..."
GUARDADOS=0
for _ in $(seq 1 90); do
  GUARDADOS=$(curl -s "$API/tickets?email=$EMAIL" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  [[ "$GUARDADOS" -ge "$ACEPTADOS" ]] && break
  sleep 1
done
python3 -c "print(f'Guardados: $GUARDADOS de $ACEPTADOS, {$(date +%s.%N) - $INICIO:.1f} s despues del primer envio')"
if [[ "$GUARDADOS" -eq "$ACEPTADOS" ]]; then echo "RESULTADO: ningun ticket aceptado se perdio"; else echo "RESULTADO: faltan tickets (revisar la cola y la DLQ)"; exit 1; fi
