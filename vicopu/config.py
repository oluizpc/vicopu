"""Carrega o config.yaml do VICOPU, aplica os padrões e expande ${VARIAVEIS}."""
import copy
import os
import re
import urllib.parse

import yaml

PADROES = {
    "geral": {
        "pasta_trabalho": "./dados",
        "buffer_minutos": 5,
        "segundos_por_segmento": 4,
        "workers_corte": 2,
        "ffmpeg": "ffmpeg",
        "qualidade_stream": "best",
        "log_nivel": "INFO",
    },
    "deteccao": {
        "aquecimento_segundos": 90,
        "janela_segundos": 10,
        "multiplicador_pico": 3.0,
        "minimo_mensagens_janela": 8,
        "cooldown_segundos": 90,
        "limiar_score": 1.0,
        "peso_palavras": 0.6,
        "peso_audio": 0.4,
        "usar_audio": True,
        "audio_salto_db": 6.0,
        "palavras_chave": [
            "kkkk", "kkkkk", "clip", "clipa", "clipe", "corta", "kekw", "lul",
            "omegalul", "pog", "poggers", "pogchamp", "monkas", "???", "wtf",
            "caraca", "mds", "nossa", "absurdo", "insano", "rachei", "socorro",
            "hahaha", "lmao", "lol", "😂", "🤣", "💀",
        ],
    },
    "corte": {
        "antes_segundos": 35,
        "depois_segundos": 12,
        "atraso_live_segundos": 0,
        "duracao_maxima": 59,
        "fps": 30,
        "layout_padrao": "auto",  # auto | split | blur | centro
        "legenda": True,
        "modelo_whisper": "small",
        "whisper_dispositivo": "auto",  # auto | cpu | cuda (só NVIDIA)
        "encoder": "auto",  # auto | nvidia | amd | intel | cpu  (placa de vídeo pra montar os clipes)
        "nitidez": 0.6,  # realce depois de ampliar (0 desliga, 1 forte)
        "idioma": "pt",
        "crf": 21,
    },
    "ia": {
        "usar_claude": True,
        "modelo": "claude-haiku-5-5",
        "respeitar_descarte": True,
        "montar_descartados": True,  # monta o vídeo dos descartados pra você conferir no painel
        "camauto_claude": True,  # se a detecção grátis de rosto não achar a cam, pergunta ao Claude
        "foco": "",  # ex.: "GTA 6" (vazio = qualquer conteúdo)
        "instrucoes_extras": "",
    },
    "publicacao": {
        "modo": "revisao",  # auto | revisao | nenhum
        "painel_host": "127.0.0.1",  # 0.0.0.0 = acessar de outro aparelho (exige painel_senha)
        "painel_porta": 8787,
        "painel_senha": "",          # senha do painel (usuário: vicopu). Obrigatória fora do 127.0.0.1
        "painel_link": "",           # endereço do painel visto de fora (ex.: http://100.x.y.z:8787), usado no aviso do celular
        "aviso_ntfy": "",            # tópico do app ntfy pra avisar no celular quando cair clipe (ex.: vicopu-luiz-8f3k2)
        # crédito do streamer em todo clipe. {streamer}, {link} e {link_curto} são trocados sozinhos
        "credito": "🎮 Corte da live de {streamer}. Live completa: {link}",
        "credito_tiktok": "🎮 Live: {link_curto}",
    },
    "youtube_app": {"client_secrets": "./credenciais/youtube_client_secret.json"},
    "tiktok_app": {"client_key": "", "client_secret": "", "redirect_uri": ""},
    "kick": {"pusher_key": "34bf7a0ff419a2a775b9", "pusher_cluster": "us2", "descobrir_chave": True},
    "contas": {"youtube": {}, "tiktok": {}},
    "canais": [],
}

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expandir(valor):
    if isinstance(valor, str):
        return _VAR.sub(lambda m: os.environ.get(m.group(1), ""), valor)
    if isinstance(valor, list):
        return [_expandir(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _expandir(v) for k, v in valor.items()}
    return valor


def _mesclar(base, extra):
    saida = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict):
            saida[k] = _mesclar(saida[k], v)
        else:
            saida[k] = v
    return saida


def preparar_canal(cfg, c):
    """Confere e completa um canal (do config ou do painel)."""
    if "nome" not in c or "plataforma" not in c or "canal" not in c:
        raise ValueError(f"Canal incompleto (precisa de nome, plataforma e canal): {c}")
    c.setdefault("layout", cfg["corte"]["layout_padrao"])
    c.setdefault("publicar_em", [])
    c.setdefault("hashtags", [])
    return c


def arquivo_canais_painel(cfg):
    return os.path.join(cfg["geral"]["pasta_trabalho"], "canais_painel.yaml")


def ler_canais_painel(cfg):
    """Canais adicionados pelo painel com o VICOPU rodando (ficam salvos fora do config.yaml)."""
    try:
        with open(arquivo_canais_painel(cfg), encoding="utf-8") as f:
            dados = yaml.safe_load(f) or []
        return [c for c in dados if isinstance(c, dict)]
    except OSError:
        return []


def salvar_canais_painel(cfg, canais):
    os.makedirs(cfg["geral"]["pasta_trabalho"], exist_ok=True)
    with open(arquivo_canais_painel(cfg), "w", encoding="utf-8") as f:
        f.write("# Canais adicionados pelo painel. Pode apagar daqui ou pelo painel.\n")
        yaml.safe_dump(canais, f, allow_unicode=True, sort_keys=False)


def arquivo_paradas(cfg):
    return os.path.join(cfg["geral"]["pasta_trabalho"], "lives_paradas.yaml")


def ler_paradas(cfg):
    """Nomes das lives do config.yaml que você parou pelo painel (continuam paradas ao reiniciar)."""
    try:
        with open(arquivo_paradas(cfg), encoding="utf-8") as f:
            dados = yaml.safe_load(f) or []
        return {str(n) for n in dados}
    except OSError:
        return set()


def salvar_paradas(cfg, nomes):
    os.makedirs(cfg["geral"]["pasta_trabalho"], exist_ok=True)
    with open(arquivo_paradas(cfg), "w", encoding="utf-8") as f:
        f.write("# Lives do config.yaml paradas pelo painel. Apague um nome daqui (ou use 'Vigiar de novo'"
                " no painel) pra voltar a vigiar.\n")
        yaml.safe_dump(sorted(nomes), f, allow_unicode=True)


def carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        bruto = yaml.safe_load(f) or {}
    cfg = _expandir(_mesclar(PADROES, bruto))
    nomes = set()
    for c in cfg["canais"]:
        preparar_canal(cfg, c)
        if c["nome"] in nomes:
            raise ValueError(f"Nome de canal repetido: {c['nome']}")
        nomes.add(c["nome"])
    os.makedirs(cfg["geral"]["pasta_trabalho"], exist_ok=True)
    paradas = ler_paradas(cfg)
    for c in cfg["canais"]:
        if c["nome"] in paradas:
            c["parado"] = True
    for c in ler_canais_painel(cfg):
        if c.get("nome") in nomes:
            continue  # o config.yaml manda
        try:
            preparar_canal(cfg, c)
        except ValueError:
            continue
        c["do_painel"] = True
        cfg["canais"].append(c)
        nomes.add(c["nome"])
    return cfg


def canal_do_link(link):
    """Transforma um link colado no painel em plataforma + canal + nome."""
    link = (link or "").strip()
    if not link:
        raise ValueError("cole o link da live")
    if not link.startswith("http"):
        link = "https://" + link
    u = urllib.parse.urlparse(link)
    host = u.netloc.lower().replace("www.", "").replace("m.", "", 1 if u.netloc.lower().startswith("m.") else 0)
    partes = [p for p in u.path.split("/") if p]
    if host.endswith("twitch.tv") and partes:
        slug = partes[0].lower()
        return {"plataforma": "twitch", "canal": slug, "nome": slug}
    if host.endswith("kick.com") and partes:
        slug = partes[0].lower()
        return {"plataforma": "kick", "canal": slug, "nome": slug}
    if host.endswith("youtube.com") or host == "youtu.be":
        if partes and partes[0].startswith("@"):
            slug = partes[0]
            return {"plataforma": "youtube", "canal": slug, "nome": slug[1:]}
        vid = urllib.parse.parse_qs(u.query).get("v", [None])[0] or (partes[-1] if partes else None)
        if vid:
            return {"plataforma": "youtube", "canal": f"https://www.youtube.com/watch?v={vid}",
                    "nome": f"yt_{vid[:8]}"}
    raise ValueError("não reconheci o link: use um link da Twitch, Kick ou YouTube")


def link_do_canal(canal):
    """Link da página do streamer (pra dar crédito): o canal, não a live do momento."""
    plat = canal["plataforma"].lower()
    alvo = str(canal["canal"])
    if alvo.startswith("http"):
        return alvo
    if plat == "twitch":
        return f"https://www.twitch.tv/{alvo}"
    if plat == "kick":
        return f"https://kick.com/{alvo}"
    if plat == "youtube":
        return f"https://www.youtube.com/{alvo if alvo.startswith('@') else '@' + alvo}"
    return ""


def credito(cfg, canal):
    """Texto de crédito do clipe (vazio se o canal tiver credito: false)."""
    if not canal or canal.get("credito", True) is False:
        return ""
    modelo = cfg["publicacao"].get("credito") or ""
    link = link_do_canal(canal)
    if not modelo or not link:
        return ""
    return modelo.format(streamer=canal.get("apelido", canal["nome"]), link=link,
                         link_curto=link.replace("https://", "").replace("www.", ""))


def url_da_live(canal):
    plat = canal["plataforma"].lower()
    alvo = str(canal["canal"])
    if alvo.startswith("http"):
        return alvo
    if plat == "twitch":
        return f"https://www.twitch.tv/{alvo}"
    if plat == "kick":
        return f"https://kick.com/{alvo}"
    if plat == "youtube":
        alvo = alvo if alvo.startswith("@") else "@" + alvo
        return f"https://www.youtube.com/{alvo}/live"
    if plat == "arquivo":
        return alvo
    raise ValueError(f"Plataforma desconhecida: {plat}")
