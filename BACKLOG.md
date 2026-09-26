# Backlog

Ideias combinadas e ainda não feitas. Ao começar uma, mover pro código/commit e tirar daqui.

## Canvas da saída (estilo OBS)
- Configurar o **canvas** (resolução/proporção da cena) na aba **Saída** do dash v2.
- O mesmo canvas aparece na aba **Palco**, como área de composição.
- Cada mídia/fonte da mesa vira um **objeto arrastável** nesse canvas: posição, tamanho, talvez
  rotação/recorte (hoje cada fonte ocupa a tela inteira: `preencher`/modo de mistura).
- Pontos a decidir: onde guardar a transformação por canal (junto do `OVERLAYS`/`BINDINGS`,
  por posição como a pilha), como isso entra na mistura (CPU `comp_last` vs. passe GL por
  camada) e o que o canvas faz quando a janela de saída tem outra proporção.
