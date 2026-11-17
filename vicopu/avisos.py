"""Avisos no celular pelo app ntfy (grátis, sem cadastro): https://ntfy.sh

No celular: instale o app ntfy, toque em + e assine o mesmo tópico do config (publicacao.aviso_ntfy).
Use um nome difícil de adivinhar (quem souber o tópico vê os avisos).
"""
import logging
import threading

log = logging.getLogger("avisos")


def enviar(cfg, titulo, texto, tags="movie_camera", prioridade=3):
    topico = (cfg["publicacao"].get("aviso_ntfy") or "").strip()
    if not topico:
        return
    servidor = "https://ntfy.sh"
    if topico.startswith("http"):  # servidor próprio: https://meu.servidor/topico
        servidor, topico = topico.rstrip("/").rsplit("/", 1)
    link = (cfg["publicacao"].get("painel_link") or "").strip()
    corpo = {"topic": topico, "title": titulo, "message": texto, "tags": [tags], "priority": prioridade}
    if link:
        corpo["click"] = link

    def mandar():
        try:
            import requests
            requests.post(servidor, json=corpo, timeout=15)  # JSON: aceita acento e emoji no título
        except Exception as e:  # noqa: BLE001
            log.debug("aviso ntfy falhou: %s", e)

    threading.Thread(target=mandar, daemon=True, name="aviso").start()
