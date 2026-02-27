#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# FASE 2 — SPOTIFY CONNECT (GO-LIBRESPOT)
# Executar como root: sudo bash 02-spotify.sh
##############################################################################

echo "===== FASE 2: SPOTIFY CONNECT ====="

# ── 2.1 Limpeza Inicial ───────────────────────────────────────────────────
echo "[1/4] Removendo raspotify e bibliotecas conflitantes..."
systemctl stop raspotify 2>/dev/null || true
apt purge -y raspotify pulseaudio pulseaudio-utils 2>/dev/null || true
apt autoremove -y

# ── 2.2 Instalar go-librespot ──────────────────────────────────────────────
echo "[2/4] Instalando go-librespot..."
INSTALL_DIR="/usr/local/bin"
TARBALL="go-librespot_linux_x86_64.tar.gz"

if [ -f "$TARBALL" ]; then
    tar -xzf "$TARBALL" -C "$INSTALL_DIR" go-librespot
    chmod +x "$INSTALL_DIR/go-librespot"
else
    echo "❌ Erro: Arquivo $TARBALL não encontrado no diretório atual."
    exit 1
fi

# ── 2.3 Configurar serviço go-librespot ────────────────────────────────────
echo "[3/4] Configurando serviço go-librespot..."

cat > /etc/systemd/system/go-librespot.service <<SVCEOF
[Unit]
Description=Go-Librespot (Spotify Connect)
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/go-librespot \\
    -c device.name=Academia \\
    -c audio.backend=alsa \\
    -c audio.device=default \\
    -c playback.bitrate=320 \\
    -c playback.autoplay=true
Restart=always
RestartSec=10
User=bruno
Group=bruno

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable go-librespot
systemctl restart go-librespot

# ── 2.4 Verificar ─────────────────────────────────────────────────────────
echo "[4/4] Verificando serviço..."
sleep 3

# ── Validação ─────────────────────────────────────────────────────────────
echo ""
echo "===== VALIDAÇÃO FASE 2 ====="
echo "Status:      $(systemctl is-active go-librespot)"
echo "Enabled:     $(systemctl is-enabled go-librespot)"
echo ""
systemctl status go-librespot --no-pager -l
echo ""
echo "✅ FASE 2 CONCLUÍDA"
echo "⚠️  Abra o Spotify no celular e verifique se 'Academia' aparece como dispositivo."
