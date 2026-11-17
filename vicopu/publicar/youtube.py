"""PUBLICA no YouTube (vídeo vertical de até 3 min vira Short automaticamente)."""
import logging
import os

ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload"]
# pedido na autorização: upload + leitura (a leitura serve pra mostrar views/likes/comentários no painel)
ESCOPOS_AUTH = ESCOPOS + ["https://www.googleapis.com/auth/youtube.readonly"]


class SemPermissaoDeLeitura(RuntimeError):
    """O token dessa conta foi criado só com permissão de upload."""
log = logging.getLogger("publicar.youtube")


def caminho_token(cfg, conta):
    return os.path.join(cfg["geral"]["pasta_trabalho"], "credenciais", f"youtube_{conta}.json")


def autorizar(cfg, conta, porta=8090, abrir_navegador=True):
    """Abre o login do Google uma vez e guarda o token da conta."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    segredo = cfg["youtube_app"]["client_secrets"]
    if not os.path.exists(segredo):
        raise SystemExit(f"Não achei {segredo}. Baixe o JSON do cliente OAuth (tipo 'App para computador') "
                         f"no Google Cloud Console e salve nesse caminho.")
    fluxo = InstalledAppFlow.from_client_secrets_file(segredo, ESCOPOS_AUTH)
    print(f"\nVai abrir o login do Google. Entre com a conta e ESCOLHA O CANAL '{conta}' onde os Shorts vão sair.\n"
          f"Se o navegador não abrir, copie o link que aparecer abaixo.\n"
          f"(Num servidor sem tela: use --sem-navegador e faça 'ssh -L {porta}:localhost:{porta} seu_servidor'.)\n")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # aceita se a pessoa desmarcar alguma permissão
    cred = fluxo.run_local_server(port=porta, open_browser=abrir_navegador, prompt="consent")
    concedidos = set(getattr(cred, "granted_scopes", None) or cred.scopes or [])
    if concedidos and not any(x.endswith("youtube.readonly") for x in concedidos):
        print("\nATENÇÃO: a permissão de VER os dados do canal não foi marcada. O upload funciona, mas o painel\n"
              "não vai mostrar views/likes/comentários. Rode de novo e marque todas as caixinhas na tela do Google.\n")
    destino = caminho_token(cfg, conta)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w") as f:
        f.write(cred.to_json())
    print(f"OK! Token salvo em {destino}")


def enviar(cfg, conta, video, titulo, descricao, tags, opcoes):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    tok = caminho_token(cfg, conta)
    if not os.path.exists(tok):
        raise RuntimeError(f"Conta YouTube '{conta}' não autorizada. Rode: python -m vicopu auth-youtube {conta}")
    cred = Credentials.from_authorized_user_file(tok, ESCOPOS)
    if not cred.valid:
        cred.refresh(Request())
        with open(tok, "w") as f:
            f.write(cred.to_json())
    yt = build("youtube", "v3", credentials=cred, cache_discovery=False)
    if "#shorts" not in (titulo + descricao).lower():
        descricao = f"{descricao}\n\n#Shorts"
    corpo = {
        "snippet": {"title": titulo[:100], "description": descricao[:4900],
                    "tags": [t.lstrip("#") for t in tags][:15], "categoryId": "20"},
        "status": {"privacyStatus": opcoes.get("privacidade", "public"),
                   "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=corpo,
                             media_body=MediaFileUpload(video, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    url = f"https://youtube.com/shorts/{resp['id']}"
    log.info("Publicado no YouTube (%s): %s", conta, url)
    return url


def estatisticas(cfg, conta, ids):
    """Views, likes e comentários dos vídeos (até 50 por chamada; custa 1 unidade de cota)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    tok = caminho_token(cfg, conta)
    if not os.path.exists(tok):
        raise RuntimeError(f"conta YouTube '{conta}' não autorizada")
    cred = Credentials.from_authorized_user_file(tok)  # usa os escopos que o token já tem
    if cred.scopes and not any(s.endswith(("youtube.readonly", "/youtube", "youtube.force-ssl")) for s in cred.scopes):
        raise SemPermissaoDeLeitura(conta)
    if not cred.valid:
        cred.refresh(Request())
        with open(tok, "w") as f:
            f.write(cred.to_json())
    yt = build("youtube", "v3", credentials=cred, cache_discovery=False)
    saida = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        try:
            resp = yt.videos().list(part="statistics,status", id=",".join(ids[i:i + 50])).execute()
        except HttpError as e:
            texto = str(e)
            if "insufficient" in texto.lower() or "SCOPE_INSUFFICIENT" in texto:
                raise SemPermissaoDeLeitura(conta) from e
            motivo = getattr(e, "reason", "") or texto
            raise RuntimeError(f"YouTube recusou ({getattr(e, 'status_code', '?')}): {motivo}") from e
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            saida[item["id"]] = {"views": int(st.get("viewCount", 0) or 0),
                                 "likes": int(st.get("likeCount", 0) or 0),
                                 "comentarios": int(st.get("commentCount", 0) or 0),
                                 "privacidade": item.get("status", {}).get("privacyStatus", "")}
    return saida
