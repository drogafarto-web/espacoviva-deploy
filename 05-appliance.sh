#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 5 — MODO APPLIANCE
# Executar como root: sudo bash 05-appliance.sh
##############################################################################

echo "===== FASE 5: MODO APPLIANCE ====="

# ── 5.1 Garantir target multi-user (sem GUI) ────────────────────────────
echo "[1/5] Configurando target multi-user..."
systemctl set-default multi-user.target

# Remover display managers se existirem
for dm in gdm3 lightdm sddm xdm; do
    if dpkg -l | grep -q "$dm"; then
        echo "  Removendo $dm..."
        apt purge -y "$dm" 2>/dev/null || true
    fi
done

# ── 5.2 Boot silencioso ─────────────────────────────────────────────────
echo "[2/5] Configurando boot silencioso..."

# Backup do GRUB config
cp /etc/default/grub /etc/default/grub.bak

# Configurar GRUB
sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"/' /etc/default/grub

# Garantir que as linhas existem
grep -q "^GRUB_TIMEOUT=" /etc/default/grub || echo 'GRUB_TIMEOUT=0' >> /etc/default/grub
grep -q "^GRUB_CMDLINE_LINUX_DEFAULT=" /etc/default/grub || echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"' >> /etc/default/grub

update-grub

# ── 5.3 Desabilitar serviços desnecessários ──────────────────────────────
echo "[3/5] Desabilitando serviços desnecessários..."
for svc in ModemManager bluetooth avahi-daemon cups; do
    if systemctl is-enabled "$svc" 2>/dev/null | grep -q "enabled"; then
        systemctl disable "$svc"
        systemctl stop "$svc" 2>/dev/null || true
        echo "  Desabilitado: $svc"
    fi
done

# ── 5.4 Verificar autostart de serviços essenciais ──────────────────────
echo "[4/5] Verificando autostart dos serviços essenciais..."
echo "  ssh:            $(systemctl is-enabled ssh)"
echo "  go-librespot:   $(systemctl is-enabled go-librespot)"
echo "  ytmusic-web:    $(systemctl is-enabled ytmusic-web)"
echo "  audio-monitor:  $(systemctl is-enabled audio-monitor)"
echo "  watchdog:       $(systemctl is-enabled watchdog)"

# ── 5.5 Configurar hostname ─────────────────────────────────────────────
echo "[5/5] Configurando hostname..."
hostnamectl set-hostname espacoviva
echo "127.0.1.1 espacoviva" >> /etc/hosts 2>/dev/null || true

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 5 ====="
echo "Default target: $(systemctl get-default)"
echo "Hostname:       $(hostname)"
echo "GRUB timeout:   $(grep GRUB_TIMEOUT /etc/default/grub)"
echo "GRUB cmdline:   $(grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub)"
echo ""
echo "Serviços essenciais habilitados:"
for svc in ssh go-librespot ytmusic-web audio-monitor watchdog; do
    printf "  %-16s %s\n" "$svc:" "$(systemctl is-enabled $svc 2>/dev/null)"
done
echo ""
echo "✅ FASE 5 CONCLUÍDA"
echo "   Sistema operará como appliance dedicado no próximo boot."
