#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 6 — WI-FI COMO BACKUP
# ⚠️  EXECUTAR SOMENTE APÓS FASES 1-5 ESTÁVEIS
# Executar como root: sudo bash 06-wifi.sh
##############################################################################

echo "===== FASE 6: WI-FI COMO BACKUP ====="
echo "⚠️  Esta fase só deve ser executada após todas as anteriores estarem funcionando."
echo ""

# ── 6.1 Instalar firmware Broadcom ───────────────────────────────────────
echo "[1/5] Instalando firmware Broadcom..."

# Adicionar non-free se necessário
if ! grep -q "non-free" /etc/apt/sources.list 2>/dev/null; then
    sed -i 's/main$/main contrib non-free non-free-firmware/' /etc/apt/sources.list
    apt update
fi

apt install -y firmware-brcm80211

# ── 6.2 Instalar NetworkManager ─────────────────────────────────────────
echo "[2/5] Instalando NetworkManager..."
apt install -y network-manager

# Desabilitar ifupdown para interfaces gerenciadas pelo NM
# Manter apenas lo no /etc/network/interfaces
cat > /etc/network/interfaces <<'IFEOF'
# Interfaces gerenciadas pelo NetworkManager
# Manter apenas loopback aqui
auto lo
iface lo inet loopback
IFEOF

# Configurar NM para gerenciar todas as interfaces
cat > /etc/NetworkManager/conf.d/10-manage-all.conf <<'NMEOF'
[main]
plugins=ifupdown,keyfile

[ifupdown]
managed=true

[device]
wifi.scan-rand-mac-address=no
NMEOF

systemctl enable NetworkManager
systemctl restart NetworkManager
sleep 3

# ── 6.3 Configurar Ethernet como primária (métrica baixa) ───────────────
echo "[3/5] Configurando Ethernet como primária..."

# Detectar nome da interface wifi
WIFI_IFACE=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2}' | head -1)
if [ -z "$WIFI_IFACE" ]; then
    echo "❌ Interface Wi-Fi não detectada. Verifique o firmware."
    echo "   Tente: ip link | grep wl"
    echo "   Ou reinicie e execute novamente."
    exit 1
fi
echo "   Interface Wi-Fi detectada: $WIFI_IFACE"

# Configurar Ethernet via NM com métrica baixa (prioridade alta)
nmcli con delete "enp4s0f0-ethernet" 2>/dev/null || true
nmcli con add type ethernet ifname enp4s0f0 con-name "enp4s0f0-ethernet" \
    ipv4.method manual \
    ipv4.addresses "192.168.3.50/24" \
    ipv4.gateway "192.168.3.1" \
    ipv4.dns "8.8.8.8,8.8.4.4" \
    ipv4.route-metric 100 \
    connection.autoconnect yes \
    connection.autoconnect-priority 100

# ── 6.4 Configurar Wi-Fi como backup (métrica alta) ─────────────────────
echo "[4/5] Configurando Wi-Fi backup..."

nmcli con delete "wifi-backup" 2>/dev/null || true
nmcli con add type wifi ifname "$WIFI_IFACE" con-name "wifi-backup" \
    ssid "Aldegundes" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "60708090" \
    ipv4.method auto \
    ipv4.route-metric 600 \
    connection.autoconnect yes \
    connection.autoconnect-priority 10

# Ativar conexões
nmcli con up "enp4s0f0-ethernet" 2>/dev/null || true
nmcli con up "wifi-backup" 2>/dev/null || true

# ── 6.5 Verificar ────────────────────────────────────────────────────────
echo "[5/5] Verificando configuração..."
sleep 5

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 6 ====="
echo ""
echo "Conexões NM:"
nmcli con show
echo ""
echo "Rotas (verificar métricas):"
ip route
echo ""
echo "Interfaces:"
ip -br addr
echo ""
echo "Wi-Fi status:"
nmcli dev wifi list 2>/dev/null | head -5
echo ""
echo "✅ FASE 6 CONCLUÍDA"
echo ""
echo "=== TESTES DE FAILOVER ==="
echo "1. Remover cabo ethernet → Wi-Fi deve assumir em ~10s"
echo "2. Recolocar cabo → Ethernet volta como primário (métrica 100 vs 600)"
echo "3. Verificar com: ip route"
