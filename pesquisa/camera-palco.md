# Câmera do palco — pesquisa (2026-11-27)

Pedido: webcam **fixa** filmando o palco, ligada por **cabo USB longo**, com o **mínimo de latência** entre o que entra
na câmera e o que sai no telão. Comprar no Brasil, chegando até **12/12**. (Não comprar na KaBuM.)

## Decisão para o show de 12/12

- **Câmera: Logitech C922**: 720p@60 fps em USB 2.0, controles manuais pelo v4l2 (exposição, foco, balanço de
  branco), estoque em todo lugar, uns R$ 480–500.
  - Lente fixa de 78°: de longe o palco fica pequeno. Dá para usar zoom digital (`zoom_absolute`, recorta e perde
    nitidez) ou pôr a câmera mais perto, que o cabo longo permite.
- **Cabo:** até ~20 m, cabo USB 2.0 **ativo** (amplificado). Até 50 m, extensor USB 2.0 **via cabo de rede (RJ45) com
  fonte** + Cat6 de fio rígido. Comprar já, de vendedor com entrega rápida, e testar 30 min assim que chegar.
- **Alternativa mais cara: Logitech Brio 4K / MX Brio**: 1080p@60, e o sensor 4K deixa o zoom digital nítido. Mas é
  **USB 3**: num extensor USB 2.0 cai para modos menores. Só vale com cabo USB 3 ativo de até ~15 m.

### Links (preço e estoque de 27/11; prefira "enviado e vendido por Amazon.com.br" ou o selo Full do Mercado Livre)

C922:
- Amazon, com tripé, vendida pela Amazon (~R$ 482): <https://www.amazon.com.br/Logitech-C%C3%A2mera-Streaming-Grava%C3%A7%C3%A3o-Inclu%C3%ADdo/dp/B01L6L52K4>
- Amazon, outra listagem: <https://www.amazon.com.br/Widescreen-Tecnologia-Replacement-Logitech-Equipamentos/dp/B01MTTMPKT>
- Amazon, outra listagem: <https://www.amazon.com.br/Logitech-Streaming-streaming-substitui%C3%A7%C3%A3o-inclu%C3%ADdo/dp/B07JGCBXYY>
- Mercado Livre, página do produto (960-001087, ~R$ 495): <https://www.mercadolivre.com.br/webcam-full-hd-logitech-c922-pro-stream-com-microfone-embutido/p/MLB18931397>
- Mercado Livre, 960-001088 (cabo de 1,8 m): <https://produto.mercadolivre.com.br/MLB-1080602222-webcam-logitech-c922-pro-streamer-full-1080p-960-001088-_JM>
- Loja oficial Logitech BR: <https://www.logitech.com/pt-br/shop/p/c922-pro-stream-webcam>
- Fugir de anúncio muito abaixo da média (ex. R$ 339): falsificação ou anúncio parado.

Brio:
- Brio 4K PRO 960-001178 (~R$ 805–1.040): <https://www.amazon.com.br/Webcam-HD-4K-Logitech-BRIO/dp/B06X92Z67Z>
- MX Brio (~R$ 1.300): <https://www.amazon.com.br/Logitech-Microfones-Qualidade-Aprimorada-Privacidade/dp/B0CX8S8JLX>

Cabos (Brasil; anúncios genéricos, não dizem se suportam "isochronous", então é aposta: testar e devolver se falhar):
- USB 2.0 ativo 15/20 m (~R$ 90–126): <https://www.magazineluiza.com.br/busca/cabo+usb+extensor+2+0/>
- Extensor USB RJ45 50 m com fonte (~R$ 94): <https://www.magazineluiza.com.br/busca/extensor+para+cabo+usb/>
  (procurar "extensor USB 2.0 RJ45 50m fonte"; exigir fonte inclusa e kit transmissor + receptor)

## Ideal, sem pressa de prazo (importados)

O ideal é uma **câmera USB industrial com lente varifocal 2.8–12 mm** (zoom e foco manuais, enquadra o palco de onde
estiver). No Brasil a lente varifocal só aparece em câmera de segurança (CFTV), sem USB.

| Câmera | Por quê | Atenção |
|---|---|---|
| [ELP 2.8–12 mm OV2710, USB 2.0](https://www.probotix.com/ACCESSORIES/WEBCAM1) | 720p@60 MJPEG, zoom manual, barata | sensor fraco no escuro; 1080p só a 30 |
| [Arducam B0362 IMX291 2.8–12 mm, USB 2.0](https://www.arducam.com/arducam-imx291-usb-camera-with-2-8-12mm-lens-b0362.html) | Sony Starvis, WDR, zoom/foco/íris manuais | 1080p@30 (720p@60 não confirmado) |
| [ELP IMX291 USB 3.0, 2.8–12 ou 5–50 mm](https://www.diyfixtool.com/products/high-speed-usb-3-0-webcam-varifocal-computer-pc-webcamera-camera) | imagem boa e 1080p@50 | USB 3 → cabo USB 3; 50 fps sob luz de 60 Hz pode cintilar |

Conferir a tabela real de formatos com `v4l2-ctl --list-formats-ext`: muitos anúncios "1080p 60 fps" da OV2710
entregam 1080p@30 e 720p@60.

## Cabo longo

| Opção | Distância | Atenção |
|---|---|---|
| USB 2.0 via Cat6 (módulo de cada lado) | até 50 m | exigir suporte **isochronous** (é o modo que webcam usa): SY Electronics USB50 e L-com dizem isso; StarTech e Lindy não deixam claro. Cat6 de fio rígido. |
| Cabos USB 2.0 ativos em sequência | ~25 m | 5 m por repetidor; há relato de C920 que falhou com 10 m. Hub com fonte na ponta da câmera ajuda. |
| Fibra USB 3 (AOC) | 15–100 m | **a maioria NÃO funciona com aparelho USB 2.0** (Vaddio e BZBGEAR avisam). Só os híbridos (IDS, Hicon, Delock 83724). |
| Câmera HDMI + placa de captura USB | até 100 m (HDBaseT) | a mais robusta; +~1 quadro de atraso e mais cara |

## Latência (estimativas típicas, não medidas)

- Câmera (exposição + leitura + USB): ~1–2 quadros, 33–66 ms a 30 fps. **A 60 fps cai pela metade**, o maior ganho
  nas nossas mãos.
- PRISMA: ffmpeg com `-fflags nobuffer`, render a 60 fps: ≤ 1 quadro + sincronia com o monitor.
- Telão/projetor: 16 a mais de 100 ms. Ligar o **modo jogo** e desligar os "melhoramentos" de imagem; processadora de
  LED soma quadros.
- **Medir:** cronômetro com milissegundos na frente da câmera e foto do celular pegando o cronômetro e o telão juntos.

### No código do PRISMA hoje

`plat.cam_input_args` força `yuyv422` 640×480@30 (sem compressão: no USB 2.0 não passa disso) e a textura é 640×480
(`native_synth.WIDTH/HEIGHT`). Para 60 fps é preciso pedir **MJPEG** (720p@60). Está no BACKLOG, seção "Câmera do palco".

## Luz que muda no palco (o palco é iluminado; o que pega são as trocas)

- **fps travado, sempre:** `exposure_dynamic_framerate=0` (ou `exposure_auto_priority=0`). No escuro ou num blackout a
  câmera cai de 30 para 15 fps sozinha e **dobra o atraso**.
- **Exposição**, duas estratégias, medir no palco qual reage melhor:
  1. automática mas presa ao fps (adapta às trocas; pode "respirar" com estrobo);
  2. manual pela cena mais clara (sem estourar) + o **auto-nível do PRISMA** (`_auto_levels`, já suavizado) cuida
     do resto. Costuma ser a mais estável.
- **Balanço de branco travado**: com gelatina colorida, o automático "corrige" a cor do show.
- **Foco travado**; **HDR de várias exposições desligado** (atrasa; WDR de uma exposição só pode ficar);
  `power_line_frequency=2` (60 Hz no Brasil: LED sem faixa piscando).

```
v4l2-ctl -d /dev/video0 -c auto_exposure=1 -c exposure_dynamic_framerate=0 \
         -c exposure_time_absolute=<fixo> -c gain=<ajustar> \
         -c focus_automatic_continuous=0 -c white_balance_automatic=0 \
         -c power_line_frequency=2
```
(Os nomes variam por câmera: `v4l2-ctl -L`.)

Outras práticas: porta USB direto do computador (não num hub dividido), suspensão automática do USB desligada,
teste de 30 min no local com o cabo inteiro.

## Fontes

Latência e exposição: [glass-to-glass](https://bloggeek.me/webrtcglossary/glass-to-glass/) ·
[Luxonis](https://discuss.luxonis.com/d/6614-deep-dive-latency-request-for-help) ·
[NVIDIA](https://forums.developer.nvidia.com/t/webcam-pipeline-with-least-amount-of-latency/144155) ·
[OBS YUY2 vs MJPEG](https://obsproject.com/forum/tags/yuy2-vs-mjpeg/) ·
[TechNexion fps em pouca luz](https://developer.technexion.com/docs/embedded-vision/vizioncam-usb3/troubleshooting/streaming-performance/low-light-framerate) ·
[Microsoft auto exposure priority](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/ksproperty-cameracontrol-auto-exposure-priority) ·
[Arducam IMX291 v4l2](https://www.arducam.com/forums/topic/v4l-ctl-settings-for-low-light-imx291/) ·
[Dell HDR](https://www.dell.com/support/kbdoc/en-au/000189124/&) · [Ceedo HDR](https://www.ceedo.com/webcam-hdr-explained/)

Cabos: [Vaddio AOC × USB 2.0](https://res.cloudinary.com/avd/image/upload/v132633739/Resources/Vaddio/Accessories/Specifications/Tech_note_USB_AOC_Cables.pdf) ·
[BZBGEAR](https://bzbgear.com/product/bg-cab-u3a-usb-3-0-am-af-active-optical-extension-cable) ·
[IDS híbrido](https://cn.ids-imaging.com/tl_files/downloads/STORE/acc_spec/26/datasheet/AD00207_EN.pdf) ·
[Delock 83724](https://www.delock.com/produkt/83724/merkmale.html) ·
[Plugable C920 com extensão](https://support.plugable.com/t/any-suggestions-on-how-to-extend-a-logitech-c920-webcam/10585) ·
[SY USB50](https://www.rcblogic.co.uk/product/sy-electronics-sy-usb50-set-usb-20-over-cat6-extender-to-50m) ·
[L-com](https://www.l-com.com/usb-2.0-extender-system-extends-up-165-feet-over-solid-core-ethernet-cable-includes-tx-transmitter-rx-receiver-lc6-usb20c-1px165) ·
[Tripp Lite](https://cdw.com/product/tripp-lite-usb-over-cat5-cat6-extender-kit-1-port-with-poc-usb-2.0-164-ft/6017397) ·
[StarTech](https://startech.com/en-mx/cards-adapters/usb2001extv) ·
[Digitus DA-70141](https://www.assmann.com/product-pdf/4016032365082?PL=pt) ·
[Kramer](https://www.kramerav.com/Product/CA-USB3/AAE)

Câmeras: [Logitech C922 BR](https://www.logitech.com/pt-br/shop/p/c922-pro-stream-webcam) ·
[Logitech Brio BR](https://www.logitech.com/pt-br/product/brio?crid=34) ·
[Buscapé C922](https://www.buscape.com.br/webcam/webcam-logitech-2-mp-filma-em-full-hd-c922) ·
[Probotix ELP](https://www.probotix.com/ACCESSORIES/WEBCAM1) ·
[Arducam B0362](https://www.arducam.com/arducam-imx291-usb-camera-with-2-8-12mm-lens-b0362.html) ·
[DIYFixTool ELP USB3](https://www.diyfixtool.com/products/high-speed-usb-3-0-webcam-varifocal-computer-pc-webcamera-camera)
