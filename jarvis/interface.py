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
    QFileDialog, QDialogButtonBox, QMessageBox, QSlider, QBoxLayout, QGroupBox,
)
from dataclasses import replace

from .configuracoes import carregar, salvar
from .horario import agora_recife
from .runtime import Runtime
from .interface_pc import PermissoesDialog, ConfirmacaoDialog

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
        self.modo = "aguardando"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.avancar)
        self.timer.start(40)

    def avancar(self):
        self.fase = (self.fase + {"aguardando":.3,"ouvindo":.8,"processando":2.,"falando":1.3}[self.modo]) % 360
        self.update()

    def estado_operacao(self, modo):
        self.modo = modo
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
        self.identidades = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mic = QComboBox()
        self.mic.addItem("Padrão do Windows (entrada atual)", None)
        self.voz = QComboBox()
        self.voz.addItem("Português automático (voz instalada)", None)
        if config.microfone is not None:
            self.mic.addItem(f"Dispositivo {config.microfone}", config.microfone)
            self.mic.setCurrentIndex(1)
        if config.voz:
            self.voz.addItem(config.voz, config.voz)
            self.voz.setCurrentIndex(1)
        self.velocidade = QSpinBox(); self.velocidade.setRange(80, 300); self.velocidade.setValue(config.velocidade)
        self.volume_voz = QDoubleSpinBox(); self.volume_voz.setRange(0, 1); self.volume_voz.setSingleStep(.05); self.volume_voz.setValue(config.volume_voz)
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
        for nome, widget in (("Microfone",self.mic),("Voz",self.voz),("Velocidade",self.velocidade),("Volume da música",self.volume),("Volume da voz",self.volume_voz),("Espera pela pergunta (s)",self.timeout),("Captura máxima (s)",self.maximo),("Limiar do microfone",self.limiar),("Modelo Whisper",self.modelo)):
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
        self.identidades = dados.get("identidades", {})
        self.mic.clear(); self.mic.addItem("Padrão do Windows (entrada atual)", None)
        escolhido = None
        for indice, nome in dados.get("microfones", []):
            self.mic.addItem(nome, indice)
            if self.config.microfone_identidade:
                if self.identidades.get(indice) == self.config.microfone_identidade:
                    escolhido = indice
            elif indice == self.config.microfone:
                escolhido = indice
        if (self.config.microfone_identidade or self.config.microfone is not None) and escolhido is None:
            self.mic.addItem("Selecionado indisponível", self.config.microfone)
            self.mic.setCurrentIndex(self.mic.count()-1)
        else:
            self.mic.setCurrentIndex(max(0, self.mic.findData(escolhido)))
        for identificador, nome in dados.get("vozes", []):
            if self.voz.findData(identificador) < 0:
                self.voz.addItem(nome, identificador)
        i = self.voz.findData(self.config.voz)
        if i >= 0: self.voz.setCurrentIndex(i)

    def resultado(self):
        return replace(self.config, microfone=self.mic.currentData(),
                       microfone_identidade=self.identidades.get(self.mic.currentData(), self.config.microfone_identidade) if self.mic.currentData() is not None else None, voz=self.voz.currentData(),
                       velocidade=self.velocidade.value(), volume=self.volume.value(), volume_voz=self.volume_voz.value(),
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
        self.estado = QLabel("Desativado · use texto ou ative o microfone"); self.estado.setWordWrap(True); layout.addWidget(self.estado)
        pc_botoes=QHBoxLayout()
        self.permissoes_pc=QPushButton("Permissões do PC");self.permissoes_pc.clicked.connect(self.configurar_pc)
        self.suspender_pc=QPushButton("Retomar controle do PC" if self.config.pc_suspenso else "Suspender controle do PC");self.suspender_pc.clicked.connect(self.runtime.suspender_pc)
        self.cancelar_acao=QPushButton("Cancelar ação");self.cancelar_acao.clicked.connect(self.runtime.cancelar_acao)
        for b in (self.permissoes_pc,self.suspender_pc,self.cancelar_acao):pc_botoes.addWidget(b)
        layout.addLayout(pc_botoes)
        self.acao_pc=QLabel("Ações do PC: nenhuma em andamento");self.acao_pc.setTextFormat(Qt.TextFormat.PlainText);self.acao_pc.setWordWrap(True);layout.addWidget(self.acao_pc)
        self.dialog_decisao=None
        centro = QHBoxLayout(); self.centro_layout = centro
        self.nucleo = Nucleo(); centro.addWidget(self.nucleo, 1)
        self.relogio = QLabel(); self.relogio.setObjectName("cartao"); self.relogio.setWordWrap(True); centro.addWidget(self.relogio, 1)
        layout.addLayout(centro)
        self.nivel = QProgressBar(); self.nivel.setRange(0,100); self.nivel.setValue(0); self.nivel.setTextVisible(False)
        legenda = QLabel("NÍVEL CAPTADO NO MICROFONE · sem captura durante fala ou música"); legenda.setObjectName("subtitulo"); legenda.setWordWrap(True)
        layout.addWidget(legenda); layout.addWidget(self.nivel)
        microfones = QHBoxLayout(); self.microfones_layout = microfones
        self.entradas = QComboBox(); self.entradas.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.entradas.setMinimumContentsLength(20); self.entradas.addItem("Padrão do Windows (entrada atual)", None)
        self.identidades = {}
        self.atualizar_mics = QPushButton("Atualizar microfones")
        self.atualizar_mics.clicked.connect(self.runtime.listar_dispositivos)
        self.testar_mic = QPushButton("Testar microfone")
        self.testar_mic.clicked.connect(self.runtime.testar_microfone)
        microfones.addWidget(self.entradas, 1); microfones.addWidget(self.atualizar_mics); microfones.addWidget(self.testar_mic)
        layout.addLayout(microfones)
        self.transcricao = QLabel("Texto reconhecido: ainda não disponível")
        self.transcricao.setWordWrap(True); layout.addWidget(self.transcricao)
        self.teste_resultado = QLabel("Teste: fique em silêncio na calibração; depois diga bom dia Jarvis.")
        self.teste_resultado.setWordWrap(True); layout.addWidget(self.teste_resultado)
        spotify=QGroupBox("Spotify · conta e mídia externa");sp_layout=QVBoxLayout(spotify)
        conta=QHBoxLayout()
        self.conectar_spotify=QPushButton("Conectar Spotify");self.conectar_spotify.clicked.connect(lambda:self.runtime.ferramenta_pc("spotify_conectar"))
        self.desconectar_spotify=QPushButton("Desconectar");self.desconectar_spotify.clicked.connect(lambda:self.runtime.ferramenta_pc("spotify_desconectar"))
        atual=QPushButton("Música atual");atual.clicked.connect(lambda:self.runtime.ferramenta_pc("spotify_controlar",{"acao":"atual"}))
        for b in (self.conectar_spotify,self.desconectar_spotify,atual):conta.addWidget(b)
        sp_layout.addLayout(conta)
        reproduzir=QHBoxLayout()
        self.spotify_botoes=[self.conectar_spotify,self.desconectar_spotify,atual]
        for nome,acao in (("Pausar Spotify","pausar"),("Retomar Spotify","retomar"),("Anterior","anterior"),("Próxima","proxima")):
            botao=QPushButton(nome);botao.clicked.connect(lambda checked=False,a=acao:self.runtime.ferramenta_pc("spotify_controlar",{"acao":a}));reproduzir.addWidget(botao);self.spotify_botoes.append(botao)
        sp_layout.addLayout(reproduzir)
        volume_sp=QHBoxLayout();volume_sp.addWidget(QLabel("Volume Spotify"))
        self.volume_spotify=QSpinBox();self.volume_spotify.setRange(0,100);self.volume_spotify.setValue(50);self.volume_spotify.setSuffix("%")
        aplicar_sp=QPushButton("Aplicar volume");aplicar_sp.clicked.connect(lambda:self.runtime.ferramenta_pc("audio_volume",{"fonte":"spotify","percentual":self.volume_spotify.value()}));self.spotify_botoes.append(aplicar_sp)
        volume_sp.addWidget(self.volume_spotify);volume_sp.addWidget(aplicar_sp);sp_layout.addLayout(volume_sp);layout.addWidget(spotify)
        cards = QHBoxLayout(); self.cards_layout = cards
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
        self.audio_estado = "parada"
        self.fala_ativa = False
        musica_controles = QHBoxLayout()
        self.pausa_musica = QPushButton("Pausar música"); self.pausa_musica.setEnabled(False)
        self.pausa_musica.clicked.connect(lambda: self.runtime.controlar_musica("retomar" if self.audio_estado == "pausada" else "pausar"))
        self.stop_musica = QPushButton("Parar música"); self.stop_musica.setEnabled(False)
        self.stop_musica.clicked.connect(lambda: self.runtime.controlar_musica("parar"))
        self.volume_musica = QSlider(Qt.Orientation.Horizontal); self.volume_musica.setRange(0,100); self.volume_musica.setValue(round(self.config.volume*100)); self.volume_musica.setMinimumWidth(50)
        self.volume_musica.setAccessibleName("Volume da música")
        self.percentual_musica = QLabel(f"{self.volume_musica.value()}%")
        musica_controles.addWidget(self.pausa_musica); musica_controles.addWidget(self.stop_musica)
        musica_controles.addWidget(QLabel("MP3")); musica_controles.addWidget(self.volume_musica,1); musica_controles.addWidget(self.percentual_musica)
        voz_controles = QHBoxLayout()
        self.habilitar_voz = QCheckBox("Responder por voz"); self.habilitar_voz.setChecked(not self.config.sem_voz)
        self.interromper_voz = QPushButton("Interromper fala"); self.interromper_voz.setEnabled(False)
        self.interromper_voz.clicked.connect(self.runtime.interromper_fala)
        self.volume_voz = QSlider(Qt.Orientation.Horizontal); self.volume_voz.setRange(0,100); self.volume_voz.setValue(round(self.config.volume_voz*100)); self.volume_voz.setMinimumWidth(50)
        self.volume_voz.setAccessibleName("Volume da voz")
        self.percentual_voz = QLabel(f"{self.volume_voz.value()}%")
        voz_controles.addWidget(self.habilitar_voz); voz_controles.addWidget(self.interromper_voz)
        voz_controles.addWidget(QLabel("Voz")); voz_controles.addWidget(self.volume_voz,1); voz_controles.addWidget(self.percentual_voz)
        todos_controles = QHBoxLayout()
        self.stop_audios = QPushButton("Parar todos os áudios"); self.stop_audios.setObjectName("parar")
        self.stop_audios.clicked.connect(self.runtime.parar_audios)
        self.status_audio = QLabel("Música: parada · voz: desativada" if self.config.sem_voz else "Música: parada · voz: pronta")
        self.status_audio.setWordWrap(True)
        todos_controles.addWidget(self.stop_audios); todos_controles.addWidget(self.status_audio,1)
        rodape_layout.addLayout(musica_controles); rodape_layout.addLayout(voz_controles); rodape_layout.addLayout(todos_controles)
        rodape_layout.addLayout(pergunta); rodape_layout.addLayout(botoes)
        self.salvar_audio_timer = QTimer(self); self.salvar_audio_timer.setSingleShot(True)
        self.salvar_audio_timer.timeout.connect(self.salvar_audio)
        self.volume_musica.valueChanged.connect(lambda v:self.alterar_audio("volume",v/100))
        self.volume_voz.valueChanged.connect(lambda v:self.alterar_audio("volume_voz",v/100))
        self.habilitar_voz.toggled.connect(lambda ativo:self.alterar_audio("sem_voz",not ativo))
        principal.addWidget(rodape); self.setCentralWidget(central)
        self.entradas.currentIndexChanged.connect(self.selecionar_microfone)
        self.runtime.dispositivos.connect(self.atualizar_microfones)
        self.runtime.reconhecido.connect(lambda texto: self.transcricao.setText("Texto reconhecido: " + (texto or "nenhuma fala reconhecida")))
        self.runtime.diagnostico.connect(self.resultado_microfone)
        QTimer.singleShot(0, self.runtime.listar_dispositivos)
        self.runtime.estado.connect(self.estado_runtime)
        self.runtime.audio.connect(self.atualizar_audio)
        self.runtime.falando.connect(self.estado_fala)
        self.runtime.acao.connect(self.estado_acao_pc)
        self.runtime.confirmacao.connect(self.confirmacao_pc)
        self.runtime.config_pc.connect(self.atualizar_config_pc)
        self.runtime.mensagem.connect(self.adicionar)
        self.runtime.ocupado.connect(self.ocupado)
        self.runtime.nivel.connect(self.amplitude)
        self.runtime.cartoes.connect(self.atualizar_cartoes)
        self.runtime.microfone.connect(lambda ativo: self.mic.setText("Desativar microfone" if ativo else "Ativar microfone"))
        self.timer = QTimer(self); self.timer.timeout.connect(self.atualizar_relogio); self.timer.start(1000)
        self.atualizar_relogio(); self.nucleo.movimento(self.config.reduzir_movimento)
        self.historico.document().setMaximumBlockCount(120)

    def configurar_pc(self):
        dialog=PermissoesDialog(self.runtime.config,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try:
                self.runtime.configurar_pc(dialog.resultado());self.config=self.runtime.config;salvar(self.config)
            except (ValueError,OSError):QMessageBox.warning(self,"Permissões","Não foi possível salvar as permissões.")

    def atualizar_config_pc(self,dados):
        self.config=self.runtime.config
        self.suspender_pc.setText("Retomar controle do PC" if self.config.pc_suspenso else "Suspender controle do PC")
        self.volume_musica.blockSignals(True);self.volume_musica.setValue(round(self.config.volume*100));self.volume_musica.blockSignals(False)
        self.percentual_musica.setText(f"{self.volume_musica.value()}%")
        self.salvar_audio_timer.start(250)

    def estado_acao_pc(self,dados):
        texto=dados["ferramenta"].replace('_',' ')+" · "+dados["status"]
        if dados.get("mensagem"):texto+="\n"+dados["mensagem"]
        self.acao_pc.setText(texto)

    def confirmacao_pc(self,pedido):
        if pedido.get("fechado"):
            if self.dialog_decisao and self.dialog_decisao.pedido["id"]==pedido["id"]:
                self.dialog_decisao.finalizar();self.dialog_decisao=None
            return
        if self.dialog_decisao:self.dialog_decisao.finalizar()
        self.dialog_decisao=ConfirmacaoDialog(pedido,self.runtime.decisoes,self);self.dialog_decisao.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,"cards_layout"):
            direcao = QBoxLayout.Direction.TopToBottom if self.width()<720 else QBoxLayout.Direction.LeftToRight
            for layout in (self.centro_layout,self.cards_layout,self.microfones_layout):
                layout.setDirection(direcao)

    def alterar_audio(self, nome, valor):
        self.runtime.preferencia_audio(nome, valor)
        self.config = self.runtime.config
        self.percentual_musica.setText(f"{self.volume_musica.value()}%")
        self.percentual_voz.setText(f"{self.volume_voz.value()}%")
        self.rotulo_audio()
        self.salvar_audio_timer.start(250)

    def salvar_audio(self):
        try: salvar(self.config)
        except (OSError, ValueError): self.aviso.setText("Não foi possível salvar as preferências de áudio.")

    def atualizar_audio(self, dados):
        self.audio_estado = dados["musica"]
        self.pausa_musica.setText("Retomar música" if self.audio_estado == "pausada" else "Pausar música")
        self.pausa_musica.setEnabled(self.audio_estado in ("tocando","pausada"))
        self.stop_musica.setEnabled(self.audio_estado != "parada")
        self.rotulo_audio()

    def rotulo_audio(self):
        voz = "falando" if self.fala_ativa else "desativada" if self.config.sem_voz else "pronta"
        self.status_audio.setText(f"Música: {self.audio_estado} · voz: {voz}")

    def estado_fala(self, falando):
        self.fala_ativa = falando
        self.rotulo_audio()
        self.interromper_voz.setEnabled(falando)
        if falando: self.nucleo.estado_operacao("falando")

    def estado_runtime(self, texto):
        self.estado.setText(texto)
        t = texto.casefold()
        modo = ("falando" if t.startswith("falando") else "ouvindo" if "ouvindo" in t or "calibrando" in t
                else "processando" if any(p in t for p in ("consultando","reconhecendo","carregando","finalizando","executando","autorizando")) else "aguardando")
        self.nucleo.estado_operacao(modo)

    def atualizar_microfones(self, dados):
        self.identidades = dados.get("identidades", {})
        self.entradas.blockSignals(True)
        self.entradas.clear(); self.entradas.addItem("Padrão do Windows (entrada atual)", None)
        escolhido = None
        for indice, nome in dados.get("microfones", []):
            self.entradas.addItem(nome, indice)
            if self.config.microfone_identidade:
                if self.identidades.get(indice) == self.config.microfone_identidade:
                    escolhido = indice
            elif indice == self.config.microfone:
                escolhido = indice
        if (self.config.microfone_identidade or self.config.microfone is not None) and escolhido is None:
            self.entradas.addItem("Selecionado indisponível · reconecte ou escolha outro", self.config.microfone)
            self.entradas.setCurrentIndex(self.entradas.count()-1)
        else:
            self.entradas.setCurrentIndex(max(0, self.entradas.findData(escolhido)))
        self.entradas.blockSignals(False)

    def selecionar_microfone(self):
        indice = self.entradas.currentData()
        identidade = self.identidades.get(indice)
        if indice is not None and identidade is None:
            return
        try:
            config = replace(self.config, microfone=indice, microfone_identidade=identidade)
            salvar(config)
            self.config = config
            self.runtime.configurar(config)
            self.transcricao.setText("Texto reconhecido: dispositivo alterado; ative ou teste o microfone")
        except (OSError, ValueError):
            self.aviso.setText("Não foi possível salvar a seleção do microfone.")

    def resultado_microfone(self, dados):
        texto = f"Captura: {dados['captura']}\nReconhecimento: {dados['reconhecimento']}"
        if "rms" in dados: texto += f"\nPico RMS capturado: {dados['rms']:.4f}"
        self.teste_resultado.setText(texto)

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
        self.testar_mic.setEnabled(not ocupado)
        self.atualizar_mics.setEnabled(not ocupado)
        self.entradas.setEnabled(not ocupado)
        for b in self.spotify_botoes:b.setEnabled(not ocupado)

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
                for widget, valor in ((self.volume_musica,round(self.config.volume*100)),(self.volume_voz,round(self.config.volume_voz*100)),(self.habilitar_voz,not self.config.sem_voz)):
                    widget.blockSignals(True)
                    if isinstance(widget,QCheckBox): widget.setChecked(valor)
                    else: widget.setValue(valor)
                    widget.blockSignals(False)
                self.percentual_musica.setText(f"{self.volume_musica.value()}%")
                self.percentual_voz.setText(f"{self.volume_voz.value()}%")
                self.nucleo.movimento(self.config.reduzir_movimento)
                self.rotulo_audio()
                self.runtime.listar_dispositivos()
            except (ValueError, OSError):
                QMessageBox.warning(self,"Configurações","Não foi possível salvar as preferências locais.")
        self.runtime.dispositivos.disconnect(dialog.atualizar_dispositivos)

    def closeEvent(self, event):
        if self.salvar_audio_timer.isActive():
            self.salvar_audio_timer.stop()
            self.salvar_audio()
        if self.dialog_decisao:self.dialog_decisao.finalizar()
        self.runtime.fechar()
        event.accept()


def iniciar(config=None):
    app = QApplication(sys.argv)
    app.setStyleSheet(ESTILO)
    janela = Janela(config)
    janela.show()
    resultado = app.exec()
    janela.runtime.fechar()
    janela.runtime.audio_thread.join(timeout=2)
    janela.runtime.monitor_thread.join(timeout=3)
    janela.runtime.thread.join(timeout=2)
    return resultado
