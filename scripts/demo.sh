#!/usr/bin/env bash
# Prueba de extremo a extremo contra un entorno desplegado. Sirve como evidencia
# (docs/pruebas.md) y como plan B de la demo si el navegador falla.
#
# Uso: ./scripts/demo.sh <url-de-la-api> [correo]
#   Sin correo usa uno de @example.com, que no recibe notificaciones.
#   Funciona igual contra la version 1:  ./scripts/demo.sh http://<servidor>
set -uo pipefail
API="${1:?Uso: demo.sh <url-de-la-api> [correo]}"; API="${API%/}"
EMAIL="${2:-demo-$(date +%s)@example.com}"
JSON=(-H 'content-type: application/json')
FALLOS=0

paso() {  # paso <descripcion> <valor esperado> <valor obtenido>
  if [[ "$2" == "$3" ]]; then echo "  OK    $1 -> $3"; else echo "  FALLO $1: esperaba $2, llego $3"; FALLOS=$((FALLOS + 1)); fi
}
codigo() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "1. El usuario crea un ticket: entra a la cola y responde de inmediato"
RESP=$(curl -s -w '\n%{http_code}' -X POST "$API/tickets" "${JSON[@]}" \
  -d "{\"email\":\"$EMAIL\",\"titulo\":\"Demo: no tengo internet\",\"descripcion\":\"Prueba de extremo a extremo\",\"prioridad\":\"ALTA\",\"categoria\":\"RED\"}")
paso "POST /tickets" 202 "$(tail -n1 <<<"$RESP")"
ID=$(head -n1 <<<"$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ticketId",""))' 2>/dev/null)
echo "        ticket: ${ID:-<sin codigo>}"
paso "POST /tickets sin campos obligatorios" 400 "$(codigo -X POST "$API/tickets" "${JSON[@]}" -d '{}')"

echo "2. El worker lo guarda en segundo plano (se consulta hasta que aparezca)"
INICIO=$(date +%s); COD=404
for _ in $(seq 1 30); do
  COD=$(codigo "$API/tickets/$ID"); [[ "$COD" == 200 ]] && break; sleep 1
done
paso "GET /tickets/$ID tras $(( $(date +%s) - INICIO )) s" 200 "$COD"

echo "3. Aparece en la cola de pendientes"
EN_COLA=$(curl -s "$API/tickets?estado=PENDIENTE" | python3 -c "import sys,json; print(sum(t['ticketId']=='$ID' for t in json.load(sys.stdin)))" 2>/dev/null)
paso "veces que aparece en GET /tickets?estado=PENDIENTE" 1 "${EN_COLA:-0}"

echo "4. Diana lo toma; Carlos lo intenta despues y es rechazado"
paso "PATCH tomar (diana)" 200 "$(codigo -X PATCH "$API/tickets/$ID" "${JSON[@]}" -d '{"accion":"tomar","agente":"diana"}')"
paso "PATCH tomar (carlos) -> conflicto" 409 "$(codigo -X PATCH "$API/tickets/$ID" "${JSON[@]}" -d '{"accion":"tomar","agente":"carlos"}')"

echo "5. Solo el agente asignado puede resolverlo"
paso "PATCH resolver (carlos) -> conflicto" 409 "$(codigo -X PATCH "$API/tickets/$ID" "${JSON[@]}" -d '{"accion":"resolver","agente":"carlos"}')"
paso "PATCH resolver (diana)" 200 "$(codigo -X PATCH "$API/tickets/$ID" "${JSON[@]}" -d '{"accion":"resolver","agente":"diana","solucion":"Se reinicio el switch"}')"

echo "6. Metricas del jefe"
curl -s "$API/metricas" | python3 -c '
import sys, json
m = json.load(sys.stdin)
print("        total:", m["total"], "| por estado:", m["porEstado"])
print("        espera promedio:", m["horasPromEspera"], "h | resolucion promedio:", m["horasPromResolucion"], "h")
print("        fuera de SLA:", [t["ticketId"] for t in m["slaVencidos"]])
for a in m["porAgente"]:
    print("        agente", a["agente"], "- asignados:", a["asignados"], "resueltos:", a["resueltos"])
'
paso "GET /metricas" 200 "$(codigo "$API/metricas")"

echo
if [[ "$FALLOS" == 0 ]]; then echo "RESULTADO: todas las comprobaciones pasaron"; else echo "RESULTADO: $FALLOS comprobacion(es) fallaron"; fi
exit "$FALLOS"
