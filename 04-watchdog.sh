#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 4 — WATCHDOG E RESILIÊNCIA
# Executar como root: sudo bash 04-watchdog.sh
##############################################################################

echo "===== FASE 4: WATCHDOG E RESILIÊNCIA ====="

# ── 4.1 Instalar watchdog ────────────────────────────────────────────────
echo "[1/4] Instalando watchdog..."
apt install -y watchdog

# ── 4.2 Configurar watchdog ──────────────────────────────────────────────
echo "[2/4] Configurando watchdog..."

cat > /etc/watchdog.conf <<'WDEOF'
# Watchdog config — espacoviva
watchdog-device     = /dev/watchdog
watchdog-timeout    = 15
max-load-1          = 24
min-memory          = 1
interval            = 10
realtime            = yes
priority            = 1

# Monitorar serviços críticos via systemctl status
repair-binary       = /usr/sbin/service
repair-timeout      = 60
test-binary         = /usr/local/bin/watchdog-test.sh
test-timeout        = 10
WDEOF

# Criar script de teste personalizado para o watchdog
cat > /usr/local/bin/watchdog-test.sh <<'WTEOF'
#!/bin/bash
# Verificar se os serviços essenciais estão ativos
services=("go-librespot" "audio-monitor" "ytmusic-web" "mpd")
for svc in "${services[@]}"; do
    if ! systemctl is-active "$svc" >/dev/null 2>&1; then
        exit 1
    fi
done
exit 0
WTEOF
chmod +x /usr/local/bin/watchdog-test.sh

# Carregar módulo watchdog do kernel (Mac mini usa softdog ou iTCO)
if [ ! -e /dev/watchdog ]; then
    echo "softdog" >> /etc/modules-load.d/watchdog.conf
    modprobe softdog 2>/dev/null || true
fi

# ── 4.3.1 Instalar e Habilitar ytmusic-web.service ─────────────────────────
echo "  Instalando ytmusic-web.service..."
CURRENT_USER=$(id -un)
CURRENT_DIR=$(pwd)
cp ytmusic-web.service /etc/systemd/system/
sed -i "s/User=bruno/User=$CURRENT_USER/" /etc/systemd/system/ytmusic-web.service
sed -i "s|WorkingDirectory=/home/bruno/espacoviva-deploy|WorkingDirectory=$CURRENT_DIR|" /etc/systemd/system/ytmusic-web.service
sed -i "s|/home/bruno/espacoviva-deploy/ytmusic-web.py|$CURRENT_DIR/ytmusic-web.py|" /etc/systemd/system/ytmusic-web.service

systemctl daemon-reload
systemctl enable ytmusic-web.service

# ── 4.4 Verificar Restart=always em serviços críticos ────────────────────
echo "[4/4] Verificando Restart=always nos serviços críticos..."

# go-librespot
echo "  go-librespot: $(systemctl show go-librespot -p Restart --value)"
echo "  ytmusic-web:  $(systemctl show ytmusic-web -p Restart --value)"

# audio-monitor (já configurado na fase 3)
echo "  audio-monitor: $(systemctl show audio-monitor -p Restart --value)"

# mpd
echo "  mpd: $(systemctl show mpd -p Restart --value)"

# ── Configurar logrotate para logs adicionais ─────────────────────────────
cat > /etc/logrotate.d/espacoviva <<'LREOF'
/var/log/mpd/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 640 mpd audio
}
LREOF

# ── Boot automático (BIOS — informativo) ─────────────────────────────────
echo ""
echo "⚠️  AÇÃO MANUAL NECESSÁRIA:"
echo "   No Mac mini, configure no BIOS/EFI para:"
echo "   • Auto Power On (ligar automaticamente após queda de energia)"
echo "   • Energy Saver → 'Restart automatically after a power failure'"

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 4 ====="
echo "Watchdog status:    $(systemctl is-active watchdog)"
echo "Watchdog enabled:   $(systemctl is-enabled watchdog)"
echo "Watchdog device:    $(ls -la /dev/watchdog 2>/dev/null || echo 'N/A')"
echo ""
systemctl status watchdog --no-pager -l
echo ""
echo "Serviços com Restart=always:"
echo "  go-librespot:  $(systemctl show go-librespot -p Restart --value)"
echo "  ytmusic-web:   $(systemctl show ytmusic-web -p Restart --value)"
echo "  audio-monitor: $(systemctl show audio-monitor -p Restart --value)"
echo "  mpd:           $(systemctl show mpd -p Restart --value)"
echo ""
echo "✅ FASE 4 CONCLUÍDA"
