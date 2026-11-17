"""VICOPU: vigia, corta e publica.

Uso:
  python -m vicopu rodar                     # liga tudo (vigias + cortes + painel)
  python -m vicopu auth-youtube <conta>      # autoriza um canal do YouTube (uma vez)
  python -m vicopu auth-tiktok <conta>       # autoriza uma conta do TikTok (uma vez)
  python -m vicopu testar-layout <canal> <video.mp4>   # gera 20 s de teste p/ calibrar a facecam
"""
import argparse
import logging
import os

# avisos inofensivos da biblioteca que baixa o modelo de legenda (Windows sem symlinks, sem token)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
import warnings  # noqa: E402
warnings.filterwarnings("ignore", module="huggingface_hub")
import shutil
import sys
import time

from . import config as cfgmod


def rodar(cfg):
    from . import painel
    from .nucleo import Central, Fabrica

    if not shutil.which(cfg["geral"]["ffmpeg"]):
        sys.exit("ffmpeg não encontrado. Instale e deixe no PATH (ou ajuste geral.ffmpeg no config).")
    if not cfg["canais"]:
        logging.getLogger("vicopu").warning("Nenhum canal no config: adicione lives pelo painel.")
    from . import corte
    corte.encoder_video(cfg["geral"]["ffmpeg"], cfg["corte"].get("encoder", "auto"))  # descobre a placa já na largada
    fabrica = Fabrica(cfg)
    central = Central(cfg, fabrica)
    central.iniciar()
    p = cfg["publicacao"]
    painel.iniciar(fabrica, central, p["painel_host"], p["painel_porta"])
    log = logging.getLogger("vicopu")
    extras = sum(1 for v in central.lista() if v.canal.get("do_painel"))
    paradas = [c["nome"] for c in central.paradas()]
    log.info("VICOPU no ar: %d canal(is)%s. Painel em http://%s:%s  (Ctrl+C para sair)",
             len(central.lista()), f" ({extras} adicionado(s) pelo painel)" if extras else "",
             p["painel_host"], p["painel_porta"])
    if paradas:
        log.info("Paradas (não estou vigiando): %s. Pra voltar: 'Vigiar de novo' no painel.", ", ".join(paradas))
    try:
        while True:
            for v in central.lista():
                v.detector.tick()
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Desligando...")
        for v in central.lista():
            v.parar()
        fabrica.pool.shutdown(wait=False, cancel_futures=True)
        logging.shutdown()
        os._exit(0)  # sai na hora, sem esperar corte/download pela metade


def testar_layout(cfg, nome, video):
    from . import corte

    canal = next((c for c in cfg["canais"] if c["nome"] == nome), None)
    if not canal:
        sys.exit(f"Canal '{nome}' não está no config.")
    pasta = os.path.join(cfg["geral"]["pasta_trabalho"], "teste_layout", nome)
    os.makedirs(pasta, exist_ok=True)

    class S:
        caminho = os.path.abspath(video)
    lista = corte.escrever_lista([S], pasta)
    saida = corte.renderizar(cfg["geral"]["ffmpeg"], shutil.which("ffprobe") or "ffprobe", lista, 0, 20,
                             pasta, canal["layout"], canal.get("facecam"), canal.get("centro_x", 0.5),
                             None, cfg["corte"]["fps"], cfg["corte"]["crf"])
    print(f"Teste salvo em {saida}. Ajuste 'facecam' (x, y, w, h em frações da tela) até a cam ficar certinha.")


def _desligar_selecao_do_console():
    """No Windows, clicar/selecionar texto no Prompt de Comando (QuickEdit) CONGELA o programa
    até apertar uma tecla: o VICOPU parava de cortar e o painel travava. Desliga isso nesta janela.
    (Pra copiar o log, use o arquivo dados/vicopu.log.)"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)  # entrada do console
        modo = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(modo)):
            k.SetConsoleMode(h, (modo.value & ~0x0040) | 0x0080)  # tira QUICK_EDIT, mantém EXTENDED_FLAGS
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser(prog="vicopu", description="VICOPU: vigia, corta e publica.")
    ap.add_argument("-c", "--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rodar")
    a = sub.add_parser("auth-youtube")
    a.add_argument("conta")
    a.add_argument("--porta", type=int, default=8090)
    a.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador (servidor sem tela)")
    b = sub.add_parser("auth-tiktok")
    b.add_argument("conta")
    t = sub.add_parser("testar-layout")
    t.add_argument("canal")
    t.add_argument("video")
    args = ap.parse_args()

    cfg = cfgmod.carregar(args.config)
    logging.basicConfig(level=cfg["geral"]["log_nivel"],
                        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    if args.cmd == "rodar":
        _desligar_selecao_do_console()
        try:  # cópia do log em arquivo (dados/vicopu.log), pra mandar/consultar sem copiar do terminal
            from logging.handlers import RotatingFileHandler
            arq = RotatingFileHandler(os.path.join(cfg["geral"]["pasta_trabalho"], "vicopu.log"),
                                      maxBytes=5_000_000, backupCount=2, encoding="utf-8")
            arq.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                                               datefmt="%Y-%m-%d %H:%M:%S"))
            logging.getLogger().addHandler(arq)
        except OSError:
            pass

    for barulhento in ("httpx", "httpx2", "httpcore", "faster_whisper", "googleapiclient"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)  # esconde o log interno das bibliotecas
    if args.cmd == "rodar":
        rodar(cfg)
    elif args.cmd == "auth-youtube":
        from .publicar import youtube
        youtube.autorizar(cfg, args.conta, args.porta, not args.sem_navegador)
    elif args.cmd == "auth-tiktok":
        from .publicar import tiktok
        tiktok.autorizar(cfg, args.conta)
    elif args.cmd == "testar-layout":
        testar_layout(cfg, args.canal, args.video)


if __name__ == "__main__":
    main()
