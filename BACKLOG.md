# Backlog

Ideias combinadas e ainda não feitas. Ao começar uma, mover pro código/commit e tirar daqui.

## Canvas / telas — o que falta
Feito: telas do palco físico (`tuning.SCREENS`, metros + pixels, editor na aba Saída) cujo contorno
é o canvas; fontes posicionadas nele (`OVERLAYS[i].rect`, vista Canvas da mesa no Palco, com prévia
com efeitos e bandeja arrasta-e-solta); fora das telas = preto.
Ainda não:
- **Várias saídas**: o pixel map (`PIXEL_MAP` + `ox/oy` por tela) já reempacota as telas num raster,
  mas é uma janela só. Falta mais de um raster (uma janela por saída/monitor, cada uma com suas
  telas) pra parede maior que um 4K ou LED + projetor. Rotação da fatia no raster (coluna deitada).
- **Rotação** e **recorte** (crop) por objeto; tela girada/não retangular (mapping).
- Imagem da cena e calibração ainda passam na janela inteira; a análise/fumaça (`_composite` na
  CPU) ignora `rect`/telas; shaders da pilha rodam com `u_resolution` da janela.

## Simulador de telão
Testar pixel mapping e projeção sem o hardware: uma janela/vista que pega o raster de saída
(`MAP_SRC`) e o "desempacota" de volta nas telas físicas do `SCREENS` (m + px, `ox/oy`), desenhando
o palco em escala — LED com grade de pixels/módulos visível, projetor com keystone/sobreposição.
Serve pra conferir se cada fatia caiu na tela certa, na orientação certa, e como fica de longe.
