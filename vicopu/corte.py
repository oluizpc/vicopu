"""CORTA: recorta do replay e monta o vídeo vertical 1080x1920 (Shorts/TikTok) com legenda."""
import logging
import os
import subprocess
import threading

log = logging.getLogger("corte")

L, A = 1080, 1920  # largura x altura do vertical
ALTURA_CAM = 640   # altura da faixa da facecam no layout "split"


def _rodar(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr.strip()[-800:]}")
    return r


def escrever_lista(segmentos, pasta):
    caminho = os.path.join(pasta, "lista.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        for s in segmentos:
            f.write(f"file '{os.path.abspath(s.caminho)}'\n")
    return caminho


def tem_audio(ffprobe, caminho):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", caminho], capture_output=True, text=True)
    return bool(r.stdout.strip())


def extrair_audio(ffmpeg, lista, inicio, duracao, pasta):
    saida = os.path.join(pasta, "audio.wav")
    # -ss/-t ANTES do -i: o trecho começa no tempo 0 (igual ao vídeo final, então a legenda bate)
    _rodar([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{duracao:.3f}",
            "-f", "concat", "-safe", "0", "-i", lista, "-vn", "-ac", "1", "-ar", "16000", saida])
    return saida


def grafo_layout(layout, facecam=None, centro_x=0.5):
    """Monta o filtro do ffmpeg para cada layout. Sai sempre em [v] 1080x1920."""
    if layout == "split":
        fc = facecam or {"x": 0.0, "y": 0.0, "w": 0.25, "h": 0.3}
        alt_jogo = A - ALTURA_CAM
        return (
            f"[0:v]split=2[cam][jogo];"
            f"[cam]crop=iw*{fc['w']}:ih*{fc['h']}:iw*{fc['x']}:ih*{fc['y']},"
            f"scale={L}:{ALTURA_CAM}:force_original_aspect_ratio=increase,crop={L}:{ALTURA_CAM}[topo];"
            f"[jogo]scale={L}:{alt_jogo}:force_original_aspect_ratio=increase,"
            f"crop={L}:{alt_jogo}:(iw-{L})*{centro_x}:0[base];"
            f"[topo][base]vstack=inputs=2,setsar=1[v]"
        )
    if layout == "centro":
        return (f"[0:v]scale={L}:{A}:force_original_aspect_ratio=increase,"
                f"crop={L}:{A}:(iw-{L})*{centro_x}:0,setsar=1[v]")
    # "blur": jogo inteiro no meio, fundo desfocado (bom quando não tem facecam)
    return (
        f"[0:v]split=2[f][p];"
        f"[f]scale={L}:{A}:force_original_aspect_ratio=increase,crop={L}:{A},boxblur=20:2,eq=brightness=-0.08[fundo];"
        f"[p]scale={L}:-2[meio];"
        f"[fundo][meio]overlay=0:(H-h)/2,setsar=1[v]"
    )


def altura_legenda(layout):
    if layout == "split":
        return ALTURA_CAM          # na divisa entre a cam e o jogo
    if layout == "blur":
        return int(A * 0.73)       # logo abaixo do jogo
    return int(A * 0.70)


def _tempo_ass(t):
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def gerar_ass(palavras, caminho, y, max_palavras=3, max_dur=1.3):
    """palavras: lista de (inicio, fim, texto) já relativas ao início do clipe."""
    cab = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Padrao,Arial,82,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,7,3,5,40,40,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    blocos, atual = [], []
    for p in palavras:
        if atual and (len(atual) >= max_palavras or p[1] - atual[0][0] > max_dur):
            blocos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        blocos.append(atual)
    linhas = []
    for i, b in enumerate(blocos):
        ini = b[0][0]
        fim = blocos[i + 1][0][0] if i + 1 < len(blocos) else b[-1][1] + 0.3
        fim = min(fim, b[-1][1] + 0.6)
        texto = " ".join(w[2].strip() for w in b).upper().replace("{", "").replace("}", "")
        cor = "{\\c&H00F0FF&}" if i % 2 else ""  # alterna branco / amarelo
        linhas.append(f"Dialogue: 0,{_tempo_ass(ini)},{_tempo_ass(fim)},Padrao,,0,0,0,,"
                      f"{{\\pos(540,{y})}}{cor}{texto}")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(cab + "\n".join(linhas) + "\n")
    return caminho


# ---------- codificador de vídeo: placa de vídeo quando der, processador quando não ----------
# ordem de tentativa no modo "auto": NVIDIA (NVENC), AMD (AMF), Intel (QuickSync), processador (x264)
ENCODERS = {
    "nvidia": "h264_nvenc",
    "amd": "h264_amf",
    "intel": "h264_qsv",
    "cpu": "libx264",
}
_escolhido = {}
_trava_enc = threading.Lock()


def _args_encoder(enc, crf):
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(crf + 2), "-b:v", "0",
                "-maxrate", "8M", "-bufsize", "16M"]
    if enc == "h264_amf":
        return ["-c:v", enc, "-quality", "balanced", "-rc", "vbr_peak", "-b:v", "6M", "-maxrate", "8M",
                "-bufsize", "16M"]
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", str(crf + 2), "-maxrate", "8M", "-bufsize", "16M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-maxrate", "8M", "-bufsize", "16M"]


def _funciona(ffmpeg, enc):
    """Codifica 1 segundinho de teste pra ver se essa placa existe e funciona nesta máquina."""
    r = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=0.5",
                        *_args_encoder(enc, 21), "-pix_fmt", "yuv420p", "-f", "null", "-"],
                       capture_output=True, timeout=60)
    return r.returncode == 0


def encoder_video(ffmpeg, preferencia="auto"):
    """Escolhe (uma vez só) o codificador de vídeo desta máquina."""
    preferencia = (preferencia or "auto").lower()
    with _trava_enc:
        if preferencia in _escolhido:
            return _escolhido[preferencia]
        if preferencia in ENCODERS:
            candidatos = [ENCODERS[preferencia]] if preferencia == "cpu" else [ENCODERS[preferencia], "libx264"]
        else:
            candidatos = [ENCODERS[k] for k in ("nvidia", "amd", "intel", "cpu")]
        for enc in candidatos:
            if enc == "libx264" or _funciona(ffmpeg, enc):
                break
        nomes = {"h264_nvenc": "placa NVIDIA (NVENC)", "h264_amf": "placa AMD (AMF)",
                 "h264_qsv": "Intel QuickSync", "libx264": "processador (x264)"}
        log.info("Montagem dos vídeos: usando %s.", nomes[enc])
        _escolhido[preferencia] = enc
        return enc


def _desistir_da_placa(preferencia):
    with _trava_enc:
        _escolhido[(preferencia or "auto").lower()] = "libx264"


def guardar_fonte(ffmpeg, lista, pasta):
    """Copia (sem recomprimir) o trecho bruto do replay pra pasta do clipe, pra dar pra
    ajustar o corte e montar de novo depois que o replay já foi apagado."""
    _rodar([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", os.path.abspath(lista), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-f", "mpegts", "fonte.ts"], cwd=pasta)
    caminho = os.path.join(pasta, "lista_fonte.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(os.path.join(pasta, 'fonte.ts'))}'\n")
    return caminho


def renderizar(ffmpeg, ffprobe, lista, inicio, duracao, pasta, layout="blur", facecam=None,
               centro_x=0.5, legenda_ass=None, fps=30, crf=21, primeiro_seg=None, encoder="auto",
               saida="final.mp4"):
    grafo = grafo_layout(layout, facecam, centro_x)
    if legenda_ass:
        grafo = grafo.replace("[v]", "[v0]") + f";[v0]subtitles={os.path.basename(legenda_ass)}[v]"
    # -ss/-t ANTES do -i: os filtros (inclusive a legenda) enxergam o clipe começando no tempo 0.
    # Com -ss depois do -i, a legenda era desenhada no tempo do replay e saía fora de sincronia.
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{duracao:.3f}",
           "-f", "concat", "-safe", "0", "-i", os.path.abspath(lista),
           "-filter_complex", grafo, "-map", "[v]"]
    if primeiro_seg is None or tem_audio(ffprobe, primeiro_seg):
        cmd += ["-map", "0:a:0?", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    enc = encoder_video(ffmpeg, encoder)
    fim = ["-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", saida]
    try:
        # cwd = pasta do clipe, assim a legenda não precisa de caminho com escape
        _rodar(cmd + _args_encoder(enc, crf) + fim, cwd=pasta)
    except RuntimeError as e:
        if enc == "libx264":
            raise
        # a placa falhou no meio (driver, limite de sessões...): refaz no processador e não insiste mais
        log.warning("A placa de vídeo falhou (%s). Passando a montar no processador.", str(e)[-200:])
        _desistir_da_placa(encoder)
        _rodar(cmd + _args_encoder("libx264", crf) + fim, cwd=pasta)
    return os.path.join(pasta, saida)
