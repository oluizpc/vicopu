"""Despacha um clipe pronto para os destinos do canal (ex.: ['youtube:meu_canal', 'tiktok:meu_tiktok'])."""
import logging

log = logging.getLogger("publicar")


def publicar(cfg, meta, destinos):
    resultados = {}
    tags = list(dict.fromkeys(meta.get("hashtags_fixas", []) + meta.get("hashtags", [])))
    tags = [t if t.startswith("#") else "#" + t for t in tags]
    for destino in destinos:
        plataforma, _, conta = destino.partition(":")
        opcoes = cfg["contas"].get(plataforma, {}).get(conta) or {}
        try:
            if plataforma == "youtube":
                from . import youtube
                resultados[destino] = youtube.enviar(
                    cfg, conta, meta["video"], meta["titulo"],
                    f"{meta['descricao']}\n\n{' '.join(tags)}", tags, opcoes)
            elif plataforma == "tiktok":
                from . import tiktok
                resultados[destino] = tiktok.enviar(
                    cfg, conta, meta["video"], f"{meta['titulo']} {' '.join(tags)}", opcoes)
            else:
                resultados[destino] = f"ERRO: destino desconhecido '{destino}'"
        except Exception as e:
            log.error("Falha ao publicar em %s: %s", destino, e)
            resultados[destino] = f"ERRO: {e}"
    return resultados
