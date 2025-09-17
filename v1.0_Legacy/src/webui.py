from __future__ import annotations

import asyncio
import base64
import io
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.websockets import WebSocketState


class WebTrackerUI:
    def __init__(
        self,
        on_connect_stream=None,
        on_disconnect_stream=None,
        on_connect_makcu=None,
        on_disconnect_makcu=None,
        on_toggle_aimbot=None,
        on_toggle_box=None,
        on_set_udp=None,
    ) -> None:
        self.app = FastAPI()
        self._last_frame: Optional[np.ndarray] = None
        self._ws: Optional[WebSocket] = None
        self._aimbot: bool = False
        self._connected_stream: bool = False
        self._connected_makcu: bool = False
        self._on_connect_stream = on_connect_stream
        self._on_disconnect_stream = on_disconnect_stream
        self._on_connect_makcu = on_connect_makcu
        self._on_disconnect_makcu = on_disconnect_makcu
        self._on_toggle_aimbot = on_toggle_aimbot
        self._on_toggle_box = on_toggle_box
        self._on_set_udp = on_set_udp
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get("/")
        async def index():
            return HTMLResponse(self._html())

        @self.app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            self._ws = ws
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        if (
                            self._ws is not None
                            and self._ws.client_state == WebSocketState.CONNECTED
                        ):
                            await self._ws.send_json(
                                {"type": "log", "message": f"ui:{data}"}
                            )
                    except Exception:
                        pass
                    if data == "toggle_aimbot":
                        self._aimbot = not self._aimbot
                        if self._on_toggle_aimbot:
                            try:
                                self._on_toggle_aimbot(self._aimbot)
                            except Exception:
                                pass
                        await ws.send_json({"type": "aimbot", "value": self._aimbot})
                    elif data == "toggle_box":
                        if self._on_toggle_box:
                            try:
                                self._on_toggle_box(True)
                            except Exception:
                                pass
                        await ws.send_json({"type": "box", "value": True})
                    elif data == "connect_stream":
                        if self._on_connect_stream:
                            try:
                                self._on_connect_stream()
                                self._connected_stream = True
                            except Exception:
                                self._connected_stream = False
                        await ws.send_json({"type": "stream", "value": True})
                    elif data == "disconnect_stream":
                        if self._on_disconnect_stream:
                            try:
                                self._on_disconnect_stream()
                                self._connected_stream = False
                            except Exception:
                                pass
                        await ws.send_json({"type": "stream", "value": False})
                    elif data.startswith("set_udp:"):
                        import json
                        try:
                            payload = json.loads(data[len("set_udp:"):])
                        except Exception:
                            payload = {}
                        if self._on_set_udp:
                            try:
                                self._on_set_udp(payload)
                                await ws.send_json({"type": "log", "message": f"udp updated: {payload}"})
                            except Exception as e:
                                await ws.send_json({"type": "err", "message": f"udp update failed: {e}"})
                    elif data == "connect_makcu":
                        if self._on_connect_makcu:
                            try:
                                self._on_connect_makcu()
                                self._connected_makcu = True
                            except Exception:
                                self._connected_makcu = False
                        await ws.send_json({"type": "makcu", "value": True})
                    elif data == "disconnect_makcu":
                        if self._on_disconnect_makcu:
                            try:
                                self._on_disconnect_makcu()
                                self._connected_makcu = False
                            except Exception:
                                pass
                        await ws.send_json({"type": "makcu", "value": False})
            except WebSocketDisconnect:
                pass
            finally:
                self._ws = None

        @self.app.get("/status")
        async def status():
            return JSONResponse(
                {
                    "aimbot": self._aimbot,
                    "stream": self._connected_stream,
                    "makcu": self._connected_makcu,
                    "box": False,
                }
            )

    def set_status(
        self, *, stream: Optional[bool] = None, makcu: Optional[bool] = None
    ) -> None:
        if stream is not None:
            self._connected_stream = stream
        if makcu is not None:
            self._connected_makcu = makcu

    async def push_frame(self, frame_bgr: np.ndarray) -> None:
        # Light JPEG encode for preview
        if self._ws is None or self._ws.client_state != WebSocketState.CONNECTED:
            return
        _, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        b64 = base64.b64encode(buf).decode("ascii")
        try:
            await self._ws.send_json({"type": "frame", "data": b64})
        except Exception:
            pass

    async def send_log(self, message: str) -> None:
        """Push an info/debug log line to the Web UI code box."""
        try:
            if self._ws is not None and self._ws.client_state == WebSocketState.CONNECTED:
                await self._ws.send_json({"type": "log", "message": message})
        except Exception:
            pass

    async def send_error(self, message: str) -> None:
        """Push an error log line to the Web UI code box."""
        try:
            if self._ws is not None and self._ws.client_state == WebSocketState.CONNECTED:
                await self._ws.send_json({"type": "err", "message": message})
        except Exception:
            pass

    def _html(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AimVal Web UI</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 0; background: #0b0d10; color: #e6edf3; }
      .wrap { display: grid; grid-template-columns: 1fr 420px; gap: 12px; padding: 12px; }
      .card { background: #11151a; border: 1px solid #21262d; border-radius: 8px; padding: 12px; }
      button { padding: 8px 12px; margin: 4px 6px 4px 0; border-radius: 6px; border: 1px solid #30363d; background: #22272e; color: #e6edf3; cursor: pointer; }
      button:hover { background: #2d333b; }
      #viewer { width: 100%; height: 100%; object-fit: contain; background: #000; border-radius: 6px; }
      .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .muted { color: #8b949e; font-size: 12px; }
      .codebox { background: #0b0d10; border: 1px solid #21262d; border-radius: 6px; padding: 8px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #c9d1d9; height: 22vh; overflow: auto; white-space: pre-wrap; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <img id="viewer" />
      </div>
      <div class="card">
        <div class="row">
          <button id="btnStream">Connect Stream</button>
          <button id="btnMakcu">Connect Makcu</button>
          <button id="btnAim">Toggle Aimbot</button>
          <button id="btnBox">Toggle Box</button>
        </div>
        <div class="row">
          <label>Host <input id="inHost" value="0.0.0.0" style="width:120px"></label>
          <label>Port <input id="inPort" type="number" value="8080" style="width:90px"></label>
          <label>RecvBuf(MB) <input id="inBuf" type="number" value="64" style="width:80px"></label>
        </div>
        <div class="row">
          <label>Scale <input id="inScale" type="number" step="0.1" min="0.2" max="1.5" value="1.0" style="width:80px"></label>
          <label><input id="inTurbo" type="checkbox"> TurboJPEG</label>
          <button id="btnApplyUdp">Apply UDP</button>
        </div>
        <div class="muted" id="status">idle</div>
        <div class="codebox" id="log"></div>
      </div>
      
    </div>
    <script>
      const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
      const img = document.getElementById('viewer');
      const status = document.getElementById('status');
      const logBox = document.getElementById('log');
      let aim = false, stream=false, makcu=false, box=false;
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'frame') {
          img.src = 'data:image/jpeg;base64,' + msg.data;
        } else if (msg.type === 'aimbot') { aim = msg.value; update(); }
        else if (msg.type === 'stream') { stream = msg.value; update(); }
        else if (msg.type === 'makcu') { makcu = msg.value; update(); }
        else if (msg.type === 'box') { box = msg.value; update(); }
        else if (msg.type === 'log') { appendLog('INFO', msg.message); }
        else if (msg.type === 'err') { appendLog('ERR', msg.message); }
      };
      function update(){ status.textContent = `stream: ${stream} | makcu: ${makcu} | aimbot: ${aim} | box: ${box}`; }
      function appendLog(level, text){
        const ts = new Date().toLocaleTimeString();
        logBox.textContent += `[${ts}] [${level}] ${text}\n`;
        const lines = logBox.textContent.split('\n');
        if(lines.length>300){ logBox.textContent = lines.slice(-300).join('\n'); }
        logBox.scrollTop = logBox.scrollHeight;
      }
      document.getElementById('btnStream').onclick = () => {
        stream = !stream; ws.send(stream ? 'connect_stream' : 'disconnect_stream'); update(); };
      document.getElementById('btnMakcu').onclick = () => { makcu = !makcu; ws.send(makcu ? 'connect_makcu' : 'disconnect_makcu'); update(); };
      document.getElementById('btnAim').onclick = () => { ws.send('toggle_aimbot'); };
      document.getElementById('btnBox').onclick = () => { ws.send('toggle_box'); };
      document.getElementById('btnApplyUdp').onclick = () => {
        const payload = {
          host: document.getElementById('inHost').value,
          port: parseInt(document.getElementById('inPort').value || '8080'),
          rcvbuf_mb: parseInt(document.getElementById('inBuf').value || '64'),
          scale: parseFloat(document.getElementById('inScale').value || '1.0'),
          turbo: document.getElementById('inTurbo').checked,
        };
        ws.send('set_udp:' + JSON.stringify(payload));
      };
    </script>
  </body>
  </html>
        """
