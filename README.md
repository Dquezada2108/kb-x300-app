# KB-X300 App

Una app propia para controlar por WiFi la cámara de acción **Kaiser Baas X300**. Sustituye a la app oficial "KB X300", que ya no está en la App Store.

Corre en tu PC y la usas desde el navegador:

- Video en vivo de la cámara
- Grabar y tomar fotos en la cámara (memoria SD)
- **Grabar en PC** y **Foto a PC** desde el video en vivo (640×360)
- Ajustes: resolución de video y foto, exposición, balance de blancos, timelapse, dividir video, HDR, imagen invertida, frecuencia de luz y sonidos
- Lista de archivos de la cámara para ver, descargar o borrar
- Batería, estado de la SD y reconexión automática

## Requisitos

- Windows, macOS o Linux con **Python 3.10+**
- `pip install -r requirements.txt` (instala OpenCV)
- La PC conectada al WiFi de la cámara (`KB-X300`; contraseña por defecto `1234567890`). Si también quieres internet, conéctala por cable de red al mismo tiempo.

## Uso

```bash
python app.py
```

Se abre el navegador en <http://localhost:8300>. En Windows también puedes hacer doble clic en `Iniciar KB-X300.bat`.

Las fotos y videos guardados en la PC quedan en la carpeta `capturas/`.

## Cómo funciona

La X300 usa un chip **AIT**. Con su WiFi encendido, la cámara crea una red propia y responde en `192.72.1.1`:

| Qué | Cómo |
|---|---|
| Leer estado y ajustes | `GET /cgi-bin/Config.cgi?action=get&property=Camera.*` |
| Cambiar un ajuste | `GET /cgi-bin/Config.cgi?action=set&property=Videores&value=1080P30` |
| Tomar foto / grabar (alterna) | `action=set&property=Video&value=capture` · `value=record` |
| Listar archivos | `action=dir&property=DCIM&format=all&count=32&from=0` (XML) |
| Borrar archivo | `action=del&property=$SD$Normal$ARCHIVO.MOV` (`/` → `$`) |
| Video en vivo | `rtsp://192.72.1.1/liveRTSP/av4` (H.264 640×360) |

`app.py` es un servidor local escrito solo con la librería estándar de Python. Usa OpenCV para convertir el video RTSP en MJPEG y así el navegador puede mostrarlo. Hace de intermediario entre la página y la cámara.

## Estado

Probado con una X300 real (firmware `KBX300`):

- ✅ Video en vivo, ajustes, foto y video a PC
- ⚠️ Lista, descarga y borrado de archivos: implementados pero sin probar, porque la SD de la cámara de prueba no se leía
- ⚠️ Cambio entre modo foto y video: la cámara acepta `UIMode=CAMERA_PREVIEW`, pero no se confirmó que cambie de modo

Proyecto personal, sin relación con Kaiser Baas.
