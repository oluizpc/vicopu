"""Painel web simples: status das lives, botão "cortar agora", e fila de revisão dos clipes."""
import html
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORES = {"pendente": "#f5a524", "publicado": "#17c964", "publicando": "#338ef7", "erro": "#f31260",
         "descartado": "#666", "descartado_ia": "#666", "pronto": "#338ef7", "renderizando": "#338ef7"}

PAGINA = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VICOPU</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0e0e10;color:#eee;margin:0;padding:20px}}
h1{{margin:0 0 4px}} .sub{{color:#999;margin-bottom:20px}}
.lives{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:24px}}
.live{{background:#1c1c20;border-radius:10px;padding:10px 14px;display:flex;gap:10px;align-items:center}}
.dot{{width:10px;height:10px;border-radius:50%}}
.grade{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}}
.card{{background:#1c1c20;border-radius:12px;padding:10px}}
video{{width:100%;aspect-ratio:9/16;background:#000;border-radius:8px}}
input{{width:100%;box-sizing:border-box;background:#0e0e10;color:#eee;border:1px solid #333;border-radius:6px;padding:6px;margin:6px 0}}
button{{border:0;border-radius:6px;padding:7px 12px;font-weight:600;cursor:pointer}}
.ok{{background:#17c964}} .no{{background:#333;color:#ddd}} .cut{{background:#9147ff;color:#fff}}
.tag{{display:inline-block;border-radius:4px;padding:2px 6px;font-size:12px;color:#000}}
small{{color:#999;display:block;margin-top:4px;word-break:break-word}}
</style></head><body>
<h1>VICOPU</h1><div class="sub">vigia · corta · publica: modo <b>{modo}</b></div>
<div class="lives">{lives}</div>
<div class="grade">{cards}</div>
<script>
async function acao(url, corpo){{await fetch(url,{{method:'POST',body:corpo||''}});location.reload()}}
setTimeout(()=>location.reload(), 20000);
</script></body></html>"""


def iniciar(fabrica, vigias, host, porta):
    por_nome = {v.canal["nome"]: v for v in vigias}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _enviar(self, codigo, corpo, tipo="text/html; charset=utf-8"):
            dados = corpo.encode() if isinstance(corpo, str) else corpo
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            if self.path.startswith("/video/"):
                return self._video(urllib.parse.unquote(self.path[7:]))
            if self.path.startswith("/camauto/"):
                nome = os.path.basename(urllib.parse.unquote(self.path[9:]))
                cam = os.path.join(fabrica.cfg["geral"]["pasta_trabalho"], "camauto", f"{nome}.jpg")
                if os.path.exists(cam):
                    with open(cam, "rb") as f:
                        return self._enviar(200, f.read(), "image/jpeg")
                return self._enviar(404, "ainda não detectou")
            if self.path == "/api/clipes":
                return self._enviar(200, json.dumps(fabrica.listar(), ensure_ascii=False), "application/json")
            lives = "".join(
                f'<div class="live"><span class="dot" style="background:{"#17c964" if v.no_ar() else "#555"}"></span>'
                f'<b>{html.escape(n)}</b> <small style="margin:0">{v.canal["plataforma"]} · '
                f'{"<a style=color:#9aa href=/camauto/" + urllib.parse.quote(n) + " target=_blank>" if v.automatico else ""}'
                f'{v.layout_atual}{" (auto)</a>" if v.automatico else ""}</small>'
                f'<button class="cut" onclick="acao(\'/cortar/{urllib.parse.quote(n)}\')">✂ cortar agora</button></div>'
                for n, v in por_nome.items())
            cards = []
            for m in fabrica.listar()[:60]:
                st = m.get("status", "")
                botoes = ""
                if st in ("pendente", "pronto", "erro"):
                    botoes = (f'<button class="ok" onclick="acao(\'/aprovar/{m["id"]}\', '
                              f'document.getElementById(\'t_{m["id"]}\').value)">Publicar</button> '
                              f'<button class="no" onclick="acao(\'/descartar/{m["id"]}\')">Descartar</button>')
                video = (f'<video controls preload="metadata" src="/video/{m["id"]}"></video>'
                         if os.path.exists(m.get("video", "")) else "")
                res = "<br>".join(f"{html.escape(k)}: {html.escape(str(v))}"
                                  for k, v in (m.get("resultados") or {}).items())
                cards.append(
                    f'<div class="card">{video}'
                    f'<span class="tag" style="background:{CORES.get(st, "#999")}">{st}</span> '
                    f'<b>{html.escape(m["canal"])}</b>'
                    f'<input id="t_{m["id"]}" value="{html.escape(m.get("titulo", ""))}">{botoes}'
                    f'<small>{html.escape(m.get("motivo", ""))}</small>'
                    f'<small>IA: {html.escape(str(m.get("nota_ia", "-")))} · {html.escape(str(m.get("motivo_ia", "")))}</small>'
                    f'<small>{res}</small></div>')
            self._enviar(200, PAGINA.format(modo=fabrica.cfg["publicacao"]["modo"], lives=lives,
                                            cards="".join(cards) or "<p>Nenhum clipe ainda.</p>"))

        def do_POST(self):
            tam = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tam).decode("utf-8", errors="ignore") if tam else ""
            partes = self.path.strip("/").split("/", 1)
            if len(partes) != 2:
                return self._enviar(404, "?")
            acao, alvo = partes[0], urllib.parse.unquote(partes[1])
            try:
                if acao == "cortar" and alvo in por_nome:
                    por_nome[alvo].detector.manual("botão 'cortar agora' no painel")
                elif acao == "aprovar":
                    fabrica.publicar_async(alvo, corpo.strip() or None)
                elif acao == "descartar":
                    fabrica.descartar(alvo)
                else:
                    return self._enviar(404, "?")
            except FileNotFoundError:
                return self._enviar(404, "clipe não encontrado")
            self._enviar(200, "ok", "text/plain")

        def _video(self, cid):
            try:
                caminho = fabrica.ler(cid)["video"]
                tamanho = os.path.getsize(caminho)
            except (FileNotFoundError, KeyError):
                return self._enviar(404, "?")
            ini, fim = 0, tamanho - 1
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if m:
                ini = int(m.group(1) or 0)
                fim = int(m.group(2)) if m.group(2) else fim
            with open(caminho, "rb") as f:
                f.seek(ini)
                dados = f.read(fim - ini + 1)
            self.send_response(206 if m else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(dados)))
            if m:
                self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
            self.end_headers()
            self.wfile.write(dados)

    srv = ThreadingHTTPServer((host, porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="painel").start()
    return srv
