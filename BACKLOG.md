# Backlog

Ideias combinadas e ainda não feitas. Ao começar uma, mover pro código/commit e tirar daqui.

## Canvas / telas — o que falta
Feito: telas do palco físico (`tuning.SCREENS`, metros + pixels, editor na aba Saída) cujo contorno
é o canvas; fontes posicionadas nele (`OVERLAYS[i].rect`, vista Canvas da mesa no Palco, com prévia
com efeitos e bandeja arrasta-e-solta); fora das telas = preto.
Ainda não:
- **Mapa de saída**: hoje a janela mostra o canvas na forma física. Falta a saída reorganizar as
  telas — pixel map pra processadora de LED (retângulos reempacotados num raster) e/ou uma janela
  por tela/monitor. A entrada continua sendo um canvas só.
- **Rotação** e **recorte** (crop) por objeto; tela girada/não retangular (mapping).
- Imagem da cena e calibração ainda passam na janela inteira; a análise/fumaça (`_composite` na
  CPU) ignora `rect`/telas; shaders da pilha rodam com `u_resolution` da janela.
