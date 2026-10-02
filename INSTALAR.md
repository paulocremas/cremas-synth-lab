# Como instalar o PRISMA!

O PRISMA! transforma imagem (câmera, tela, vídeos e fotos) em visual reagindo ao som do computador,
e manda o resultado pra um monitor, projetor ou telão de LED. Este guia cobre **Linux** e **Windows**.

## Antes de começar

| | Linux | Windows |
|---|---|---|
| Sistema | Ubuntu 22.04 ou mais novo, Linux Mint 21 ou mais novo (64 bits) | Windows 10 ou 11 (64 bits) |
| Sessão | **Xorg (X11)** — no Wayland a captura de tela e os monitores não funcionam | — |
| Vídeo | placa com OpenGL (qualquer NVIDIA, AMD ou Intel dos últimos ~10 anos) | idem, com o driver do fabricante instalado |
| Espaço | ~300 MB | ~350 MB |

O instalador fica na página de versões do projeto:
**<https://github.com/paulocremas/cremas-synth-lab/releases/latest>** — role até **Assets** e baixe o
arquivo do seu sistema.

---

## Linux

### 1. Baixar

Na página de versões, baixe o arquivo que termina em **`_amd64.deb`** (ex.: `prisma_0.1.0_amd64.deb`).

### 2. Instalar

**Pelo gerenciador de arquivos:** dê dois cliques no `.deb` e clique em **Instalar** (pede sua senha).

**Pelo terminal** (na pasta onde o arquivo foi baixado):

```bash
sudo apt install ./prisma_0.1.0_amd64.deb
```

Use `./` antes do nome: assim o `apt` instala o arquivo **e** baixa sozinho o que o PRISMA! precisa
(ffmpeg, captura de áudio, ferramentas de monitor).

### 3. Abrir

Procure **PRISMA!** no menu de aplicativos, ou digite `prisma` no terminal. Abrem duas janelas:

- a **saída** — a imagem que vai pro telão/projetor;
- o **painel de controle** (dash), no Brave ou Chrome se você tiver um deles, senão no navegador padrão.

Pra fechar tudo: aperte **Esc três vezes** em qualquer uma das duas janelas.

### Desinstalar

```bash
sudo apt remove prisma
```

Suas configurações, sets e mídias ficam em `~/.local/share/prisma/` e **não** são apagados. Pra
apagar também: `rm -r ~/.local/share/prisma ~/.config/prisma`.

---

## Windows

### 1. Baixar

Na página de versões, baixe o arquivo que termina em **`-setup.exe`** (ex.: `PRISMA-0.1.0-setup.exe`).

> **Sem instalar (portátil):** baixe o **`-windows-portatil.zip`**, clique com o botão direito >
> **Extrair tudo**, abra a pasta **PRISMA** e dê dois cliques em **`prisma.exe`** (o aviso do
> SmartScreen do passo 2 vale aqui também). Roda de qualquer lugar, até de um pendrive: sets,
> mídias e ajustes ficam na pasta `dados` ali dentro. Pra remover, apague a pasta. Quando sair
> versão nova, ele avisa e abre a página pra baixar o zip novo — copie a pasta `dados` da versão
> antiga pra nova pra manter seus sets.

### 2. Instalar

1. Dê dois cliques no arquivo baixado.
2. Se aparecer **"O Windows protegeu o computador"**: clique em **Mais informações** e depois em
   **Executar assim mesmo**. O aviso aparece porque o instalador não tem assinatura digital paga —
   não é vírus.
3. Siga o assistente. Não precisa ser administrador: o PRISMA! é instalado só pro seu usuário.
   Marque **Criar um ícone na Área de Trabalho** se quiser.
4. No fim, deixe marcado **Executar PRISMA!** e clique em **Concluir**.

### 3. Abrir

Pelo menu Iniciar (**PRISMA!**) ou pelo atalho da área de trabalho. Abrem duas janelas: a **saída**
e o **painel de controle** (no Edge, Chrome ou Brave). **Esc três vezes** fecha tudo.

**Câmera:** se ela não aparecer, libere em **Configurações > Privacidade e segurança > Câmera** e
ative **Permitir que aplicativos da área de trabalho acessem a câmera**.

**Som:** o PRISMA! escuta o som que sai do computador (música, vídeo…) sem configurar nada. Pra usar
outra entrada (microfone, placa de som), escolha no painel, aba **Áudio**.

### Desinstalar

**Configurações > Aplicativos > Aplicativos instalados > PRISMA! > Desinstalar.**

Configurações, sets e mídias ficam em `%LOCALAPPDATA%\prisma` (cole isso na barra do Explorador de
Arquivos) e **não** são apagados — apague a pasta se quiser remover tudo.

---

## Atualizações

Toda vez que o PRISMA! abre com internet, ele confere se existe versão nova:

- **mesma versão** ou **sem internet** → abre normal, sem perguntar nada;
- **versão nova** → aparece uma janela com o que mudou e dois botões:
  - **Atualizar**: baixa e instala sozinho (no Linux pede sua senha; no Windows abre o assistente) e
    reabre o PRISMA! já atualizado;
  - **Agora não**: abre a versão que você tem. A pergunta volta na próxima vez.

Atualizar **não apaga** seus sets, mídias e ajustes.

---

## Ligar no telão ou projetor

1. Conecte o cabo (HDMI/DisplayPort) do telão, projetor ou processadora de LED.
2. No painel, abra a aba **Saída**, cadastre as telas do palco em **Telas do palco** e clique em
   **⚡ detectar telão**. O PRISMA! acha a saída nova, ajusta o mapa de pixels pra resolução dela e
   abre a imagem lá em tela cheia.

---

## Problemas comuns

| O que acontece | O que fazer |
|---|---|
| Linux: a janela de saída fica preta ou não abre | Confira se a sessão é **Xorg** (na tela de login, engrenagem ao lado da senha). Atualize o driver de vídeo. |
| As barras de som não se mexem | Toque algum som no computador. No painel, aba **Áudio**, confira a fonte escolhida. |
| A câmera não aparece | Feche outros programas que estejam usando a câmera (Zoom, Meet, OBS). No Windows, veja a permissão de câmera acima. |
| O painel não abriu | Abra no navegador: **<http://127.0.0.1:8765/v2>** |
| Pretos acinzentados no telão | Na placa de vídeo, ajuste a faixa de cor da saída HDMI para **Completa / Full (0–255)**. |
| Windows: algo não funciona | Mande o arquivo `%LOCALAPPDATA%\prisma\prisma.log` junto com a descrição do problema. |
