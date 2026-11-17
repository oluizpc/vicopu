"""Carrega o config.yaml do VICOPU, aplica os padrões e expande ${VARIAVEIS}."""
import copy
import os
import re

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
        "idioma": "pt",
        "crf": 21,
    },
    "ia": {
        "usar_claude": True,
        "modelo": "claude-haiku-5-5",
        "respeitar_descarte": True,
        "camauto_claude": True,  # se a detecção grátis de rosto não achar a cam, pergunta ao Claude
        "foco": "",  # ex.: "GTA 6" (vazio = qualquer conteúdo)
        "instrucoes_extras": "",
    },
    "publicacao": {
        "modo": "revisao",  # auto | revisao | nenhum
        "painel_host": "127.0.0.1",
        "painel_porta": 8787,
        # crédito do streamer em todo clipe. {streamer}, {link} e {link_curto} são trocados sozinhos
        "credito": "🎮 Corte da live de {streamer}. Live completa: {link}",
        "credito_tiktok": "🎮 Live: {link_curto}",
    },
    "youtube_app": {"client_secrets": "./credenciais/youtube_client_secret.json"},
    "tiktok_app": {"client_key": "", "client_secret": "", "redirect_uri": ""},
    "kick": {"pusher_key": "32cbd69e4b950bf97679", "pusher_cluster": "us2"},
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


def carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        bruto = yaml.safe_load(f) or {}
    cfg = _expandir(_mesclar(PADROES, bruto))
    nomes = set()
    for c in cfg["canais"]:
        if "nome" not in c or "plataforma" not in c or "canal" not in c:
            raise ValueError(f"Canal incompleto no config (precisa de nome, plataforma e canal): {c}")
        if c["nome"] in nomes:
            raise ValueError(f"Nome de canal repetido: {c['nome']}")
        nomes.add(c["nome"])
        c.setdefault("layout", cfg["corte"]["layout_padrao"])
        c.setdefault("publicar_em", [])
        c.setdefault("hashtags", [])
    os.makedirs(cfg["geral"]["pasta_trabalho"], exist_ok=True)
    return cfg


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
