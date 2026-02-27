#!/usr/bin/env bash
# Script para configurar acesso remoto seguro via Cloudflare Tunnel

echo "===== CONFIGURANDO ACESSO REMOTO (TÚNEL) ====="

# 1. Instalação
if ! command -v cloudflared &> /dev/null; then
    echo "[1/3] Instalando cloudflared..."
    # Baixar binário oficial para amd64
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    sudo dpkg -i cloudflared-linux-amd64.deb
    rm cloudflared-linux-amd64.deb
else
    echo "[1/3] cloudflared já instalado."
fi

# 2. Criar túnel temporário para teste rápido
echo "[2/3] Iniciando túnel rápido..."
echo "Aguarde o link ser gerado..."

# Iniciar em background e salvar o log para pegar a URL
nohup cloudflared tunnel --url http://localhost:8080 > ~/tunnel.log 2>&1 &

sleep 5
URL=$(grep -o 'https://[-a-z0-9.]*\.trycloudflare.com' ~/tunnel.log | head -n 1)

if [ -n "$URL" ]; then
    echo "✅ TÚNEL ATIVO!"
    echo "🔗 URL DE ACESSO: $URL"
    echo "$URL" > ~/tunnel_url.txt
else
    echo "❌ Falha ao obter URL do túnel. Verifique ~/tunnel.log"
fi

echo "===== CONFIGURAÇÃO CONCLUÍDA ====="
