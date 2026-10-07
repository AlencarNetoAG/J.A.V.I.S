"""Janela Qt com esfera procedural; widgets e desenho na thread principal."""

import html
import sys

from PySide6.QtCore import Qt, QTimer, QEvent, QPropertyAnimation
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QDialog,
    QFormLayout,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QFileDialog,
    QDialogButtonBox,
    QMessageBox,
    QSlider,
    QBoxLayout,
    QGroupBox,
    QSizePolicy,
    QListWidget,
    QListWidgetItem,
    QGraphicsOpacityEffect,
)
from dataclasses import replace

from .configuracoes import carregar, salvar
from .horario import agora_recife
from .runtime import Runtime
from .interface_pc import PermissoesDialog, ConfirmacaoDialog
from .esfera import Nucleo

ESTILO = """
QWidget { background:#02080e; color:#d2e7f1; font-family:'Segoe UI'; font-size:14px; }
QLabel#titulo { font-size:24px; letter-spacing:8px; color:#82dcff; font-weight:500; }
QLabel#subtitulo { color:#809cae; font-size:12px; }
QLabel#cartao { background:#050f19; border:1px solid #153748; border-radius:9px; padding:14px; line-height:1.4; }
QPushButton { background:#071622; border:1px solid #1b3e51; border-radius:6px; padding:7px 9px; }
QPushButton:hover { background:#0b2638; border-color:#57bbdf; }
QPushButton:checked { color:#8de5ff; border-color:#3582a2; }
QPushButton:disabled { color:#526776; border-color:#132936; }
QPushButton#parar { color:#e5b4a9; border-color:#57413e; }
QPushButton#recolher { text-align:left; background:transparent; color:#86b2c9; border:0; padding:6px 0; }
QLineEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget { background:#05111b; border:1px solid #173747; border-radius:6px; padding:7px; selection-background-color:#18465e; }
QTextBrowser#resposta { background:transparent; border:0; padding:3px; font-size:15px; }
QGroupBox { border:1px solid #183445; border-radius:6px; margin-top:12px; padding:12px; }
QGroupBox::title { subcontrol-origin:margin; color:#81b5cb; }
QProgressBar { background:#0a1a29; border:0; border-radius:3px; max-height:5px; }
QProgressBar::chunk { background:#43c7f6; border-radius:3px; }
QSlider::groove:horizontal { height:3px; background:#153247; }
QSlider::sub-page:horizontal { background:#329ac6; }
QSlider::handle:horizontal { background:#97dbf4; width:10px; margin:-4px 0; border-radius:5px; }
QCheckBox::indicator { width:12px; height:12px; border:1px solid #31566c; border-radius:3px; }
QCheckBox::indicator:checked { background:#5bbde2; border-color:#83d7f2; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#030b12; width:7px; }
QScrollBar::handle:vertical { background:#1b3c50; border-radius:3px; min-height:20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
"""


class RespostaTexto(QTextBrowser):
    def loadResource(self, tipo, nome):
        # Markdown de respostas não carrega imagens remotas nem arquivos locais.
        return None


class Preferencias(QDialog):
    def __init__(self, config, parent):
        super().__init__(parent)
        self.setWindowTitle("Configurações locais")
        self.setMinimumWidth(480)
        self.resize(560, 680)
        self.config = replace(config)
        self.identidades = {}
        principal = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        conteudo = QWidget()
        layout = QVBoxLayout(conteudo)
        scroll.setWidget(conteudo)
        principal.addWidget(scroll, 1)
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
        self.velocidade = QSpinBox()
        self.velocidade.setRange(80, 300)
        self.velocidade.setValue(config.velocidade)
        self.volume_voz = QDoubleSpinBox()
        self.volume_voz.setRange(0, 1)
        self.volume_voz.setSingleStep(0.05)
        self.volume_voz.setValue(config.volume_voz)
        self.volume = QDoubleSpinBox()
        self.volume.setRange(0, 1)
        self.volume.setSingleStep(0.02)
        self.volume.setValue(config.volume)
        self.timeout = QSpinBox()
        self.timeout.setRange(3, 60)
        self.timeout.setValue(int(config.timeout_pergunta))
        self.maximo = QSpinBox()
        self.maximo.setRange(3, 30)
        self.maximo.setValue(int(config.captura_maxima))
        self.limiar = QDoubleSpinBox()
        self.limiar.setDecimals(3)
        self.limiar.setRange(0.001, 0.5)
        self.limiar.setSingleStep(0.005)
        self.limiar.setValue(config.limiar)
        self.modelo = QLineEdit(config.modelo)
        self.provedor = QComboBox()
        self.provedor.addItem("Local / Ollama (padrão)", "local")
        self.provedor.addItem("OpenAI (opcional)", "openai")
        self.provedor.setCurrentIndex(self.provedor.findData(config.provedor_ia))
        self.arquivo = QLineEdit(config.musica)
        escolher = QPushButton("Escolher MP3")
        escolher.clicked.connect(self.escolher)
        caminho = QHBoxLayout()
        caminho.addWidget(self.arquivo)
        caminho.addWidget(escolher)
        self.reduzir = QCheckBox("Reduzir movimento")
        self.reduzir.setChecked(config.reduzir_movimento)
        self.sem_voz = QCheckBox("Desativar fala")
        self.sem_voz.setChecked(config.sem_voz)
        self.sem_musica = QCheckBox("Desativar música")
        self.sem_musica.setChecked(config.sem_musica)
        for nome, widget in (
            ("Microfone", self.mic),
            ("Voz", self.voz),
            ("Velocidade", self.velocidade),
            ("Volume da música", self.volume),
            ("Volume da voz", self.volume_voz),
            ("Espera pela pergunta (s)", self.timeout),
            ("Captura máxima (s)", self.maximo),
            ("Limiar do microfone", self.limiar),
            ("Modelo Whisper", self.modelo),
            ("Conversa livre", self.provedor),
        ):
            form.addRow(nome, widget)
        form.addRow("Música local", caminho)
        layout.addLayout(form)
        layout.addWidget(self.reduzir)
        layout.addWidget(self.sem_voz)
        layout.addWidget(self.sem_musica)
        aviso = QLabel(
            "Vozes são as instaladas no computador. Comandos do PC e Google continuam locais. "
            "Conversa livre: Ollama local, ou OpenAI opcional (envia texto e exige chave/saldo de API no .env). "
            "A ativação por voz nunca envia áudio à OpenAI."
        )
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        principal.addWidget(botoes)

    def escolher(self):
        nome, _ = QFileDialog.getOpenFileName(
            self, "Escolher sua música", "", "Áudio MP3 (*.mp3)"
        )
        if nome:
            self.arquivo.setText(nome)

    def atualizar_dispositivos(self, dados):
        self.identidades = dados.get("identidades", {})
        self.mic.clear()
        self.mic.addItem("Padrão do Windows (entrada atual)", None)
        escolhido = None
        for indice, nome in dados.get("microfones", []):
            self.mic.addItem(nome, indice)
            if self.config.microfone_identidade:
                if self.identidades.get(indice) == self.config.microfone_identidade:
                    escolhido = indice
            elif indice == self.config.microfone:
                escolhido = indice
        if (
            self.config.microfone_identidade or self.config.microfone is not None
        ) and escolhido is None:
            self.mic.addItem("Selecionado indisponível", self.config.microfone)
            self.mic.setCurrentIndex(self.mic.count() - 1)
        else:
            self.mic.setCurrentIndex(max(0, self.mic.findData(escolhido)))
        for identificador, nome in dados.get("vozes", []):
            if self.voz.findData(identificador) < 0:
                self.voz.addItem(nome, identificador)
        i = self.voz.findData(self.config.voz)
        if i >= 0:
            self.voz.setCurrentIndex(i)

    def resultado(self):
        return replace(
            self.config,
            microfone=self.mic.currentData(),
            microfone_identidade=(
                self.identidades.get(
                    self.mic.currentData(), self.config.microfone_identidade
                )
                if self.mic.currentData() is not None
                else None
            ),
            voz=self.voz.currentData(),
            velocidade=self.velocidade.value(),
            volume=self.volume.value(),
            volume_voz=self.volume_voz.value(),
            timeout_pergunta=self.timeout.value(),
            captura_maxima=self.maximo.value(),
            limiar=self.limiar.value(),
            modelo=self.modelo.text().strip() or "tiny",
            musica=self.arquivo.text(),
            reduzir_movimento=self.reduzir.isChecked(),
            sem_voz=self.sem_voz.isChecked(),
            sem_musica=self.sem_musica.isChecked(),
            provedor_ia=self.provedor.currentData(),
        ).validar()


class Janela(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or carregar()
        self.runtime = Runtime(self.config)
        self.setWindowTitle("JARVIS · Assistente pessoal")
        self.resize(1220, 850)
        self.setMinimumSize(580, 420)
        self.audio_estado = "parada"
        self.fala_ativa = False
        self.dialog_decisao = None
        self.animacoes = {}
        self.compacto = None
        self.musica_dados = {}
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo = QWidget()
        layout = QVBoxLayout(conteudo)
        layout.setContentsMargins(24, 4, 24, 12)
        layout.setSpacing(10)
        titulo = QLabel("JARVIS")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titulo)
        self.estado = QLabel("Microfone desativado · use texto ou ative o microfone")
        self.estado.setObjectName("subtitulo")
        self.estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.estado.setWordWrap(True)
        layout.addWidget(self.estado)

        # Laterais simétricas deixam o núcleo no centro. Resultados permanecem até substituição.
        self.centro_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.centro_layout.setSpacing(22)
        self.lateral_esquerda = QWidget()
        self.lateral_direita = QWidget()
        self.esquerda_layout = QBoxLayout(
            QBoxLayout.Direction.TopToBottom, self.lateral_esquerda
        )
        self.direita_layout = QBoxLayout(
            QBoxLayout.Direction.TopToBottom, self.lateral_direita
        )
        for lateral in (self.esquerda_layout, self.direita_layout):
            lateral.setContentsMargins(0, 20, 0, 20)
            lateral.setSpacing(12)
        self.relogio = self.criar_cartao()
        self.clima = self.criar_cartao()
        self.dolar = self.criar_cartao()
        self.musica_cartao = self.criar_cartao()
        self.esquerda_layout.addWidget(self.relogio)
        self.esquerda_layout.addWidget(self.clima)
        self.esquerda_layout.addStretch()
        self.direita_layout.addWidget(self.dolar)
        self.direita_layout.addWidget(self.musica_cartao)
        self.direita_layout.addStretch()
        for card in (self.clima, self.dolar, self.musica_cartao):
            card.hide()
        self.esfera_area = QWidget()
        orb_layout = QVBoxLayout(self.esfera_area)
        orb_layout.setContentsMargins(0, 0, 0, 0)
        orb_layout.setSpacing(8)
        orb_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.nucleo = Nucleo()
        self.nucleo.setMaximumHeight(520)
        orb_layout.addWidget(self.nucleo, 1)
        self.transcricao = QLabel("Diga ‘Jarvis’ ou digite um comando abaixo.")
        self.transcricao.setTextFormat(Qt.TextFormat.PlainText)
        self.transcricao.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.transcricao.setWordWrap(True)
        self.transcricao.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        self.transcricao.setMaximumHeight(70)
        self.transcricao.setObjectName("subtitulo")
        orb_layout.addWidget(self.transcricao)
        self.resposta = RespostaTexto()
        self.resposta.setObjectName("resposta")
        self.resposta.setOpenExternalLinks(False)
        self.resposta.setOpenLinks(False)
        self.resposta.setMinimumHeight(80)
        self.resposta.setMaximumHeight(150)
        self.resposta.hide()
        orb_layout.addWidget(self.resposta)
        self.resultados_arquivos = QListWidget()
        self.resultados_arquivos.setAccessibleName(
            "Resultados da busca de arquivos; clique para abrir"
        )
        self.resultados_arquivos.setMaximumHeight(140)
        self.resultados_arquivos.setWordWrap(True)
        self.resultados_arquivos.itemClicked.connect(self.abrir_resultado)
        self.resultados_arquivos.hide()
        orb_layout.addWidget(self.resultados_arquivos)
        self.centro_layout.addWidget(self.lateral_esquerda)
        self.centro_layout.addWidget(self.esfera_area, 1)
        self.centro_layout.addWidget(self.lateral_direita)
        layout.addLayout(self.centro_layout, 1)
        self.acao_pc = QLabel("")
        self.acao_pc.setTextFormat(Qt.TextFormat.PlainText)
        self.acao_pc.setWordWrap(True)
        self.acao_pc.setObjectName("subtitulo")
        self.acao_pc.hide()
        layout.addWidget(self.acao_pc)
        self.aviso = QLabel(
            "Ativação local · bom dia Jarvis: horário, clima, dólar e seu MP3."
        )
        self.aviso.setObjectName("subtitulo")
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)
        self.historico_botao = QPushButton("▸ Histórico da conversa")
        self.historico_botao.setObjectName("recolher")
        self.historico_botao.setCheckable(True)
        resultados_controles = QHBoxLayout()
        resultados_controles.addWidget(self.historico_botao, 1)
        self.dispensar = QPushButton("Dispensar resultados")
        self.dispensar.setObjectName("recolher")
        self.dispensar.clicked.connect(self.dispensar_resultados)
        self.dispensar.hide()
        resultados_controles.addWidget(self.dispensar)
        layout.addLayout(resultados_controles)
        self.historico = QTextBrowser()
        self.historico.setOpenExternalLinks(False)
        self.historico.setMinimumHeight(130)
        self.historico.setMaximumHeight(240)
        self.historico.hide()
        self.historico_botao.toggled.connect(
            lambda ativo: self.recolher(
                self.historico_botao, self.historico, ativo, "Histórico da conversa"
            )
        )
        layout.addWidget(self.historico)

        # Diagnóstico, permissões e Spotify continuam disponíveis em uma área recolhível.
        self.detalhes = QWidget()
        detalhes_layout = QVBoxLayout(self.detalhes)
        detalhes_layout.setContentsMargins(0, 0, 0, 0)
        self.detalhes.hide()
        layout.addWidget(self.detalhes)
        legenda = QLabel("MICROFONE · nível do áudio capturado")
        legenda.setObjectName("subtitulo")
        detalhes_layout.addWidget(legenda)
        self.nivel = QProgressBar()
        self.nivel.setRange(0, 100)
        self.nivel.setValue(0)
        self.nivel.setTextVisible(False)
        detalhes_layout.addWidget(self.nivel)
        self.microfones_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.entradas = QComboBox()
        self.entradas.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.entradas.setMinimumContentsLength(14)
        self.entradas.addItem("Padrão do Windows (entrada atual)", None)
        self.identidades = {}
        self.atualizar_mics = QPushButton("Atualizar microfones")
        self.atualizar_mics.clicked.connect(self.runtime.listar_dispositivos)
        self.testar_mic = QPushButton("Testar microfone")
        self.testar_mic.clicked.connect(self.runtime.testar_microfone)
        self.microfones_layout.addWidget(self.entradas, 1)
        self.microfones_layout.addWidget(self.atualizar_mics)
        self.microfones_layout.addWidget(self.testar_mic)
        detalhes_layout.addLayout(self.microfones_layout)
        self.teste_resultado = QLabel(
            "Teste: silêncio na calibração; depois diga bom dia Jarvis."
        )
        self.teste_resultado.setWordWrap(True)
        detalhes_layout.addWidget(self.teste_resultado)
        pc_botoes = QHBoxLayout()
        self.permissoes_pc = QPushButton("Permissões do PC")
        self.permissoes_pc.clicked.connect(self.configurar_pc)
        self.suspender_pc = QPushButton(
            "Retomar controle do PC"
            if self.config.pc_suspenso
            else "Suspender controle do PC"
        )
        self.suspender_pc.clicked.connect(self.runtime.suspender_pc)
        self.limpar = QPushButton("Limpar conversa")
        self.limpar.clicked.connect(self.limpar_conversa)
        for b in (self.permissoes_pc, self.suspender_pc, self.limpar):
            pc_botoes.addWidget(b)
        detalhes_layout.addLayout(pc_botoes)
        spotify = QGroupBox("Spotify · conta e mídia externa")
        sp_layout = QVBoxLayout(spotify)
        conta = QHBoxLayout()
        self.conectar_spotify = QPushButton("Conectar Spotify")
        self.conectar_spotify.clicked.connect(
            lambda: self.runtime.ferramenta_pc("spotify_conectar")
        )
        self.desconectar_spotify = QPushButton("Desconectar")
        self.desconectar_spotify.clicked.connect(
            lambda: self.runtime.ferramenta_pc("spotify_desconectar")
        )
        atual = QPushButton("Música atual")
        atual.clicked.connect(
            lambda: self.runtime.ferramenta_pc("spotify_controlar", {"acao": "atual"})
        )
        for b in (self.conectar_spotify, self.desconectar_spotify, atual):
            conta.addWidget(b)
        sp_layout.addLayout(conta)
        reproduzir = QHBoxLayout()
        self.spotify_botoes = [self.conectar_spotify, self.desconectar_spotify, atual]
        for nome, acao in (
            ("Pausar Spotify", "pausar"),
            ("Retomar Spotify", "retomar"),
            ("Anterior", "anterior"),
            ("Próxima", "proxima"),
        ):
            botao = QPushButton(nome)
            botao.clicked.connect(
                lambda checked=False, a=acao: self.runtime.ferramenta_pc(
                    "spotify_controlar", {"acao": a}
                )
            )
            reproduzir.addWidget(botao)
            self.spotify_botoes.append(botao)
        sp_layout.addLayout(reproduzir)
        volume_sp = QHBoxLayout()
        volume_sp.addWidget(QLabel("Volume Spotify"))
        self.volume_spotify = QSpinBox()
        self.volume_spotify.setRange(0, 100)
        self.volume_spotify.setValue(50)
        self.volume_spotify.setSuffix("%")
        aplicar_sp = QPushButton("Aplicar volume")
        aplicar_sp.clicked.connect(
            lambda: self.runtime.ferramenta_pc(
                "audio_volume",
                {"fonte": "spotify", "percentual": self.volume_spotify.value()},
            )
        )
        self.spotify_botoes.append(aplicar_sp)
        volume_sp.addWidget(self.volume_spotify)
        volume_sp.addWidget(aplicar_sp)
        sp_layout.addLayout(volume_sp)
        detalhes_layout.addWidget(spotify)

        self.scroll.setWidget(conteudo)
        central = QWidget()
        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(0)
        principal.addWidget(self.scroll, 1)
        # Histórico e dispensa permanecem alcançáveis enquanto o conteúdo é rolado.
        layout.removeWidget(titulo)
        layout.removeWidget(self.estado)
        layout.removeItem(resultados_controles)
        resultados_controles.setParent(None)
        cabecalho = QWidget()
        cabecalho_layout = QVBoxLayout(cabecalho)
        cabecalho_layout.setContentsMargins(24, 12, 24, 6)
        cabecalho_layout.setSpacing(6)
        navegacao = QHBoxLayout()
        titulo.setAlignment(Qt.AlignmentFlag.AlignLeft)
        navegacao.addWidget(titulo, 1)
        navegacao.addLayout(resultados_controles)
        cabecalho_layout.addLayout(navegacao)
        cabecalho_layout.addWidget(self.estado)
        principal.insertWidget(0, cabecalho)
        rodape = QWidget()
        rodape_layout = QVBoxLayout(rodape)
        rodape_layout.setContentsMargins(18, 8, 18, 12)
        rodape_layout.setSpacing(7)
        pergunta = QHBoxLayout()
        self.entrada = QLineEdit()
        self.entrada.setMaxLength(4000)
        self.entrada.setPlaceholderText("Digite um comando ou bom dia Jarvis…")
        self.enviar = QPushButton("Enviar")
        self.enviar.clicked.connect(self.enviar_texto)
        self.entrada.returnPressed.connect(self.enviar_texto)
        pergunta.addWidget(self.entrada, 1)
        pergunta.addWidget(self.enviar)
        rodape_layout.addLayout(pergunta)
        botoes = QHBoxLayout()
        self.mic = QPushButton("Ativar microfone")
        self.mic.clicked.connect(self.runtime.alternar_microfone)
        self.parar = QPushButton("Parar")
        self.parar.setObjectName("parar")
        self.parar.clicked.connect(self.runtime.parar)
        self.cancelar_acao = QPushButton("Cancelar ação")
        self.cancelar_acao.clicked.connect(self.runtime.cancelar_acao)
        self.preferencias = QPushButton("Configurações")
        self.preferencias.clicked.connect(self.configurar)
        self.detalhes_botao = QPushButton("Detalhes")
        self.detalhes_botao.setCheckable(True)
        self.detalhes_botao.toggled.connect(self.detalhes.setVisible)
        for botao in (
            self.mic,
            self.parar,
            self.cancelar_acao,
            self.preferencias,
            self.detalhes_botao,
        ):
            botoes.addWidget(botao)
        rodape_layout.addLayout(botoes)
        audio_controles = QHBoxLayout()
        self.pausa_musica = QPushButton("Pausar música")
        self.pausa_musica.setEnabled(False)
        self.pausa_musica.clicked.connect(
            lambda: self.runtime.controlar_musica(
                "retomar" if self.audio_estado == "pausada" else "pausar"
            )
        )
        self.stop_musica = QPushButton("Parar música")
        self.stop_musica.setEnabled(False)
        self.stop_musica.clicked.connect(lambda: self.runtime.controlar_musica("parar"))
        self.interromper_voz = QPushButton("Interromper fala")
        self.interromper_voz.setEnabled(False)
        self.interromper_voz.clicked.connect(self.runtime.interromper_fala)
        self.stop_audios = QPushButton("Parar todos os áudios")
        self.stop_audios.setObjectName("parar")
        self.stop_audios.clicked.connect(self.runtime.parar_audios)
        for botao in (
            self.pausa_musica,
            self.stop_musica,
            self.interromper_voz,
            self.stop_audios,
        ):
            audio_controles.addWidget(botao)
        rodape_layout.addLayout(audio_controles)
        volumes = QHBoxLayout()
        self.habilitar_voz = QCheckBox("Resposta por voz")
        self.habilitar_voz.setChecked(not self.config.sem_voz)
        self.volume_musica = QSlider(Qt.Orientation.Horizontal)
        self.volume_voz = QSlider(Qt.Orientation.Horizontal)
        self.percentual_musica = QLabel()
        self.percentual_voz = QLabel()
        volumes.addWidget(self.habilitar_voz)
        for nome, slider, rotulo, valor in (
            ("MP3", self.volume_musica, self.percentual_musica, self.config.volume),
            ("Voz", self.volume_voz, self.percentual_voz, self.config.volume_voz),
        ):
            slider.setRange(0, 100)
            slider.setValue(round(valor * 100))
            slider.setMinimumWidth(40)
            slider.setAccessibleName(
                "Volume da música" if nome == "MP3" else "Volume da voz"
            )
            rotulo.setText(f"{slider.value()}%")
            volumes.addWidget(QLabel(nome))
            volumes.addWidget(slider, 1)
            volumes.addWidget(rotulo)
        rodape_layout.addLayout(volumes)
        self.status_audio = QLabel()
        self.status_audio.setObjectName("subtitulo")
        self.status_audio.setWordWrap(True)
        rodape_layout.addWidget(self.status_audio)
        self.rotulo_audio()
        principal.addWidget(rodape)
        self.setCentralWidget(central)
        self.salvar_audio_timer = QTimer(self)
        self.salvar_audio_timer.setSingleShot(True)
        self.salvar_audio_timer.timeout.connect(self.salvar_audio)
        self.volume_musica.valueChanged.connect(
            lambda v: self.alterar_audio("volume", v / 100)
        )
        self.volume_voz.valueChanged.connect(
            lambda v: self.alterar_audio("volume_voz", v / 100)
        )
        self.habilitar_voz.toggled.connect(
            lambda ativo: self.alterar_audio("sem_voz", not ativo)
        )
        self.entradas.currentIndexChanged.connect(self.selecionar_microfone)
        self.runtime.dispositivos.connect(self.atualizar_microfones)
        self.runtime.reconhecido.connect(self.texto_reconhecido)
        self.runtime.diagnostico.connect(self.resultado_microfone)
        self.runtime.estado.connect(self.estado_runtime)
        self.runtime.audio.connect(self.atualizar_audio)
        self.runtime.falando.connect(self.estado_fala)
        self.runtime.nivel_voz.connect(self.amplitude_voz)
        self.runtime.acao.connect(self.estado_acao_pc)
        self.runtime.confirmacao.connect(self.confirmacao_pc)
        self.runtime.config_pc.connect(self.atualizar_config_pc)
        self.runtime.mensagem.connect(self.adicionar)
        self.runtime.ocupado.connect(self.ocupado)
        self.runtime.nivel.connect(self.amplitude)
        self.runtime.cartoes.connect(self.atualizar_cartoes)
        self.runtime.microfone.connect(self.estado_microfone)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.atualizar_relogio)
        self.timer.start(1000)
        self.erro_timer = QTimer(self)
        self.erro_timer.setSingleShot(True)
        self.erro_timer.timeout.connect(lambda: self.nucleo.falha(False))
        self.atualizar_relogio()
        self.nucleo.movimento(self.config.reduzir_movimento)
        self.reorganizar()
        QTimer.singleShot(0, self.runtime.listar_dispositivos)

    @staticmethod
    def criar_cartao():
        card = QLabel()
        card.setObjectName("cartao")
        card.setWordWrap(True)
        card.setTextFormat(Qt.TextFormat.PlainText)
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return card

    def recolher(self, botao, widget, ativo, nome):
        widget.setVisible(ativo)
        botao.setText(("▾ " if ativo else "▸ ") + nome)
        if ativo:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(widget))

    def mostrar_resultado(self, widget):
        if widget.isVisible() and not widget.property("saindo"):
            return
        self.transicionar(widget, True)
        self.dispensar.show()

    def transicionar(self, widget, mostrar):
        antiga = self.animacoes.pop(widget, None)
        if antiga:
            antiga.stop()
            antiga.deleteLater()
        widget.setProperty("saindo", not mostrar)
        widget.show()
        if self.config.reduzir_movimento or self.isMinimized():
            widget.setGraphicsEffect(None)
            widget.setVisible(mostrar)
            return
        efeito = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(efeito)
        animacao = QPropertyAnimation(efeito, b"opacity", widget)
        animacao.setDuration(220)
        animacao.setStartValue(0.0 if mostrar else 1.0)
        animacao.setEndValue(1.0 if mostrar else 0.0)
        self.animacoes[widget] = animacao
        animacao.finished.connect(lambda: self.finalizar_transicao(widget, not mostrar))
        animacao.start()

    def finalizar_transicao(self, widget, ocultar):
        widget.setGraphicsEffect(None)
        self.animacoes.pop(widget, None)
        if ocultar:
            widget.hide()
        widget.setProperty("saindo", False)

    def dispensar_resultados(self):
        for widget in (
            self.clima,
            self.dolar,
            self.musica_cartao,
            self.resposta,
            self.resultados_arquivos,
            self.acao_pc,
        ):
            if widget.isVisible():
                self.transicionar(widget, False)
        self.dispensar.hide()

    def texto_reconhecido(self, texto):
        self.transcricao.setText(
            "Texto reconhecido: " + (texto or "nenhuma fala reconhecida")
        )
        self.ajustar_textos()

    def ajustar_textos(self):
        altura = self.transcricao.heightForWidth(max(180, self.transcricao.width()))
        self.transcricao.setFixedHeight(max(18, min(70, altura)))
        if self.resposta.isVisible():
            documento = self.resposta.document()
            documento.setTextWidth(max(180, self.resposta.viewport().width() - 6))
            self.resposta.setFixedHeight(
                max(60, min(150, int(documento.size().height()) + 12))
            )

    def estado_microfone(self, ativo):
        self.mic.setText("Desativar microfone" if ativo else "Ativar microfone")
        if not ativo and self.nucleo.modo in ("ouvindo", "aguardando"):
            self.nucleo.estado_operacao("desativado")

    def abrir_resultado(self, item):
        if not self.runtime.ferramenta_pc(
            "arquivo_abrir", {"alvo": item.data(Qt.ItemDataRole.UserRole)}
        ):
            self.aviso.setText(
                "Aguarde a ação atual ou cancele antes de abrir o arquivo."
            )

    def reorganizar(self):
        QTimer.singleShot(0, self.ajustar_textos)
        compacto = self.width() < 940
        self.nucleo.setMinimumHeight(110 if compacto else 180)
        altura = max(
            110 if compacto else 180,
            min(520, self.height() - (330 if compacto else 365)),
        )
        self.nucleo.setMaximumHeight(altura)
        if compacto == self.compacto:
            return
        self.compacto = compacto
        for widget in (self.lateral_esquerda, self.esfera_area, self.lateral_direita):
            self.centro_layout.removeWidget(widget)
        self.centro_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compacto
            else QBoxLayout.Direction.LeftToRight
        )
        ordem = (
            (self.esfera_area, self.lateral_esquerda, self.lateral_direita)
            if compacto
            else (self.lateral_esquerda, self.esfera_area, self.lateral_direita)
        )
        for widget in ordem:
            self.centro_layout.addWidget(widget, 1 if widget is self.esfera_area else 0)
        for widget in (self.lateral_esquerda, self.lateral_direita):
            widget.setMinimumWidth(0 if compacto else 198)
            widget.setMaximumWidth(16777215 if compacto else 210)
        for lateral in (self.esquerda_layout, self.direita_layout):
            lateral.setDirection(
                QBoxLayout.Direction.LeftToRight
                if compacto
                else QBoxLayout.Direction.TopToBottom
            )
            lateral.setStretch(0, 1 if compacto else 0)
            lateral.setStretch(1, 1 if compacto else 0)
            lateral.setStretch(2, 0 if compacto else 1)
        self.microfones_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compacto
            else QBoxLayout.Direction.LeftToRight
        )

    def configurar_pc(self):
        dialog = PermissoesDialog(self.runtime.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.runtime.configurar_pc(dialog.resultado())
                self.config = self.runtime.config
                salvar(self.config)
            except (ValueError, OSError):
                QMessageBox.warning(
                    self, "Permissões", "Não foi possível salvar as permissões."
                )

    def atualizar_config_pc(self, dados):
        self.config = self.runtime.config
        self.suspender_pc.setText(
            "Retomar controle do PC"
            if self.config.pc_suspenso
            else "Suspender controle do PC"
        )
        self.volume_musica.blockSignals(True)
        self.volume_musica.setValue(round(self.config.volume * 100))
        self.volume_musica.blockSignals(False)
        self.percentual_musica.setText(f"{self.volume_musica.value()}%")
        self.salvar_audio_timer.start(250)

    def estado_acao_pc(self, dados):
        texto = dados["ferramenta"].replace("_", " ") + " · " + dados["status"]
        if dados.get("mensagem"):
            texto += "\n" + dados["mensagem"]
        self.acao_pc.setText(texto)
        self.acao_pc.show()
        if "arquivos" in dados:
            self.resultados_arquivos.clear()
            for arquivo in dados["arquivos"]:
                item = QListWidgetItem(arquivo["nome"] + "\n" + arquivo["caminho"])
                item.setData(Qt.ItemDataRole.UserRole, arquivo["caminho"])
                self.resultados_arquivos.addItem(item)
            if self.resultados_arquivos.count():
                self.mostrar_resultado(self.resultados_arquivos)
            else:
                self.resultados_arquivos.hide()
        if dados.get("fonte") in ("spotify", "sistema") and "tocando" in dados:
            self.musica_cartao.setText(
                "MÚSICA · "
                + dados["fonte"].upper()
                + "\n"
                + dados.get("titulo", "Título não informado")
                + "\n"
                + dados.get("artista", "Artista não informado")
                + "\n"
                + (
                    "Reproduzindo"
                    if dados["tocando"]
                    else "Reprodução pausada ou encerrada"
                )
            )
            self.mostrar_resultado(self.musica_cartao)

    def confirmacao_pc(self, pedido):
        if pedido.get("fechado"):
            if self.dialog_decisao and self.dialog_decisao.pedido["id"] == pedido["id"]:
                self.dialog_decisao.finalizar()
                self.dialog_decisao = None
            return
        if self.dialog_decisao:
            self.dialog_decisao.finalizar()
        self.dialog_decisao = ConfirmacaoDialog(pedido, self.runtime.decisoes, self)
        self.dialog_decisao.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "microfones_layout"):
            self.reorganizar()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "nucleo"):
            self.nucleo.suspender(self.isMinimized())
            if self.isMinimized():
                self.timer.stop()
                for widget, animacao in list(self.animacoes.items()):
                    animacao.stop()
                    self.finalizar_transicao(widget, bool(widget.property("saindo")))
            else:
                self.timer.start(1000)

    def alterar_audio(self, nome, valor):
        self.runtime.preferencia_audio(nome, valor)
        self.config = self.runtime.config
        self.percentual_musica.setText(f"{self.volume_musica.value()}%")
        self.percentual_voz.setText(f"{self.volume_voz.value()}%")
        self.rotulo_audio()
        self.salvar_audio_timer.start(250)

    def salvar_audio(self):
        try:
            salvar(self.config)
        except (OSError, ValueError):
            self.aviso.setText("Não foi possível salvar as preferências de áudio.")

    def atualizar_audio(self, dados):
        self.audio_estado = dados["musica"]
        self.pausa_musica.setText(
            "Retomar música" if self.audio_estado == "pausada" else "Pausar música"
        )
        self.pausa_musica.setEnabled(self.audio_estado in ("tocando", "pausada"))
        self.stop_musica.setEnabled(self.audio_estado != "parada")
        self.rotulo_audio()
        if dados.get("titulo"):
            self.musica_dados = dados
        if self.musica_dados:
            self.musica_cartao.setText(
                "MÚSICA · MP3 LOCAL\n"
                + self.musica_dados["titulo"]
                + "\n"
                + self.musica_dados.get("artista", "Artista não informado")
                + "\n"
                + self.audio_estado.capitalize()
            )
            self.mostrar_resultado(self.musica_cartao)

    def rotulo_audio(self):
        voz = (
            "falando"
            if self.fala_ativa
            else "desativada" if self.config.sem_voz else "pronta"
        )
        self.status_audio.setText(f"Música: {self.audio_estado} · voz: {voz}")

    def estado_fala(self, falando):
        self.fala_ativa = falando
        self.rotulo_audio()
        self.interromper_voz.setEnabled(falando)
        if not falando:
            self.nucleo.amplitude(0.0)

    def estado_runtime(self, texto):
        if texto == "Desativado":
            texto = "Microfone desativado"
        self.estado.setText(texto)
        t = texto.casefold()
        modo = (
            "falando"
            if t.startswith("falando")
            else (
                "ouvindo"
                if "ouvindo" in t or "calibrando" in t
                else (
                    "processando"
                    if any(
                        p in t
                        for p in (
                            "consultando",
                            "reconhecendo",
                            "carregando",
                            "finalizando",
                            "executando",
                            "autorizando",
                            "preparando",
                        )
                    )
                    else (
                        "desativado"
                        if not self.runtime.ativo or "pausado" in t or "desativado" in t
                        else "aguardando"
                    )
                )
            )
        )
        self.nucleo.estado_operacao(modo)
        if t.startswith("erro") and not self.erro_timer.isActive():
            self.nucleo.falha(True)
            self.erro_timer.start(1400)

    def atualizar_microfones(self, dados):
        self.identidades = dados.get("identidades", {})
        self.entradas.blockSignals(True)
        self.entradas.clear()
        self.entradas.addItem("Padrão do Windows (entrada atual)", None)
        escolhido = None
        for indice, nome in dados.get("microfones", []):
            self.entradas.addItem(nome, indice)
            if self.config.microfone_identidade:
                if self.identidades.get(indice) == self.config.microfone_identidade:
                    escolhido = indice
            elif indice == self.config.microfone:
                escolhido = indice
        if (
            self.config.microfone_identidade or self.config.microfone is not None
        ) and escolhido is None:
            self.entradas.addItem(
                "Selecionado indisponível · reconecte ou escolha outro",
                self.config.microfone,
            )
            self.entradas.setCurrentIndex(self.entradas.count() - 1)
        else:
            self.entradas.setCurrentIndex(max(0, self.entradas.findData(escolhido)))
        self.entradas.blockSignals(False)

    def selecionar_microfone(self):
        indice = self.entradas.currentData()
        identidade = self.identidades.get(indice)
        if indice is not None and identidade is None:
            return
        try:
            config = replace(
                self.config, microfone=indice, microfone_identidade=identidade
            )
            salvar(config)
            self.config = config
            self.runtime.configurar(config)
            self.transcricao.setText(
                "Texto reconhecido: dispositivo alterado; ative ou teste o microfone"
            )
        except (OSError, ValueError):
            self.aviso.setText("Não foi possível salvar a seleção do microfone.")

    def resultado_microfone(self, dados):
        texto = (
            f"Captura: {dados['captura']}\nReconhecimento: {dados['reconhecimento']}"
        )
        if "rms" in dados:
            texto += f"\nPico RMS capturado: {dados['rms']:.4f}"
        self.teste_resultado.setText(texto)

    def atualizar_relogio(self):
        agora = agora_recife()
        self.relogio.setText(
            f"HORÁRIO · SALGUEIRO\n\n{agora:%H:%M}\n{agora:%d/%m/%Y}\nAmerica/Recife"
        )

    def enviar_texto(self):
        texto = self.entrada.text()
        if self.runtime.enviar(texto):
            self.transcricao.setText("Comando digitado: " + texto)
            self.ajustar_textos()
            self.entrada.clear()
        elif self.entrada.text().strip():
            self.aviso.setText(
                "Aguarde a operação atual ou use Cancelar ação / Parar antes de enviar."
            )

    def adicionar(self, papel, texto):
        if papel == "Aviso":
            self.aviso.setText(texto)
        elif papel == "Jarvis":
            self.resposta.document().setMarkdown(
                texto, QTextDocument.MarkdownFeature.MarkdownNoHTML
            )
            self.mostrar_resultado(self.resposta)
            QTimer.singleShot(0, self.ajustar_textos)
        else:
            if not self.transcricao.text().startswith(
                ("Texto reconhecido:", "Comando digitado:")
            ):
                self.transcricao.setText(papel + ": " + texto)
                self.ajustar_textos()
        self.historico.append(
            f'<p><b style="color:#5de9ff">{html.escape(papel)}</b><br>{html.escape(texto).replace(chr(10), "<br>")}</p>'
        )

    def ocupado(self, ocupado):
        self.enviar.setEnabled(not ocupado)
        self.preferencias.setEnabled(not ocupado)
        self.testar_mic.setEnabled(not ocupado)
        self.atualizar_mics.setEnabled(not ocupado)
        self.entradas.setEnabled(not ocupado)
        for b in self.spotify_botoes:
            b.setEnabled(not ocupado)

    def amplitude(self, valor):
        self.nivel.setValue(int(valor * 100))
        if self.nucleo.modo == "ouvindo":
            self.nucleo.amplitude(valor)

    def amplitude_voz(self, valor):
        if self.nucleo.modo == "falando":
            self.nucleo.amplitude(valor)

    def atualizar_cartoes(self, dados):
        for nome, widget, titulo in (
            ("clima", self.clima, "CLIMA · SALGUEIRO"),
            ("dolar", self.dolar, "USD / BRL"),
        ):
            if nome in dados:
                widget.setText(titulo + "\n\n" + dados[nome])
                self.mostrar_resultado(widget)

    def limpar_conversa(self):
        self.runtime.limpar()
        self.historico.clear()
        self.resposta.clear()
        self.resposta.hide()
        self.resultados_arquivos.clear()
        self.resultados_arquivos.hide()
        self.acao_pc.hide()

    def configurar(self):
        self.runtime.parar()
        dialog = Preferencias(self.config, self)
        self.runtime.dispositivos.connect(dialog.atualizar_dispositivos)
        self.runtime.listar_dispositivos()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.config = dialog.resultado()
                salvar(self.config)
                self.runtime.configurar(self.config)
                for widget, valor in (
                    (self.volume_musica, round(self.config.volume * 100)),
                    (self.volume_voz, round(self.config.volume_voz * 100)),
                    (self.habilitar_voz, not self.config.sem_voz),
                ):
                    widget.blockSignals(True)
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(valor)
                    else:
                        widget.setValue(valor)
                    widget.blockSignals(False)
                self.percentual_musica.setText(f"{self.volume_musica.value()}%")
                self.percentual_voz.setText(f"{self.volume_voz.value()}%")
                self.nucleo.movimento(self.config.reduzir_movimento)
                self.rotulo_audio()
                self.runtime.listar_dispositivos()
            except (ValueError, OSError):
                QMessageBox.warning(
                    self,
                    "Configurações",
                    "Não foi possível salvar as preferências locais.",
                )
        self.runtime.dispositivos.disconnect(dialog.atualizar_dispositivos)

    def closeEvent(self, event):
        self.nucleo.suspender(True)
        self.timer.stop()
        self.erro_timer.stop()
        if self.salvar_audio_timer.isActive():
            self.salvar_audio_timer.stop()
            self.salvar_audio()
        if self.dialog_decisao:
            self.dialog_decisao.finalizar()
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
