# espacoviva-deploy

Servidor de áudio 24/7 para academia — Debian 12 em Mac mini 2010.

## Uso Rápido

```bash
# Copiar para o servidor
scp -r espacoviva-deploy/ user@192.168.3.50:/tmp/

# No servidor: executar tudo (fases 1-5)
ssh user@192.168.3.50
cd /tmp/espacoviva-deploy
sudo bash deploy-all.sh

# Após validar: Wi-Fi backup (fase 6)
sudo bash 06-wifi.sh

# Validação final
sudo bash 99-validate.sh
```

## Scripts

| Script | Fase | Descrição |
|--------|------|-----------|
| `01-baseline.sh` | 1 | Sistema base, timezone, ssh, journald, CPU |
| `02-spotify.sh` | 2 | Spotify Connect (raspotify) |
| `03-fallback.sh` | 3 | MPD + monitor de fallback |
| `04-watchdog.sh` | 4 | Watchdog + resiliência |
| `05-appliance.sh` | 5 | Modo appliance (boot silencioso) |
| `06-wifi.sh` | 6 | Wi-Fi backup (executar por último) |
| `deploy-all.sh` | 1-5 | Executa fases 1-5 em sequência |
| `99-validate.sh` | — | Validação completa do sistema |

## Execução por Fase

```bash
# Executar fase individual
sudo bash 01-baseline.sh

# Ou começar do deploy-all a partir da fase 3
sudo bash deploy-all.sh 3
```

## Ação Manual (Mac mini)

Configurar no BIOS/EFI do Mac mini:
- **Energy Saver → Restart after power failure** = ON
