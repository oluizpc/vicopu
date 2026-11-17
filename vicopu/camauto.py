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
    try:
        resposta = perguntar_claude(jpeg, cfg["ia"]["modelo"])
    except Exception as e:
        log.warning("[%s] Claude não conseguiu analisar a cam (%s).", nome_canal, e)
        resposta = None
    if resposta is None:
        log.warning("[%s] Detecção automática da cam precisa da ANTHROPIC_API_KEY. Usando blur.", nome_canal)
        return None
    if not resposta["tem_cam"]:
        log.info("[%s] Nenhuma webcam na tela. Usando blur.", nome_canal)
        return None
    bruta = {k: resposta[k] for k in ("x", "y", "w", "h")}
    final = refinar(bruta, cinzas)
    log.info("[%s] Cam encontrada: %s (Claude: %s)", nome_canal, final, bruta)
    destino = os.path.join(cfg["geral"]["pasta_trabalho"], "camauto", f"{nome_canal}.jpg")
    salvar_previa(ff, caminhos_segmentos[len(caminhos_segmentos) // 2], final, destino)
    return final
