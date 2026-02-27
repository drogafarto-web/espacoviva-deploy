#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 1 — BASELINE DO SISTEMA
# Executar como root: sudo bash 01-baseline.sh
##############################################################################

echo "===== FASE 1: BASELINE DO SISTEMA ====="

# ── 1.1 Atualizar pacotes ──────────────────────────────────────────────────
echo "[1/8] Atualizando pacotes..."
apt update && apt full-upgrade -y
apt autoremove -y && apt autoclean

# ── 1.2 Instalar utilitários essenciais ────────────────────────────────────
echo "[2/8] Instalando utilitários..."
apt install -y \
  curl wget htop iotop nano vim tmux net-tools lsof dnsutils rsync unzip \
  bash-completion ca-certificates gnupg apt-transport-https \
  cpufrequtils alsa-utils mpv ffmpeg python3-pip

# ── 1.2.0 Garantir volume máximo do hardware ────────────────────────────────
echo "  Configurando volume ALSA para 100%..."
amixer sset Master 100% 2>/dev/null || true
amixer sset PCM 100% 2>/dev/null || true
amixer sset Headphone 100% 2>/dev/null || true
amixer sset Speaker 100% 2>/dev/null || true
alsactl store
# ── 1.2.1 Instalar yt-dlp atualizado ─────────────────────────────────────────
echo "  Instalando yt-dlp via curl..."
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
chmod a+rx /usr/local/bin/yt-dlp
/usr/local/bin/yt-dlp -U || true

# ── 1.3 Configurar timezone ───────────────────────────────────────────────
echo "[3/8] Configurando timezone..."
timedatectl set-timezone America/Sao_Paulo
echo "Timezone: $(timedatectl show --property=Timezone --value)"

# ── 1.4 Unattended upgrades (security only) ───────────────────────────────
echo "[4/8] Configurando unattended-upgrades..."
apt install -y unattended-upgrades

cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'UUEOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
UUEOF

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
AUEOF

# ── 1.5 SSH: ativo permanentemente + desabilitar root login ───────────────
echo "[5/8] Configurando SSH..."
systemctl enable ssh.service
systemctl start ssh.service

# Desabilitar login root via SSH
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
# Garantir que não há override
if ! grep -q "^PermitRootLogin no" /etc/ssh/sshd_config; then
    echo "PermitRootLogin no" >> /etc/ssh/sshd_config
fi
systemctl restart ssh.service

# ── 1.6 Journald com limite de tamanho ────────────────────────────────────
echo "[6/8] Configurando journald..."
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size-limit.conf <<'JEOF'
[Journal]
SystemMaxUse=100M
SystemMaxFileSize=10M
MaxRetentionSec=1month
JEOF
systemctl restart systemd-journald

# ── 1.7 CPU governor em performance ──────────────────────────────────────
echo "[7/8] Configurando CPU governor..."
cat > /etc/default/cpufrequtils <<'CPUEOF'
GOVERNOR="performance"
CPUEOF
systemctl enable cpufrequtils
systemctl restart cpufrequtils 2>/dev/null || true
# Aplicar imediatamente
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo "performance" > "$cpu" 2>/dev/null || true
done

# ── 1.8 Desabilitar sleep/hibernate ──────────────────────────────────────
echo "[8/9] Desabilitando sleep/hibernate..."
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# ── 1.9 Mac Mini: Auto-Power-On (NVIDIA MCP89) ──────────────────────────
echo "[9/9] Configurando Auto-Power-On após queda de energia..."
# Configura o registrador 0x7b do LPC Bridge (00:03.0) para "Stay On" (0x19)
# Nota: Funciona especificamente no Mac Mini 2010 (7,1)
setpci -s 00:03.0 0x7b.b=0x19 2>/dev/null || true

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 1 ====="
echo "Timezone:    $(timedatectl show --property=Timezone --value)"
echo "SSH:         $(systemctl is-enabled ssh)"
echo "Root SSH:    $(grep '^PermitRootLogin' /etc/ssh/sshd_config)"
echo "Journal max: $(cat /etc/systemd/journald.conf.d/size-limit.conf | grep SystemMaxUse)"
echo "CPU gov:     $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'N/A')"
echo "Sleep mask:  $(systemctl is-enabled sleep.target 2>/dev/null || echo 'masked')"
echo ""
echo "✅ FASE 1 CONCLUÍDA"
