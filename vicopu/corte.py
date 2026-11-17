"""CORTA: recorta do replay e monta o vídeo vertical 1080x1920 (Shorts/TikTok) com legenda."""
import os
import subprocess

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


def renderizar(ffmpeg, ffprobe, lista, inicio, duracao, pasta, layout="blur", facecam=None,
               centro_x=0.5, legenda_ass=None, fps=30, crf=21, primeiro_seg=None):
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
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-maxrate", "8M",
            "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart",
            "final.mp4"]
    _rodar(cmd, cwd=pasta)  # cwd = pasta do clipe, assim a legenda não precisa de caminho com escape
    return os.path.join(pasta, "final.mp4")
