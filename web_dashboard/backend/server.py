#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
server.py
Servidor FastAPI e WebSocket em tempo real para o Dashboard Quantitativo ProfitDLL / B3.
"""

import os
import sys
import asyncio
import logging
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Adicionar diretório backend ao path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from data_service import get_dashboard_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
log = logging.getLogger("DashboardServer")

app = FastAPI(title="ProfitDLL Quantitative Dashboard API", version="1.0.0")

# CORS para permitir conexões do Vite (porta 5173) e qualquer host local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        log.info(f"Cliente WebSocket conectado. Total ativos: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        log.info(f"Cliente WebSocket desconectado. Total ativos: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


@app.get("/api/health")
async def health_check():
    return {"status": "online", "service": "ProfitDLL Dashboard API"}


@app.get("/api/snapshot")
async def get_snapshot(ticker: str = Query("WDOU26")):
    """Retorna o snapshot de mercado mais recente via REST."""
    return get_dashboard_data(ticker)


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket, ticker: str = "WDOU26"):
    """
    Endpoint WebSocket de streaming em tempo real.
    Envia snapshot inicial imediato e depois atualiza a cada 1 segundo.
    """
    await manager.connect(websocket)
    try:
        # Enviar snapshot inicial
        initial_data = get_dashboard_data(ticker)
        await websocket.send_json(initial_data)

        while True:
            # Polling em loop com sleep assíncrono de 1s
            await asyncio.sleep(1.0)
            data = get_dashboard_data(ticker)
            await websocket.send_json(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.debug(f"Erro no loop WebSocket: {e}")
        manager.disconnect(websocket)


# Montar arquivos estáticos se o frontend React estiver construído (produção)
FRONTEND_DIST = os.path.abspath(os.path.join(CURRENT_DIR, "..", "frontend", "dist"))
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
else:
    @app.get("/")
    async def root():
        return {
            "message": "ProfitDLL Dashboard API ativa!",
            "frontend_status": "Vite dev server em http://localhost:5173 ou build em dist/",
            "endpoints": {
                "snapshot": "/api/snapshot?ticker=WDOU26",
                "websocket": "ws://localhost:8000/ws/live?ticker=WDOU26"
            }
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
