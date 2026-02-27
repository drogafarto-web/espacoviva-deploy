#!/usr/bin/env bash
##############################################################################
# VALIDAÇÃO FINAL — espacoviva
# Executar como root: sudo bash 99-validate.sh
##############################################################################

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           VALIDAÇÃO FINAL — espacoviva                         ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# ── Sistema ───────────────────────────────────────────────────────────────
echo "━━━ SISTEMA ━━━"
echo "Hostname:    $(hostname)"
echo "Uptime:      $(uptime -p)"
echo "Timezone:    $(timedatectl show --property=Timezone --value)"
echo "Default tgt: $(systemctl get-default)"
echo "Kernel:      $(uname -r)"
echo ""

# ── Serviços ──────────────────────────────────────────────────────────────
echo "━━━ SERVIÇOS CRÍTICOS ━━━"
fmt="  %-18s %-10s %-10s %-10s\n"
printf "$fmt" "SERVIÇO" "ATIVO" "HABILITADO" "RESTART"
printf "$fmt" "────────────────" "────────" "────────" "────────"
for svc in go-librespot mpd audio-monitor watchdog ssh ytmusic-web; do
    active=$(systemctl is-active "$svc" 2>/dev/null || echo "N/A")
    enabled=$(systemctl is-enabled "$svc" 2>/dev/null || echo "N/A")
    restart=$(systemctl show "$svc" -p Restart --value 2>/dev/null || echo "N/A")
    printf "$fmt" "$svc" "$active" "$enabled" "$restart"
done
echo ""

# ── Status detalhado ─────────────────────────────────────────────────────
echo "━━━ GO-LIBRESPOT ━━━"
systemctl status go-librespot --no-pager -l 2>/dev/null | head -10
echo ""

echo "━━━ YTMUSIC WEB ━━━"
systemctl status ytmusic-web --no-pager -l 2>/dev/null | head -10
echo ""

echo "━━━ MPD ━━━"
systemctl status mpd --no-pager -l 2>/dev/null | head -10
echo ""

echo "━━━ AUDIO MONITOR ━━━"
systemctl status audio-monitor --no-pager -l 2>/dev/null | head -10
echo ""

echo "━━━ WATCHDOG ━━━"
systemctl status watchdog --no-pager -l 2>/dev/null | head -10
echo ""

# ── Rede ──────────────────────────────────────────────────────────────────
echo "━━━ REDE ━━━"
echo ""
echo "Interfaces:"
ip -br addr
echo ""
echo "Rotas:"
ip route
echo ""
if command -v nmcli &>/dev/null; then
    echo "Conexões NM:"
    nmcli con show --active
    echo ""
fi

# ── Recursos ──────────────────────────────────────────────────────────────
echo "━━━ RECURSOS ━━━"
echo ""
echo "Memória:"
free -h
echo ""
echo "Disco:"
df -h /
echo ""
echo "CPU governor:"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "N/A"
echo ""

# ── Áudio ─────────────────────────────────────────────────────────────────
echo "━━━ ÁUDIO ━━━"
echo "Dispositivos ALSA:"
aplay -l 2>/dev/null || echo "Nenhum dispositivo ALSA encontrado"
echo ""
echo "PulseAudio: $(dpkg -l 2>/dev/null | grep -c pulseaudio || echo '0') pacotes"
echo ""

# ── Segurança ─────────────────────────────────────────────────────────────
echo "━━━ SEGURANÇA ━━━"
echo "SSH root login: $(grep '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null || echo 'default')"
echo "Sleep masked:   $(systemctl is-enabled sleep.target 2>/dev/null)"
echo "Journal limit:  $(cat /etc/systemd/journald.conf.d/size-limit.conf 2>/dev/null | grep SystemMaxUse || echo 'default')"
echo ""

# ── Resumo ────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                     RESUMO                                     ║"
echo "╠══════════════════════════════════════════════════════════════════╣"

check() {
    local label="$1"
    local condition="$2"
    if eval "$condition" 2>/dev/null; then
        printf "║  ✅ %-58s ║\n" "$label"
    else
        printf "║  ❌ %-58s ║\n" "$label"
    fi
}

check "Spotify Connect (go-librespot)" "systemctl is-active go-librespot -q"
check "YouTube Music Web Backend" "systemctl is-active ytmusic-web -q"
check "Fallback MPD instalado" "command -v mpd"
check "Audio Monitor ativo" "systemctl is-active audio-monitor -q"
check "Watchdog ativo" "systemctl is-active watchdog -q"
check "SSH ativo" "systemctl is-active ssh -q"
check "Boot silencioso" "grep -q 'quiet' /etc/default/grub"
check "CPU performance" "grep -q 'performance' /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null"
check "Sleep desabilitado" "systemctl is-enabled sleep.target 2>/dev/null | grep -q masked"

if command -v nmcli &>/dev/null; then
    check "NetworkManager ativo" "systemctl is-active NetworkManager -q"
    check "Wi-Fi backup configurado" "nmcli con show wifi-backup 2>/dev/null | grep -q wifi"
fi

echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Servidor de áudio espacoviva — validação completa."
