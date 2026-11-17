# VICOPU: VIgia, COrta e PUblica

O VICOPU assiste várias lives ao mesmo tempo (Twitch, Kick e YouTube), percebe sozinho quando algo interessante acontece e corta o momento **enquanto a live ainda está rolando**. O clipe sai em vídeo vertical 1080x1920, com a webcam do streamer em cima, o jogo embaixo, legenda sincronizada, título escrito por IA e crédito do streamer. Depois, você aprova no painel e ele publica no YouTube Shorts ou no TikTok.

Tudo roda **no seu computador**. Não precisa de servidor, e o único custo é a API do Claude, de centavos por dia.

```
 live ──► captura contínua ──► replay dos últimos 5 min (sem recodificar)
 chat ──► detector: pico de mensagens + palavras de reação + pico de volume ──► MOMENTO!
                                                                    │
     ┌──────────────────────────────────────────────────────────────┘
     ▼
 recorta 35 s antes + 12 s depois ─► legenda (Whisper) ─► Claude: vale a pena? título? onde cortar?
     ─► vídeo vertical 1080x1920 (placa de vídeo) ─► painel ─► YouTube Shorts / TikTok
```

---

## Sumário

1. [O que você precisa](#1-o-que-você-precisa)
2. [Instalação no Windows, passo a passo](#2-instalação-no-windows-passo-a-passo)
3. [Primeiro teste em 5 minutos](#3-primeiro-teste-em-5-minutos)
4. [Chave do Claude](#4-chave-do-claude)
5. [Configurando as lives (`config.yaml`)](#5-configurando-as-lives-configyaml)
6. [O painel](#6-o-painel)
7. [Publicar no YouTube](#7-publicar-no-youtube)
8. [Publicar no TikTok](#8-publicar-no-tiktok)
9. [Como a detecção funciona e como calibrar](#9-como-a-detecção-funciona-e-como-calibrar)
10. [Webcam automática (layout `auto`)](#10-webcam-automática-layout-auto)
11. [Placa de vídeo](#11-placa-de-vídeo)
12. [Atualizar o VICOPU](#12-atualizar-o-vicopu)
13. [Checklist pra um dia de lançamento](#13-checklist-pra-um-dia-de-lançamento)
14. [Lendo o log](#14-lendo-o-log)
15. [Problemas comuns](#15-problemas-comuns)
16. [Custos, direitos e monetização](#16-custos-direitos-e-monetização)
17. [Referência completa do config](#17-referência-completa-do-config)
18. [Estrutura do projeto](#18-estrutura-do-projeto)

---

## 1. O que você precisa

- **Windows 10 ou 11.** Também roda em Linux e Mac, com comandos equivalentes.
- **Python 3.10 ou mais novo.** Testado com o 3.14.
- **ffmpeg**, o programa que corta e monta os vídeos.
- **git**, pra baixar e atualizar o VICOPU.
- **Internet estável.** Cada live em 1080p puxa uns 6 a 8 Mbps o tempo todo.
- **Opcional, mas recomendado:** uma chave da API do Claude, pra títulos, filtro de qualidade e detecção da webcam.
- **Opcional:** placa de vídeo AMD, NVIDIA ou Intel, pra montar os clipes mais rápido.

---

## 2. Instalação no Windows, passo a passo

Abra o **Prompt de Comando** e rode **um comando por vez**, esperando cada um terminar.

### 2.1 Instalar os programas (uma vez só)

```bat
winget install Python.Python.3.14
```
Se aparecer `Do you agree to all the source agreements terms? [Y] Yes [N] No`, digite **y** e Enter.

```bat
winget install Gyan.FFmpeg
```
```bat
winget install Git.Git
```

> ⚠️ Rode os três **separados**. Se você colar todos de uma vez, a pergunta do winget "engole" os comandos seguintes.

**Feche o Prompt e abra um novo**, e confira se os três respondem:
```bat
py --version
ffmpeg -version
git --version
```
Use **`py`**, e não `python`, antes de criar o ambiente. O `py` sempre funciona depois de instalar o Python.

### 2.2 Baixar o VICOPU

```bat
cd C:\
git clone https://github.com/oluizpc/vicopu.git
cd vicopu
```
Como o repositório é privado, na primeira vez abre uma janela de login do GitHub. Entre com a conta dona do repo.

> Não instale em `C:\Program Files`, porque o Windows bloqueia gravação lá. `C:\vicopu` é o lugar certo.

### 2.3 Criar o ambiente e instalar as bibliotecas

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Depois do `activate`, aparece `(.venv)` no começo da linha. **Sempre** que abrir um Prompt novo pra usar o VICOPU, rode antes:
```bat
cd C:\vicopu
.venv\Scripts\activate
```

### 2.4 Criar o seu config

```bat
copy config.exemplo.yaml config.yaml
```
Ou, pra usar a lista pronta do lançamento do GTA 6:
```bat
copy config.gta6.yaml config.yaml
```
O `config.yaml` é **seu**: ele não vai pro git, e o `git pull` nunca mexe nele. Cada computador tem o próprio.

### 2.5 Atalhos de dois cliques (recomendado)

Na pasta `C:\vicopu` tem dois arquivos que fazem tudo sozinhos:
- **`iniciar.bat`:** entra na pasta, ativa o `.venv` certo, liga o VICOPU e abre o painel no navegador. Pra desligar, Ctrl+C na janela.
- **`atualizar.bat`:** baixa a versão nova (`git pull`) e instala o que mudou.

Dica: clique com o botão direito no `iniciar.bat` → **Enviar para → Área de trabalho (criar atalho)**.

**Pelo Prompt, o equivalente é** (um comando por linha):
```bat
cd C:\vicopu
.venv\Scripts\activate
python -m vicopu rodar
```
A linha precisa mostrar `(.venv) C:\vicopu>` antes do último comando. Se aparecer `(.venv)` mas a pasta for outra (ex.: `C:\Users\voce`), rode `deactivate` e comece pelo `cd`.

---

## 3. Primeiro teste em 5 minutos

1. Ache uma live qualquer que esteja no ar e abra o config:
   ```bat
   notepad config.yaml
   ```
2. Apague tudo (Ctrl+A, Delete) e cole, trocando o canal:
   ```yaml
   publicacao:
     modo: nenhum

   canais:
     - nome: teste
       apelido: NomeDoStreamer
       plataforma: twitch          # twitch | kick | youtube
       canal: nome_na_url          # twitch.tv/NOME  ·  kick.com/NOME  ·  YouTube: "@handle"
       layout: auto
       publicar_em: []
   ```
   ⚠️ **Os espaços no começo das linhas fazem parte do formato.** Cole exatamente como está.
3. Salve com Ctrl+S e rode:
   ```bat
   python -m vicopu rodar
   ```
4. Espere aparecer `NO AR. Vigiando.`, abra **http://127.0.0.1:8787** e clique em **✂ Cortar agora**.
5. Em 1 a 2 minutos, o clipe aparece no painel. Ele também fica salvo em `C:\vicopu\dados\clipes\`.

Na primeira vez, o VICOPU baixa o modelo de legenda (uns 500 MB), então o primeiro corte demora mais.

Pra desligar: **Ctrl+C** no Prompt.

---

## 4. Chave do Claude

O Claude faz três coisas no VICOPU:
- **avalia** cada clipe e descarta os fracos sozinho;
- **escreve** o título e a descrição, e acerta o começo e o fim do corte;
- **acha a webcam** quando a detecção grátis não consegue.

Sem a chave, o VICOPU funciona, mas com título genérico, sem filtro de qualidade e com webcam só pela detecção grátis.

1. Entre em **https://platform.claude.com**, coloque crédito em **Adicionar saldo** (US$ 5 duram bastante) e deixe a recarga automática **desligada**.
2. Vá em **Chaves de API → + Criar chave → "Em outro lugar"**. Dê o nome `vicopu` e deixe expirar em **Nunca**.
3. **Copie a chave na hora**, porque ela só aparece uma vez. Cole direto no Prompt:
   ```bat
   setx ANTHROPIC_API_KEY "sk-ant-sua-chave"
   ```
4. **Feche e abra o Prompt de novo.** O `setx` só vale pra janelas novas.

Pra conferir sem mostrar a chave inteira: `echo %ANTHROPIC_API_KEY:~0,10%`

> 🔒 Nunca coloque a chave no `config.yaml` nem em nenhum arquivo do repo, e não mande em chat ou print.

---

## 5. Configurando as lives (`config.yaml`)

Cada live é um bloco em `canais:`. Pode ter quantas quiser. **Quem estiver offline não gasta nada**: o VICOPU checa a cada 60 segundos e começa a vigiar sozinho quando a live abrir.

```yaml
canais:
  - nome: alanzoka               # identificador único (sem espaço)
    apelido: Alanzoka            # nome do streamer no título e no crédito
    plataforma: twitch           # twitch | kick | youtube
    canal: alanzoka              # ver tabela abaixo
    layout: auto                 # auto | split | blur | centro
    sensibilidade: baixa         # alta | normal | baixa
    idioma: pt                   # pt, en, es... ("" = detectar sozinho)
    hashtags: ["#gta6", "#alanzoka"]
    publicar_em: [youtube:principal]
```

**O que vai em `canal:`**

| Plataforma | O que colocar | Exemplo |
|---|---|---|
| Twitch | o nome que aparece em `twitch.tv/...` | `alanzoka` |
| Kick | o nome que aparece em `kick.com/...` | `nomedocanal` |
| YouTube | o **@ do canal**, entre aspas | `"@IShowSpeed"` |

> No YouTube, use **sempre o @**, e não o link `watch?v=...`: o link do vídeo muda a cada live, e o @ sempre aponta pra live atual.

**Sensibilidade, de acordo com o tamanho do chat**

| Valor | Pra quem |
|---|---|
| `alta` | streamer pequeno, com chat calmo |
| `normal` | streamer médio (é o padrão) |
| `baixa` | streamer gigante, com chat sempre lotado |

Ajuste fino só pra um canal: `deteccao: {cooldown_segundos: 60, multiplicador_pico: 5}` dentro do bloco dele.

**Dica pro Claude** (na seção `ia:`):
```yaml
ia:
  foco: "GTA 6"
  instrucoes_extras: "Nunca dê spoiler da história no título nem na descrição."
```

A lista de **todas** as opções está na [seção 17](#17-referência-completa-do-config).

---

## 6. O painel

Abra **http://127.0.0.1:8787** com o VICOPU ligado. A página atualiza sozinha a cada 4 segundos e **não perde o que você está digitando**.

**Lives:** cada uma tem plataforma, status (ao vivo ou offline), layout, sensibilidade, número de clipes e o botão **✂ Cortar agora**, que corta na hora sem depender do chat.

**Clipes**, separados em abas: **Aguardando você · Em andamento · Publicados · Descartados · Todos**.

Em cada clipe:
- **selos** com a duração e a nota da IA (verde, amarelo ou vermelho);
- **título editável**, salvo sozinho;
- **prévia do post**: a descrição como vai sair no YouTube (texto, crédito e hashtags) e, ao abrir, a legenda do TikTok;
- botões **Publicar · ⬇ Baixar · 📋 Copiar · Descartar · 🗑 Excluir**;
- **"Por que esse clipe?"**, com o motivo do corte e a avaliação da IA;
- depois de publicado: os links **abrir** e **abrir no Studio**.

**Seleção em lote:** clique na caixinha ✓ de cada clipe. **Shift+clique** marca um intervalo, e **Esc** limpa a seleção. Na barra roxa aparecem **Selecionar todos da aba · Publicar · Descartar · Excluir**. Clipes que não podem receber a ação são pulados, e o painel mostra o motivo.

**Postar na mão:** use **⬇ Baixar** e **📋 Copiar**. O Copiar leva título, descrição, crédito e hashtags juntos.

Por segurança, o painel só abre no próprio PC (`painel_host: 127.0.0.1`).

---

## 7. Publicar no YouTube

### 7.1 Criar o app no Google Cloud (uma vez só)

1. Em **console.cloud.google.com**, abra o seletor de projetos e clique em **Novo projeto**. Nome: `vicopu`. Não precisa ativar o teste gratuito nem cadastrar cartão.
2. **Ative a API:** console.cloud.google.com/apis/library/youtube.googleapis.com → **Ativar**.
3. **Tela de permissão:** Google Auth Platform → **Começar**.
   - Nome do app: `VICOPU`, e o seu e-mail de suporte.
   - Público: **Externo**. Contato: o seu e-mail. Aceite e clique em **Criar**.
4. **Usuários de teste:** em **Público-alvo**, clique em **+ Add users** e adicione o **Gmail dono de cada canal** que vai publicar.
5. **Credencial:** em **Clientes**, clique em **+ Criar cliente**, escolha **App para computador**, nome `vicopu`, e depois **Baixar JSON**.
6. **Salve o arquivo** em `C:\vicopu\credenciais\youtube_client_secret.json`. Rode **numa linha só**:
   ```bat
   mkdir C:\vicopu\credenciais
   move "%USERPROFILE%\Downloads\client_secret_*.json" C:\vicopu\credenciais\youtube_client_secret.json
   ```

### 7.2 Autorizar um canal

```bat
python -m vicopu auth-youtube principal
```
1. O navegador abre. Entre com a **conta dona do canal**.
2. Na tela "O Google não verificou este app", clique em **Avançado → Acessar VICOPU**. O app é seu, então pode seguir.
3. **Continuar**. Se perguntar, escolha o canal.
4. No Prompt aparece `OK! Token salvo em ./dados\credenciais\youtube_principal.json`.

Se o navegador abrir com a conta errada e der "Acesso bloqueado", copie o link que aparece no Prompt (selecione e clique com o botão direito) e abra numa **janela anônima** (Ctrl+Shift+N).

### 7.3 Ligar no config

```yaml
contas:
  youtube:
    principal:
      privacidade: private       # private | unlisted | public

canais:
  - nome: ...
    publicar_em: [youtube:principal]
```

### 7.4 Coisas importantes do YouTube

- **Os vídeos sobem privados.** Projetos ainda não auditados pelo Google sobem como privados. Nos testes, deu pra mudar pra **público** depois, no YouTube Studio: o painel tem o atalho **abrir no Studio**, e o app do YouTube Studio no celular também serve.
- **Autorização que vence:** em modo "Teste", o Google derruba a autorização a cada **7 dias**. Pra uso contínuo, vá em **Público-alvo → Publicar app**.
- **Cota diária:** o limite padrão permite poucos uploads por dia. Peça aumento na página da YouTube Data API v3, na aba **"Cotas e limites do sistema"**. Pode levar dias.
- **Mais de um canal:** use o mesmo projeto e a mesma credencial. Adicione o usuário de teste e rode `auth-youtube` com outro nome.
- **Vários computadores:** copie `credenciais\youtube_client_secret.json` e `dados\credenciais\youtube_*.json`, ou refaça o `auth-youtube` em cada máquina.

---

## 8. Publicar no TikTok

> ⚠️ A parte do TikTok está implementada, mas **ainda não foi testada com uma conta real**.

1. Em **developers.tiktok.com**, crie um app com **Login Kit** e **Content Posting API**. Os escopos são `video.upload` e `video.publish`, e o redirect URI é qualquer URL https sua.
2. Guarde a chave e o segredo do app no Windows (`setx TIKTOK_CLIENT_KEY "..."` e `setx TIKTOK_CLIENT_SECRET "..."`, depois feche e abra o Prompt) e adicione ao `config.yaml`:
   ```yaml
   tiktok_app:
     client_key: ${TIKTOK_CLIENT_KEY}        # lido do Windows, não escreva a chave aqui
     client_secret: ${TIKTOK_CLIENT_SECRET}
     redirect_uri: https://seusite.com/tiktok/callback
   ```
3. Rode `python -m vicopu auth-tiktok minhaconta`, autorize e cole de volta o endereço completo da barra do navegador.
4. No config:
   ```yaml
   contas:
     tiktok:
       minhaconta:
         modo: rascunho            # rascunho: cai no app pra você postar · direto: publica sozinho
   ```
   No modo `direto`, enquanto o app não passar na auditoria do TikTok, os vídeos saem **privados**.

---

## 9. Como a detecção funciona e como calibrar

O VICOPU não usa um número fixo de mensagens. Ele **aprende o ritmo normal de cada live** e dispara quando o chat fica várias vezes acima dele. Por isso funciona tanto num chat pequeno quanto num gigante.

1. **Contagem:** a cada segundo, conta as mensagens dos **últimos 10 segundos**.
2. **O normal:** guarda uma média que se ajusta devagar. Nos primeiros **90 segundos** de cada live, ele só aprende.
3. **A pontuação** soma três sinais:
   - quanto o chat subiu em relação ao normal (o principal);
   - quantas mensagens têm reação (KKKK, KEKW, LUL, "clipa", 😂, ???...);
   - pico de **volume** no áudio (grito, explosão, risada).
4. **Disparo:** se passar do limite, ele corta **35 s antes e 12 s depois** do pico. A reação do chat vem depois do lance, então o lance fica dentro do corte. Depois disso, espera **90 segundos** antes de cortar de novo naquela live.
5. **Filtro:** o Claude lê a transcrição e **descarta** os trechos fracos. No corte manual, ele nunca descarta.

**Calibração rápida**, no config:

| Problema | O que mudar |
|---|---|
| Corta demais | `sensibilidade: baixa` no canal, ou `deteccao: {multiplicador_pico: 5}` |
| Não corta nunca (chat pequeno) | `sensibilidade: alta` |
| Perde momentos seguidos | `deteccao: {cooldown_segundos: 60}` no canal |
| O clipe começa tarde e perde o lance | `corte: {antes_segundos: 45}` |
| Clipes longos demais | `corte: {duracao_maxima: 45}` |

Cada corte mostra no log o motivo, tipo `chat 1180 msgs/10s (normal 290, x4.1), palavras 210, áudio sim`. Use esses números pra calibrar.

---

## 10. Webcam automática (layout `auto`)

Com `layout: auto`, que é o padrão, o VICOPU acha a webcam sozinho, uns 20 a 30 segundos depois de a live entrar no ar, e repete a cada 15 minutos.

1. **Grátis, no seu PC:** procura um **rosto parado** no mesmo lugar em vários quadros. Personagens do jogo se mexem, a webcam não. Em react, entre dois rostos parados, ele escolhe o mais perto da lateral. Depois, sai do rosto pra fora até achar a moldura da cam.
2. **Claude, só quando precisa:** se não achar rosto, se o rosto estiver no meio da tela (provável vídeo de react) ou se a cam não tiver moldura clara, ele manda um quadro pro Claude apontar a cam. Custa frações de centavo.
3. **Achou** a cam: usa o layout `split`. **Não achou:** usa o `blur`.

No painel, clique no layout ao lado da live (**split (auto)**) pra ver **onde ele achou a cam**, com um retângulo verde.

**Os layouts:**
- `split`: webcam em cima, jogo embaixo, legenda na divisa.
- `blur`: jogo inteiro no meio, com fundo desfocado. Bom pra quem joga sem cam.
- `centro`: recorte vertical do meio da tela. `centro_x: 0.3` puxa pra esquerda.

**Fixar a cam na mão** (se quiser): `layout: split` + `facecam: {x: 0.0, y: 0.5, w: 0.17, h: 0.27}`, em frações da tela. Pra calibrar com um vídeo de amostra do streamer:
```bat
python -m vicopu testar-layout nome_do_canal amostra.mp4
```

Pra nunca usar o Claude nessa parte: `ia: {camauto_claude: false}`.

---

## 11. Placa de vídeo

- **Montagem dos clipes:** na largada, o VICOPU testa e usa a placa que funcionar: **NVIDIA (NVENC)**, **AMD (AMF)** ou **Intel (QuickSync)**. Se nenhuma funcionar, usa o processador. O log mostra a escolha: `Montagem dos vídeos: usando ...`. Se a placa falhar no meio de um clipe, ele refaz no processador sozinho. Pra forçar uma: `corte: {encoder: amd}` (ou `nvidia`, `intel`, `cpu`).
- **Legenda (Whisper):** só acelera com **NVIDIA**. Nesse caso: `pip install -r requirements-nvidia.txt` (uns 1,2 GB). Com AMD, Intel ou sem placa, ela roda no processador, uns 10 a 15 segundos por clipe. Se pesar com muitas lives, use `corte: {modelo_whisper: base}`.
- **O aviso `cublas64_12.dll ... Usando o processador`** é inofensivo: aparece em máquinas com NVIDIA desligada ou sem as bibliotecas. Pra esconder: `corte: {whisper_dispositivo: cpu}`.

---

## 12. Atualizar o VICOPU

Dois cliques no **`atualizar.bat`**, ou pelo Prompt:
```bat
cd C:\vicopu
.venv\Scripts\activate
git pull
pip install -r requirements.txt
```
Depois, reinicie o VICOPU (Ctrl+C e `python -m vicopu rodar`) e aperte **F5** no painel.

O `git pull` não mexe no `config.yaml`, na pasta `dados` (clipes e autorizações), em `credenciais` nem no `.venv`.

**Instalar em outro computador:** siga a seção 2 e depois copie o seu `config.yaml` e as credenciais do YouTube (seção 7.4).

---

## 13. Checklist pra um dia de lançamento

**No dia anterior:**
- [ ] `git pull` e `pip install -r requirements.txt` no PC principal
- [ ] `copy config.gta6.yaml config.yaml`, e revisar a lista de streamers
- [ ] Rodar uma vez: todos aparecem como offline, sem erro
- [ ] **Energia:** Configurações → Sistema → Energia → suspender **Nunca**
- [ ] **Pausar as atualizações do Windows** (elas reiniciam o PC sozinhas)
- [ ] Conferir a chave do Claude (`echo %ANTHROPIC_API_KEY:~0,10%`)
- [ ] Testar a publicação no canal de teste

**No dia:**
- [ ] Ligar o VICOPU uns 15 minutos antes das lives
- [ ] Deixar o painel aberto e aprovar os clipes da aba **Aguardando você**
- [ ] Olhar no log os primeiros cortes de cada streamer grande e calibrar se precisar

> Rode o VICOPU em **uma máquina só** com a mesma lista de lives. Duas máquinas vigiando os mesmos streamers geram clipes e publicações em dobro.

---

## 14. Lendo o log

| Mensagem | O que quer dizer |
|---|---|
| `Montagem dos vídeos: usando placa AMD (AMF).` | qual placa vai montar os clipes |
| `Conectando em ...` | tentando abrir a live |
| `NO AR. Vigiando.` | a live está sendo capturada |
| `Offline no momento. Vou checar a cada 60 s...` | o streamer não está ao vivo (aparece uma vez só) |
| `Chat da Twitch conectado` / `Chat do YouTube conectado` | o chat está sendo lido |
| `Cam encontrada (rosto local, grátis)` / `(Claude)` | a webcam foi achada |
| `Layout automático: split` | usando a cam em cima |
| `MOMENTO! score 1.6 \| chat ...` | o detector achou um pico e vai cortar |
| `Corte manual pedido` | você clicou em Cortar agora |
| `Cortando ... (47 s de vídeo)` | montando o clipe |
| `Claude descartou ...: <motivo>` | trecho fraco, nem vira vídeo |
| `Clipe pronto (pendente)` | apareceu no painel pra você aprovar |
| `A live parou de chegar` | a live acabou ou caiu; ele tenta de novo sozinho |

---

## 15. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `'python' não é reconhecido` | Use `py` antes de criar o `.venv`. Depois do `activate`, `python` funciona. Ou feche e abra o Prompt. |
| O winget instalou só o primeiro programa | A pergunta de termos "engoliu" os outros comandos. Rode um por vez. |
| `getaddrinfo failed` / `NameResolutionError` | A rede não achou o endereço da Twitch. Algumas redes (trabalho, faculdade) bloqueiam a Twitch. Use outra rede. Na sua própria rede, trocar o DNS pra 1.1.1.1 e 8.8.8.8 costuma resolver. |
| `Não consegui abrir a live (...)` repetindo | Erro de rede ou canal errado. Confira o nome do canal na URL. |
| Chat do YouTube não conecta | Rode `pip install -U yt-dlp`. O YouTube muda de vez em quando, e o yt-dlp acompanha. |
| Chat da Kick não conecta | Instale `curl_cffi` (já está no requirements) ou coloque `kick_chatroom_id` no canal. |
| O Prompt parou de mostrar o log | Você selecionou texto com o mouse e a janela pausou (o título começa com "Selecionar"). Aperte **Esc**. |
| `Address already in use` / porta 8787 ou 8090 | Ficou um VICOPU antigo aberto. Feche as janelas, ou rode `taskkill /F /IM python.exe`. |
| Erro ao ler o `config.yaml` | Quase sempre são espaços: cada nível tem 2 espaços, e o `- nome:` dos canais fica alinhado. Links e @ vão entre aspas. |
| `Não achei ./credenciais/youtube_client_secret.json` | Arquivo com nome ou lugar errado. Cuidado com o `.json.json` quando o Windows esconde a extensão. Rode `dir C:\vicopu\credenciais`. |
| "Acesso bloqueado" no login do Google | O Gmail não está nos usuários de teste, ou o navegador abriu com outra conta. Veja a seção 7.2. |
| O botão Publicar está cinza | O canal não tem `publicar_em`. O card mostra o aviso. |
| Painel com visual antigo depois de atualizar | Reinicie o VICOPU e aperte **Ctrl+F5**. |
| Legenda fora do tempo | Corrigido na versão atual. Rode `git pull`. |

---

## 16. Custos, direitos e monetização

**Custos:** o VICOPU é grátis e roda local. O Claude Haiku custa frações de centavo por clipe e por detecção de cam: menos de US$ 0,20 por dia com 10 lives, numa estimativa. O gasto real aparece em **Gastos e uso**, no console do Claude.

**Direitos:** a live é conteúdo do streamer. Pra publicar com segurança:
- prefira streamers que **liberam canais de cortes**, ou peça autorização;
- mantenha o **crédito** em todo clipe (o VICOPU faz isso sozinho);
- revise antes de publicar e acrescente valor com título, legenda e escolha do melhor trecho;
- até **59 segundos**: no YouTube, Shorts de mais de 1 minuto com conteúdo reivindicado são bloqueados e não podem ser monetizados.

**Monetização de Shorts:** a receita vem de um fundo dividido pelas visualizações, e o valor por mil visualizações é baixo, então o dinheiro vem do volume. Visualizações de reupload não contam, e canais de puro reupload podem perder a monetização. A partir de fevereiro de 2027, pra receber pelos Shorts, o canal precisa de 10 milhões de visualizações de Shorts a cada 90 dias.

---

## 17. Referência completa do config

Tudo é opcional, exceto `canais`. O que você não colocar usa o padrão.

### `geral`
| Opção | Padrão | O que faz |
|---|---|---|
| `pasta_trabalho` | `./dados` | onde ficam o replay, os clipes e as autorizações |
| `buffer_minutos` | `5` | quantos minutos de cada live ficam guardados |
| `segundos_por_segmento` | `4` | tamanho dos pedaços do replay |
| `workers_corte` | `2` | quantos clipes são montados ao mesmo tempo |
| `qualidade_stream` | `best` | qualidade da captura (`720p60`, `1080p60`...) |
| `ffmpeg` | `ffmpeg` | caminho do ffmpeg |
| `log_nivel` | `INFO` | `DEBUG` mostra mais detalhes |

### `deteccao`
| Opção | Padrão | O que faz |
|---|---|---|
| `aquecimento_segundos` | `90` | tempo aprendendo o ritmo do chat no começo da live |
| `janela_segundos` | `10` | janela da contagem de mensagens |
| `multiplicador_pico` | `3.0` | quantas vezes acima do normal conta como pico |
| `minimo_mensagens_janela` | `8` | mínimo de mensagens na janela pra considerar |
| `cooldown_segundos` | `90` | intervalo mínimo entre cortes da mesma live |
| `limiar_score` | `1.0` | pontuação pra disparar |
| `peso_palavras` / `peso_audio` | `0.6` / `0.4` | peso das reações e do volume |
| `usar_audio` / `audio_salto_db` | `true` / `6` | pico de volume, em dB acima do normal |
| `palavras_chave` | lista pronta | palavras que contam como reação |

### `corte`
| Opção | Padrão | O que faz |
|---|---|---|
| `antes_segundos` / `depois_segundos` | `35` / `12` | quanto pegar antes e depois do pico |
| `atraso_live_segundos` | `0` | desloca a janela pra trás (lives com muito atraso) |
| `duracao_maxima` | `59` | duração máxima do clipe final |
| `fps` / `crf` | `30` / `21` | quadros por segundo e qualidade (menor = melhor) |
| `layout_padrao` | `auto` | layout de quem não define `layout` |
| `legenda` | `true` | liga ou desliga a legenda |
| `modelo_whisper` | `small` | `tiny`, `base`, `small` ou `medium` |
| `whisper_dispositivo` | `auto` | `auto`, `cpu` ou `cuda` (NVIDIA) |
| `encoder` | `auto` | `auto`, `amd`, `nvidia`, `intel` ou `cpu` |
| `idioma` | `pt` | idioma padrão da legenda (`""` = detectar sozinho) |

### `ia`
| Opção | Padrão | O que faz |
|---|---|---|
| `usar_claude` | `true` | título, descrição e filtro pelo Claude |
| `modelo` | `claude-haiku-5-5` | modelo usado |
| `respeitar_descarte` | `true` | trechos fracos não viram clipe (nunca no corte manual) |
| `camauto_claude` | `true` | usa o Claude quando a detecção grátis da cam falha |
| `foco` | `""` | assunto do canal (ex.: `GTA 6`) |
| `instrucoes_extras` | `""` | regras extras pro Claude (ex.: sem spoiler) |

### `publicacao`
| Opção | Padrão | O que faz |
|---|---|---|
| `modo` | `revisao` | `revisao` (você aprova), `auto` (publica sozinho) ou `nenhum` (só gera) |
| `painel_host` / `painel_porta` | `127.0.0.1` / `8787` | endereço do painel |
| `credito` | `🎮 Corte da live de {streamer}. Live completa: {link}` | crédito na descrição do YouTube |
| `credito_tiktok` | `🎮 Live: {link_curto}` | crédito na legenda do TikTok |

### `contas`
```yaml
contas:
  youtube:
    nome_da_conta: {privacidade: private}       # private | unlisted | public
  tiktok:
    nome_da_conta: {modo: rascunho, privacidade: PUBLIC_TO_EVERYONE}
```

### Opções de cada canal
| Opção | Obrigatória | O que faz |
|---|---|---|
| `nome` | ✔ | identificador único |
| `plataforma` | ✔ | `twitch`, `kick`, `youtube` ou `arquivo` (teste com um vídeo local) |
| `canal` | ✔ | nome do canal, `"@handle"` ou link |
| `apelido` | | nome do streamer no título e no crédito |
| `layout` | | `auto`, `split`, `blur` ou `centro` |
| `facecam` | | posição fixa da cam, com `layout: split` |
| `centro_x` | | 0 a 1, foco horizontal no `centro` e no `split` |
| `sensibilidade` | | `alta`, `normal` ou `baixa` |
| `deteccao` | | ajustes finos de detecção só pra esse canal |
| `idioma` | | idioma da legenda desse canal |
| `hashtags` | | hashtags fixas |
| `publicar_em` | | lista de destinos, ex.: `[youtube:principal, tiktok:minhaconta]` |
| `credito` | | `false` desliga o crédito desse canal |
| `qualidade` | | qualidade da captura só desse canal |
| `kick_chatroom_id` | | ID do chat da Kick, se a busca automática falhar |

---

## 18. Estrutura do projeto

```
vicopu/
  __main__.py   comandos: rodar, auth-youtube, auth-tiktok, testar-layout
  config.py     leitura do config, padrões, links e crédito
  captura.py    VIGIA: streamlink → ffmpeg → replay; offline/reconexão
  chat.py       VIGIA: chat da Twitch (IRC + reserva WebSocket), Kick, YouTube (yt-dlp)
  detector.py   VIGIA: pico de chat + reações + volume → Momento
  camauto.py    webcam automática (rosto grátis + Claude)
  ia.py         legenda (Whisper) + Claude (avaliação, título, descrição, recorte)
  corte.py      CORTA: layouts 9:16, legenda sincronizada, placa de vídeo
  nucleo.py     junta tudo: um Vigia por live + a fila de cortes
  publicar/     PUBLICA: youtube.py, tiktok.py
  painel.py     painel web (abas, lote, prévia, baixar, copiar)
config.exemplo.yaml   modelo comentado
config.gta6.yaml      lista pronta do lançamento do GTA 6
requirements.txt      bibliotecas
requirements-nvidia.txt  opcional: legenda na placa NVIDIA
```

**Comandos:**
```bat
python -m vicopu rodar                              :: liga tudo
python -m vicopu auth-youtube <conta>               :: autoriza um canal do YouTube
python -m vicopu auth-youtube <conta> --sem-navegador  :: em servidor sem tela
python -m vicopu auth-tiktok <conta>                :: autoriza uma conta do TikTok
python -m vicopu testar-layout <canal> <video.mp4>  :: prévia do layout com um vídeo
python -m vicopu -c outro.yaml rodar                :: usa outro arquivo de config
```
