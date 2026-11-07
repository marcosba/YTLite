# YTLite

[English](README.md) | **Español**

Reproductor de YouTube de una sola ventana para hardware viejo (pensado y apuntado a un ThinkPad T60p con antiX Linux). Sin navegador, sin frameworks pesados: **Python + Tkinter** para la interfaz, **mpv** para reproducir y **yt-dlp** para extraer el video.

El video empieza a verse a los pocos segundos de pegar la URL y el búfer vive en **RAM**, no en disco, para no martillar un disco mecánico lento.

> **Estado:** el reproductor, el control por IPC, la recuperación de caídas, las capturas y la persistencia de cola/historial fueron probados con mpv real sobre un video local en un X virtual. La extracción real desde YouTube (reproducción, playlists, búsqueda, medición de calidad automática, descargas) y el rendimiento en hardware de ~2006 **no fueron verificados todavía**. Si algo falla, abrí un issue con el contenido de *Herramientas → Ver log*.

## Características

**Reproducción**
- Pegar una URL de video o playlist y reproducir en la misma ventana (mpv embebido).
- Play/pausa, barra de progreso con búsqueda, velocidad 0.5x–2x, volumen, silencio y pantalla completa.
- Selector de calidad (360p / 480p / 720p / 1080p) que recarga el video en el mismo minuto, sin reiniciar la app.
- **Auto**: mide la conexión antes de reproducir y elige la calidad.
- **Solo audio**, activable y desactivable en plena reproducción.
- Transmisiones en vivo: la barra de progreso se adapta ("EN VIVO").
- Subtítulos y saltos de capítulo cuando el video los tiene.

**Cola y playlists**
- Cola con avance automático, reordenar, quitar, vaciar y filtrar por texto.
- Playlists completas: cada video muestra de qué lista viene (columna y color propio).
- Guardar/cargar la cola en un archivo `.json` y autoguardado al cerrar.

**Memoria y navegación**
- Historial con reanudación automática desde el minuto donde quedaste.
- Buscador interno de YouTube (sin abrir el navegador).
- Favoritos.

**Extras**
- Capturas de pantalla, descarga del video actual (con prioridad baja de CPU y disco).
- Temporizador de apagado (15/30/60 min o fin del video) con cuenta regresiva cancelable.
- Notificación al terminar la cola, barra de estado, manual y log de diagnóstico dentro de la app.

**Robustez**
- Si mpv se cae, se relanza solo y retoma cerca del punto donde estaba (hasta 3 intentos).
- URL inválida, playlist cuando querías un video, extracción fallida: se informa en la barra de estado, sin colgar la ventana.
- Botón para actualizar yt-dlp.

## Requisitos

- Linux con **X11** (el video se embebe con `--wid`; no funciona en Wayland puro).
- Python 3.8 o superior.
- `mpv` y `python3-tk`.
- Opcionales: `ffmpeg` (descargas con video+audio unidos) y `libnotify-bin` (notificaciones).
- `yt-dlp`: la app puede descargarlo e instalarlo sola en `~/.local/bin` (ver abajo).

## Instalación

```sh
sudo apt install mpv python3-tk ffmpeg libnotify-bin
git clone <URL-DEL-REPO> ytlite
cd ytlite
sh install.sh
```

`install.sh` copia la app a `~/.local/share/ytlite/`, crea el comando `ytlite` en `~/.local/bin/` y registra la entrada de menú (`ytlite.desktop`).

Después abrí YTLite y usá **Herramientas → Actualizar yt-dlp**. Descarga la última versión a `~/.local/bin/yt-dlp`, que la app prefiere sobre la del sistema (la de apt suele estar vieja y YouTube cambia seguido).

Si no aparece en el menú de antiX, probá `desktop-menu --write-out-global` o reiniciá el gestor de ventanas.

También se puede ejecutar directamente:

```sh
python3 ytlite.py [URL ...]
```

## Uso rápido

1. Pegá una URL y pulsá **Enter** (o el botón **Pegar**, que toma el portapapeles y reproduce).
2. **Encolar** agrega al final de la cola. **Playlist** agrega todos los videos de la lista.
3. Una URL de video con `&list=...` reproduce solo el video; para toda la lista usá **Playlist**.
4. Si el video se ve negro al principio, un clic sobre él inicia la reproducción.

El manual completo está en **Ayuda → Manual de uso**.

### Atajos

| Tecla | Acción |
|---|---|
| Espacio / clic | Pausa / reanudar |
| ← / → | −5 s / +5 s |
| Shift + ← / → | −30 s / +30 s |
| ↑ / ↓, `+` / `-`, rueda | Volumen |
| M | Silenciar |
| `[` / `]` | Velocidad menos / más |
| N / P | Siguiente / anterior |
| F / Esc | Pantalla completa / salir |
| S | Captura |
| A | Solo audio |
| C | Subtítulos |
| B | Favorito |
| RePág / AvPág | Capítulo anterior / siguiente |

Las teclas de letra no actúan mientras escribís en un campo de texto.

## Configuración

Todo se guarda en `~/.config/ytlite/`:

| Archivo | Contenido |
|---|---|
| `config.json` | Preferencias |
| `queue.json` | Cola (se restaura al abrir) |
| `history.json` | Historial y posiciones |
| `favorites.json` | Favoritos |
| `ytlite.log` | Log rotativo (~200 KB) |

Las preferencias se editan en **Herramientas → Preferencias**: modo conservador, loudnorm, subtítulos, tamaño del búfer en RAM, salida de video, carpetas de capturas y descargas, límite de descarga, acción del temporizador, entre otras.

Opciones extra de yt-dlp (cookies, runtime de JavaScript, etc.) van en `~/.config/yt-dlp/config`; se aplican también a lo que reproduce mpv.

## Si el rendimiento no alcanza

1. Usá **Solo audio** o **360p**: es lo que más CPU ahorra.
2. Mantené el **modo conservador** (tope 480p, H.264, decodificación rápida). H.264 es lo que un procesador de 2006 puede decodificar con menos esfuerzo; VP9/AV1 no.
3. Ajustá el **búfer en RAM** (por defecto 64 MiB adelante, 8 MiB atrás): subilo si te sobra memoria, bajalo si te falta.
4. Desactivá **loudnorm** y los **subtítulos**.
5. No descargues mientras mirás otro video: las descargas escriben disco (corren con `nice`/`ionice`, pero un disco mecánico lento igual lo siente).
6. Salida de video en `auto` prueba `xv`, luego `x11`, luego `gpu`. Si ves negro con sonido, fijá `x11` en Preferencias.

## Problemas frecuentes

- **"Error de extracción" / no carga ningún video de YouTube:** *Herramientas → Actualizar yt-dlp*. Si persiste, revisá en la documentación de yt-dlp si YouTube exige ahora un runtime de JavaScript (deno o node). Deno no corre en sistemas de 32 bits; ahí habría que usar node.
- **El reproductor se cae:** se relanza solo hasta 3 veces; después avisa. *Herramientas → Ver log* muestra la salida de mpv.
- **Video negro con audio:** cambiá la salida de video a `x11` o `gpu`.
- **No hay notificaciones:** instalá `libnotify-bin`; sin él, la app solo hace un beep.

## Cómo funciona

```
Tkinter (ventana, cola, historial, búsqueda)
   │  IPC JSON por socket Unix
   ▼
mpv  --wid=<frame Tk>   ← embebido en la ventana, caché solo en RAM
   │  hook ytdl
   ▼
yt-dlp  → streams de YouTube
```

- mpv corre como proceso aparte: si cae, la interfaz sigue y puede relanzarlo.
- La interfaz solo lee propiedades cacheadas del reproductor, así que responde aunque la red esté lenta.
- Los atajos con la ventana de video enfocada pasan por mpv (`script-message`) y vuelven a la app, por eso funcionan igual con el foco en el video o fuera de él.
