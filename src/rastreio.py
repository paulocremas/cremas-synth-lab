"""RASTREIO por IA (cv2.dnn, modelos ONNX do opencv_zoo em models/): rosto + olhos, corpo, objetos.

Cada detector recebe um quadro RGB (h, w, 3) uint8 e devolve geometria em uv 0..1 da FONTE com origem
EM CIMA (o mesmo `st` topo->baixo dos atomos). Sem estado de render: o native roda numa thread por
tipo (so' pras fontes que um atomo de mascara pede) e sobe o resultado como uniform.

- Rosto  (YuNet, 230 KB):        [(cx, cy, w, h, lx, ly, rx, ry, conf)], ate' MAX_FACES, maior primeiro.
- Corpo  (BlazePose, 5.5 MB):    (33, 3) = x, y, visibilidade dos 33 pontos do MediaPipe, ou None.
                                  Uma pessoa. A caixa inicial vem do Objetos (classe pessoa); depois o
                                  proprio corpo diz onde olhar no proximo quadro (como o MediaPipe).
- Objetos (NanoDet-Plus, 3.8 MB): [(x0, y0, x1, y1, conf, classe COCO)], maior confianca primeiro.
- Contorno (Face Mesh do MediaPipe, 1.2 MB, .tflite): por rosto do YuNet, o CONTORNO das palpebras =
                                  (2, OLHO_PTS, 2) — olho da esquerda e da direita da imagem, 16 pontos em volta.

Modelos do opencv_zoo (github.com/opencv/opencv_zoo) + face_landmark do MediaPipe
(storage.googleapis.com/mediapipe-assets), todos Apache 2 / MIT. `python src/rastreio.py --selfcheck [imagem]`.
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(_ROOT, 'models')
FACE_MODEL = os.path.join(MODELS, 'face_detection_yunet_2023mar.onnx')
POSE_MODEL = os.path.join(MODELS, 'pose_estimation_mediapipe_2023mar.onnx')
OBJ_MODEL = os.path.join(MODELS, 'object_detection_nanodet_2022nov.onnx')
MESH_MODEL = os.path.join(MODELS, 'face_landmark_mediapipe.tflite')

MAX_FACES, MAX_OBJS = 4, 8
OLHO_PTS = 16                   # pontos do contorno de cada olho (u_olho = MAX_FACES x 2 olhos x 16 pontos)
# indices do Face Mesh (468 pontos) em volta de cada olho, em ordem: palpebra de baixo, canto, de cima
OLHO_MESH = ((33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246),
             (263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466))      # = tamanho dos arrays de uniform (u_rosto[4], u_obj[8])
PESSOA = 0                      # classe COCO "person"
COCO = ('pessoa bicicleta carro moto aviao onibus trem caminhao barco semaforo hidrante placa parquimetro banco '
        'passaro gato cachorro cavalo ovelha vaca elefante urso zebra girafa mochila guarda-chuva bolsa gravata mala '
        'frisbee esqui snowboard bola pipa taco luva skate prancha raquete garrafa taca xicara garfo faca colher tigela '
        'banana maca sanduiche laranja brocolis cenoura cachorro-quente pizza rosquinha bolo cadeira sofa planta cama '
        'mesa privada tv notebook mouse controle teclado celular microondas forno torradeira pia geladeira livro relogio '
        'vaso tesoura ursinho secador escova').split()

# ossos do esqueleto do MediaPipe (pares de pontos); o atomo Corpo desenha a mesma lista em GLSL
OSSOS = ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
         (23, 25), (25, 27), (24, 26), (26, 28), (27, 31), (28, 32), (15, 19), (16, 20))


class Rosto:
    W = 320                      # largura em que roda (~2 ms)

    def __init__(self, path=FACE_MODEL, conf=0.6):
        import cv2
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(path, '', (self.W, self.W), conf)

    def __call__(self, rgb):
        cv2 = self.cv2
        h, w = rgb.shape[:2]
        dh = max(1, round(h * self.W / w))
        self.det.setInputSize((self.W, dh))
        _n, faces = self.det.detect(cv2.cvtColor(cv2.resize(rgb, (self.W, dh)), cv2.COLOR_RGB2BGR))
        out = []
        for f in faces if faces is not None else ():
            x, y, fw, fh = f[0] / self.W, f[1] / dh, f[2] / self.W, f[3] / dh
            ax, ay, bx, by = f[4] / self.W, f[5] / dh, f[6] / self.W, f[7] / dh
            if ax > bx:                  # l = o olho da ESQUERDA da imagem
                ax, ay, bx, by = bx, by, ax, ay
            out.append((x + fw / 2, y + fh / 2, fw, fh, ax, ay, bx, by, float(f[14])))
        out.sort(key=lambda r: -r[2] * r[3])
        return out[:MAX_FACES]


class Contorno:
    """Contorno dos olhos: o YuNet acha o rosto, o recorte (1.5x o rosto, girado pela linha dos olhos)
    vai pro Face Mesh (192 px, ~10 ms por rosto) e os 16 pontos de cada palpebra voltam pra uv da fonte."""
    S, ZOOM = 192, 1.5

    def __init__(self, path=MESH_MODEL, rosto=None):
        import cv2
        self.cv2, self.rosto = cv2, rosto or Rosto()
        self.net = cv2.dnn.readNetFromTFLite(path)
        self.out = self.net.getUnconnectedOutLayersNames()

    def __call__(self, rgb):
        """-> [(2, OLHO_PTS, 2) uv topo->baixo, olho da esquerda da imagem primeiro], maior rosto primeiro."""
        cv2 = self.cv2
        h, w = rgb.shape[:2]
        out = []
        for cx, cy, fw, fh, ax, ay, bx, by, _c in self.rosto(rgb):
            cx, cy, ax, ay, bx, by = cx * w, cy * h, ax * w, ay * h, bx * w, by * h
            side = max(fw * w, fh * h) * self.ZOOM
            M = cv2.getRotationMatrix2D((cx, cy), float(np.degrees(np.arctan2(by - ay, bx - ax))), self.S / side)
            M[:, 2] += (self.S / 2 - cx, self.S / 2 - cy)
            crop = cv2.warpAffine(rgb, M, (self.S, self.S)).astype(np.float32) / 255.0   # MediaPipe: 0..1
            self.net.setInput(crop.transpose(2, 0, 1)[None])                            # NCHW
            pts = self.net.forward(self.out)[0].reshape(468, 3)[:, :2]
            P = np.c_[pts, np.ones(468)] @ cv2.invertAffineTransform(M).T / (w, h)
            eyes = np.stack([P[list(i)] for i in OLHO_MESH]).astype(np.float32)
            if eyes[0, :, 0].mean() > eyes[1, :, 0].mean():   # [0] = o olho da ESQUERDA da imagem
                eyes = eyes[::-1].copy()
            out.append(eyes)
        return out


class Objetos:
    S = 416
    STRIDES, REG = (8, 16, 32), 7

    def __init__(self, path=OBJ_MODEL, conf=0.25, iou=0.6):   # conf baixo: o limiar do atomo Objeto escolhe
        import cv2
        self.cv2, self.conf, self.iou = cv2, conf, iou
        self.net = cv2.dnn.readNet(path)
        self.anchors = []
        for st in self.STRIDES:
            n = self.S // st
            yv, xv = np.mgrid[0:n, 0:n] * st
            self.anchors.append(np.column_stack((xv.ravel(), yv.ravel())) + 0.5 * (st - 1))
        self.mean = np.array([103.53, 116.28, 123.675], np.float32)
        self.std = np.array([57.375, 57.12, 58.395], np.float32)

    def __call__(self, rgb):
        cv2 = self.cv2
        h, w = rgb.shape[:2]
        k = self.S / max(w, h)           # cabe inteiro no quadrado (barras embaixo/do lado)
        nw, nh = max(1, round(w * k)), max(1, round(h * k))
        img = np.zeros((self.S, self.S, 3), np.float32)
        img[:nh, :nw] = (cv2.resize(rgb, (nw, nh))[..., ::-1].astype(np.float32) - self.mean) / self.std
        self.net.setInput(cv2.dnn.blobFromImage(img))
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        boxes, scores = [], []
        by = {o.shape[-2:]: o for o in outs}   # (ancoras, 80 classes) | (ancoras, 32 = 4 lados x 8): casa pela forma
        for anc, st in zip(self.anchors, self.STRIDES):
            cls, reg = by[(len(anc), 80)].reshape(len(anc), 80), np.exp(by[(len(anc), 32)].reshape(-1, self.REG + 1))
            d = (reg / reg.sum(1, keepdims=True)) @ np.arange(self.REG + 1) * st
            d = d.reshape(-1, 4)
            boxes.append(np.column_stack((anc - d[:, :2], anc + d[:, 2:])))
            scores.append(cls)
        boxes, scores = np.concatenate(boxes), np.concatenate(scores)
        cid, conf = scores.argmax(1), scores.max(1)
        sel = conf >= self.conf
        boxes, cid, conf = boxes[sel], cid[sel], conf[sel]
        if not len(conf):
            return []
        wh = np.column_stack((boxes[:, :2], boxes[:, 2:] - boxes[:, :2]))
        keep = cv2.dnn.NMSBoxesBatched(wh.tolist(), conf.tolist(), cid.tolist(), self.conf, self.iou)
        out = []
        for i in np.asarray(keep).ravel()[:MAX_OBJS * 2]:
            x0, y0, x1, y1 = np.clip(boxes[i] / k, 0, None)
            out.append((min(1.0, x0 / w), min(1.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h), float(conf[i]), int(cid[i])))
        out.sort(key=lambda r: -r[4])
        return out


class Corpo:
    S = 256
    SCALE = 1.25                 # folga da janela em volta do corpo (MediaPipe)

    def __init__(self, path=POSE_MODEL, objetos=None, conf=0.5):
        import cv2
        self.cv2, self.conf = cv2, conf
        self.net = cv2.dnn.readNet(path)
        self.obj = objetos           # acha a pessoa quando perde (ou None = so' testa o rastreio)
        self.roi = None              # (cx, cy, lado, giro rad) em px do quadro: onde olhar no proximo

    def _roi_from_box(self, b, w, h):
        x0, y0, x1, y1 = b[0] * w, b[1] * h, b[2] * w, b[3] * h
        return ((x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * self.SCALE, 0.0)

    def __call__(self, rgb, pessoas=None):
        """pessoas = caixas do Objetos ja' calculadas nesse quadro (poupa rodar de novo)."""
        h, w = rgb.shape[:2]
        if self.roi is None:
            if pessoas is None:
                pessoas = [o for o in (self.obj(rgb) if self.obj else []) if o[5] == PESSOA]
            if not pessoas:
                return None
            big = max(pessoas, key=lambda o: (o[2] - o[0]) * (o[3] - o[1]))
            self.roi = self._roi_from_box(big, w, h)
        lm = self._pose(rgb, *self.roi)
        if lm is None:
            self.roi = None
            return None
        hip, top = lm[33, :2], lm[34, :2]     # pontos de alinhamento: centro do quadril e "topo" do corpo
        v = top - hip
        self.roi = (hip[0], hip[1], 2 * np.hypot(*v) * self.SCALE, np.pi / 2 - np.arctan2(-v[1], v[0]))
        out = lm[:33][:, (0, 1, 3)].copy()        # x, y, visibilidade
        out[:, 0] /= w
        out[:, 1] /= h
        return out

    def _pose(self, rgb, cx, cy, side, rot):
        """Roda o BlazePose numa janela quadrada girada; devolve (39, 5) px do quadro: x, y, z, vis, presenca."""
        cv2, S = self.cv2, self.S
        c, s = np.cos(rot), np.sin(rot)
        k = side / S
        # entrada (u, v) -> quadro: centro + R(rot) * (u - S/2, v - S/2) * k
        A = np.array([[c * k, -s * k, cx - (c * k * S / 2 - s * k * S / 2)],
                      [s * k, c * k, cy - (s * k * S / 2 + c * k * S / 2)]], np.float32)
        crop = cv2.warpAffine(rgb, A, (S, S), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT)
        self.net.setInput(crop[None].astype(np.float32) / 255.0)
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        by = {o.size: o for o in outs}
        conf = float(by[1].ravel()[0])
        if conf < self.conf:
            return None
        lm = by[195].reshape(39, 5).astype(np.float64)
        lm[:, 3:] = 1 / (1 + np.exp(-lm[:, 3:]))
        xy = lm[:, :2] @ A[:, :2].T + A[:, 2]
        lm[:, :2] = xy
        return lm


def _selfcheck(img_path=None):
    import time
    import cv2
    assert len(COCO) == 80, len(COCO)
    for p in (FACE_MODEL, POSE_MODEL, OBJ_MODEL, MESH_MODEL):
        assert os.path.exists(p), p
    blank = np.zeros((360, 640, 3), np.uint8)
    rosto, obj = Rosto(), Objetos()
    corpo, contorno = Corpo(objetos=obj), Contorno(rosto=rosto)
    assert rosto(blank) == [] and obj(blank) == [] and corpo(blank) is None and contorno(blank) == [], 'quadro preto: nada'
    # a janela girada volta pro lugar: um ponto branco no quadro aparece no centro do recorte
    dot = blank.copy()
    cv2.circle(dot, (400, 120), 6, (255, 255, 255), -1)
    for rot in (0.0, 0.7, -2.0):
        c, s = np.cos(rot), np.sin(rot)
        A = np.array([[c, -s, 400 - (c * 128 - s * 128)], [s, c, 120 - (s * 128 + c * 128)]], np.float32)
        cr = cv2.warpAffine(dot, A, (256, 256), flags=cv2.WARP_INVERSE_MAP)
        yx = np.argwhere(cr[..., 0] > 128).mean(0)
        assert abs(yx[0] - 128) < 2 and abs(yx[1] - 128) < 2, (rot, yx)
    if img_path:
        rgb = cv2.imread(img_path)[..., ::-1].copy()
        for name, fn in (('rosto', rosto), ('objetos', obj), ('corpo', corpo), ('contorno', contorno)):
            fn(rgb)
            t = time.perf_counter()
            for _ in range(10):
                r = fn(rgb)
            ms = (time.perf_counter() - t) * 100
            if name == 'objetos':
                r = [(COCO[o[5]], round(o[4], 2)) for o in r]
            elif name == 'corpo' and r is not None:
                r = {i: tuple(np.round(r[i], 2)) for i in (0, 2, 5, 11, 12)}   # nariz, olhos, ombros
            elif name == 'contorno':
                r = [np.round(e.mean(1), 3).tolist() for e in r]                # centro de cada olho
            print(f'{name}: {ms:.1f} ms ->', r)
    print('rastreio ok')


if __name__ == '__main__':
    if '--selfcheck' in sys.argv:
        _selfcheck(next((a for a in sys.argv[1:] if not a.startswith('-')), None))
