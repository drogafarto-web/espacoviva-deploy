#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import sys

# Forçar output imediato para o log do systemd
def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

MPV_SOCKET = "/tmp/mpv-ytmusic"
QUEUE_FILE = os.path.expanduser("~/.ytmusic_queue.json")
PORT = 8080

state = {
    "queue": [],      
    "current_idx": -1,
    "loop": True,
    "shuffle": False,
    "status": "stopped",
    "title": "",
    "volume": 80,
    "infinite_mode": True,
    "last_query": "gym workout mix",
    "history": [] # IDs das últimas músicas para evitar repetição
}
mpv_proc = None
lock = threading.Lock()
refill_lock = False
last_check_pos = 0
last_check_time = 0

def save_state():
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump({
                "queue": state["queue"],
                "current_idx": state["current_idx"],
                "loop": state["loop"],
                "shuffle": state["shuffle"],
                "volume": state["volume"],
                "infinite_mode": state["infinite_mode"],
                "last_query": state["last_query"]
            }, f)
    except Exception as e: log(f"ERRO save_state: {e}")

def load_state():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r") as f:
                data = json.load(f)
                state["queue"] = data.get("queue", [])
                state["current_idx"] = data.get("current_idx", -1)
                state["loop"] = data.get("loop", True)
                state["shuffle"] = data.get("shuffle", False)
                state["volume"] = data.get("volume", 80)
                state["infinite_mode"] = data.get("infinite_mode", True)
                state["last_query"] = data.get("last_query", "gym workout mix")
                # Se carregou com -1 mas tem fila, tratar para auto-resume (v4.1)
                if state["current_idx"] == -1 and state["queue"]:
                    state["current_idx"] = 0
            log(f"Estado carregado (v4.1). Fila: {len(state['queue'])}. Indice: {state['current_idx']}")
        except Exception as e: log(f"ERRO load_state: {e}")

def mpv_command(*args):
    try:
        log(f"Enviando mpv_command: {args}")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(MPV_SOCKET)
        cmd = json.dumps({"command": list(args)}) + "\n"
        s.sendall(cmd.encode())
        resp = s.recv(4096).decode().strip()
        s.close()
        log(f"Resposta mpv_command: {resp[:100]}...")
        return json.loads(resp) if resp else {}
    except Exception as e: 
        log(f"AVISO mpv_command falhou (mpv pode estar morto): {e}")
        return {"error": str(e)}

def mpv_get_property(prop):
    data = mpv_command("get_property", prop)
    return data.get("data") if data else None

def get_yt_info(query_or_url, is_playlist_search=False):
    log(f"Busca yt-dlp: '{query_or_url}' (modo_playlist={is_playlist_search})")
    if "youtube.com" in query_or_url or "youtu.be" in query_or_url: target = query_or_url
    else:
        q = query_or_url
        if is_playlist_search: target = f"ytsearch30:{q} playlist music"
        else: target = f"ytsearch30:{q}"

    cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s|||%(title)s|||%(duration_string)s", target]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        results = []
        if r.returncode != 0: log(f"ERRO yt-dlp: {r.stderr}")
        for line in r.stdout.strip().split("\n"):
            if "|||" in line:
                p = line.split("|||")
                results.append({"id": p[0], "title": p[1].strip(), "duration": p[2] if len(p)>2 else "", "url": f"https://www.youtube.com/watch?v={p[0]}"})
        log(f"Busca OK: {len(results)} itens.")
        return results
    except Exception as e: log(f"ERRO get_yt_info: {e}"); return []

def refill_queue():
    global refill_lock
    try:
        log(f"THREADS - refill_queue para '{state['last_query']}'")
        items = get_yt_info(state["last_query"])
        if items:
            with lock:
                # Filtrar duplicatas recentes (últimas 50 músicas)
                history_ids = set(state.get("history", [])[-50:])
                new_items = [it for it in items if it["id"] not in history_ids]
                if not new_items: new_items = items[:10] # Fallback se tudo for repetido
                
                state["queue"].extend(new_items)
                save_state()
                log(f"THREADS - Refil OK: +{len(new_items)} (Orig: {len(items)})")
    finally:
        refill_lock = False

def ensure_mpv():
    global mpv_proc
    with lock:
        if mpv_proc and mpv_proc.poll() is None: 
            return True
        log("Iniciando processo mpv...")
        # Limpeza agressiva do socket
        if os.path.exists(MPV_SOCKET) or os.path.islink(MPV_SOCKET):
            try: 
                os.remove(MPV_SOCKET)
                log(f"Socket antigo {MPV_SOCKET} removido.")
            except Exception as e: 
                log(f"Erro ao remover socket: {e}")
        cmd = [
            "mpv",
            "--no-video",
            "--input-ipc-server=" + MPV_SOCKET,
            "--cache=yes",
            "--demuxer-max-bytes=50M",
            "--demuxer-readahead-secs=30",
            "--ytdl-format=bestaudio[ext=m4a]/bestaudio/best",
            "--volume=" + str(state["volume"]),
            "--idle=yes",
            "--force-window=no"
        ]

        try:
            log(f"Executando mpv: {' '.join(cmd)}")
            mpv_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for i in range(50):
                if os.path.exists(MPV_SOCKET): 
                    log(f"Processo mpv OK (Socket criado em {i*0.1}s)")
                    return True
                time.sleep(0.1)
        except Exception as e:
            log(f"ERRO ao iniciar mpv: {e}")
        log("FALHA ao iniciar mpv (Socket nao encontrado apos 5s)")
        return False

def play_item(idx):
    if not (0 <= idx < len(state["queue"])): 
        log(f"play_item falhou: idx {idx} fora da fila ({len(state['queue'])})")
        return
    if ensure_mpv():
        state["current_idx"] = idx
        item = state["queue"][idx]
        log(f"AÇAO - TENTANDO TOCAR [{idx}]: {item['title']}")
        res = mpv_command("loadfile", item["url"])
        if "error" in res:
            log(f"ERRO play_item loadfile: {res['error']}")
        else:
            state["status"] = "playing"; state["title"] = item["title"]
            # Adicionar ao histórico
            if "history" not in state: state["history"] = []
            if item["id"] not in state["history"]:
                state["history"].append(item["id"])
                if len(state["history"]) > 200: state["history"].pop(0)
            log(f"AÇAO - play_item TOCANDO OK")

def stop_playback():
    global mpv_proc
    log("AÇAO - stop_playback")
    mpv_command("quit")
    if mpv_proc: 
        try: mpv_proc.kill()
        except: pass
        mpv_proc = None
    state["status"] = "stopped"; state["title"] = ""; state["current_idx"] = -1

def monitor_thread():
    global refill_lock, last_check_pos, last_check_time
    log("Monitor thread (Watchdog) iniciada.")
    while True:
        try:
            # 1. Manter reprodução (Idle detection)
            if state["status"] == "playing":
                idle = mpv_get_property("idle-active")
                if idle is True:
                    log("Watchdog: idle detectado. Seguindo fila...")
                    with lock:
                        n = state["current_idx"] + 1
                        if n >= len(state["queue"]):
                            if state["loop"]: n = 0
                            else: stop_playback(); n = -1
                        if n != -1: play_item(n)
                
                # 1.1 Stall Watchdog (se a música travar ou o socket não responder)
                curr_pos = mpv_get_property("time-pos")
                curr_time = time.time()
                if curr_pos is not None:
                    if curr_pos == last_check_pos and (curr_time - last_check_time) > 45:
                        # Se msm posição por 45s e o pause não estiver ativo
                        pause = mpv_get_property("pause")
                        if pause is False:
                            log("CRÍTICO: Stall detectado (musica parada mas 'playing'). Reiniciando player...")
                            play_item(state["current_idx"])
                    
                    if curr_pos != last_check_pos:
                        last_check_pos = curr_pos
                        last_check_time = curr_time

            # 2. Refil Infinito
            if state["infinite_mode"] and not refill_lock:
                remaining = len(state["queue"]) - (state["current_idx"] + 1)
                if remaining < 5 and state["queue"]:
                    log(f"Watchdog: fila baixa ({remaining}). Refill...")
                    refill_lock = True
                    threading.Thread(target=refill_queue, daemon=True).start()
                    
        except Exception as e: log(f"AVISO monitor_thread: {e}")
        time.sleep(5)

def get_sys_info():
    info = {"cpu": "0", "ram": 0, "internet": False, "source": "YT Music"}
    try:
        # PING rápido
        ping_cmd = ["ping", "-c", "1", "-W", "1", "8.8.8.8"] if sys.platform != "win32" else ["ping", "-n", "1", "-w", "1000", "8.8.8.8"]
        res = subprocess.run(ping_cmd, capture_output=True)
        info["internet"] = (res.returncode == 0)
        
        if sys.platform != "win32":
            # Status via systemctl
            info["source"] = "YT Music"
            
            # Stats robustas (Fallback Debian/Mac)
            try:
                # CPU load average (1 min)
                with open("/proc/loadavg", "r") as f: 
                    info["cpu"] = f.read().split()[0]
                # RAM
                with open("/proc/meminfo", "r") as f: 
                    lines = f.readlines()
                    total = int(lines[0].split()[1])
                    available = int(lines[2].split()[1])
                    used = total - available
                    info["ram"] = round((used / total) * 100, 1)
            except:
                # Fallback via top para macOS ou Debian truncado
                cpu_val = subprocess.check_output("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'", shell=True).decode().strip()
                info["cpu"] = cpu_val if cpu_val else "0.1"
    except Exception as e: 
        log(f"AVISO get_sys_info: {e}")
    return info

HTML_V3 = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Academia Espaço viva Infinite | Remote Control v4.1</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #05060b;
      --glass: rgba(255, 255, 255, 0.03);
      --glass-border: rgba(255, 255, 255, 0.08);
      --accent: hsl(265, 89%, 60%);
      --accent-glow: hsla(265, 89%, 60%, 0.4);
      --secondary: hsl(300, 89%, 55%);
      --success: hsl(142, 71%, 45%);
      --warning: hsl(38, 92%, 50%);
      --danger: hsl(350, 89%, 60%);
      --text: #ffffff;
      --text-dim: rgba(255, 255, 255, 0.5);
      --safe-bottom: env(safe-area-inset-bottom);
    }
    * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color: transparent; }
    body { font-family: 'Outfit', sans-serif; background: var(--bg); background: radial-gradient(circle at 50% -20%, hsl(265, 80%, 15%) 0%, var(--bg) 80%); color: var(--text); min-height: 100vh; padding-bottom: calc(180px + var(--safe-bottom)); overflow-x: hidden; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
    .brand h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; background: linear-gradient(to right, #fff, var(--text-dim)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .sys-info { display: flex; gap: 8px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
    .status-pill { background: var(--glass); border: 1px solid var(--glass-border); padding: 4px 10px; border-radius: 8px; display: flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .dot { width: 8px; height: 8px; border-radius: 50%; position: relative; }
    .dot-online { background: var(--success); box-shadow: 0 0 12px var(--success); }
    .dot-online::after { content: ''; position: absolute; width: 100%; height: 100%; background: inherit; border-radius: 50%; animation: ping 1.5s infinite; }
    .dot-offline { background: var(--danger); box-shadow: 0 0 12px var(--danger); }
    @keyframes ping { 0% { transform: scale(1); opacity: 0.8; } 100% { transform: scale(2.5); opacity: 0; } }

    .card { background: var(--glass); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid var(--glass-border); border-radius: 20px; padding: 20px; margin-bottom: 20px; transition: transform 0.3s; }
    .card:hover { border-color: var(--accent-glow); }
    .card-title { font-size: 11px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
    .search-box { position: relative; margin-bottom: 15px; }
    input { width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--glass-border); border-radius: 12px; padding: 14px 16px; color: #fff; font-size: 15px; outline: none; transition: 0.3s; }
    input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
    .search-btn { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: var(--accent); border: none; border-radius: 10px; width: 40px; height: 40px; color: white; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: 0.2s; }
    .btn { border: none; border-radius: 12px; padding: 12px; font-weight: 700; font-size: 14px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: 0.2s; }
    .btn-primary { background: var(--accent); color: #fff; box-shadow: 0 4px 15px var(--accent-glow); }
    .btn-secondary { background: var(--glass); border: 1px solid var(--glass-border); color: #fff; }
    .chips-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; max-height: 120px; overflow-y: auto; }
    .chip { background: var(--glass); border: 1px solid var(--glass-border); padding: 8px 14px; border-radius: 50px; font-size: 11px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: 0.2s; }
    .chip:active { transform: scale(0.9); }
    .q-item { display: flex; align-items: center; gap: 12px; padding: 12px; background: rgba(255,255,255,0.02); border-radius: 12px; margin-bottom:8px; cursor: pointer; border: 1px solid transparent; transition: 0.2s; }
    .q-item.playing { background: hsla(265, 89%, 60%, 0.15); border-color: var(--accent-glow); }
    .q-idx { font-size: 10px; font-weight: 700; color: var(--text-dim); width: 24px; }
    .q-title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .player-bar { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(7, 9, 18, 0.9); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border-top: 1px solid var(--glass-border); padding: 16px 20px calc(16px + var(--safe-bottom)); z-index: 1000; }
    .np-title { font-size: 15px; font-weight: 700; text-align: center; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .np-status { font-size: 10px; text-transform: uppercase; letter-spacing: 2px; font-weight: 700; text-align: center; color: var(--accent); margin-bottom: 12px; }
    .player-ctrls { display: flex; justify-content: center; align-items: center; gap: 32px; }
    .p-btn-main { width: 56px; height: 56px; background: #fff; color: #000; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 24px; box-shadow: 0 4px 20px rgba(255,255,255,0.3); }
    .volume-ctrl { display: flex; align-items: center; gap: 10px; width: 100%; max-width: 250px; margin: 15px auto 0; }
    .volume-slider { flex: 1; -webkit-appearance: none; height: 4px; background: var(--glass-border); border-radius: 2px; outline: none; }
    .volume-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; background: #fff; border-radius: 50%; cursor: pointer; }

    #logview { background: #000; color: #0f0; font-family: monospace; font-size: 9px; padding: 10px; border-radius: 8px; max-height: 80px; overflow-y: auto; margin-top: 20px; border: 1px solid #111; opacity: 0.6; }
    .auth-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: var(--bg); z-index: 10000; display: flex; align-items: center; justify-content: center; padding: 20px; }
    .auth-card { width: 100%; max-width: 320px; text-align: center; }
    .auth-input { width: 100%; text-align: center; font-size: 20px; letter-spacing: 4px; margin-bottom: 20px; background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); border-radius: 12px; padding: 12px; color: #fff; outline:none; }
  </style>
</head>
<body>
<div id="auth" class="auth-overlay">
  <div class="auth-card">
    <div class="brand"><h1>Academia Espaço viva</h1></div>
    <p style="margin-bottom: 24px; opacity: 0.6; font-size: 14px;">Forever Music Server v4.1</p>
    <input type="password" id="pass" class="auth-input" placeholder="••••" onkeydown="if(event.key==='Enter') login()">
    <button class="btn btn-primary" style="width: 100%;" onclick="login()">ENTRAR NO PAINEL</button>
  </div>
</div>

<div class="container">
  <header>
    <div class="brand"><h1>Espaço viva Infinite</h1></div>
    <div class="sys-info">
      <div class="status-pill" title="Network"><div class="dot" id="dotNet"></div> <span id="netText">---</span></div>
      <div class="status-pill" title="Hardware load">CPU <span id="cpuText">---</span></div>
      <div class="status-pill" title="Service">🛡️ <span id="statusSource">CHECK</span></div>
    </div>
  </header>

  <div class="card">
    <div class="card-title">BUSCA INTELIGENTE <span id="infBadge" onclick="api('/infinite').then(refresh)" style="color:var(--success); cursor:pointer;">AUTO-REFILL ON</span></div>
    <div class="search-box">
      <input type="text" id="inp" placeholder="Playlist ou música..." onkeydown="if(event.key==='Enter') add('track')">
      <button class="search-btn" onclick="add('track')">🔍</button>
    </div>
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
      <button class="btn btn-primary" onclick="add('playlist')">📂 Playlists</button>
      <button class="btn btn-secondary" onclick="confirmClear(this)">🗑️ Limpar Tudo</button>
    </div>
    <div class="chips-grid">
        <div class="chip" onclick="quick('🔥 Cross Brutal (Hardstyle)')">🔥 Cross Brutal</div>
        <div class="chip" onclick="quick('⚡ Cardio Techno')">⚡ Cardio Techno</div>
        <div class="chip" onclick="quick('💣 PR Day Mix')">💣 PR Day</div>
        <div class="chip" onclick="quick('🇧🇷 Brasil Workout Remix')">🇧🇷 Brasil Remix</div>
        <div class="chip" onclick="quick('🎧 Pop Internacional Remix')">🎧 Pop Remix</div>
        <div class="chip" onclick="quick('🥊 Fight Training')">🥊 Fight Training</div>
        <div class="chip" onclick="quick('rock nacional brasileiro anos 80 90')">🎸 Rock BR</div>
    </div>
  </div>

  <div class="card" id="qCard" style="display:none">
    <div class="card-title">FILA DE REPRODUÇÃO</div>
    <div id="qList"></div>
  </div>

  <div id="logview">Sincronizando com Mac Mini...</div>
</div>

<div class="player-bar">
  <div class="now-playing"><div class="np-title" id="npTitle">---</div><div class="np-status" id="npStatus">Desconectado</div></div>
  <div class="player-ctrls">
    <button class="btn" style="background:none" onclick="api('/prev').then(refresh)">⏮</button>
    <button class="p-btn-main" id="playBtn" onclick="api('/toggle').then(refresh)">▶</button>
    <button class="btn" style="background:none" onclick="api('/next').then(refresh)">⏭</button>
  </div>
  <div class="volume-ctrl">
    <span>🔈</span><input type="range" class="volume-slider" id="vol" min="0" max="100" oninput="setVol(this.value)"><span>🔊</span>
  </div>
</div>

<script>
let lastStatus = "";
function addLog(m) { const l = document.getElementById('logview'); l.innerHTML = "["+new Date().toLocaleTimeString()+"] "+m+"<br>"+l.innerHTML.split("<br>").slice(0,5).join("<br>"); }

async function api(p, data={}) {
  const auth = localStorage.getItem('espacoviva_auth');
  if(!auth) return;
  try {
    const r = await fetch('/api'+p, { method:'POST', cache:'no-cache', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json', 'X-Api-Key': auth } });
    if(r.status === 401) { logout(); return; }
    return r.json();
  } catch(e) { addLog("Erro API: "+p); }
}

function login() {
  const p = document.getElementById('pass').value;
  if(p === 'espacoviva') { localStorage.setItem('espacoviva_auth', p); document.getElementById('auth').style.display = 'none'; refresh(); }
  else { alert('Senha incorreta!'); }
}
function logout() { localStorage.removeItem('espacoviva_auth'); location.reload(); }
if(localStorage.getItem('espacoviva_auth') === 'espacoviva') document.getElementById('auth').style.display = 'none';

async function refresh() {
  const auth = localStorage.getItem('espacoviva_auth');
  if(!auth) return;
  try {
    const s = await fetch('/api/state?t=' + Date.now() + '&auth=' + auth).then(r=>r.json());
    document.getElementById('npTitle').textContent = s.title || (s.status === 'playing' ? 'Tocando...' : 'Pausado');
    document.getElementById('npStatus').textContent = s.status === 'playing' ? '● AO VIVO' : 'SISTEMA EM IDLE';
    document.getElementById('playBtn').textContent = s.status === 'playing' ? '⏸' : '▶';
    
    if(s.queue.length > 0) {
        document.getElementById('qCard').style.display = 'block';
        document.getElementById('qList').innerHTML = s.queue.slice(0, 30).map((it, i) => `
            <div class="q-item ${s.current_idx == i ? 'playing' : ''}" onclick="play(${i})">
                <div class="q-idx">${i+1}</div>
                <div class="q-title">${it.title}</div>
            </div>`).join('');
    } else { document.getElementById('qCard').style.display = 'none'; }

    document.getElementById('dotNet').className = 'dot ' + (s.sys.internet ? 'dot-online' : 'dot-offline');
    document.getElementById('netText').textContent = s.sys.internet ? 'Online' : 'Offline';
    document.getElementById('cpuText').textContent = s.sys.cpu + (String(s.sys.cpu).includes('%') ? '' : '%');
    document.getElementById('statusSource').textContent = s.sys.source || "ONLINE";
    document.getElementById('infBadge').textContent = s.infinite_mode ? "AUTO-REFILL ON" : "AUTO-REFILL OFF";
    document.getElementById('infBadge').style.color = s.infinite_mode ? "var(--success)" : "var(--text-dim)";
    
    if(s.status != lastStatus) { addLog("Status alterado para: "+s.status); lastStatus = s.status; }
  } catch(e) { document.getElementById('npStatus').textContent = "SEM RESPOSTA DO MAC MINI ⚠️"; }
}

async function add(mode) { 
  const v = document.getElementById('inp').value; if(!v) return;
  addLog("Buscando: "+v);
  await api('/add', { q: v, mode: mode });
  document.getElementById('inp').value = '';
  setTimeout(refresh, 1500);
}
function quick(q) { document.getElementById('inp').value = q; add('playlist'); }
function play(idx) { api('/play', {i: idx}).then(refresh); }
function setVol(v) { api('/volume', {v: v}); }
function confirmClear(btn) { api('/clear').then(() => { addLog("Fila limpa"); refresh(); }); }

setInterval(refresh, 5000); refresh();
</script>
</body>
</html>"""

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer): pass
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def check_auth(self):
        # Permitir index e assets sem senha
        if self.path == "/" or "/index.html" in self.path: return True
        # Check API Key
        key = self.headers.get("X-Api-Key")
        if not key:
            # Fallback for state via URL param (used in simple fetch)
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            key = params.get("auth", [None])[0]
        
        if key == "espacoviva": return True
        self._unauthorized()
        return False

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "unauthorized"}).encode())

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.end_headers()

    def do_GET(self):
        if not self.check_auth(): return
        if self.path == "/" or "/index.html" in self.path: 
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_V3.encode('utf-8'))
        elif "/api/state" in self.path:
            t = mpv_get_property("media-title"); p = mpv_get_property("pause")
            st = "playing" if p is False else "stopped"
            state["title"] = t or state["title"]; state["status"] = st
            self._json({ **state, "sys": get_sys_info() })

    def do_POST(self):
        if not self.check_auth(): return
        try:
            cl = int(self.headers.get('Content-Length', 0)); data = json.loads(self.rfile.read(cl)) if cl else {}
            log(f"API RECEBIDA: {self.path} - DATA: {data}")
            if self.path == "/api/add":
                q = data.get("q")
                items = get_yt_info(q, is_playlist_search=("playlist" in data.get("mode", "")))
                with lock: 
                    state["queue"].extend(items); save_state()
                self._json({"ok": True, "count": len(items)})
            elif self.path == "/api/clear":
                with lock: stop_playback(); state["queue"] = []; state["current_idx"] = -1; save_state()
                self._json({"ok": True})
            elif self.path == "/api/remove":
                idx = int(data.get("i", -1))
                with lock:
                    if 0 <= idx < len(state["queue"]):
                        state["queue"].pop(idx)
                        if idx == state["current_idx"]: stop_playback()
                        elif idx < state["current_idx"]: state["current_idx"] -= 1
                        save_state()
                self._json({"ok": True})
            elif self.path == "/api/play": play_item(int(data.get("i", 0))); self._json({"ok": True})
            elif self.path == "/api/toggle":
                ensure_mpv()
                if state["status"] == "stopped" and state["queue"]: 
                    play_item(max(0, state["current_idx"]))
                else: 
                    mpv_command("cycle", "pause")
                self._json({"ok": True})
            elif self.path == "/api/next":
                with lock:
                    if state["current_idx"] + 1 < len(state["queue"]): play_item(state["current_idx"]+1)
                    elif state["loop"]: play_item(0)
                self._json({"ok": True})
            elif self.path == "/api/prev":
                with lock:
                    if state["current_idx"] > 0: play_item(state["current_idx"] - 1)
                self._json({"ok": True})
            elif self.path == "/api/infinite": state["infinite_mode"] = not state["infinite_mode"]; save_state(); self._json({"infinite": state["infinite_mode"]})
            elif self.path == "/api/volume":
                v = int(data.get("v", 80))
                state["volume"] = v; mpv_command("set_property", "volume", v); save_state()
                self._json({"ok": True})
        except Exception as e: log(f"ERRO API_POST: {e}"); self._json({"error": str(e)})

load_state()
# Auto-resume on startup if queue exists
log(f"Auto-resume DEBUG: queue_len={len(state['queue'])}, current_idx={state['current_idx']}")
if state["queue"] and state["current_idx"] >= 0:
    log(f"Auto-resume: iniciando reprodução do índice {state['current_idx']} em 5 segundos...")
    def auto_play():
        time.sleep(5)
        play_item(state["current_idx"])
    threading.Thread(target=auto_play, daemon=True).start()
else:
    log("Auto-resume: fila vazia, nada para tocar.")

threading.Thread(target=monitor_thread, daemon=True).start()
log(f"Academia Infinite Premium v4.0 iniciada na porta {PORT}")
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
