"""PUBLICA no TikTok pela Content Posting API.

Dois modos:
- "rascunho" (padrão): o vídeo cai na caixa de entrada do TikTok da conta, e você toca em publicar
  no celular. Funciona sem a auditoria do app.
- "direto": publica sozinho. Enquanto o app não passar na auditoria do TikTok, só sai como privado
  (SELF_ONLY).
"""
import json
import logging
import os
import secrets
import time
import urllib.parse

import requests

API = "https://open.tiktokapis.com/v2"
log = logging.getLogger("publicar.tiktok")


def caminho_token(cfg, conta):
    return os.path.join(cfg["geral"]["pasta_trabalho"], "credenciais", f"tiktok_{conta}.json")


def _salvar(cfg, conta, dados):
    dados["expira_em"] = time.time() + int(dados.get("expires_in", 0)) - 120
    destino = caminho_token(cfg, conta)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w") as f:
        json.dump(dados, f)


def autorizar(cfg, conta):
    app = cfg["tiktok_app"]
    if not (app["client_key"] and app["client_secret"] and app["redirect_uri"]):
        raise SystemExit("Preencha tiktok_app (client_key, client_secret, redirect_uri) no config.")
    estado = secrets.token_urlsafe(12)
    url = ("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": app["client_key"], "response_type": "code",
        "scope": "user.info.basic,video.upload,video.publish",
        "redirect_uri": app["redirect_uri"], "state": estado}))
    print(f"\n1) Abra e autorize com a conta '{conta}':\n{url}\n")
    print("2) Depois de autorizar, o navegador vai para o seu redirect_uri (pode até dar erro de página).")
    volta = input("   Cole aqui o endereço COMPLETO da barra do navegador: ").strip()
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(volta).query)
    if "code" not in qs:
        raise SystemExit("Não achei o 'code' nesse endereço.")
    r = requests.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": app["client_key"], "client_secret": app["client_secret"],
        "code": qs["code"][0], "grant_type": "authorization_code", "redirect_uri": app["redirect_uri"]})
    dados = r.json()
    if "access_token" not in dados:
        raise SystemExit(f"TikTok recusou: {dados}")
    _salvar(cfg, conta, dados)
    print(f"OK! Token salvo. Escopos liberados: {dados.get('scope')}")


def _token(cfg, conta):
    cam = caminho_token(cfg, conta)
    if not os.path.exists(cam):
        raise RuntimeError(f"Conta TikTok '{conta}' não autorizada. Rode: python -m vicopu auth-tiktok {conta}")
    with open(cam) as f:
        dados = json.load(f)
    if time.time() > dados.get("expira_em", 0):
        app = cfg["tiktok_app"]
        r = requests.post(f"{API}/oauth/token/", timeout=30, data={
            "client_key": app["client_key"], "client_secret": app["client_secret"],
            "grant_type": "refresh_token", "refresh_token": dados["refresh_token"]})
        novo = r.json()
        if "access_token" not in novo:
            raise RuntimeError(f"Falha ao renovar token do TikTok: {novo}")
        _salvar(cfg, conta, novo)
        dados = novo
    return dados["access_token"]


def _post(token, caminho, corpo):
    r = requests.post(f"{API}{caminho}", json=corpo, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    dados = r.json()
    erro = dados.get("error", {})
    if erro.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok {caminho}: {erro}")
    return dados.get("data", {})


def _info_upload(tamanho):
    # Regras do TikTok: pedaços de 5 a 64 MB; o último pode ser maior. Vídeo pequeno = 1 pedaço só.
    if tamanho <= 64 * 1024 * 1024:
        return tamanho, 1
    pedaco = 10 * 1024 * 1024
    return pedaco, tamanho // pedaco


def _enviar_arquivo(url_upload, video, tamanho, pedaco, total):
    with open(video, "rb") as f:
        for i in range(total):
            ini = i * pedaco
            fim = tamanho - 1 if i == total - 1 else ini + pedaco - 1
            f.seek(ini)
            bloco = f.read(fim - ini + 1)
            r = requests.put(url_upload, data=bloco, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(bloco)),
                "Content-Range": f"bytes {ini}-{fim}/{tamanho}"})
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"Upload TikTok falhou ({r.status_code}): {r.text[:300]}")


def enviar(cfg, conta, video, legenda, opcoes):
    token = _token(cfg, conta)
    tamanho = os.path.getsize(video)
    pedaco, total = _info_upload(tamanho)
    fonte = {"source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": pedaco,
             "total_chunk_count": total}
    modo = opcoes.get("modo", "rascunho")
    if modo == "direto":
        info = _post(token, "/post/publish/creator_info/query/", {})
        opcoes_priv = info.get("privacy_level_options", [])
        priv = opcoes.get("privacidade", "SELF_ONLY")
        if priv not in opcoes_priv:
            priv = "SELF_ONLY" if "SELF_ONLY" in opcoes_priv else (opcoes_priv or ["SELF_ONLY"])[0]
        dados = _post(token, "/post/publish/video/init/", {
            "post_info": {"title": legenda[:2200], "privacy_level": priv,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                          "video_cover_timestamp_ms": 1000},
            "source_info": fonte})
    else:
        dados = _post(token, "/post/publish/inbox/video/init/", {"source_info": fonte})
    _enviar_arquivo(dados["upload_url"], video, tamanho, pedaco, total)
    pid = dados["publish_id"]
    for _ in range(60):  # espera o TikTok processar (até ~5 min)
        st = _post(token, "/post/publish/status/fetch/", {"publish_id": pid})
        status = st.get("status")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            res = "rascunho enviado pro app" if status == "SEND_TO_USER_INBOX" else "publicado"
            log.info("TikTok (%s): %s", conta, res)
            return f"tiktok:{res}:{pid}"
        if status == "FAILED":
            raise RuntimeError(f"TikTok recusou o vídeo: {st.get('fail_reason')}")
        time.sleep(5)
    return f"tiktok:processando:{pid}"
