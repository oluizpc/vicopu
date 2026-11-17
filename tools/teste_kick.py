"""Diagnóstico do chat da Kick: mostra tudo que o servidor manda por 60 s.

Uso:  python tools\\teste_kick.py 16543790          (número da sala do chat)
      python tools\\teste_kick.py 16543790 sem-origin
"""
import json
import sys
import time

import websocket

sala = sys.argv[1] if len(sys.argv) > 1 else "16543790"
com_origin = "sem-origin" not in sys.argv
url = ("wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
       "?protocol=7&client=js&version=8.4.0&flash=false")
cabecalho = ["Origin: https://kick.com"] if com_origin else []

t0 = time.time()


def log(*a):
    print(f"[{time.time() - t0:5.1f}s]", *a, flush=True)


log("conectando", "(com Origin)" if com_origin else "(sem Origin)")
ws = websocket.create_connection(url, timeout=30, header=cabecalho)
log("conectado")
assinou = False
try:
    while time.time() - t0 < 60:
        op, dado = ws.recv_data(control_frame=True)
        nome = {1: "texto", 2: "binario", 8: "FECHOU", 9: "ping", 10: "pong"}.get(op, op)
        if op == 8:
            codigo = int.from_bytes(dado[:2], "big") if len(dado) >= 2 else None
            log("FECHOU  codigo:", codigo, "motivo:", dado[2:].decode(errors="replace"))
            break
        if op == 9:
            ws.pong(dado)
        texto = dado.decode(errors="replace") if isinstance(dado, bytes) else str(dado)
        log(nome, texto[:200])
        if op == 1:
            try:
                ev = json.loads(texto).get("event", "")
            except ValueError:
                ev = ""
            if ev == "pusher:connection_established" and not assinou:
                ws.send(json.dumps({"event": "pusher:subscribe",
                                    "data": {"auth": "", "channel": f"chatrooms.{sala}.v2"}}))
                assinou = True
                log("pedi pra entrar na sala", sala)
            elif ev == "pusher:ping":
                ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
except Exception as e:  # noqa: BLE001
    log("ERRO:", type(e).__name__, e)
log("fim")
