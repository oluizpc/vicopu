"""Despacha um clipe pronto para os destinos do canal (ex.: ['youtube:meu_canal', 'tiktok:meu_tiktok'])."""
import logging

from ..config import credito

log = logging.getLogger("publicar")


def publicar(cfg, meta, destinos):
    resultados = {}
    tags = list(dict.fromkeys(meta.get("hashtags_fixas", []) + meta.get("hashtags", [])))
    tags = [t if t.startswith("#") else "#" + t for t in tags]
    canal = next((c for c in cfg["canais"] if c["nome"] == meta.get("canal")), None)
    cred = credito(cfg, canal)
    cred_tiktok = credito({**cfg, "publicacao": {**cfg["publicacao"],
                                                 "credito": cfg["publicacao"].get("credito_tiktok")}}, canal)
    for destino in destinos:
        plataforma, _, conta = destino.partition(":")
        opcoes = cfg["contas"].get(plataforma, {}).get(conta) or {}
        try:
            if plataforma == "youtube":
                from . import youtube
                resultados[destino] = youtube.enviar(
                    cfg, conta, meta["video"], meta["titulo"],
                    "\n\n".join(x for x in (meta.get("descricao", ""), cred, " ".join(tags)) if x), tags, opcoes)
            elif plataforma == "tiktok":
                from . import tiktok
                resultados[destino] = tiktok.enviar(
                    cfg, conta, meta["video"],
                    " ".join(x for x in (meta["titulo"], cred_tiktok, " ".join(tags)) if x), opcoes)
            else:
                resultados[destino] = f"ERRO: destino desconhecido '{destino}'"
        except Exception as e:
            log.error("Falha ao publicar em %s: %s", destino, e)
            resultados[destino] = f"ERRO: {e}"
    return resultados
