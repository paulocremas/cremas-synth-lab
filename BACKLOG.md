# Backlog

Ideias combinadas e ainda não feitas. Ao começar uma, mover pro código/commit e tirar daqui.

## Canvas / telas — o que falta
Feito: telas do palco físico (`tuning.SCREENS`, metros + pixels, editor na aba Saída) cujo contorno
é o canvas; fontes posicionadas nele (`OVERLAYS[i].rect`, vista Canvas da mesa no Palco, com prévia
com efeitos e bandeja arrasta-e-solta); fora das telas = preto. Tela com forma livre (`rot` + `poly`,
editor com giro/vértices/formas prontas/lápis; native, pixel map e telao_sim).
Ainda não:
- **Várias saídas**: o pixel map (`PIXEL_MAP` + blocos `ox/oy/pw/ph`) é um raster/janela só. Falta mais de
  um (uma janela por saída/monitor) pra parede maior que um 4K ou LED + projetor. Bloco girado no raster
  (gabinete deitado na processadora).
- **Rotação** e **recorte** (crop) por OBJETO (fonte no canvas). Tela com keystone/quad livre (projeção;
  hoje o painel é retângulo girado + polígono). Ímã com tela girada (hoje desliga).
- Imagem da cena e calibração ainda passam na janela inteira; a análise/fumaça (`_composite` na
  CPU) ignora `rect`/telas; shaders da pilha rodam com `u_resolution` da janela.

## Telão simulado — o que falta (`src/telao_sim.py` já desempacota o raster no palco)
- Grade de LEDs/módulos visível no zoom; projetor com keystone/sobreposição.
- Versão Windows (hoje X11: wmctrl/xwininfo/x11grab por id).

## Saída no telão real
- Reconhecimento automático só roda com o dash aberto (`pollOutputs`); telão que some deixa a janela de saída
  sem destino (só avisa) — voltar pra janela normal?
- vsync explícito na janela de saída (tearing no LED); fontes/shaders em 640×480 deixam o conteúdo mais mole
  que o painel.

## Windows / distribuição
- 1º teste real no Windows: `v0.1.0-beta.1` (pré-lançamento, zip portátil) foi pra um amigo — esperar o
  `prisma.log` (`dados\prisma.log` no portátil). Pontos não vistos rodando: OpenGL com driver de verdade,
  loopback WASAPI (`plat.PcmProc`), câmera dshow, dash no Edge, monitores DPI-aware.
- `--region`/`--window` e `_raise_output_over_dash` só no Linux.
- Release final `v0.1.0`: juntar `dashboard-channels-output` no `master` e taggear de lá.
- Actions avisa Node 20 depreciado (`checkout@v4`, `setup-python@v5`) — subir as versões.
- Instalador/zip sem assinatura de código (SmartScreen avisa).
