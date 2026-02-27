#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 3 — FALLBACK OFFLINE (MPD + MONITOR)
# Executar como root: sudo bash 03-fallback.sh
##############################################################################

echo "===== FASE 3: FALLBACK OFFLINE ====="

# ── 3.1 Instalar MPD + MPC ───────────────────────────────────────────────
echo "[1/5] Instalando MPD e MPC..."
apt install -y mpd mpc

# ── 3.2 Criar diretório de música ────────────────────────────────────────
echo "[2/5] Criando diretório /srv/music..."
mkdir -p /srv/music/fallback
chown -R mpd:audio /srv/music

# ── 3.3 Configurar MPD ───────────────────────────────────────────────────
echo "[3/5] Configurando MPD..."

# Backup do original
cp /etc/mpd.conf /etc/mpd.conf.bak 2>/dev/null || true

cat > /etc/mpd.conf <<'MPDEOF'
# MPD Configuration — espacoviva fallback

music_directory     "/srv/music"
playlist_directory  "/var/lib/mpd/playlists"
db_file             "/var/lib/mpd/tag_cache"
log_file            "/var/log/mpd/mpd.log"
pid_file            "/run/mpd/pid"
state_file          "/var/lib/mpd/state"
sticker_file        "/var/lib/mpd/sticker.sql"

bind_to_address     "localhost"
port                "6600"

# Desabilitar saída pulse, usar ALSA direto
audio_output {
    type        "alsa"
    name        "ALSA Output"
    device      "plughw:0,0"
    mixer_type  "software"
}

# Volume e reprodução
volume_normalization    "yes"
auto_update             "yes"
auto_update_depth       "3"
filesystem_charset      "UTF-8"
MPDEOF

# Garantir diretório de log
mkdir -p /var/log/mpd
chown mpd:audio /var/log/mpd

# Garantir Restart=always no MPD
mkdir -p /etc/systemd/system/mpd.service.d
cat > /etc/systemd/system/mpd.service.d/restart.conf <<'MRSEOF'
[Service]
Restart=always
RestartSec=5
MRSEOF

systemctl daemon-reload

# MPD começa desabilitado — só inicia quando o monitor aciona
systemctl disable mpd
systemctl stop mpd 2>/dev/null || true

# ── 3.4 Criar script de monitoramento ────────────────────────────────────
echo "[4/5] Criando script audio-monitor..."

cat > /usr/local/bin/audio-monitor.sh <<'MONEOF'
#!/usr/bin/env bash
##############################################################################
# audio-monitor.sh — Triple Failover (YT Music -> Spotify -> MPD Offline)
##############################################################################

PING_TARGET="8.8.8.8"
PING_INTERVAL=15
FAIL_THRESHOLD=3
FAIL_COUNT=0
STATE="online"  # online | offline
SOURCE="ytmusic" # ytmusic | spotify | mpd

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [audio-monitor] $1"
}

# Funções de Fluxo
stop_all() {
    systemctl stop ytmusic-web 2>/dev/null || true
    systemctl stop go-librespot 2>/dev/null || true
    systemctl stop mpd 2>/dev/null || true
    killall -9 mpv 2>/dev/null || true
}

start_ytmusic() {
    log "▶ Iniciando YouTube Music (Primary)..."
    stop_all
    systemctl start ytmusic-web
    SOURCE="ytmusic"
}

start_spotify() {
    log "▶ Iniciando Spotify (Secondary)..."
    stop_all
    systemctl start go-librespot
    SOURCE="spotify"
}

start_mpd() {
    log "▶ Iniciando MPD (Offline Fallback)..."
    stop_all
    systemctl start mpd
    sleep 2
    mpc update --wait 2>/dev/null || true
    mpc clear 2>/dev/null || true
    mpc ls | mpc add 2>/dev/null || true
    mpc repeat on 2>/dev/null || true
    mpc volume 80 2>/dev/null || true
    mpc play 2>/dev/null || true
    SOURCE="mpd"
}

log "Iniciando monitoramento Triple Failover..."

# Aguardar serviços iniciais
sleep 15

while true; do
    if ping -c 1 -W 3 "$PING_TARGET" > /dev/null 2>&1; then
        # INTERNET OK
        FAIL_COUNT=0
        if [ "$STATE" = "offline" ]; then
            log "✅ Internet restaurada. Voltando para YouTube Music..."
            STATE="online"
            start_ytmusic
        fi

        # Health Check YTMusic (se estiver no modo online)
        if [ "$STATE" = "online" ] && [ "$SOURCE" = "ytmusic" ]; then
            if ! systemctl is-active ytmusic-web > /dev/null; then
                log "⚠ YTMusic parou. Tentando Spotify como secundário..."
                start_spotify
            fi
        fi
    else
        # INTERNET DOWN
        FAIL_COUNT=$((FAIL_COUNT + 1))
        log "⚠ Ping falhou ($FAIL_COUNT/$FAIL_THRESHOLD)"

        if [ "$FAIL_COUNT" -ge "$FAIL_THRESHOLD" ] && [ "$STATE" = "online" ]; then
            log "🚨 Internet Offline detectada! Ativando MPD Local..."
            STATE="offline"
            start_mpd
        fi
    fi

    sleep "$PING_INTERVAL"
done
MONEOF

chmod +x /usr/local/bin/audio-monitor.sh

# ── 3.5 Criar serviço systemd para o monitor ─────────────────────────────
echo "[5/5] Criando serviço audio-monitor..."

cat > /etc/systemd/system/audio-monitor.service <<'SVCEOF'
[Unit]
Description=Audio Failover Monitor (Spotify ↔ MPD)
After=network-online.target go-librespot.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/audio-monitor.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=audio-monitor

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable audio-monitor
systemctl start audio-monitor

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 3 ====="
echo "MPD instalado:      $(mpd --version | head -1)"
echo "MPD status:         $(systemctl is-active mpd) (esperado: inactive)"
echo "Monitor status:     $(systemctl is-active audio-monitor)"
echo "Monitor enabled:    $(systemctl is-enabled audio-monitor)"
echo "Music dir:          $(ls -la /srv/music/)"
echo ""
systemctl status audio-monitor --no-pager -l
echo ""
echo "✅ FASE 3 CONCLUÍDA"
echo "⚠️  Coloque arquivos MP3 em /srv/music/ para fallback funcionar."
echo "⚠️  Teste: desconecte internet e verifique se MPD assume em ~45s."
