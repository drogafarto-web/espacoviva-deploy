#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# DEPLOY COMPLETO — espacoviva
# Executa todas as fases em sequência.
# Executar como root: sudo bash deploy-all.sh
#
# Ou para executar a partir de uma fase específica:
#   sudo bash deploy-all.sh 3   (começa da fase 3)
##############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_PHASE="${1:-1}"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║        DEPLOY COMPLETO — espacoviva                            ║"
echo "║        Servidor de Áudio 24/7 para Academia                    ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Iniciando da fase: $START_PHASE"
echo ""

run_phase() {
    local phase=$1
    local script=$2
    local desc=$3

    if [ "$phase" -lt "$START_PHASE" ]; then
        echo "⏭  Fase $phase ($desc) — pulando"
        return
    fi

    echo ""
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║  FASE $phase — $desc"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo ""

    if [ ! -f "$SCRIPT_DIR/$script" ]; then
        echo "❌ Script não encontrado: $SCRIPT_DIR/$script"
        exit 1
    fi

    bash "$SCRIPT_DIR/$script"

    echo ""
    echo "───────────────────────────────────────────────────────────────────"
    echo "  Fase $phase concluída. Continuando em 5 segundos..."
    echo "  (Ctrl+C para interromper)"
    echo "───────────────────────────────────────────────────────────────────"
    sleep 5
}

run_phase 1 "01-baseline.sh"    "BASELINE DO SISTEMA"
run_phase 2 "02-spotify.sh"     "SPOTIFY CONNECT"
run_phase 3 "03-fallback.sh"    "FALLBACK OFFLINE"
run_phase 4 "04-watchdog.sh"    "WATCHDOG E RESILIÊNCIA"
run_phase 5 "05-appliance.sh"   "MODO APPLIANCE"

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  ⚠️  FASE 6 (Wi-Fi) NÃO será executada automaticamente.       ║"
echo "║  Execute manualmente APÓS validar as fases 1-5:                ║"
echo "║     sudo bash 06-wifi.sh                                      ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Validação final (sem Wi-Fi)
echo "Executando validação..."
bash "$SCRIPT_DIR/99-validate.sh"
