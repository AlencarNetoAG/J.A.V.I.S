"""Painel Qt original. Widgets e animações permanecem na thread principal."""
import html
import math
import sys

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QLineEdit, QProgressBar, QScrollArea,
    QDialog, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QDialogButtonBox, QMessageBox,
)
from dataclasses import replace

from .configuracoes import carregar, salvar
from .horario import agora_recife
from .runtime import Runtime

ESTILO = """
QWidget { background:#050d17; color:#d7eaf5; font-family:'Segoe UI'; font-size:14px; }
QLabel#titulo { font-size:30px; letter-spacing:7px; color:#5de9ff; font-weight:600; }
QLabel#subtitulo { color:#8ca6bc; font-size:12px; }
QLabel#cartao { background:#0a1a29; border:1px solid #17435b; border-radius:12px; padding:15px; }
QPushButton { background:#0b263a; border:1px solid #20607b; border-radius:8px; padding:10px; }
QPushButton:hover { background:#124259; border-color:#5de9ff; }
QPushButton:disabled { color:#526776; border-color:#1b2a35; }
QPushButton#parar { color:#ffbdab; border-color:#925949; }
QLineEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox { background:#081522; border:1px solid #21465c; border-radius:7px; padding:8px; }
QTextBrowser { padding:12px; }
QProgressBar { background:#0a1a29; border:0; border-radius:4px; max-height:7px; }
QProgressBar::chunk { background:#43dff6; border-radius:4px; }
QScrollArea { border:0; }
"""


class Nucleo(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.setMinimumWidth(180)
        self.fase = 0.0
        self.nivel = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.avancar)
        self.timer.start(40)

    def avancar(self):
        self.fase = (self.fase + 0.8) % 360
        self.update()

    def movimento(self, reduzir):
        self.timer.stop() if reduzir else self.timer.start(40)
        self.update()

    def amplitude(self, nivel):
        self.nivel = nivel
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        raio = min(self.width(), self.height()) * 0.39
        p.translate(cx, cy)
        for escala, cor, largura in ((1, "#174660", 1), (.89, "#38cfe9", 2), (.73, "#206ba1", 3), (.57, "#5de9ff", 2)):
            r = raio * escala
            p.setPen(QPen(QColor(cor), largura))
            p.drawArc(QRectF(-r, -r, r * 2, r * 2), int((self.fase / escala) * 16), 285 * 16)
        for i in range(48):
            a = math.radians(i * 7.5)
            r = raio * 1.08
            comprimento = 5 + self.nivel * 17
            p.setPen(QPen(QColor("#297894"), 2))
            from PySide6.QtCore import QPointF
            p.drawLine(QPointF(math.cos(a)*r, math.sin(a)*r), QPointF(math.cos(a)*(r+comprimento), math.sin(a)*(r+comprimento)))
        p.setPen(QColor("#baf5ff"))
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        p.drawText(QRectF(-80, -22, 160, 44), Qt.AlignmentFlag.AlignCenter, "J A R V I S")


class Preferencias(QDialog):
    def __init__(self, config, parent):
        super().__init__(parent)
        self.setWindowTitle("Configurações locais")
        self.setMinimumWidth(480)
        self.config = replace(config)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mic = QComboBox()
        self.mic.addItem("Padrão do Windows", None)
        self.voz = QComboBox()
        self.voz.addItem("Português automático (voz instalada)", None)
        if config.microfone is not None:
            self.mic.addItem(f"Dispositivo {config.microfone}", config.microfone)
            self.mic.setCurrentIndex(1)
        if config.voz:
            self.voz.addItem(config.voz, config.voz)
            self.voz.setCurrentIndex(1)
        self.velocidade = QSpinBox(); self.velocidade.setRange(80, 300); self.velocidade.setValue(config.velocidade)
        self.volume = QDoubleSpinBox(); self.volume.setRange(0, 1); self.volume.setSingleStep(.02); self.volume.setValue(config.volume)
        self.timeout = QSpinBox(); self.timeout.setRange(3, 60); self.timeout.setValue(int(config.timeout_pergunta))
        self.maximo = QSpinBox(); self.maximo.setRange(3, 30); self.maximo.setValue(int(config.captura_maxima))
        self.limiar = QDoubleSpinBox(); self.limiar.setDecimals(3); self.limiar.setRange(.001, .5); self.limiar.setSingleStep(.005); self.limiar.setValue(config.limiar)
        self.modelo = QLineEdit(config.modelo)
        self.arquivo = QLineEdit(config.musica)
        escolher = QPushButton("Escolher MP3")
        escolher.clicked.connect(self.escolher)
        caminho = QHBoxLayout(); caminho.addWidget(self.arquivo); caminho.addWidget(escolher)
        self.reduzir = QCheckBox("Reduzir movimento"); self.reduzir.setChecked(config.reduzir_movimento)
        self.sem_voz = QCheckBox("Desativar fala"); self.sem_voz.setChecked(config.sem_voz)
        self.sem_musica = QCheckBox("Desativar música"); self.sem_musica.setChecked(config.sem_musica)
        for nome, widget in (("Microfone",self.mic),("Voz",self.voz),("Velocidade",self.velocidade),("Volume da música",self.volume),("Espera pela pergunta (s)",self.timeout),("Captura máxima (s)",self.maximo),("Limiar do microfone",self.limiar),("Modelo Whisper",self.modelo)):
            form.addRow(nome,widget)
        form.addRow("Música local", caminho)
        layout.addLayout(form)
        layout.addWidget(self.reduzir); layout.addWidget(self.sem_voz); layout.addWidget(self.sem_musica)
        aviso = QLabel("Vozes disponíveis são as instaladas no computador.\nA chave da API é configurada somente no .env local.")
        aviso.setWordWrap(True); layout.addWidget(aviso)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.accept); botoes.rejected.connect(self.reject); layout.addWidget(botoes)

    def escolher(self):
        nome, _ = QFileDialog.getOpenFileName(self, "Escolher sua música", "", "Áudio MP3 (*.mp3)")
        if nome:
            self.arquivo.setText(nome)

    def atualizar_dispositivos(self, dados):
        for combo, chave, selecionado in ((self.mic, "microfones", self.config.microfone),(self.voz,"vozes",self.config.voz)):
            for identificador, nome in dados.get(chave, []):
                if combo.findData(identificador) < 0:
                    combo.addItem(nome, identificador)
            i = combo.findData(selecionado)
            if i >= 0:
                combo.setCurrentIndex(i)

    def resultado(self):
        return replace(self.config, microfone=self.mic.currentData(), voz=self.voz.currentData(),
                       velocidade=self.velocidade.value(), volume=self.volume.value(),
                       timeout_pergunta=self.timeout.value(), captura_maxima=self.maximo.value(),
                       limiar=self.limiar.value(), modelo=self.modelo.text().strip() or "tiny",
                       musica=self.arquivo.text(), reduzir_movimento=self.reduzir.isChecked(),
                       sem_voz=self.sem_voz.isChecked(), sem_musica=self.sem_musica.isChecked()).validar()


class Janela(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or carregar()
        self.runtime = Runtime(self.config)
        self.setWindowTitle("JARVIS · Assistente pessoal")
        self.resize(1000, 760)
        self.setMinimumSize(580, 420)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        conteudo = QWidget(); layout = QVBoxLayout(conteudo); layout.setContentsMargins(20,16,20,16); layout.setSpacing(8)
        titulo = QLabel("JARVIS"); titulo.setObjectName("titulo"); layout.addWidget(titulo)
        subtitulo = QLabel("ASSISTENTE PESSOAL  /  RECONHECIMENTO LOCAL  /  SALGUEIRO · PE")
        subtitulo.setObjectName("subtitulo"); subtitulo.setWordWrap(True); layout.addWidget(subtitulo)
        self.estado = QLabel("Desativado · use texto ou ative o microfone"); layout.addWidget(self.estado)
        centro = QHBoxLayout()
        self.nucleo = Nucleo(); centro.addWidget(self.nucleo, 1)
        self.relogio = QLabel(); self.relogio.setObjectName("cartao"); self.relogio.setWordWrap(True); centro.addWidget(self.relogio, 1)
        layout.addLayout(centro)
        self.nivel = QProgressBar(); self.nivel.setRange(0,100); self.nivel.setValue(0); self.nivel.setTextVisible(False)
        legenda = QLabel("NÍVEL CAPTADO NO MICROFONE · sem captura durante fala ou música"); legenda.setObjectName("subtitulo"); legenda.setWordWrap(True)
        layout.addWidget(legenda); layout.addWidget(self.nivel)
        cards = QHBoxLayout()
        self.clima = QLabel("CLIMA · SALGUEIRO\nAinda não consultado\nDiga ou digite bom dia Jarvis")
        self.dolar = QLabel("USD / BRL\nAinda não consultado\nCompra · referência de mercado")
        for card in (self.clima, self.dolar):
            card.setObjectName("cartao"); card.setWordWrap(True); card.setMinimumHeight(115); cards.addWidget(card,1)
        layout.addLayout(cards)
        self.historico = QTextBrowser(); self.historico.setMinimumHeight(110); layout.addWidget(self.historico,1)
        self.aviso = QLabel("A conversa geral requer uma chave da API no .env. Bom dia funciona sem chave.")
        self.aviso.setObjectName("subtitulo"); self.aviso.setWordWrap(True); layout.addWidget(self.aviso)
        pergunta = QHBoxLayout()
        self.entrada = QLineEdit(); self.entrada.setMaxLength(4000); self.entrada.setPlaceholderText("Pergunte ou digite bom dia Jarvis…")
        self.enviar = QPushButton("Enviar"); self.enviar.clicked.connect(self.enviar_texto); self.entrada.returnPressed.connect(self.enviar_texto)
        pergunta.addWidget(self.entrada,1); pergunta.addWidget(self.enviar)
        botoes = QHBoxLayout()
        self.mic = QPushButton("Ativar microfone"); self.mic.clicked.connect(self.runtime.alternar_microfone)
        self.parar = QPushButton("Parar"); self.parar.setObjectName("parar"); self.parar.clicked.connect(self.runtime.parar)
        self.limpar = QPushButton("Limpar conversa"); self.limpar.clicked.connect(self.limpar_conversa)
        self.preferencias = QPushButton("Configurações"); self.preferencias.clicked.connect(self.configurar)
        for botao in (self.mic,self.parar,self.limpar,self.preferencias): botoes.addWidget(botao)
        # Entrada e controles fixos; somente o painel superior usa rolagem.
        # Assim Parar permanece acessível mesmo em uma janela pequena.
        scroll.setWidget(conteudo)
        central = QWidget(); principal = QVBoxLayout(central); principal.setContentsMargins(0,0,0,0)
        principal.addWidget(scroll,1)
        rodape = QWidget(); rodape_layout = QVBoxLayout(rodape); rodape_layout.setContentsMargins(20,0,20,12)
        rodape_layout.addLayout(pergunta); rodape_layout.addLayout(botoes)
        principal.addWidget(rodape); self.setCentralWidget(central)
        self.runtime.estado.connect(self.estado.setText)
        self.runtime.mensagem.connect(self.adicionar)
        self.runtime.ocupado.connect(self.ocupado)
        self.runtime.nivel.connect(self.amplitude)
        self.runtime.cartoes.connect(self.atualizar_cartoes)
        self.runtime.microfone.connect(lambda ativo: self.mic.setText("Desativar microfone" if ativo else "Ativar microfone"))
        self.timer = QTimer(self); self.timer.timeout.connect(self.atualizar_relogio); self.timer.start(1000)
        self.atualizar_relogio(); self.nucleo.movimento(self.config.reduzir_movimento)
        self.historico.document().setMaximumBlockCount(120)

    def atualizar_relogio(self):
        agora = agora_recife()
        self.relogio.setText(f"SALGUEIRO · PERNAMBUCO\n\n{agora:%H:%M:%S}\n{agora:%d/%m/%Y}\n\nAmerica/Recife")

    def enviar_texto(self):
        if self.runtime.enviar(self.entrada.text()):
            self.entrada.clear()

    def adicionar(self, papel, texto):
        if papel == "Aviso":
            self.aviso.setText(texto)
            return
        self.historico.append(f'<p><b style="color:#5de9ff">{html.escape(papel)}</b><br>{html.escape(texto).replace(chr(10), "<br>")}</p>')

    def ocupado(self, ocupado):
        self.enviar.setEnabled(not ocupado)
        self.preferencias.setEnabled(not ocupado)

    def amplitude(self, valor):
        self.nivel.setValue(int(valor * 100)); self.nucleo.amplitude(valor)

    def atualizar_cartoes(self, dados):
        self.clima.setText("CLIMA · SALGUEIRO\n" + dados["clima"])
        self.dolar.setText("USD / BRL\n" + dados["dolar"])

    def limpar_conversa(self):
        self.runtime.limpar(); self.historico.clear()

    def configurar(self):
        self.runtime.parar()
        dialog = Preferencias(self.config, self)
        self.runtime.dispositivos.connect(dialog.atualizar_dispositivos)
        self.runtime.listar_dispositivos()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.config = dialog.resultado(); salvar(self.config)
                self.runtime.configurar(self.config)
                self.nucleo.movimento(self.config.reduzir_movimento)
            except (ValueError, OSError):
                QMessageBox.warning(self,"Configurações","Não foi possível salvar as preferências locais.")
        self.runtime.dispositivos.disconnect(dialog.atualizar_dispositivos)

    def closeEvent(self, event):
        self.runtime.fechar()
        event.accept()


def iniciar(config=None):
    app = QApplication(sys.argv)
    app.setStyleSheet(ESTILO)
    janela = Janela(config)
    janela.show()
    return app.exec()
