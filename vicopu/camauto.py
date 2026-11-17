"""Acha a webcam do streamer sozinho.

1) O Claude olha um quadro da live e diz onde está a webcam (caixa aproximada).
2) Um "ímã" de bordas encaixa a caixa na moldura real da cam, usando vários quadros
   (a moldura fica parada, o jogo se mexe; então a média dos quadros destaca a moldura).
Sem cam encontrada (ou sem chave do Claude) -> o canal usa o layout "blur".
"""
import base64
import json
import logging
import os
import re
import subprocess

import numpy as np

log = logging.getLogger("camauto")
LARG, ALT = 640, 360  # resolução de análise (rápida)

PROMPT = """Esta é uma imagem de uma live (jogo/stream). Encontre a WEBCAM do streamer: a janela onde aparece a pessoa REAL filmada pela câmera (não personagens do jogo, não avatares, não fotos estáticas, não emotes).
Responda SÓ com JSON, coordenadas em frações da imagem (0 a 1), cobrindo exatamente a área do vídeo da câmera (sem banners, nomes ou molduras decorativas em volta):
{"tem_cam": true, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
Se não houver webcam de pessoa real, responda {"tem_cam": false}."""


def extrair_quadros(ffmpeg, caminhos, n=5):
    """Pega n quadros (cinza, 640x360) espalhados pelos segmentos + 1 quadro colorido em JPEG."""
    cinzas, jpeg = [], None
    escolhidos = [caminhos[int(i * (len(caminhos) - 1) / max(1, n - 1))] for i in range(n)] if caminhos else []
    for i, cam in enumerate(escolhidos):
        r = subprocess.run([ffmpeg, "-v", "error", "-i", cam, "-frames:v", "1", "-vf",
                            f"scale={LARG}:{ALT}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True)
        if len(r.stdout) == LARG * ALT:
            cinzas.append(np.frombuffer(r.stdout, np.uint8).reshape(ALT, LARG).astype(np.float32))
        if i == len(escolhidos) // 2:
            r = subprocess.run([ffmpeg, "-v", "error", "-i", cam, "-frames:v", "1", "-vf", "scale=1280:720",
                                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"], capture_output=True)
            jpeg = r.stdout or None
    return cinzas, jpeg


def extrair_cinza_hd(ffmpeg, caminhos, n=5):
    """Quadros em cinza 1280x720 (rostos pequenos de webcam precisam de mais resolução)."""
    L, A = 1280, 720
    saida = []
    escolhidos = [caminhos[int(i * (len(caminhos) - 1) / max(1, n - 1))] for i in range(n)] if caminhos else []
    for cam in escolhidos:
        r = subprocess.run([ffmpeg, "-v", "error", "-i", cam, "-frames:v", "1", "-vf", f"scale={L}:{A}",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        if len(r.stdout) == L * A:
            saida.append(np.frombuffer(r.stdout, np.uint8).reshape(A, L))
    return saida


def achar_rosto_local(quadros):
    """Detecção de rosto grátis, no próprio PC (OpenCV). Só aceita rosto que fica PARADO no mesmo lugar
    em vários quadros: é assim que se diferencia a webcam de personagens do jogo, que se mexem.
    Retorna (x, y, w, h) em frações, ou None."""
    try:
        import cv2
    except ImportError:
        log.info("OpenCV não instalado: pulando a detecção local de rosto.")
        return None
    if not quadros:
        return None
    A, L = quadros[0].shape
    base = cv2.data.haarcascades
    frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
    perfil = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
    achados = []  # (indice_quadro, x, y, w, h)
    for i, q in enumerate(quadros):
        q = cv2.equalizeHist(q)
        caixas = list(frontal.detectMultiScale(q, 1.1, 6, minSize=(28, 28)))
        caixas += list(perfil.detectMultiScale(q, 1.1, 6, minSize=(28, 28)))
        espelho = cv2.flip(q, 1)  # o classificador de perfil só vê um lado; espelhando pega o outro
        for (x, y, w, h) in perfil.detectMultiScale(espelho, 1.1, 6, minSize=(28, 28)):
            caixas.append((L - x - w, y, w, h))
        achados += [(i, int(x), int(y), int(w), int(h)) for (x, y, w, h) in caixas]
    # agrupa rostos no mesmo lugar (centro a menos de 4% da tela) e conta em quantos quadros aparecem
    precisa = max(2, int(np.ceil(len(quadros) * 0.6)))
    candidatos = []
    for _, x, y, w, h in achados:
        cx, cy = x + w / 2, y + h / 2
        grupo = [a for a in achados if abs(a[1] + a[3] / 2 - cx) < 0.04 * L and abs(a[2] + a[4] / 2 - cy) < 0.04 * A]
        qtd = len({a[0] for a in grupo})
        if qtd >= precisa:
            caixa = tuple(int(np.median([a[k] for a in grupo])) for k in (1, 2, 3, 4))
            if caixa not in [c[1] for c in candidatos]:
                candidatos.append((qtd, caixa))
    if not candidatos:
        return None
    # Mais de um rosto parado (ex.: react, com o vídeo reagido no meio da tela): a webcam do streamer
    # quase sempre fica num canto. Ganha quem aparece em mais quadros; no empate, o mais perto da lateral.
    def nota(c):
        qtd, (x, y, w, h) = c
        dist_lateral = min(x + w / 2, L - (x + w / 2)) / L  # 0 = colado na lateral, 0.5 = no meio
        return (qtd, -dist_lateral)
    _, (x, y, w, h) = max(candidatos, key=nota)
    if len(candidatos) > 1:
        log.info("Achei %d rostos parados na tela; escolhi o mais perto da lateral (provável webcam).",
                 len(candidatos))
    return {"x": x / L, "y": y / A, "w": w / L, "h": h / A}


def moldura_a_partir_do_rosto(rosto, cinzas):
    """Sai do rosto pra fora, em cada direção, até achar a moldura da webcam (linha reta e contínua).
    Se não achar moldura num lado, usa o enquadramento típico de cam (ou a borda da tela)."""
    tipica = caixa_em_volta_do_rosto(rosto)
    if not cinzas:
        return tipica
    gx = np.mean([np.abs(np.diff(q, axis=1)) for q in cinzas], axis=0)
    gy = np.mean([np.abs(np.diff(q, axis=0)) for q in cinzas], axis=0)
    fx0, fx1 = rosto["x"] * LARG, (rosto["x"] + rosto["w"]) * LARG
    fy0, fy1 = rosto["y"] * ALT, (rosto["y"] + rosto["h"]) * ALT
    fw, fh = fx1 - fx0, fy1 - fy0
    # mede cada linha candidata só num trecho que com certeza está dentro da cam (a faixa do rosto)
    faixa_y = slice(max(0, int(fy0 - 0.3 * fh)), min(ALT, int(fy1 + 0.3 * fh)))
    faixa_x = slice(max(0, int(fx0 - 0.3 * fw)), min(LARG - 1, int(fx1 + 0.3 * fw)))
    limiar = 12.0
    perfil_x = (gx[faixa_y, :] > limiar).mean(axis=0)
    perfil_y = (gy[:, faixa_x] > limiar).mean(axis=1)

    def procurar(perfil, de, ate, padrao, borda_tela):
        de, ate = int(round(de)), int(round(ate))
        passo = 1 if ate >= de else -1
        idx = list(range(de, ate + passo, passo))
        idx = [i for i in idx if 0 <= i < len(perfil)]
        fortes = [i for i in idx if perfil[i] >= 0.8]  # linha quase inteira = moldura
        if fortes:
            return fortes[0]  # a primeira moldura saindo do rosto
        return borda_tela if borda_tela is not None else padrao

    tx0, ty0 = tipica["x"] * LARG, tipica["y"] * ALT
    tx1, ty1 = (tipica["x"] + tipica["w"]) * LARG, (tipica["y"] + tipica["h"]) * ALT
    folga_x, folga_y = 0.05 * LARG, 0.05 * ALT
    x0 = procurar(perfil_x, fx0 - 0.15 * fw, tx0 - folga_x, tx0, 0 if tx0 - folga_x <= 0 else None)
    x1 = procurar(perfil_x, fx1 + 0.15 * fw, tx1 + folga_x, tx1, LARG - 1 if tx1 + folga_x >= LARG - 1 else None)
    y0 = procurar(perfil_y, fy0 - 0.15 * fh, ty0 - folga_y, ty0, 0 if ty0 - folga_y <= 0 else None)
    y1 = procurar(perfil_y, fy1 + 0.15 * fh, ty1 + folga_y, ty1, ALT - 1 if ty1 + folga_y >= ALT - 1 else None)
    # a diferença (diff) fica entre o pixel i e i+1: a área da cam começa em i+1 (esq/topo) e acaba em i (dir/baixo)
    x0, y0 = (x0 + 1 if x0 > 0 else 0), (y0 + 1 if y0 > 0 else 0)
    x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1  # recua 1 px pra não pegar a linha da moldura
    if x1 - x0 < fw or y1 - y0 < fh:
        return tipica
    return {"x": round(max(0, x0) / LARG, 4), "y": round(max(0, y0) / ALT, 4),
            "w": round((x1 - max(0, x0)) / LARG, 4), "h": round((y1 - max(0, y0)) / ALT, 4)}


def caixa_em_volta_do_rosto(rosto):
    """Palpite da janela da webcam a partir do rosto (enquadramento típico de cam de streamer)."""
    x = rosto["x"] - 1.3 * rosto["w"]
    y = rosto["y"] - 0.9 * rosto["h"]
    w = rosto["w"] * 3.6
    h = rosto["h"] * 2.9
    x, y = max(0.0, x), max(0.0, y)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    return {"x": x, "y": y, "w": w, "h": h}


def perguntar_claude(jpeg, modelo):
    if not jpeg or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    r = anthropic.Anthropic().messages.create(
        model=modelo, max_tokens=200,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": PROMPT}]}])
    texto = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    dados = json.loads(re.search(r"\{.*\}", texto, re.S).group(0))
    if not dados.get("tem_cam"):
        return {"tem_cam": False}
    caixa = {k: float(dados[k]) for k in ("x", "y", "w", "h")}
    if caixa["w"] < 0.03 or caixa["h"] < 0.03:
        return {"tem_cam": False}
    return {"tem_cam": True, **caixa}


def _melhor_linha(perfil, centro, fora, dentro, sentido):
    """Procura, perto de 'centro', a linha reta mais contínua (moldura). Retorna o índice ou None.

    perfil = fração do lado da caixa coberta por borda forte em cada posição (0 a 1).
    Linhas mais perto do palpite do Claude ganham um bônus, pra não pular pra molduras vizinhas.
    """
    # sentido -1 = a moldura está à esquerda/acima do ponto de partida; +1 = à direita/abaixo
    if sentido < 0:
        a, b = centro - fora, centro + dentro
    else:
        a, b = centro - dentro, centro + fora
    a, b = max(0, a), min(len(perfil) - 1, b)
    janela = perfil[a:b + 1]
    if len(janela) < 3:
        return None
    dist = np.abs(np.arange(a, b + 1) - centro) / max(fora, 1)
    nota = janela * (1.0 - 0.3 * dist)
    i = int(np.argmax(nota))
    if janela[i] < 0.5:  # menos da metade do lado é borda: não é uma moldura de verdade
        return None
    return a + i


def refinar(caixa, cinzas):
    """Encaixa a caixa aproximada nas bordas reais da cam (frações 0-1 entram e saem)."""
    if not cinzas:
        return caixa
    gx = np.mean([np.abs(np.diff(q, axis=1)) for q in cinzas], axis=0)  # bordas verticais
    gy = np.mean([np.abs(np.diff(q, axis=0)) for q in cinzas], axis=0)  # bordas horizontais
    x0, x1 = int(caixa["x"] * LARG), int((caixa["x"] + caixa["w"]) * LARG)
    y0, y1 = int(caixa["y"] * ALT), int((caixa["y"] + caixa["h"]) * ALT)
    # começa um pouco pra dentro: a borda mais próxima "de dentro pra fora" é a moldura da cam,
    # e não a de algum banner/chat colado nela (exceto quando o lado está colado na tela)
    dx, dy = int(0.10 * (x1 - x0)), int(0.10 * (y1 - y0))
    x0 = x0 if x0 <= 3 else x0 + dx
    x1 = x1 if x1 >= LARG - 4 else x1 - dx
    y0 = y0 if y0 <= 3 else y0 + dy
    y1 = y1 if y1 >= ALT - 4 else y1 - dy
    # perfis: força média da borda ao longo do lado da caixa (só o miolo do lado, sem os cantos)
    m_y = slice(max(0, y0 + (y1 - y0) // 6), min(ALT, y1 - (y1 - y0) // 6))
    m_x = slice(max(0, x0 + (x1 - x0) // 6), min(LARG - 1, x1 - (x1 - x0) // 6))
    limiar = 12.0  # diferença de brilho que conta como "borda"
    perfil_x = (gx[m_y, :] > limiar).mean(axis=0)   # quanto de cada coluna é borda
    perfil_y = (gy[:, m_x] > limiar).mean(axis=1)   # quanto de cada linha é borda
    novo = {}
    for nome, perfil, c, deslocar, limite, sentido in (
            ("x0", perfil_x, x0, 1, LARG, -1), ("x1", perfil_x, x1, 1, LARG, 1),
            ("y0", perfil_y, y0, 1, ALT, -1), ("y1", perfil_y, y1, 1, ALT, 1)):
        fora, dentro = int(0.12 * limite), int(0.02 * limite)
        if c <= 3:
            novo[nome] = 0          # colada na borda da tela
            continue
        if c >= limite - 4:
            novo[nome] = limite
            continue
        linha = _melhor_linha(perfil, c, fora, dentro, sentido)
        if linha is None and (c - fora <= 0 if sentido < 0 else c + fora >= limite - 1):
            linha = -1 if sentido < 0 else limite - 1  # sem moldura até a borda da tela: cam colada nela
        # diff desloca meio pixel: a borda entre i e i+1 vira o início da área em i+1
        novo[nome] = c if linha is None else linha + deslocar
    x0, x1, y0, y1 = novo["x0"], novo["x1"], novo["y0"], novo["y1"]
    if x1 - x0 < 0.03 * LARG or y1 - y0 < 0.03 * ALT:
        return caixa
    # recua 1 px pra não pegar a linha da moldura
    x0, y0 = min(x0 + 1, x1), min(y0 + 1, y1)
    x1, y1 = max(x1 - 1, x0), max(y1 - 1, y0)
    return {"x": round(x0 / LARG, 4), "y": round(y0 / ALT, 4),
            "w": round((x1 - x0) / LARG, 4), "h": round((y1 - y0) / ALT, 4)}


def salvar_previa(ffmpeg, segmento, caixa, destino):
    """Imagem com um retângulo verde onde o VICOPU achou a cam (pra você conferir)."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    filtro = "scale=960:540"
    if caixa:
        filtro += (f",drawbox=x=iw*{caixa['x']}:y=ih*{caixa['y']}:w=iw*{caixa['w']}:h=ih*{caixa['h']}"
                   f":color=lime:t=4")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", segmento, "-frames:v", "1", "-vf", filtro, destino],
                   capture_output=True)


def detectar(cfg, caminhos_segmentos, nome_canal):
    """Retorna dict facecam (frações) ou None se não houver cam."""
    ff = cfg["geral"]["ffmpeg"]
    cinzas, jpeg = extrair_quadros(ff, caminhos_segmentos)

    # 1) grátis: detecção de rosto no próprio PC
    rosto = achar_rosto_local(extrair_cinza_hd(ff, caminhos_segmentos))
    usa_claude = cfg["ia"].get("camauto_claude", True) and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if rosto and usa_claude:
        centro = rosto["x"] + rosto["w"] / 2
        if 0.3 < centro < 0.7:
            # rosto no meio da tela costuma ser CONTEÚDO (react, vídeo, cutscene), não a webcam:
            # nesse caso quem decide é o Claude, que entende o layout inteiro
            log.info("[%s] Rosto achado no meio da tela (pode ser o vídeo de um react). Confirmando com o Claude...",
                     nome_canal)
            rosto = None
    if rosto:
        final = moldura_a_partir_do_rosto(rosto, cinzas)
        log.info("[%s] Cam encontrada (rosto local, grátis): %s", nome_canal, final)
        destino = os.path.join(cfg["geral"]["pasta_trabalho"], "camauto", f"{nome_canal}.jpg")
        salvar_previa(ff, caminhos_segmentos[len(caminhos_segmentos) // 2], final, destino)
        return final
    else:
        # 2) não achou rosto parado (streamer de perfil, cam pequena...): pergunta ao Claude
        if not cfg["ia"].get("camauto_claude", True):
            log.info("[%s] Nenhum rosto achado localmente e o Claude está desligado. Usando blur.", nome_canal)
            return None
        try:
            resposta = perguntar_claude(jpeg, cfg["ia"]["modelo"])
        except Exception as e:
            log.warning("[%s] Claude não conseguiu analisar a cam (%s).", nome_canal, e)
            resposta = None
        if resposta is None:
            log.info("[%s] Nenhum rosto achado localmente (e sem ANTHROPIC_API_KEY pro Claude). Usando blur.",
                     nome_canal)
            return None
        if not resposta["tem_cam"]:
            log.info("[%s] Nenhuma webcam na tela. Usando blur.", nome_canal)
            return None
        bruta, fonte = {k: resposta[k] for k in ("x", "y", "w", "h")}, "Claude"
    final = refinar(bruta, cinzas)
    log.info("[%s] Cam encontrada (%s): %s", nome_canal, fonte, final)
    destino = os.path.join(cfg["geral"]["pasta_trabalho"], "camauto", f"{nome_canal}.jpg")
    salvar_previa(ff, caminhos_segmentos[len(caminhos_segmentos) // 2], final, destino)
    return final
