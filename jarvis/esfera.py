"""Esfera procedural Qt: partículas 3D e filamentos orgânicos, sem imagens."""

import math
import random
import time
from PySide6.QtCore import QPointF, QRectF, QTimer, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


class Nucleo(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(180, 180)
        self.fase = 0.0
        self.nivel = 0.0
        self.alvo = 0.0
        self.modo = "desativado"
        self.erro = False
        self.reduzir = False
        self.suspenso = False
        self.ultimo_audio = 0.0
        rng = random.Random(19)
        # Distribuição fixa na superfície: animação transforma posições, sem ruído aleatório por frame.
        self.particulas = []
        for i in range(420):
            z = 1 - 2 * (i + 0.5) / 420
            a = i * 2.3999632297
            r = math.sqrt(max(0, 1 - z * z))
            self.particulas.append(
                (r * math.cos(a), z, r * math.sin(a), rng.uniform(0.45, 1.2))
            )
        self.anel = [
            (
                i * 2.3999632297,
                rng.uniform(-0.023, 0.023),
                i % 6,
                rng.uniform(0.45, 1.0),
            )
            for i in range(720)
        ]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.avancar)
        self.timer.start(33)

    def sizeHint(self):
        return QSize(480, 430)

    def avancar(self):
        if self.suspenso or self.reduzir:
            return
        if time.monotonic() - self.ultimo_audio > 0.18:
            self.alvo = self.nivel = 0.0
        self.nivel += 0.45 * (self.alvo - self.nivel)
        velocidade = 0.012 if self.modo == "processando" else 0.0035
        self.fase = (self.fase + velocidade) % (math.tau * 100)
        self.update()

    def estado_operacao(self, modo):
        self.modo = modo
        if modo not in ("falando", "ouvindo"):
            self.nivel = self.alvo = 0.0
        self.update()

    def movimento(self, reduzir):
        self.reduzir = reduzir
        self._timer()
        self.update()

    def falha(self, ativo):
        self.erro = ativo
        self.update()

    def suspender(self, pausar):
        self.suspenso = pausar
        self._timer()

    def _timer(self):
        (
            self.timer.stop()
            if self.reduzir or self.suspenso or not self.isVisible()
            else self.timer.start(33)
        )

    def amplitude(self, nivel):
        self.alvo = max(0.0, min(1.0, float(nivel)))
        self.ultimo_audio = time.monotonic()
        if self.alvo < 0.015:
            self.nivel = (
                0.0  # Silêncio reduz imediatamente a energia; repouso continua.
            )
        elif self.reduzir:
            self.nivel = self.alvo
        self.update()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._timer()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        energia = self.nivel if self.modo in ("ouvindo", "falando") else 0.0
        movimento = 0.0 if self.reduzir else self.fase
        ganho = 0.58 if self.modo == "desativado" else 1.0
        raio = min(self.width(), self.height()) * 0.365
        expansao = 1.0 + (
            0.0 if self.reduzir else energia * 0.105 + 0.006 * math.sin(movimento * 2)
        )
        r = raio * expansao
        # Luz difusa contida dentro da área do widget, com núcleo pequeno e sensação de volume.
        halo = QRadialGradient(QPointF(0, 0), r * 1.31)
        halo.setColorAt(0, QColor(5, 41, 74, int(80 * ganho)))
        halo.setColorAt(0.65, QColor(1, 66, 98, int((30 + energia * 32) * ganho)))
        halo.setColorAt(1, QColor(0, 9, 18, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(0, 0), r * 1.3, r * 1.3)
        # Dez faixas: contorno irregular + curvatura em profundidade, inspirado na referência de energia.
        for j in range(10):
            path = QPainterPath()
            for i in range(145):
                a = math.tau * i / 144
                onda = 0.052 * math.sin(
                    a * 3 + movimento * 2 + j * 0.35
                ) + 0.025 * math.sin(a * 7 - movimento * 3 + j * 0.5)
                radial = r * (
                    0.93
                    + j * 0.006
                    + onda
                    + energia * 0.045 * math.sin(a * 5 + j + movimento * 6)
                )
                x = math.cos(a) * radial
                y = (
                    math.sin(a)
                    * radial
                    * (0.86 + 0.1 * math.sin(j * 0.55 + movimento * 0.5))
                )
                y += r * 0.055 * math.sin(a * 2 + j + movimento)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(25, 155, 235, int(18 * ganho)), 3.0))
            p.drawPath(path)
            p.setPen(
                QPen(
                    QColor(
                        36,
                        184 + int(j * 5),
                        245,
                        int((68 + j * 4 + energia * 38) * ganho),
                    ),
                    0.7 + (0.2 if j % 3 == 0 else 0),
                )
            )
            p.drawPath(path)
        # Poeira no contorno dá espessura aos filamentos, sem multiplicar a carga de desenho.
        p.setPen(Qt.PenStyle.NoPen)
        for a, deslocamento, faixa, tamanho in self.anel:
            a += movimento * (0.22 if self.modo == "processando" else 0.04)
            rr = r * (
                0.94
                + faixa * 0.011
                + deslocamento
                + 0.052 * math.sin(a * 3 + movimento * 2 + faixa * 0.35)
                + 0.025 * math.sin(a * 7 - movimento * 3 + faixa * 0.5)
                + energia * 0.035 * math.sin(a * 5 + faixa + movimento * 6)
            )
            y = (
                math.sin(a)
                * rr
                * (0.9 + 0.065 * math.sin(faixa * 0.55 + movimento * 0.5))
            )
            y += r * 0.025 * math.sin(a * 2 + faixa + movimento)
            p.setBrush(
                QColor(58, 198, 249, int((48 + tamanho * 48 + energia * 35) * ganho))
            )
            p.drawEllipse(QPointF(math.cos(a) * rr, y), tamanho * 0.75, tamanho * 0.75)
        # Projeção ortográfica de partículas e meridianos luminosos; trás escuro, frente nítida.
        ang = movimento * (1.8 if self.modo == "processando" else 0.6)
        ca, sa = math.cos(ang), math.sin(ang)
        for x, y, z, tamanho in self.particulas:
            xx = x * ca + z * sa
            zz = z * ca - x * sa
            escala = 1.0 + zz * 0.09
            alpha = int((22 + (zz + 1) * 29 + energia * 40) * ganho)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(48, 170 + int((zz + 1) * 27), 250, alpha))
            p.drawEllipse(
                QPointF(xx * r * escala, y * r * escala),
                tamanho * (0.7 + (zz + 1) * 0.28),
                tamanho * (0.7 + (zz + 1) * 0.28),
            )
        for j in range(5):
            path = QPainterPath()
            for i in range(100):
                a = math.tau * i / 99
                phi = j * 0.61 + ang + 0.025 * math.sin(a * 5 + movimento)
                x = math.cos(a) * math.cos(phi) * r * 0.94
                y = math.sin(a) * r * 0.91
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(QColor(47, 178, 247, int((24 + energia * 25) * ganho)), 0.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        # Raios finos e contínuos, jamais flashes: sua extensão depende da energia medida.
        if energia > 0.04 and not self.reduzir:
            for j in range(7):
                a = j * 0.897 + movimento * 0.18
                caminho = QPainterPath()
                rr = r * (0.42 + j % 3 * 0.07)
                caminho.moveTo(math.cos(a) * rr, math.sin(a) * rr)
                for k in range(1, 5):
                    distancia = rr + (r * 0.37 + energia * r * 0.12) * k / 4
                    aa = a + 0.027 * math.sin(k * 2 + j + movimento)
                    caminho.lineTo(math.cos(aa) * distancia, math.sin(aa) * distancia)
                p.setPen(QPen(QColor(85, 220, 255, int(35 + energia * 38)), 0.7))
                p.drawPath(caminho)
        nucleo = QRadialGradient(QPointF(-r * 0.035, -r * 0.025), r * 0.17)
        nucleo.setColorAt(0, QColor(102, 233, 255, int((125 + energia * 70) * ganho)))
        nucleo.setColorAt(0.26, QColor(22, 161, 222, int(90 * ganho)))
        nucleo.setColorAt(1, QColor(1, 74, 115, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(nucleo)
        p.drawEllipse(QPointF(0, 0), r * 0.17, r * 0.17)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(36, 179, 224, int(55 * ganho)), 0.7))
        p.drawEllipse(QPointF(0, 0), r * 0.125, r * 0.125)
        if self.erro or self.modo == "erro":
            p.setPen(QPen(QColor(220, 138, 125, 110), 1))
            p.drawArc(QRectF(-r, -r, r * 2, r * 2), 30 * 16, 95 * 16)
