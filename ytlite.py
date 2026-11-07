#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTLite - reproductor liviano de YouTube para hardware viejo.

Tecnologia: Python 3 + Tkinter (GUI) + mpv (reproduccion, embebido via --wid,
controlado por IPC JSON) + yt-dlp (extraccion). Sin navegador, sin Qt/GTK.
El bufer de red vive en RAM (mpv, cache-on-disk=no): no se escribe disco
mientras se reproduce.
"""
import collections
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from tkinter import font as tkfont
except ImportError:
    sys.exit("Falta Tkinter. Instalalo con: sudo apt install python3-tk")

import logging
from logging.handlers import RotatingFileHandler

APP = "YTLite"
VERSION = "1.0"
CFG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "ytlite")
os.makedirs(CFG_DIR, exist_ok=True)
F_CFG = os.path.join(CFG_DIR, "config.json")
F_QUEUE = os.path.join(CFG_DIR, "queue.json")
F_HIST = os.path.join(CFG_DIR, "history.json")
F_FAV = os.path.join(CFG_DIR, "favorites.json")
F_LOG = os.path.join(CFG_DIR, "ytlite.log")
LOCAL_YTDLP = os.path.expanduser("~/.local/bin/yt-dlp")

DEFAULTS = {
    "quality": "480p",          # Auto / 360p / 480p / 720p / 1080p
    "audio_only": False,
    "loudnorm": False,
    "conservative": True,       # tope 480p, H.264, decodificacion rapida
    "cache_mb": 64,             # bufer en RAM hacia adelante
    "back_cache_mb": 8,         # bufer en RAM hacia atras
    "vo": "auto",               # auto | xv | x11 | gpu
    "volume": 80,
    "shot_dir": os.path.expanduser("~/Pictures/YTLite"),
    "dl_dir": os.path.expanduser("~/Videos/YTLite"),
    "subs": True,
    "sub_langs": "es.*|en.*",
    "max_playlist": 300,
    "dl_rate": "",
    "timer_action": "poweroff",  # poweroff | quit
    "shutdown_cmd": "poweroff || sudo -n poweroff",
    "notify": True,
    "geometry": "1000x600",
}
QUALITIES = ["Auto", "360p", "480p", "720p", "1080p"]
SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
RESTART_KEYS = ("conservative", "cache_mb", "back_cache_mb", "vo", "subs", "sub_langs")
PL_COLORS = ["#e8f0fe", "#fdecea", "#e6f4ea", "#fff4e0", "#f3e8fd", "#e0f7fa"]

# (tecla mpv, keysym Tk, requiere shift, accion)
KEYS = [
    ("SPACE", "space", 0, "pause"),
    ("LEFT", "Left", 0, "seek:-5"), ("RIGHT", "Right", 0, "seek:5"),
    ("Shift+LEFT", "Left", 1, "seek:-30"), ("Shift+RIGHT", "Right", 1, "seek:30"),
    ("UP", "Up", 0, "vol:5"), ("DOWN", "Down", 0, "vol:-5"),
    ("+", "plus", 0, "vol:5"), ("-", "minus", 0, "vol:-5"),
    ("m", "m", 0, "mute"), ("f", "f", 0, "fs"), ("ESC", "Escape", 0, "fs_off"),
    ("n", "n", 0, "next"), ("p", "p", 0, "prev"),
    ("]", "bracketright", 0, "speed:up"), ("[", "bracketleft", 0, "speed:down"),
    ("s", "s", 0, "shot"), ("a", "a", 0, "audio"), ("c", "c", 0, "sub"), ("b", "b", 0, "fav"),
    ("PGUP", "Prior", 0, "chap:-1"), ("PGDWN", "Next", 0, "chap:1"),
]

MANUAL = """\
YTLITE - MANUAL DE USO
======================

QUE ES
------
Reproductor de YouTube de una sola ventana, pensado para equipos viejos.
Usa mpv (reproduce) y yt-dlp (obtiene el video). No abre ningun navegador.
El video empieza a verse a los pocos segundos; el bufer esta en RAM, no en disco.

REPRODUCIR
----------
* Pega una URL en el campo de arriba y pulsa Enter o "Reproducir".
* "Pegar" toma la URL del portapapeles y la reproduce directamente.
* "Encolar" la agrega al final de la cola sin interrumpir lo que suena.
* "Playlist" agrega TODOS los videos de la playlist de la URL (si la URL es de un
  video con &list=..., por defecto se toma solo el video; con este boton se
  toma la lista completa).
* Si pegas una URL de playlist con "Reproducir", la app pregunta si queres
  agregar toda la lista.
* Si la pantalla de video se ve negra, un clic sobre ella inicia/pausa.
* "Reproducir" con el campo vacio reproduce el elemento elegido en la cola
  (o el actual / el primero).

CONTROLES
---------
* Barra de progreso: clic o arrastre para saltar. En vivo muestra "EN VIVO".
* Velocidad: 0.5x a 2x (lista desplegable o teclas [ y ]).
* Volumen: control deslizante, rueda del mouse sobre el video, flechas arriba/abajo.
* Calidad: Auto / 360p / 480p / 720p / 1080p. Se aplica al instante
  (recarga el video en el mismo minuto). "Auto" mide tu conexion antes de reproducir.
* Solo audio: ahorra CPU y datos al maximo; se puede activar y desactivar en
  plena reproduccion.
* Estrella: marca/desmarca el video actual como favorito.
* Foto: captura de pantalla del video (carpeta configurable).
* Pantalla completa: boton o tecla F. Esc para salir.

COLA
----
* Al terminar un video pasa solo al siguiente. Al terminar la cola avisa.
* Doble clic o Enter sobre un elemento: reproducirlo.
* Botones: subir, bajar, quitar (tambien tecla Supr), vaciar, guardar y cargar
  (archivo .json). El filtro de arriba busca por titulo o nombre de playlist;
  con un filtro activo no se puede reordenar.
* Cada fila de una playlist lleva el nombre de su lista y un color propio.
* La cola se guarda sola al cerrar y se restaura al abrir.

HISTORIAL, FAVORITOS Y BUSCADOR
-------------------------------
* Historial: lo visto, con el minuto donde quedaste. Al volver a reproducir un
  video se retoma automaticamente (si no estaba casi terminado).
* Favoritos: lista de videos marcados con la estrella.
* Buscar: busca en YouTube sin navegador. Doble clic reproduce; "Encolar" agrega.

MENUS
-----
* Archivo: guardar/cargar cola, descargar el video actual (para verlo sin conexion),
  cancelar descarga.
  Aviso: descargar escribe en disco; corre con prioridad minima, pero en
  equipos muy lentos conviene descargar sin reproducir otra cosa.
* Reproduccion: captura, subtitulos, solo audio, capitulos, temporizador.
* Herramientas: preferencias, actualizar yt-dlp, reiniciar reproductor, ver log.

TEMPORIZADOR DE APAGADO
-----------------------
15, 30 o 60 minutos, o "fin del video actual". Al vencer se pausa y se muestra una
cuenta regresiva de 30 s (se puede cancelar). Despues apaga el equipo o solo
cierra la app, segun Preferencias.

SUBTITULOS Y CAPITULOS
----------------------
* Tecla C: cicla entre subtitulos disponibles (empiezan apagados).
* Menu Reproduccion > Capitulos, o teclas RePag/AvPag, si el video los tiene.

ATAJOS
------
  Espacio / clic       Pausa / reanudar
  Izq / Der            -5 s / +5 s
  Shift+Izq / Der      -30 s / +30 s
  Arriba / Abajo, + -  Volumen (tambien rueda del mouse)
  M                    Silenciar
  [  ]                 Velocidad menos / mas
  N / P                Siguiente / anterior
  F / Esc              Pantalla completa / salir
  S                    Captura
  A                    Solo audio on/off
  C                    Subtitulos
  B                    Favorito on/off
  RePag / AvPag        Capitulo anterior / siguiente
(Las teclas de letra no funcionan mientras escribis en un campo de texto.)

SI ALGO FALLA
-------------
* Error de extraccion (YouTube cambio algo): Herramientas > Actualizar yt-dlp.
* Si el reproductor se cae, se relanza solo y retoma cerca de donde estaba
  (hasta 3 intentos; despues avisa).
* Herramientas > Ver log muestra el diagnostico (tambien en ~/.config/ytlite/).
* Video negro con sonido: Preferencias > Salida de video = x11 (o gpu).
* Los errores aparecen en rojo en la barra de estado.

ARCHIVOS
--------
~/.config/ytlite/  config.json, queue.json, history.json, favorites.json, ytlite.log
Opciones extra de yt-dlp (cookies, etc.): ~/.config/yt-dlp/config
"""

# --------------------------------------------------------------------------
# Log: memoria + archivo rotativo chico
# --------------------------------------------------------------------------
LOG = collections.deque(maxlen=1500)


class MemHandler(logging.Handler):
    def emit(self, rec):
        try:
            LOG.append(self.format(rec))
        except Exception:
            pass


log = logging.getLogger("ytlite")
log.setLevel(logging.DEBUG)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
_mh = MemHandler()
_mh.setFormatter(_fmt)
log.addHandler(_mh)
try:
    _fh = RotatingFileHandler(F_LOG, maxBytes=200000, backupCount=1, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _fh.setLevel(logging.INFO)
    log.addHandler(_fh)
except Exception:
    pass


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        log.warning("No pude leer %s: %s", path, e)
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.error("No pude guardar %s: %s", path, e)
        return False


def fmt_time(s):
    if s is None:
        return "--:--"
    s = int(max(0, s))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, sec) if h else "%02d:%02d" % (m, sec)


def find_ytdlp():
    if os.path.isfile(LOCAL_YTDLP) and os.access(LOCAL_YTDLP, os.X_OK):
        return LOCAL_YTDLP
    return shutil.which("yt-dlp")


def lowprio(cmd):
    pre = []
    if shutil.which("nice"):
        pre = ["nice", "-n", "15"]
    if shutil.which("ionice"):
        pre = ["ionice", "-c3"] + pre
    return pre + cmd


YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
            "youtu.be", "www.youtube-nocookie.com")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_url(raw):
    """-> (tipo, url_canonica, list_id). tipo: video | video_list | playlist | invalid"""
    raw = (raw or "").strip()
    if not re.match(r"^https?://", raw, re.I):
        if re.match(r"^(www\.|m\.)?(youtube\.com|youtu\.be)/", raw, re.I):
            raw = "https://" + raw
        else:
            return ("invalid", raw, None)
    u = urlparse(raw)
    host = u.netloc.lower()
    if not host or " " in raw:
        return ("invalid", raw, None)
    if host not in YT_HOSTS:
        return ("video", raw, None)          # otro sitio: que lo resuelva yt-dlp
    q = parse_qs(u.query)
    lst = q.get("list", [None])[0]
    vid = None
    if "v" in q:
        vid = q["v"][0]
    elif host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    else:
        m = re.match(r"^/(shorts|live|embed|v)/([A-Za-z0-9_-]{11})", u.path)
        if m:
            vid = m.group(2)
    if u.path.startswith("/playlist") and lst:
        return ("playlist", "https://www.youtube.com/playlist?list=" + lst, lst)
    if vid:
        if not ID_RE.match(vid):
            return ("invalid", raw, None)
        return ("video_list" if lst else "video", "https://www.youtube.com/watch?v=" + vid, lst)
    if lst:
        return ("playlist", "https://www.youtube.com/playlist?list=" + lst, lst)
    return ("invalid", raw, None)


def mk_item(url, title="", playlist="", duration=None):
    return {"url": url, "title": title, "playlist": playlist, "duration": duration}


def build_format(height, audio_only):
    if audio_only:
        return "bestaudio[ext=m4a]/bestaudio/best"
    h = int(height)
    return ("bv*[height<=%d][vcodec^=avc1]+ba[ext=m4a]/b[height<=%d][vcodec^=avc1]/"
            "bv*[height<=%d]+ba/b[height<=%d]/b" % (h, h, h, h))


def run_ytdlp(args, timeout=60, low=False):
    exe = find_ytdlp()
    if not exe:
        raise RuntimeError("yt-dlp no esta instalado: Herramientas > Actualizar yt-dlp")
    cmd = [exe, "--no-warnings", "--socket-timeout", "15"] + args
    if low:
        cmd = lowprio(cmd)
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                           universal_newlines=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise RuntimeError("yt-dlp tardo demasiado (%ds); revisa la conexion" % timeout)
    if p.returncode != 0 and not p.stdout.strip():
        errs = [l for l in p.stderr.splitlines() if l.strip()]
        raise RuntimeError(errs[-1][:200] if errs else "yt-dlp fallo (codigo %d)" % p.returncode)
    return p.stdout


def na(s):
    s = (s or "").strip()
    return "" if s in ("NA", "None", "null") else s


def parse_rows(out):
    """Filas 'id \\t titulo \\t campo_a \\t campo_b' -> [(id, titulo, a, b)]"""
    rows = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) < 4 or not ID_RE.match(p[0].strip()):
            continue
        rows.append((p[0].strip(), "\t".join(p[1:-2]).strip(), na(p[-2]), na(p[-1])))
    return rows


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def fetch_playlist(url, lst_id, limit):
    out = run_ytdlp(["--flat-playlist", "--ignore-errors", "--playlist-end", str(limit), "--print",
                     "%(id)s\t%(title)s\t%(duration)s\t%(playlist_title)s", url], timeout=120)
    items = []
    for vid, title, dur, ptitle in parse_rows(out):
        items.append(mk_item("https://www.youtube.com/watch?v=" + vid, title,
                             ptitle or "Lista " + (lst_id or "")[-6:], to_float(dur)))
    return items


def fetch_search(q, n=15):
    out = run_ytdlp(["--flat-playlist", "--print", "%(id)s\t%(title)s\t%(duration)s\t%(channel,uploader)s",
                     "ytsearch%d:%s" % (n, q)], timeout=60)
    return [dict(mk_item("https://www.youtube.com/watch?v=" + vid, title, "", to_float(dur)), channel=ch)
            for vid, title, dur, ch in parse_rows(out)]


SPEED_URLS = ["https://speed.cloudflare.com/__down?bytes=2000000", "https://proof.ovh.net/files/10Mb.dat"]


def measure_mbps(max_bytes=1500000, timeout=8):
    for u in SPEED_URLS:
        try:
            t0 = time.time()
            got = 0
            with urlopen(Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
                while got < max_bytes and time.time() - t0 < timeout:
                    b = r.read(65536)
                    if not b:
                        break
                    got += len(b)
            if got > 100000:
                return got * 8.0 / max(time.time() - t0, 0.05) / 1e6
        except Exception as e:
            log.warning("medicion de ancho de banda fallo (%s): %s", u, e)
    return None


def auto_height(mbps, cap):
    # bitrates H.264 aprox: 360p 0.8, 480p 1.5, 720p 3, 1080p 6 Mbps; pedimos ~2x de margen
    h = 360
    for need, hh in ((3.0, 480), (6.0, 720), (12.0, 1080)):
        if mbps >= need:
            h = hh
    return min(h, cap)


_VOS = None


def pick_vo(pref):
    global _VOS
    if pref and pref != "auto":
        return pref
    if _VOS is None:
        _VOS = []
        try:
            out = subprocess.run(["mpv", "--vo=help"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 universal_newlines=True, timeout=10).stdout
            for l in out.splitlines():
                m = re.match(r"^\s+([a-z0-9_-]+)\s", l)
                if m:
                    _VOS.append(m.group(1))
        except Exception:
            pass
    # lista en orden de preferencia: mpv usa la primera que pueda inicializar de verdad
    avail = [v for v in ("xv", "x11", "gpu") if v in _VOS]
    return ",".join(avail) if avail else None


# --------------------------------------------------------------------------
# Player: proceso mpv embebido + IPC JSON
# --------------------------------------------------------------------------
OBSERVE = ["time-pos", "duration", "pause", "volume", "mute", "speed", "media-title", "chapter-list",
           "paused-for-cache", "demuxer-cache-duration", "video-params/h"]


class Player:
    def __init__(self):
        self.proc = None
        self.sock = None
        self.ready = False
        self.props = {}
        self.evq = queue.Queue()
        self.callbacks = {}
        self.req_id = 0
        self.last_error = ""
        self.err_tail = collections.deque(maxlen=30)
        rd = os.environ.get("XDG_RUNTIME_DIR")
        base = rd if rd and os.path.isdir(rd) and os.access(rd, os.W_OK) else "/tmp"
        self.sockpath = os.path.join(base, "ytlite-%d.sock" % os.getpid())
        self.conf = os.path.join(base, "ytlite-%d.conf" % os.getpid())

    # -- ciclo de vida
    def start(self, wid, cfg):
        self.stop()
        mpv = shutil.which("mpv")
        if not mpv:
            raise RuntimeError("mpv no esta instalado (sudo apt install mpv)")
        self.evq = queue.Queue()
        self.props = {}
        self.ready = False
        self.last_error = ""
        self.err_tail.clear()
        lines = ["%s script-message ytl %s" % (k, act) for k, _, _, act in KEYS]
        lines += ["MBTN_LEFT script-message ytl click", "WHEEL_UP script-message ytl vol:5",
                  "WHEEL_DOWN script-message ytl vol:-5"]
        with open(self.conf, "w") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.unlink(self.sockpath)
        except OSError:
            pass
        a = [mpv, "--idle=yes", "--force-window=yes", "--keep-open=no", "--no-config",
             "--wid=%d" % wid, "--input-ipc-server=" + self.sockpath,
             "--no-input-default-bindings", "--input-conf=" + self.conf, "--input-terminal=no",
             "--osc=no", "--osd-level=1", "--msg-level=all=warn",
             "--ytdl=yes", "--script-opts=ytdl_hook-ytdl_path=" + (find_ytdlp() or "yt-dlp"),
             "--ytdl-format=" + build_format(480, False),
             "--volume=%d" % cfg["volume"],
             "--cache=yes", "--cache-on-disk=no",
             "--demuxer-max-bytes=%dMiB" % cfg["cache_mb"],
             "--demuxer-max-back-bytes=%dMiB" % cfg["back_cache_mb"],
             "--demuxer-readahead-secs=90", "--network-timeout=20",
             "--audio-display=no", "--sid=no", "--slang=es,en", "--cursor-autohide=2000"]
        vo = pick_vo(cfg["vo"])
        if vo:
            a.append("--vo=" + vo)
        if cfg["conservative"]:
            a += ["--framedrop=vo", "--vd-lavc-fast", "--vd-lavc-skiploopfilter=nonref",
                  "--sws-scaler=fast-bilinear", "--hr-seek=no", "--video-sync=audio"]
        if cfg["subs"]:
            a.append("--ytdl-raw-options=write-subs=,sub-langs=" + cfg["sub_langs"])
        log.info("Lanzando mpv: %s", " ".join(a))
        proc = subprocess.Popen(a, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                universal_newlines=True, encoding="utf-8", errors="replace")
        self.proc = proc
        threading.Thread(target=self._err_loop, args=(proc,), daemon=True).start()
        threading.Thread(target=self._ipc_loop, args=(proc, self.evq, self.props), daemon=True).start()

    def stop(self):
        p = self.proc
        self.proc = None
        self.ready = False
        s = self.sock
        self.sock = None
        if s:
            try:
                s.send(b'{"command":["quit"]}\n', socket.MSG_DONTWAIT)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        if p:
            try:
                p.wait(timeout=1.5)
            except Exception:
                try:
                    p.kill()
                    p.wait(timeout=1)
                except Exception:
                    pass
        for f in (self.sockpath,):
            try:
                os.unlink(f)
            except OSError:
                pass

    def cleanup(self):
        self.stop()
        try:
            os.unlink(self.conf)
        except OSError:
            pass

    # -- hilos
    def _err_loop(self, proc):
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                self.err_tail.append(line)
                log.info("mpv: %s", line)
                if "ERROR" in line or "error" in line.lower():
                    self.last_error = re.sub(r"^\[[^\]]*\]\s*", "", line)
        except Exception:
            pass

    def _ipc_loop(self, proc, evq, props):
        sock = None
        for _ in range(150):
            if proc.poll() is not None:
                return
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(self.sockpath)
                sock = s
                break
            except OSError:
                s.close()
                time.sleep(0.1)
        if sock is None:
            evq.put(("ipc_fail", {}))
            return
        if proc is not self.proc:
            sock.close()
            return
        self.sock = sock
        for i, name in enumerate(OBSERVE, 1):
            self._send({"command": ["observe_property", i, name]})
        self.ready = True
        evq.put(("ready", {}))
        buf = b""
        while True:
            try:
                d = sock.recv(65536)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    m = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                ev = m.get("event")
                if ev == "property-change":
                    props[m.get("name")] = m.get("data")
                elif ev:
                    evq.put((ev, m))
                elif "request_id" in m:
                    cb = self.callbacks.pop(m["request_id"], None)
                    if cb:
                        evq.put(("reply", {"cb": cb, "msg": m}))
        evq.put(("ipc_closed", {}))

    # -- comandos
    def _send(self, obj):
        s = self.sock
        if not s:
            return False
        try:
            s.send((json.dumps(obj) + "\n").encode("utf-8"), socket.MSG_DONTWAIT)
            return True
        except OSError as e:
            log.warning("IPC send fallo: %s", e)
            return False

    def cmd(self, *args, **kw):
        o = {"command": list(args)}
        cb = kw.get("cb")
        if cb:
            self.req_id += 1
            o["request_id"] = self.req_id
            self.callbacks[self.req_id] = cb
        return self._send(o)

    def setp(self, name, val):
        return self.cmd("set_property", name, val)


# --------------------------------------------------------------------------
# Pestana generica de lista (historial, favoritos, busqueda)
# --------------------------------------------------------------------------
class ListTab(ttk.Frame):
    def __init__(self, parent, cols, play_cb, enq_cb, extra=()):
        ttk.Frame.__init__(self, parent)
        self.items = {}
        self.tv = ttk.Treeview(self, columns=[c[0] for c in cols], show="headings", selectmode="extended")
        for i, (cid, title, w) in enumerate(cols):
            self.tv.heading(cid, text=title)
            self.tv.column(cid, width=w, stretch=(i == 0), anchor="w")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        bf = ttk.Frame(self)
        bf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(bf, text="Reproducir", command=lambda: play_cb(self.selected())).pack(side="left")
        ttk.Button(bf, text="Encolar", command=lambda: enq_cb(self.selected())).pack(side="left", padx=2)
        for label, cb in extra:
            ttk.Button(bf, text=label, command=lambda cb=cb: cb(self.selected())).pack(side="left")
        self.tv.bind("<Double-1>", lambda e: play_cb(self.selected()))
        self.tv.bind("<Return>", lambda e: play_cb(self.selected()))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def set_rows(self, rows):
        self.tv.delete(*self.tv.get_children())
        self.items = {}
        for i, (it, vals) in enumerate(rows):
            self.items[str(i)] = it
            self.tv.insert("", "end", iid=str(i), values=vals)

    def selected(self):
        return [self.items[i] for i in self.tv.selection() if i in self.items]


# --------------------------------------------------------------------------
# Aplicacion
# --------------------------------------------------------------------------
class App:
    def __init__(self, root, argv):
        self.root = root
        self.cfg = dict(DEFAULTS)
        self.cfg.update(load_json(F_CFG, {}))
        if self.cfg["quality"] not in QUALITIES:
            self.cfg["quality"] = "480p"
        self.queue = []
        self.cur = None
        self.history = load_json(F_HIST, {})
        self.favs = load_json(F_FAV, [])
        self.player = Player()
        self.ui_q = queue.Queue()
        self.title_q = queue.Queue()
        self.pl_map = {}
        self.loaded = False
        self.loading = False
        self.live = False
        self.loaded_at = 0
        self.dragging = False
        self.loaded_audio_fmt = False
        self.pending_seek = None
        self.deferred = None
        self.crash_resume = None
        self.restarts = 0
        self.restart_pos = 0
        self.err_streak = 0
        self.last_pos = 0
        self.gave_up = False
        self.load_gen = 0
        self.fullscreen = False
        self.chapters = []
        self.timer_at = None
        self.timer_end = False
        self.dl_proc = None
        self.speed_cache = None
        self.hist_dirty = False
        self.q_dirty = False
        self.last_flush = time.time()
        self.quitting = False
        self.n = 0
        self._pkey = None
        self._ui_upd = False
        self._shown_title = None
        self._fav_state = None
        self.build_ui()
        self.restore_queue()
        self.root.update()
        self.start_player()
        threading.Thread(target=self.title_loop, daemon=True).start()
        urls = [a for a in argv if a.strip()]
        for i, u in enumerate(urls):
            self.handle_url(u, play=(i == 0))
        self.root.after(100, self.loop)

    # ------------------------------------------------------------ UI
    def build_ui(self):
        r = self.root
        r.title(APP)
        r.geometry(self.cfg["geometry"])
        r.minsize(780, 480)
        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass
        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)
        self.build_menu()

        top = ttk.Frame(r, padding=(6, 6, 6, 2))
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.url_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.url_var)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self.on_play_click())
        for txt, cmd in (("Reproducir", self.on_play_click), ("Encolar", self.on_enqueue_click),
                         ("Playlist", self.on_playlist_click), ("Pegar", self.on_paste_click)):
            ttk.Button(top, text=txt, command=cmd, width=10).pack(side="left", padx=(4, 0))

        self.video = tk.Frame(r, bg="black", width=480, height=270)
        self.video.grid(row=1, column=0, sticky="nsew")
        self.video.bind("<Button-1>", lambda ev: self.do_action("click"))

        ctl = ttk.Frame(r, padding=(6, 4))
        ctl.grid(row=2, column=0, sticky="ew")
        pr = ttk.Frame(ctl)
        pr.pack(fill="x")
        self.lbl_pos = ttk.Label(pr, text="--:--", width=8)
        self.lbl_pos.pack(side="left")
        self.pbar = tk.Canvas(pr, height=20, bg="#222", highlightthickness=0, cursor="hand2")
        self.pbar.pack(side="left", fill="x", expand=True)
        self.lbl_dur = ttk.Label(pr, text="--:--", width=8, anchor="e")
        self.lbl_dur.pack(side="left")
        self.pbar.bind("<Button-1>", self.pb_press)
        self.pbar.bind("<B1-Motion>", self.pb_motion)
        self.pbar.bind("<ButtonRelease-1>", self.pb_release)
        self.pbar.bind("<Configure>", lambda ev: self.draw_progress(self._frac, self._dur_v, self.live))
        self._frac, self._dur_v = 0.0, None

        r1 = ttk.Frame(ctl)
        r1.pack(fill="x", pady=(4, 0))
        ttk.Button(r1, text="|<", width=3, command=self.prev_item).pack(side="left", padx=1)
        self.btn_play = ttk.Button(r1, text=">", width=4, command=lambda: self.do_action("pause"))
        self.btn_play.pack(side="left", padx=1)
        ttk.Button(r1, text=">|", width=3, command=lambda: self.next_item(False)).pack(side="left", padx=1)
        ttk.Label(r1, text="  Vel:").pack(side="left")
        self.speed_var = tk.StringVar(value="1x")
        sp = ttk.Combobox(r1, textvariable=self.speed_var, width=5, state="readonly",
                          values=["%gx" % s for s in SPEEDS])
        sp.pack(side="left")
        sp.bind("<<ComboboxSelected>>", self.on_speed_sel)
        ttk.Label(r1, text="  Vol:").pack(side="left")
        self.vol = ttk.Scale(r1, from_=0, to=100, length=90, command=self.on_vol)
        self.vol.set(self.cfg["volume"])
        self.vol.pack(side="left")
        self.btn_mute = ttk.Button(r1, text="Mudo", width=5, command=lambda: self.do_action("mute"))
        self.btn_mute.pack(side="left", padx=2)

        r2 = ttk.Frame(ctl)
        r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="Calidad:").pack(side="left")
        self.q_var = tk.StringVar(value=self.cfg["quality"])
        qc = ttk.Combobox(r2, textvariable=self.q_var, width=6, state="readonly", values=QUALITIES)
        qc.pack(side="left")
        qc.bind("<<ComboboxSelected>>", self.on_quality)
        self.audio_var = tk.BooleanVar(value=self.cfg["audio_only"])
        ttk.Checkbutton(r2, text="Solo audio", variable=self.audio_var, command=self.on_audio_toggle,
                        takefocus=0).pack(side="left", padx=6)
        self.btn_fav = ttk.Button(r2, text="\u2606", width=3, command=self.toggle_fav)
        self.btn_fav.pack(side="left", padx=1)
        ttk.Button(r2, text="Foto", width=5, command=self.screenshot).pack(side="left", padx=1)
        ttk.Button(r2, text="Pantalla completa", command=lambda: self.do_action("fs")).pack(side="left", padx=1)

        # panel derecho
        self.nb = ttk.Notebook(r, width=370)
        self.nb.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(4, 6), pady=(2, 0))
        self.build_queue_tab()
        self.hist_tab = ListTab(self.nb, [("t", "Titulo", 190), ("p", "Posicion", 85), ("d", "Fecha", 70)],
                                self.play_items, self.enqueue,
                                extra=[("Quitar", self.hist_remove), ("Borrar todo", self.hist_clear)])
        self.nb.add(self.hist_tab, text="Historial")
        self.fav_tab = ListTab(self.nb, [("t", "Titulo", 280), ("d", "Dur.", 60)], self.play_items, self.enqueue,
                               extra=[("Quitar", self.fav_remove)])
        self.nb.add(self.fav_tab, text="Favoritos")
        sf = ttk.Frame(self.nb)
        self.nb.add(sf, text="Buscar")
        sb = ttk.Frame(sf)
        sb.pack(fill="x", pady=2)
        self.search_var = tk.StringVar()
        se = ttk.Entry(sb, textvariable=self.search_var)
        se.pack(side="left", fill="x", expand=True)
        se.bind("<Return>", lambda ev: self.do_search())
        ttk.Button(sb, text="Buscar", command=self.do_search, width=8).pack(side="left", padx=(4, 0))
        self.search_tab = ListTab(sf, [("t", "Resultado", 220), ("c", "Canal", 90), ("d", "Dur.", 50)],
                                  self.play_items, self.enqueue)
        self.search_tab.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>", lambda ev: self.refresh_tabs())

        sbar = ttk.Frame(r, padding=(6, 2))
        sbar.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.st_msg = ttk.Label(sbar, text="Listo. Pega una URL de YouTube.", anchor="w")
        self.st_msg.pack(side="left", fill="x", expand=True)
        self.st_info = ttk.Label(sbar, text="", anchor="e")
        self.st_info.pack(side="right")
        self.chrome = [top, ctl, self.nb, sbar]

        r.bind_all("<Key>", self.on_key)
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_tabs()

    def build_menu(self):
        r = self.root
        mb = tk.Menu(r)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Guardar cola...", command=self.q_save)
        m.add_command(label="Cargar cola...", command=self.q_load)
        m.add_separator()
        m.add_command(label="Descargar video actual", command=self.download_current)
        m.add_command(label="Cancelar descarga", command=self.cancel_download)
        m.add_separator()
        m.add_command(label="Salir", command=self.on_close)
        mb.add_cascade(label="Archivo", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Captura de pantalla (S)", command=self.screenshot)
        m.add_command(label="Subtitulos (C)", command=lambda: self.do_action("sub"))
        m.add_command(label="Solo audio (A)", command=lambda: self.do_action("audio"))
        self.chap_menu = tk.Menu(m, tearoff=0, postcommand=self.fill_chapters)
        m.add_cascade(label="Capitulos", menu=self.chap_menu)
        tm = tk.Menu(m, tearoff=0)
        for label, v in (("15 minutos", 15), ("30 minutos", 30), ("60 minutos", 60),
                         ("Fin del video actual", "end"), ("Desactivar", None)):
            tm.add_command(label=label, command=lambda v=v: self.set_timer(v))
        m.add_cascade(label="Temporizador de apagado", menu=tm)
        mb.add_cascade(label="Reproduccion", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Preferencias...", command=self.prefs_dialog)
        m.add_command(label="Actualizar yt-dlp", command=self.update_ytdlp)
        m.add_command(label="Reiniciar reproductor", command=self.restart_player)
        m.add_command(label="Ver log", command=self.show_log)
        mb.add_cascade(label="Herramientas", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Manual de uso", command=self.show_manual)
        m.add_command(label="Acerca de", command=lambda: messagebox.showinfo(
            APP, "%s %s\nTkinter + mpv + yt-dlp\nConfig: %s" % (APP, VERSION, CFG_DIR)))
        mb.add_cascade(label="Ayuda", menu=m)
        r.config(menu=mb)

    def build_queue_tab(self):
        qf = ttk.Frame(self.nb)
        self.nb.add(qf, text="Cola")
        ff = ttk.Frame(qf)
        ff.pack(fill="x", pady=2)
        ttk.Label(ff, text="Filtrar:").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(ff, textvariable=self.filter_var).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.filter_var.trace_add("write", lambda *a: self.render_queue())
        tf = ttk.Frame(qf)
        tf.pack(fill="both", expand=True)
        self.q_tv = ttk.Treeview(tf, columns=("n", "t", "l"), show="headings", selectmode="extended")
        for cid, title, w, st in (("n", "#", 34, False), ("t", "Titulo", 200, True), ("l", "Lista", 90, False)):
            self.q_tv.heading(cid, text=title)
            self.q_tv.column(cid, width=w, stretch=st, anchor="w")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.q_tv.yview)
        self.q_tv.configure(yscrollcommand=sb.set)
        self.q_tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        for i, c in enumerate(PL_COLORS):
            self.q_tv.tag_configure("pl%d" % i, background=c)
        self.q_tv.tag_configure("playing", background="#cfe8ff", font=self.bold)
        self.q_tv.bind("<Double-1>", lambda e: self.play_selected())
        self.q_tv.bind("<Return>", lambda e: self.play_selected())
        self.q_tv.bind("<Delete>", lambda e: self.q_remove())
        bf = ttk.Frame(qf)
        bf.pack(fill="x", pady=2)
        for txt, cmd, w in (("\u25b2", lambda: self.q_move(-1), 3), ("\u25bc", lambda: self.q_move(1), 3),
                            ("Quitar", self.q_remove, 7), ("Vaciar", self.q_clear, 7),
                            ("Guardar", self.q_save, 8), ("Cargar", self.q_load, 7)):
            ttk.Button(bf, text=txt, command=cmd, width=w).pack(side="left", padx=1)
        self.q_count = ttk.Label(qf, text="0 videos")
        self.q_count.pack(anchor="w")

    # ------------------------------------------------------------ estado / hilos
    def status(self, msg, err=False):
        log.log(logging.ERROR if err else logging.INFO, "%s", msg)
        self.st_msg.config(text=msg, foreground="#b00020" if err else "#000000")

    def post(self, fn):
        self.ui_q.put(fn)

    def bg(self, fn, ok, err=None):
        def work():
            try:
                res = fn()
            except Exception as e:
                log.warning("tarea en segundo plano fallo: %s", e)
                self.post(lambda e=e: (err or (lambda x: self.status(str(x), True)))(e))
                return
            self.post(lambda: ok(res))
        threading.Thread(target=work, daemon=True).start()

    def notify(self, title, body=""):
        if not self.cfg["notify"]:
            return
        if shutil.which("notify-send"):
            try:
                subprocess.Popen(["notify-send", "-a", APP, title, body], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
        self.root.bell()

    def save_cfg(self):
        save_json(F_CFG, self.cfg)

    # ------------------------------------------------------------ bucle principal
    def loop(self):
        if self.quitting:
            return
        try:
            self.n += 1
            self.drain()
            if self.n % 3 == 0:
                self.refresh()
            if self.n % 10 == 0:
                self.watch()
        except Exception:
            log.exception("error en el bucle principal")
        self.root.after(100, self.loop)

    def drain(self):
        while True:
            try:
                f = self.ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                f()
            except Exception:
                log.exception("error en callback de UI")
        while True:
            try:
                ev, m = self.player.evq.get_nowait()
            except queue.Empty:
                break
            try:
                self.on_event(ev, m)
            except Exception:
                log.exception("error manejando evento %s", ev)

    def on_event(self, ev, m):
        P = self.player
        if ev == "ready":
            P.setp("volume", self.cfg["volume"])
            self.apply_runtime()
            if self.crash_resume:
                it, pos = self.crash_resume
                self.crash_resume = None
                self.play_item(it, seek=pos, retry=True)
            elif self.deferred:
                fn, self.deferred = self.deferred, None
                fn()
            else:
                self.status("Listo.")
        elif ev == "start-file":
            self.loading = True
        elif ev == "file-loaded":
            self.loading = False
            self.loaded = True
            self.loaded_at = time.time()
            self.err_streak = 0
            P.setp("pause", False)
            if self.pending_seek and self.pending_seek > 3:
                P.cmd("seek", float(self.pending_seek), "absolute")
                self.status("Retomando desde %s" % fmt_time(self.pending_seek))
            else:
                self.status("Reproduciendo")
            self.pending_seek = None
            if self.cur:
                self.hist_touch(self.cur)
        elif ev == "end-file":
            r = m.get("reason")
            if r == "eof":
                self.on_eof()
            elif r == "error":
                self.on_play_error(m.get("file_error"))
        elif ev == "client-message":
            a = m.get("args") or []
            if len(a) >= 2 and a[0] == "ytl":
                self.do_action(a[1])
        elif ev == "reply":
            m["cb"](m["msg"])
        elif ev == "ipc_fail":
            if not self.quitting:
                self.handle_crash("no pude conectar con mpv (IPC)")

    def watch(self):
        """Cada ~1 s: salud del reproductor, historial, temporizador, autoguardado."""
        p = self.player.proc
        if p is not None and p.poll() is not None and not self.quitting:
            self.handle_crash("mpv termino (codigo %s)" % p.returncode)
        if self.loaded and not self.live and self.cur:
            self.hist_touch(self.cur, self.last_pos)
        if self.timer_at and time.time() >= self.timer_at:
            self.timer_at = None
            self.timer_trigger()
        if time.time() - self.last_flush > 60:
            self.last_flush = time.time()
            if self.hist_dirty:
                self.save_history()
            if self.q_dirty:
                self.save_queue()

    # ------------------------------------------------------------ reproductor
    def start_player(self):
        try:
            self.root.update_idletasks()
            self.player.start(self.video.winfo_id(), self.cfg)
        except Exception as e:
            self.status("No pude iniciar mpv: %s" % e, True)

    def restart_player(self):
        it = self.cur if (self.loaded or self.loading) else None
        pos = self.last_pos
        self.loaded = self.loading = False
        self.start_player()
        if it:
            self.crash_resume = (it, max(0, pos - 2))
        self.status("Reproductor reiniciado")

    def handle_crash(self, reason):
        log.error("Reproductor caido: %s | ultimas lineas: %s", reason, " / ".join(self.player.err_tail))
        was = self.cur if (self.loaded or self.loading) else None
        pos = self.last_pos
        self.loaded = self.loading = False
        if self.restarts >= 3:
            self.player.stop()
            self.gave_up = True
            self.status("El reproductor se cayo 3 veces seguidas; me rindo. Mira Herramientas > Ver log.", True)
            return
        self.restarts += 1
        self.status("Reproductor caido (%s); relanzando (%d/3)..." % (reason, self.restarts), True)
        self.start_player()
        if was:
            self.crash_resume = (was, max(0, pos - 3))

    def apply_runtime(self):
        self.player.setp("af", "lavfi=[loudnorm=I=-16:TP=-1.5:LRA=11]" if self.cfg["loudnorm"] else "")

    def cur_index(self):
        for i, it in enumerate(self.queue):
            if it is self.cur:
                return i
        return -1

    def height_for(self, q):
        h = int(q[:-1])
        return min(h, 480) if self.cfg["conservative"] else h

    def resume_point(self, it):
        h = self.history.get(it["url"])
        if h and h.get("pos", 0) > 10 and (h.get("dur") or 0) - h["pos"] > 20:
            return max(0, h["pos"] - 2)
        return None

    def play_item(self, it, seek=None, retry=False):
        if it is None:
            return
        if self.player.proc is None or self.player.proc.poll() is not None:
            self.start_player()
        self.gave_up = False
        self.cur = it
        self.loaded = False
        self.loading = True
        self.live = False
        self.chapters = []
        self.player.last_error = ""
        if not retry:
            self.restarts = 0
        self.pending_seek = seek if seek is not None else self.resume_point(it)
        self.restart_pos = self.pending_seek or 0
        self.last_pos = self.pending_seek or 0
        self.render_queue()
        self.status("Cargando: %s" % (it["title"] or it["url"]))
        self.update_title()
        self.load_gen += 1
        gen = self.load_gen
        q = self.cfg["quality"]
        if q == "Auto" and not self.audio_var.get():
            c = self.speed_cache
            if c and time.time() - c[0] < 600:
                self.begin_load(it, auto_height(c[1], 480 if self.cfg["conservative"] else 1080), gen)
            else:
                self.status("Midiendo la conexion...")
                self.bg(measure_mbps, lambda m: self.after_measure(it, m, gen), lambda e: None)
        else:
            self.begin_load(it, self.height_for(q if q != "Auto" else "480p"), gen)

    def after_measure(self, it, mbps, gen):
        if gen != self.load_gen:
            return
        cap = 480 if self.cfg["conservative"] else 1080
        if mbps:
            self.speed_cache = (time.time(), mbps)
            h = auto_height(mbps, cap)
            self.status("Conexion ~%.1f Mbps -> %dp" % (mbps, h))
        else:
            h = 480
            self.status("No pude medir la conexion; uso 480p")
        self.begin_load(it, h, gen)

    def begin_load(self, it, height, gen):
        if gen != self.load_gen:
            return
        if not find_ytdlp():
            self.loading = False
            self.status("yt-dlp no esta instalado: Herramientas > Actualizar yt-dlp", True)
            return
        audio = self.audio_var.get()
        fmt = build_format(height, audio)
        self.loaded_audio_fmt = audio
        self.req_height = height

        def go():
            P = self.player
            P.setp("ytdl-format", fmt)
            P.setp("vid", "auto")
            P.setp("pause", False)
            P.cmd("loadfile", it["url"], "replace")
        if self.player.ready:
            go()
        else:
            self.deferred = go

    def on_eof(self):
        self.loaded = False
        if self.cur:
            self.hist_touch(self.cur, 0)
        if self.timer_end:
            self.timer_end = False
            self.timer_trigger()
            return
        self.next_item(True)

    def on_play_error(self, file_error):
        was_loaded = self.loaded
        self.loaded = self.loading = False
        msg = self.player.last_error or file_error or "error desconocido"
        if was_loaded and self.last_pos > 5 and self.restarts < 3 and self.cur:
            self.restarts += 1
            self.status("Se corto la reproduccion (%s); reintento %d/3" % (msg[:80], self.restarts), True)
            self.play_item(self.cur, seek=max(0, self.last_pos - 3), retry=True)
            return
        self.err_streak += 1
        self.status("Error: %s  (si es de YouTube: Herramientas > Actualizar yt-dlp)" % msg[:140], True)
        idx = self.cur_index()
        if self.err_streak < 3 and 0 <= idx < len(self.queue) - 1:
            self.root.after(1500, lambda: self.next_item(True) if not self.loaded and not self.loading else None)

    def next_item(self, auto):
        idx = self.cur_index() + 1
        if idx < len(self.queue):
            self.play_item(self.queue[idx])
        elif auto:
            self.loaded = self.loading = False
            self.status("Cola terminada")
            self.notify("Cola terminada", "No quedan mas videos")
        else:
            self.status("No hay mas videos en la cola")

    def prev_item(self):
        idx = self.cur_index() - 1
        if idx >= 0:
            self.play_item(self.queue[idx])
        else:
            self.status("Ya estas en el primero")

    def play_current_or_selected(self):
        sel = self.q_sel()
        if sel:
            self.play_item(self.queue[sel[0]])
        elif self.cur:
            self.play_item(self.cur)
        elif self.queue:
            self.play_item(self.queue[0])
        else:
            self.status("La cola esta vacia: pega una URL")

    def toggle_pause(self):
        if self.loaded:
            self.player.cmd("cycle", "pause")
        elif self.loading:
            self.player.setp("pause", False)
        else:
            self.play_current_or_selected()

    # ------------------------------------------------------------ acciones / teclas
    def on_key(self, e):
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return
        shift = bool(e.state & 1)
        for _, ks, sh, act in KEYS:
            if e.keysym == ks and (bool(sh) == shift or ks not in ("Left", "Right")):
                if isinstance(w, ttk.Treeview) and ks in ("Up", "Down", "space", "Prior", "Next"):
                    return
                self.do_action(act)
                return

    def do_action(self, a):
        name, _, arg = a.partition(":")
        P = self.player
        if name in ("pause", "click"):
            self.toggle_pause()
        elif name == "seek":
            if self.loaded and not self.live:
                P.cmd("seek", float(arg), "relative")
        elif name == "vol":
            P.cmd("add", "volume", float(arg))
        elif name == "mute":
            P.cmd("cycle", "mute")
        elif name == "fs":
            self.set_fullscreen(not self.fullscreen)
        elif name == "fs_off":
            self.set_fullscreen(False)
        elif name == "next":
            self.next_item(False)
        elif name == "prev":
            self.prev_item()
        elif name == "speed":
            self.step_speed(1 if arg == "up" else -1)
        elif name == "shot":
            self.screenshot()
        elif name == "audio":
            self.audio_var.set(not self.audio_var.get())
            self.on_audio_toggle()
        elif name == "sub":
            P.cmd("cycle", "sub")
            P.cmd("show-text", "Subtitulos: ${sid}", 1500)
        elif name == "chap":
            P.cmd("add", "chapter", int(arg))
        elif name == "fav":
            self.toggle_fav()

    def set_fullscreen(self, on):
        if on == self.fullscreen:
            return
        self.fullscreen = on
        if on:
            for w in self.chrome:
                w.grid_remove()
            self.video.grid_configure(columnspan=2)
        else:
            self.video.grid_configure(columnspan=1)
            for w in self.chrome:
                w.grid()
        self.root.attributes("-fullscreen", on)

    def step_speed(self, d):
        cur = self.player.props.get("speed") or 1.0
        i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - cur))
        i = max(0, min(len(SPEEDS) - 1, i + d))
        self.player.setp("speed", SPEEDS[i])

    def on_speed_sel(self, e):
        try:
            self.player.setp("speed", float(self.speed_var.get().rstrip("x")))
        except ValueError:
            pass
        self.root.focus_set()

    def on_vol(self, v):
        if not self._ui_upd:
            self.player.setp("volume", float(v))

    def on_quality(self, e):
        self.cfg["quality"] = self.q_var.get()
        self.save_cfg()
        self.root.focus_set()
        if self.cur and (self.loaded or self.loading) and not self.audio_var.get():
            self.play_item(self.cur, seek=self.last_pos, retry=True)

    def on_audio_toggle(self):
        on = self.audio_var.get()
        self.cfg["audio_only"] = on
        self.save_cfg()
        if not (self.loaded or self.loading):
            self.status("Modo solo audio: " + ("activado" if on else "desactivado"))
            return
        if on:
            self.player.setp("vid", "no")
            self.status("Solo audio activado")
        elif self.loaded_audio_fmt:
            self.play_item(self.cur, seek=self.last_pos, retry=True)
        else:
            self.player.setp("vid", "auto")
            self.status("Video reactivado")

    def screenshot(self):
        if not self.loaded:
            self.status("No hay nada que capturar", True)
            return
        if self.audio_var.get():
            self.status("En modo solo audio no hay imagen para capturar", True)
            return
        d = self.cfg["shot_dir"]
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            self.status("No pude crear %s: %s" % (d, e), True)
            return
        path = os.path.join(d, "ytlite_%s.jpg" % time.strftime("%Y%m%d_%H%M%S"))

        def cb(m):
            if m.get("error") == "success":
                self.status("Captura guardada: " + path)
            else:
                self.status("No pude capturar: %s" % m.get("error"), True)
        self.player.cmd("screenshot-to-file", path, "video", cb=cb)

    def fill_chapters(self):
        m = self.chap_menu
        m.delete(0, "end")
        ch = self.player.props.get("chapter-list") or []
        if not ch:
            m.add_command(label="(este video no tiene capitulos)", state="disabled")
            return
        for i, c in enumerate(ch[:80]):
            m.add_command(label="%s  %s" % (fmt_time(c.get("time")), (c.get("title") or "")[:50]),
                          command=lambda i=i: self.player.setp("chapter", i))

    # ------------------------------------------------------------ barra de progreso
    def draw_progress(self, frac, dur, live):
        c = self.pbar
        w, h = c.winfo_width(), c.winfo_height()
        key = (w, int(frac * w) if w else 0, live, len(self.chapters))
        if key == self._pkey:
            return
        self._pkey = key
        c.delete("all")
        y = h // 2
        c.create_rectangle(0, y - 3, w, y + 3, fill="#555", outline="")
        if live:
            c.create_rectangle(0, y - 3, w, y + 3, fill="#b33", outline="")
            c.create_text(w // 2, y, text="EN VIVO", fill="white")
            return
        x = int(frac * w)
        c.create_rectangle(0, y - 3, x, y + 3, fill="#3a8", outline="")
        if dur:
            for ch in self.chapters:
                t = ch.get("time")
                if t:
                    cx = int(t / dur * w)
                    c.create_line(cx, y - 5, cx, y + 5, fill="#ddd")
        c.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#fff", outline="")

    def _pb_frac(self, e):
        w = max(1, self.pbar.winfo_width())
        return max(0.0, min(1.0, e.x / float(w)))

    def pb_press(self, e):
        if self.live or not self.loaded or not self.player.props.get("duration"):
            return
        self.dragging = True
        self.pb_motion(e)

    def pb_motion(self, e):
        if not self.dragging:
            return
        f = self._pb_frac(e)
        dur = self.player.props.get("duration") or 0
        self._frac = f
        self.draw_progress(f, dur, False)
        self.lbl_pos.config(text=fmt_time(f * dur))

    def pb_release(self, e):
        if not self.dragging:
            return
        self.dragging = False
        dur = self.player.props.get("duration")
        if dur:
            t = self._pb_frac(e) * dur
            self.last_pos = t
            self.player.cmd("seek", float(t), "absolute")

    # ------------------------------------------------------------ refresco de la UI
    def refresh(self):
        pr = self.player.props
        pos, dur = pr.get("time-pos"), pr.get("duration")
        if self.loaded and isinstance(pos, (int, float)):
            self.last_pos = pos
            if self.restarts and pos > self.restart_pos + 45:
                self.restarts = 0
        self.live = bool(self.loaded and pos is not None and dur is None and time.time() - self.loaded_at > 3)
        cur = self.cur
        mt = pr.get("media-title")
        if cur and self.loaded and isinstance(mt, str) and mt and not mt.startswith("http") and not cur["title"]:
            cur["title"] = mt
            self.update_row(cur)
            self.update_title()
        if not self.dragging:
            self._frac = (pos / dur) if (isinstance(pos, (int, float)) and dur) else 0.0
            self._dur_v = dur
            self.draw_progress(self._frac, dur, self.live)
            self.lbl_pos.config(text=fmt_time(pos))
        self.chapters = pr.get("chapter-list") or []
        self.lbl_dur.config(text="--:--" if self.live else fmt_time(dur))
        paused = pr.get("pause")
        self.btn_play.config(text=">" if (paused or not self.loaded) else "||")
        v = pr.get("volume")
        if isinstance(v, (int, float)) and abs(self.vol.get() - min(v, 100)) > 1:
            self._ui_upd = True
            self.vol.set(min(v, 100))
            self._ui_upd = False
        self.btn_mute.config(text="Mudo*" if pr.get("mute") else "Mudo")
        sp = pr.get("speed")
        if isinstance(sp, (int, float)):
            s = "%gx" % sp
            if self.speed_var.get() != s:
                self.speed_var.set(s)
        fav = bool(cur and any(f["url"] == cur["url"] for f in self.favs))
        if fav != self._fav_state:
            self._fav_state = fav
            self.btn_fav.config(text="\u2605" if fav else "\u2606")
        info = []
        if pr.get("paused-for-cache"):
            info.append("BUFFERING")
        if self.audio_var.get():
            info.append("solo audio")
        elif pr.get("video-params/h"):
            info.append("%sp" % pr["video-params/h"])
        cd = pr.get("demuxer-cache-duration")
        if self.loaded and isinstance(cd, (int, float)):
            info.append("buf %ds" % cd)
        if self.timer_at:
            info.append("apagado en %s" % fmt_time(self.timer_at - time.time()))
        elif self.timer_end:
            info.append("apagado al fin del video")
        if self.dl_proc:
            info.append("descargando")
        self.st_info.config(text="  |  ".join(info))

    def update_title(self):
        t = (self.cur["title"] or self.cur["url"]) if self.cur else ""
        if t != self._shown_title:
            self._shown_title = t
            self.root.title("%s - %s" % (t, APP) if t else APP)

    # ------------------------------------------------------------ URLs y colas
    def on_play_click(self):
        raw = self.url_var.get().strip()
        if not raw:
            self.play_current_or_selected()
        elif self.handle_url(raw, play=True):
            self.url_var.set("")

    def on_enqueue_click(self):
        raw = self.url_var.get().strip()
        if raw and self.handle_url(raw, play=False):
            self.url_var.set("")

    def on_playlist_click(self):
        raw = self.url_var.get().strip()
        if raw and self.handle_url(raw, play=True, force_playlist=True):
            self.url_var.set("")

    def on_paste_click(self):
        try:
            txt = self.root.clipboard_get().strip()
        except tk.TclError:
            self.status("El portapapeles esta vacio", True)
            return
        self.url_var.set(txt)
        self.on_play_click()

    def handle_url(self, raw, play, force_playlist=False):
        kind, url, lst = parse_url(raw)
        if kind == "invalid":
            self.status("URL invalida: pega un enlace de video o playlist de YouTube "
                        "(para buscar usa la pestana Buscar)", True)
            return False
        if force_playlist:
            if not lst:
                self.status("Esa URL no contiene una playlist", True)
                return False
            self.load_playlist("https://www.youtube.com/playlist?list=" + lst, lst, play)
            return True
        if kind == "video_list":
            self.status("La URL incluye una playlist: tomo solo el video (boton Playlist para toda la lista)")
            kind = "video"
        if kind == "playlist":
            if not messagebox.askyesno(APP, "Esa URL es una playlist.\n\nAgregar todos sus videos a la cola"
                                       + (" y reproducirla?" if play else "?")):
                self.status("Cancelado")
                return False
            self.load_playlist(url, lst, play)
            return True
        it = mk_item(url)
        if play:
            self.play_items([it])
        else:
            self.enqueue([it])
        return True

    def load_playlist(self, url, lst, play):
        self.status("Leyendo la playlist...")

        def ok(items):
            if not items:
                self.status("La playlist esta vacia o no es accesible (privada?)", True)
                return
            first = len(self.queue)
            self.queue.extend(items)
            self.q_dirty = True
            self.render_queue()
            self.status("%d videos agregados desde la playlist" % len(items))
            if play:
                self.play_item(self.queue[first])
        self.bg(lambda: fetch_playlist(url, lst, int(self.cfg["max_playlist"])), ok)

    def play_items(self, items):
        if not items:
            return
        new = [dict(i) for i in items]
        idx = self.cur_index()
        pos = idx + 1 if idx >= 0 else len(self.queue)
        self.queue[pos:pos] = new
        self.q_dirty = True
        self.play_item(new[0])
        for it in new:
            if not it.get("title"):
                self.title_q.put(it)

    def enqueue(self, items):
        if not items:
            return
        new = [dict(i) for i in items]
        self.queue.extend(new)
        self.q_dirty = True
        self.render_queue()
        for it in new:
            if not it.get("title"):
                self.title_q.put(it)
        self.status("%d agregado(s) a la cola" % len(new))

    def title_loop(self):
        while True:
            it = self.title_q.get()
            if it is None:
                return
            if it.get("title"):
                continue
            try:
                out = run_ytdlp(["--no-playlist", "--print", "%(title)s\t%(duration)s", it["url"]],
                                timeout=60, low=True)
                p = out.strip().splitlines()[0].split("\t")
                t, d = (p[0], to_float(p[-1])) if len(p) > 1 else (p[0], None)
                self.post(lambda it=it, t=t, d=d: self.set_title(it, t, d))
            except Exception as e:
                log.info("no pude obtener el titulo de %s: %s", it["url"], e)
            time.sleep(0.5)

    def set_title(self, it, title, dur):
        it["title"] = title
        it["duration"] = dur
        self.update_row(it)
        self.update_title()

    # ------------------------------------------------------------ cola (vista)
    def pl_idx(self, name):
        return self.pl_map.setdefault(name, len(self.pl_map)) % len(PL_COLORS)

    def render_queue(self):
        tv = self.q_tv
        flt = self.filter_var.get().strip().lower()
        tv.delete(*tv.get_children())
        for i, it in enumerate(self.queue):
            title = it["title"] or it["url"]
            if flt and flt not in title.lower() and flt not in (it.get("playlist") or "").lower():
                continue
            playing = it is self.cur
            tags = ("playing",) if playing else (("pl%d" % self.pl_idx(it["playlist"]),) if it.get("playlist") else ())
            tv.insert("", "end", iid=str(i), tags=tags,
                      values=(i + 1, ("> " if playing else "") + title, it.get("playlist") or ""))
        idx = self.cur_index()
        if idx >= 0 and tv.exists(str(idx)):
            tv.see(str(idx))
        self.q_count.config(text="%d videos en la cola" % len(self.queue))

    def update_row(self, it):
        idx = self.cur_index() if it is self.cur else next((i for i, x in enumerate(self.queue) if x is it), -1)
        if idx >= 0 and self.q_tv.exists(str(idx)):
            self.q_tv.set(str(idx), "t", ("> " if it is self.cur else "") + (it["title"] or it["url"]))

    def q_sel(self):
        return sorted(int(i) for i in self.q_tv.selection())

    def play_selected(self):
        sel = self.q_sel()
        if sel:
            self.play_item(self.queue[sel[0]])

    def q_remove(self):
        sel = self.q_sel()
        if not sel:
            return
        S = set(sel)
        self.queue = [it for i, it in enumerate(self.queue) if i not in S]
        self.q_dirty = True
        self.render_queue()

    def q_clear(self):
        if self.queue and messagebox.askyesno(APP, "Vaciar toda la cola?"):
            self.queue = []
            self.q_dirty = True
            self.render_queue()

    def q_move(self, d):
        if self.filter_var.get().strip():
            self.status("Quita el filtro para reordenar la cola", True)
            return
        sel = sorted(self.q_sel(), reverse=(d > 0))
        S = set(sel)
        n = len(self.queue)
        for i in sel:
            j = i + d
            if 0 <= j < n and j not in S:
                self.queue[i], self.queue[j] = self.queue[j], self.queue[i]
                S.discard(i)
                S.add(j)
        self.q_dirty = True
        self.render_queue()
        for i in S:
            if self.q_tv.exists(str(i)):
                self.q_tv.selection_add(str(i))

    def q_save(self):
        f = filedialog.asksaveasfilename(defaultextension=".json", initialfile="cola.json",
                                         filetypes=[("Cola YTLite", "*.json")])
        if f and save_json(f, {"version": 1, "items": self.queue}):
            self.status("Cola guardada en " + f)

    def q_load(self):
        f = filedialog.askopenfilename(filetypes=[("Cola YTLite", "*.json"), ("Todos", "*")])
        if not f:
            return
        data = load_json(f, None)
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            self.status("Archivo de cola invalido", True)
            return
        items = [mk_item(i["url"], i.get("title", ""), i.get("playlist", ""), i.get("duration"))
                 for i in items if isinstance(i, dict) and isinstance(i.get("url"), str)]
        if not items:
            self.status("El archivo no contiene videos", True)
            return
        if self.queue:
            ans = messagebox.askyesnocancel(APP, "Reemplazar la cola actual?\n\nSi = reemplazar, No = agregar al final")
            if ans is None:
                return
            self.queue = items if ans else self.queue + items
        else:
            self.queue = items
        for it in items:
            if not it["title"]:
                self.title_q.put(it)
        self.q_dirty = True
        self.render_queue()
        self.status("%d videos cargados" % len(items))

    # ------------------------------------------------------------ historial / favoritos / busqueda
    def hist_touch(self, it, pos=None):
        h = self.history.setdefault(it["url"], {"url": it["url"], "title": it["title"], "pos": 0, "dur": 0, "ts": 0})
        if it["title"]:
            h["title"] = it["title"]
        h["ts"] = time.time()
        if pos is not None:
            h["pos"] = pos
        d = self.player.props.get("duration")
        if d:
            h["dur"] = d
        self.hist_dirty = True

    def refresh_tabs(self):
        rows = []
        for h in sorted(self.history.values(), key=lambda x: -x.get("ts", 0))[:300]:
            rows.append((mk_item(h["url"], h.get("title", "")),
                         (h.get("title") or h["url"], "%s / %s" % (fmt_time(h.get("pos")), fmt_time(h.get("dur"))),
                          time.strftime("%d/%m %H:%M", time.localtime(h.get("ts", 0))))))
        self.hist_tab.set_rows(rows)
        self.fav_tab.set_rows([(f, (f.get("title") or f["url"], fmt_time(f.get("duration")))) for f in self.favs])

    def hist_remove(self, items):
        for it in items:
            self.history.pop(it["url"], None)
        self.hist_dirty = True
        self.refresh_tabs()

    def hist_clear(self, _items):
        if self.history and messagebox.askyesno(APP, "Borrar todo el historial?"):
            self.history = {}
            self.hist_dirty = True
            self.refresh_tabs()

    def toggle_fav(self):
        if not self.cur:
            self.status("No hay un video actual", True)
            return
        u = self.cur["url"]
        if any(f["url"] == u for f in self.favs):
            self.favs = [f for f in self.favs if f["url"] != u]
            self.status("Quitado de favoritos")
        else:
            self.favs.append(mk_item(u, self.cur["title"], "", self.cur.get("duration")))
            self.status("Agregado a favoritos")
        save_json(F_FAV, self.favs)
        self.refresh_tabs()

    def fav_remove(self, items):
        urls = set(i["url"] for i in items)
        self.favs = [f for f in self.favs if f["url"] not in urls]
        save_json(F_FAV, self.favs)
        self.refresh_tabs()

    def do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.status("Buscando '%s'..." % q)

        def ok(res):
            if not res:
                self.status("Sin resultados para '%s'" % q, True)
            else:
                self.status("%d resultados" % len(res))
            self.search_tab.set_rows([(r, (r["title"], r.get("channel", ""), fmt_time(r.get("duration"))))
                                      for r in res])
        self.bg(lambda: fetch_search(q), ok)

    # ------------------------------------------------------------ persistencia
    def save_history(self):
        if len(self.history) > 500:
            keep = sorted(self.history.items(), key=lambda kv: -kv[1].get("ts", 0))[:500]
            self.history = dict(keep)
        if save_json(F_HIST, self.history):
            self.hist_dirty = False

    def save_queue(self):
        if save_json(F_QUEUE, {"items": self.queue, "cur": self.cur_index()}):
            self.q_dirty = False

    def restore_queue(self):
        d = load_json(F_QUEUE, {})
        items = d.get("items") if isinstance(d, dict) else None
        if not items:
            return
        self.queue = [mk_item(i["url"], i.get("title", ""), i.get("playlist", ""), i.get("duration"))
                      for i in items if isinstance(i, dict) and isinstance(i.get("url"), str)]
        c = d.get("cur", -1)
        if isinstance(c, int) and 0 <= c < len(self.queue):
            self.cur = self.queue[c]
        self.render_queue()
        self.update_title()
        self.status("Cola restaurada (%d videos). Pulsa Reproducir para continuar." % len(self.queue))

    def save_all(self):
        v = self.player.props.get("volume")
        if isinstance(v, (int, float)):
            self.cfg["volume"] = int(min(v, 100))
        if not self.fullscreen:
            self.cfg["geometry"] = "%dx%d" % (self.root.winfo_width(), self.root.winfo_height())
        if self.loaded and not self.live and self.cur:
            self.hist_touch(self.cur, self.last_pos)
        self.save_cfg()
        self.save_queue()
        self.save_history()

    def on_close(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            self.save_all()
        except Exception:
            log.exception("error al guardar el estado")
        self.title_q.put(None)
        if self.dl_proc:
            try:
                self.dl_proc.terminate()
            except Exception:
                pass
        self.player.cleanup()
        self.root.destroy()

    # ------------------------------------------------------------ descargas
    def download_current(self):
        it = self.cur
        if not it:
            self.status("No hay un video actual para descargar", True)
            return
        if self.dl_proc:
            self.status("Ya hay una descarga en curso", True)
            return
        exe = find_ytdlp()
        if not exe:
            self.status("yt-dlp no esta instalado: Herramientas > Actualizar yt-dlp", True)
            return
        d = self.cfg["dl_dir"]
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            self.status("No pude crear %s: %s" % (d, e), True)
            return
        q = self.cfg["quality"]
        h = 720 if q == "Auto" else int(q[:-1])
        if self.audio_var.get():
            fmt, extra = "bestaudio[ext=m4a]/bestaudio", []
        elif shutil.which("ffmpeg"):
            fmt = ("bv*[height<=%d][vcodec^=avc1]+ba[ext=m4a]/b[height<=%d][ext=mp4]/b[height<=%d]/b" % (h, h, h))
            extra = ["--merge-output-format", "mp4"]
        else:
            fmt, extra = "b[height<=%d][ext=mp4]/b[height<=%d]/b" % (h, h), []
        cmd = [exe, "--no-playlist", "--newline", "--no-warnings", "-f", fmt, "-o",
               os.path.join(d, "%(title).120s [%(id)s].%(ext)s")] + extra
        if self.cfg["dl_rate"].strip():
            cmd += ["--limit-rate", self.cfg["dl_rate"].strip()]
        cmd.append(it["url"])
        cmd = lowprio(cmd)
        self.status("Descargando (prioridad baja)...")

        def work():
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                                     encoding="utf-8", errors="replace")
                self.dl_proc = p
                tail = collections.deque(maxlen=5)
                last = 0
                for line in p.stdout:
                    tail.append(line.strip())
                    m = re.search(r"(\d+(?:\.\d+)?)%", line)
                    if m and time.time() - last > 1.5:
                        last = time.time()
                        self.post(lambda pc=m.group(1): self.status("Descargando %s%%" % pc))
                rc = p.wait()
                if rc == 0:
                    self.post(lambda: (self.status("Descarga lista en " + d), self.notify("Descarga lista", d)))
                else:
                    self.post(lambda: self.status("La descarga fallo: " + str(tail[-1] if tail else rc)[:150], True))
            except Exception as e:
                self.post(lambda e=e: self.status("La descarga fallo: %s" % e, True))
            finally:
                self.dl_proc = None
        threading.Thread(target=work, daemon=True).start()

    def cancel_download(self):
        if self.dl_proc:
            try:
                self.dl_proc.terminate()
                self.status("Descarga cancelada")
            except Exception:
                pass
        else:
            self.status("No hay descarga en curso")

    # ------------------------------------------------------------ yt-dlp
    def update_ytdlp(self):
        self.status("Descargando la ultima version de yt-dlp...")

        def work():
            url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
            os.makedirs(os.path.dirname(LOCAL_YTDLP), exist_ok=True)
            tmp = LOCAL_YTDLP + ".new"
            with urlopen(Request(url, headers={"User-Agent": "ytlite"}), timeout=30) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            os.chmod(tmp, 0o755)
            v = subprocess.run([tmp, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=90)
            if v.returncode != 0:
                os.unlink(tmp)
                raise RuntimeError("El yt-dlp descargado no funciona: " + v.stderr.strip()[-120:])
            os.replace(tmp, LOCAL_YTDLP)
            return v.stdout.strip()

        def ok(ver):
            self.status("yt-dlp actualizado a %s (en %s)" % (ver, LOCAL_YTDLP))
            self.restart_player()
        self.bg(work, ok, lambda e: self.status("No pude actualizar yt-dlp: %s" % e, True))

    # ------------------------------------------------------------ temporizador
    def set_timer(self, mode):
        self.timer_at = None
        self.timer_end = False
        if mode is None:
            self.status("Temporizador desactivado")
        elif mode == "end":
            self.timer_end = True
            self.status("Se apagara al terminar el video actual")
        else:
            self.timer_at = time.time() + mode * 60
            self.status("Temporizador: %d minutos" % mode)

    def timer_trigger(self):
        self.player.setp("pause", True)
        top = tk.Toplevel(self.root)
        top.title("Temporizador")
        top.transient(self.root)
        top.resizable(False, False)
        lbl = ttk.Label(top, padding=20)
        lbl.pack()
        st = {"n": 30, "on": True}

        def cancel():
            st["on"] = False
            top.destroy()
            self.status("Temporizador cancelado")

        def tick():
            if not st["on"] or self.quitting:
                return
            if st["n"] <= 0:
                top.destroy()
                self.timer_fire()
                return
            lbl.config(text="%s en %d s" % ("Apagando el equipo" if self.cfg["timer_action"] == "poweroff"
                                            else "Cerrando la app", st["n"]))
            st["n"] -= 1
            top.after(1000, tick)
        ttk.Button(top, text="Cancelar", command=cancel).pack(pady=(0, 12))
        top.protocol("WM_DELETE_WINDOW", cancel)
        tick()

    def timer_fire(self):
        log.info("Temporizador vencido: %s", self.cfg["timer_action"])
        self.save_all()
        if self.cfg["timer_action"] == "poweroff":
            try:
                subprocess.Popen(["sh", "-c", self.cfg["shutdown_cmd"]])
            except OSError as e:
                log.error("no pude apagar: %s", e)
        self.on_close()

    # ------------------------------------------------------------ dialogos
    def prefs_dialog(self):
        spec = [
            ("conservative", "bool", "Modo conservador (max. 480p, H.264, decodificacion rapida)"),
            ("loudnorm", "bool", "Normalizar volumen (loudnorm; usa algo mas de CPU)"),
            ("subs", "bool", "Cargar subtitulos disponibles"),
            ("sub_langs", "str", "Idiomas de subtitulos (regex yt-dlp)"),
            ("cache_mb", "int", "Bufer en RAM hacia adelante (MiB)"),
            ("back_cache_mb", "int", "Bufer en RAM hacia atras (MiB)"),
            ("vo", "str", "Salida de video (auto, xv, x11, gpu)"),
            ("shot_dir", "dir", "Carpeta de capturas"),
            ("dl_dir", "dir", "Carpeta de descargas"),
            ("max_playlist", "int", "Maximo de videos por playlist"),
            ("dl_rate", "str", "Limite de descarga (ej. 500K; vacio = sin limite)"),
            ("timer_action", "choice", "Al vencer el temporizador"),
            ("shutdown_cmd", "str", "Comando de apagado"),
            ("notify", "bool", "Notificar al terminar la cola"),
        ]
        top = tk.Toplevel(self.root)
        top.title("Preferencias")
        top.transient(self.root)
        top.grab_set()
        fr = ttk.Frame(top, padding=10)
        fr.pack(fill="both", expand=True)
        vars_ = {}
        for r, (key, kind, label) in enumerate(spec):
            if kind == "bool":
                v = tk.BooleanVar(value=bool(self.cfg[key]))
                ttk.Checkbutton(fr, text=label, variable=v).grid(row=r, column=0, columnspan=3, sticky="w", pady=1)
            else:
                v = tk.StringVar(value=str(self.cfg[key]))
                ttk.Label(fr, text=label).grid(row=r, column=0, sticky="w", pady=1, padx=(0, 8))
                if kind == "choice":
                    ttk.Combobox(fr, textvariable=v, values=["poweroff", "quit"], state="readonly",
                                 width=12).grid(row=r, column=1, sticky="w")
                else:
                    ttk.Entry(fr, textvariable=v, width=34).grid(row=r, column=1, sticky="ew")
                    if kind == "dir":
                        ttk.Button(fr, text="...", width=3, command=lambda v=v: v.set(
                            filedialog.askdirectory(initialdir=v.get(), parent=top) or v.get())).grid(row=r, column=2)
            vars_[key] = (kind, v)

        def save():
            new = {}
            for key, (kind, v) in vars_.items():
                val = v.get()
                if kind == "int":
                    try:
                        val = max(1, int(val))
                    except ValueError:
                        messagebox.showerror(APP, "Valor numerico invalido en: " + key, parent=top)
                        return
                new[key] = val
            restart = any(new[k] != self.cfg[k] for k in RESTART_KEYS)
            self.cfg.update(new)
            self.save_cfg()
            top.destroy()
            if restart:
                self.restart_player()
            else:
                self.apply_runtime()
                self.status("Preferencias guardadas")
        bf = ttk.Frame(fr)
        bf.grid(row=len(spec), column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="Cancelar", command=top.destroy).pack(side="right", padx=4)
        ttk.Button(bf, text="Guardar", command=save).pack(side="right")

    def text_window(self, title, content, refresh=None):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry("720x520")
        fr = ttk.Frame(top)
        fr.pack(fill="both", expand=True)
        t = tk.Text(fr, wrap="word", font="TkFixedFont")
        sb = ttk.Scrollbar(fr, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)

        def fill(txt):
            t.config(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", txt)
            t.config(state="disabled")
            t.see("end" if refresh else "1.0")
        fill(content)
        if refresh:
            bf = ttk.Frame(top)
            bf.pack(fill="x")
            ttk.Button(bf, text="Actualizar", command=lambda: fill(refresh())).pack(side="left", padx=4, pady=4)
            ttk.Button(bf, text="Copiar", command=lambda: (self.root.clipboard_clear(),
                                                           self.root.clipboard_append(refresh()))).pack(side="left")

    def show_manual(self):
        self.text_window("Manual de uso - " + APP, MANUAL)

    def show_log(self):
        self.text_window("Log de diagnostico", "\n".join(LOG), refresh=lambda: "\n".join(LOG))


def main():
    root = tk.Tk()
    App(root, sys.argv[1:])
    root.mainloop()


if __name__ == "__main__":
    main()
