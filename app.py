"""KB-X300 App: control propio para la camara Kaiser Baas X300 (chip AIT) por WiFi.

Uso: conecta la PC al WiFi de la camara (KB-X300) y ejecuta `python app.py`.
Se abre el navegador en http://localhost:8300
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

CAM = "192.72.1.1"
CGI = f"http://{CAM}/cgi-bin/Config.cgi"
RTSP = f"rtsp://{CAM}/liveRTSP/av4"
PORT = 8300
HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES = os.path.join(HERE, "capturas")

# Ajustes que la camara acepta (verificados contra la X300)
SETTINGS = {
    "Videores": {"menu": "VideoRes", "label": "Resolución de video", "options": [
        ["4K15", "4K · 15 fps"], ["2.7K30", "2.7K · 30 fps"], ["1080P60", "1080p · 60 fps"],
        ["1080P30", "1080p · 30 fps"], ["720P120", "720p · 120 fps"], ["720P60", "720p · 60 fps"]]},
    "Imageres": {"menu": "ImageRes", "label": "Resolución de foto", "options": [
        ["12MP", "12 MP"], ["8MP", "8 MP"], ["5MP", "5 MP"], ["3MP", "3 MP"]]},
    "EV": {"menu": "EV", "label": "Exposición", "options": [
        ["EVN200", "−2.0"], ["EVN167", "−1.7"], ["EVN133", "−1.3"], ["EVN100", "−1.0"], ["EVN067", "−0.7"],
        ["EVN033", "−0.3"], ["EV0", "0"], ["EVP033", "+0.3"], ["EVP067", "+0.7"], ["EVP100", "+1.0"],
        ["EVP133", "+1.3"], ["EVP167", "+1.7"], ["EVP200", "+2.0"]]},
    "AWB": {"menu": "AWB", "label": "Balance de blancos", "options": [
        ["AUTO", "Automático"], ["DAYLIGHT", "Luz de día"], ["CLOUDY", "Nublado"],
        ["FLUORESCENT1", "Fluorescente 1"], ["FLUORESCENT2", "Fluorescente 2"],
        ["FLUORESCENT3", "Fluorescente 3"], ["INCANDESCENT", "Incandescente"]]},
    "Timelapse": {"menu": "Timelapse", "label": "Timelapse", "options": [
        ["OFF", "Apagado"], ["1SEC", "Cada 1 s"], ["5SEC", "Cada 5 s"], ["10SEC", "Cada 10 s"],
        ["30SEC", "Cada 30 s"], ["60SEC", "Cada 60 s"]]},
    "VideoClipTime": {"menu": "VideoClipTime", "label": "Dividir video", "options": [
        ["OFF", "No"], ["3MIN", "Cada 3 min"], ["5MIN", "Cada 5 min"]]},
    "HDR": {"menu": "HDR", "label": "HDR", "options": [["OFF", "Apagado"], ["ON", "Encendido"]]},
    "UpsideDown": {"menu": "UpsideDown", "label": "Imagen invertida", "options": [
        ["Normal", "Normal"], ["Upsidedown", "Invertida"]]},
    "Flicker": {"menu": "Flicker", "label": "Frecuencia de luz", "options": [["50Hz", "50 Hz"], ["60Hz", "60 Hz"]]},
    "SoundIndicator": {"menu": "SoundIndicator", "label": "Sonidos", "options": [["ON", "Encendidos"], ["OFF", "Apagados"]]},
}

cam_lock = threading.Lock()


# ---------------------------------------------------------------- camara (HTTP)
def cgi(**params):
    """Llama a Config.cgi y devuelve (codigo, lineas)."""
    url = CGI + "?" + urllib.parse.urlencode(params, safe="*$/")
    with cam_lock:
        with urllib.request.urlopen(url, timeout=5) as r:
            text = r.read().decode("utf-8", "replace")
    lines = text.strip().splitlines()
    if lines and lines[0].strip().lstrip("-").isdigit():
        return int(lines[0]), lines[1:]
    return 0, lines


def get_props(pattern="Camera.*"):
    code, lines = cgi(action="get", property=pattern)
    props = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def normalize(value, options):
    """La camara a veces trunca valores ('OF' en vez de 'OFF')."""
    for opt, _ in options:
        if opt.lower() == value.lower():
            return opt
    for opt, _ in options:
        if opt.lower().startswith(value.lower()) and value:
            return opt
    return value


def status():
    p = get_props("Camera.*")
    menu = lambda k: p.get("Camera.Menu." + k, "")
    rec_state = p.get("Camera.Preview.MJPEG.status.record", "")
    return {
        "online": True,
        "battery": p.get("Camera.Battery.Level", ""),
        "sd": menu("SD0"),
        "recording": rec_state.lower().startswith("rec") or p.get("Camera.Record.Start") == "1",
        "recordState": rec_state,
        "mode": p.get("Camera.Preview.MJPEG.status.mode", ""),
        "uiMode": menu("UIMode"),
        "firmware": menu("FWversion"),
        "files": p.get("Camera.File.Total", ""),
        "recordRemaining": p.get("Camera.Record.Available", ""),
        "settings": {k: normalize(menu(s["menu"]), s["options"]) for k, s in SETTINGS.items()},
    }


FILE_RE = re.compile(r"<file>(.*?)</file>", re.S)
TAG_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.S)


def list_files():
    seen, out = set(), []
    for folder in ("DCIM", "Normal", "Photo", "Event"):
        start = 0
        while True:
            url = CGI + f"?action=dir&property={folder}&format=all&count=32&from={start}"
            with cam_lock:
                with urllib.request.urlopen(url, timeout=8) as r:
                    xml = r.read().decode("utf-8", "replace")
            blocks = FILE_RE.findall(xml)
            for b in blocks:
                f = dict(TAG_RE.findall(b))
                name = f.get("name", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    out.append({"name": name, "size": f.get("size", ""), "time": f.get("time", ""),
                                "format": f.get("format", "")})
            if len(blocks) < 32:
                break
            start += 32
    return out


def safe_cam_path(path):
    if not path.startswith("/") or ".." in path:
        raise ValueError("ruta inválida")
    return path


# ---------------------------------------------------------------- video en vivo (RTSP -> MJPEG)
class LiveVideo:
    def __init__(self):
        self.frame = None          # ultimo frame (numpy)
        self.jpeg = None           # ultimo frame en JPEG
        self.seq = 0
        self.cond = threading.Condition()
        self.last_viewer = 0.0
        self.fps = 15.0
        self.writer = None
        self.rec_path = None
        self.rec_started = 0.0
        self.thread = None
        self.lock = threading.Lock()

    def touch(self):
        self.last_viewer = time.time()
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;udp")
        while time.time() - self.last_viewer < 15 or self.writer:
            cap = cv2.VideoCapture(RTSP, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                time.sleep(2)
                continue
            times = []
            while time.time() - self.last_viewer < 15 or self.writer:
                ok, frame = cap.read()
                if not ok:
                    break
                now = time.time()
                times = [t for t in times if now - t < 3] + [now]
                if len(times) > 5:
                    self.fps = max(5.0, min(30.0, (len(times) - 1) / (times[-1] - times[0])))
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                with self.cond:
                    self.frame, self.jpeg = frame, buf.tobytes()
                    self.seq += 1
                    if self.writer:
                        self.writer.write(frame)
                    self.cond.notify_all()
            cap.release()
        with self.cond:
            self.frame = self.jpeg = None

    def wait_frame(self, last_seq, timeout=5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq and self.jpeg, timeout=timeout)
            return self.seq, self.jpeg

    def snapshot(self):
        with self.cond:
            frame = self.frame
        if frame is None:
            raise RuntimeError("No hay video en vivo todavía")
        os.makedirs(CAPTURES, exist_ok=True)
        path = os.path.join(CAPTURES, datetime.now().strftime("foto_%Y-%m-%d_%H-%M-%S.jpg"))
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return path

    def start_rec(self):
        with self.cond:
            if self.writer:
                return self.rec_path
            if self.frame is None:
                raise RuntimeError("No hay video en vivo todavía")
            h, w = self.frame.shape[:2]
            os.makedirs(CAPTURES, exist_ok=True)
            self.rec_path = os.path.join(CAPTURES, datetime.now().strftime("video_%Y-%m-%d_%H-%M-%S.mp4"))
            self.writer = cv2.VideoWriter(self.rec_path, cv2.VideoWriter_fourcc(*"mp4v"), round(self.fps), (w, h))
            self.rec_started = time.time()
            return self.rec_path

    def stop_rec(self):
        with self.cond:
            path, w = self.rec_path, self.writer
            self.writer = None
        if w:
            w.release()
        return path


live = LiveVideo()


# ---------------------------------------------------------------- servidor web local
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def query(self):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}

    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            if route == "/":
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif route == "/api/status":
                s = status()
                s["pcRecording"] = bool(live.writer)
                s["pcRecSeconds"] = int(time.time() - live.rec_started) if live.writer else 0
                s["liveFps"] = round(live.fps, 1)
                self.send_json(s)
            elif route == "/api/settings":
                self.send_json(SETTINGS)
            elif route == "/api/files":
                self.send_json(list_files())
            elif route == "/api/file":
                self.proxy_file(safe_cam_path(self.query()["path"]))
            elif route == "/stream.mjpg":
                self.stream()
            else:
                self.send_json({"error": "no encontrado"}, 404)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if route.startswith("/api/"):
                self.send_json({"online": False, "error": f"Cámara no responde: {e}"}, 503)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        q = self.query()
        try:
            if route == "/api/set":
                prop, value = q["prop"], q["value"]
                if prop not in SETTINGS or value not in [o[0] for o in SETTINGS[prop]["options"]]:
                    raise ValueError("ajuste no permitido")
                code, lines = cgi(action="set", property=prop, value=value)
                self.send_json({"ok": code == 0, "code": code, "msg": " ".join(lines)})
            elif route == "/api/photo":
                code, lines = cgi(action="set", property="Video", value="capture")
                self.send_json({"ok": code == 0, "code": code})
            elif route == "/api/record":
                code, lines = cgi(action="set", property="Video", value="record")
                self.send_json({"ok": code == 0, "code": code})
            elif route == "/api/delete":
                path = safe_cam_path(q["path"])
                code, lines = cgi(action="del", property=path.replace("/", "$"))
                self.send_json({"ok": code == 0, "code": code, "msg": " ".join(lines)})
            elif route == "/api/pc/photo":
                self.send_json({"ok": True, "path": live.snapshot()})
            elif route == "/api/pc/record":
                if live.writer:
                    self.send_json({"ok": True, "recording": False, "path": live.stop_rec()})
                else:
                    self.send_json({"ok": True, "recording": True, "path": live.start_rec()})
            elif route == "/api/pc/open":
                os.makedirs(CAPTURES, exist_ok=True)
                os.startfile(CAPTURES)
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "no encontrado"}, 404)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            self.send_json({"ok": False, "error": f"Cámara no responde: {e}"}, 503)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def proxy_file(self, path):
        url = f"http://{CAM}" + urllib.parse.quote(path)
        with urllib.request.urlopen(url, timeout=15) as r:
            self.send_response(200)
            self.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
            if r.headers.get("Content-Length"):
                self.send_header("Content-Length", r.headers["Content-Length"])
            if self.query().get("download"):
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
            self.end_headers()
            while chunk := r.read(256 * 1024):
                self.wfile.write(chunk)

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        seq = 0
        try:
            while True:
                live.touch()
                seq, jpeg = live.wait_frame(seq)
                if not jpeg:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"KB-X300 App en http://localhost:{PORT}  (Ctrl+C para salir)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        live.stop_rec()
