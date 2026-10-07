"""Painéis locais de permissões, catálogo e confirmação; nenhum acesso à API."""

from dataclasses import replace
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QListWidget,
    QFileDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QInputDialog,
    QMessageBox,
    QComboBox,
    QTextBrowser,
)
from .ferramentas.aplicativos import carregar_catalogo, salvar_catalogo
from .ferramentas.arquivos import pastas_pessoais
from .ferramentas.base import ErroFerramenta


class CatalogoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Catálogo de aplicativos confiáveis")
        self.resize(700, 400)
        layout = QVBoxLayout(self)
        aviso = QLabel(
            "Edite nomes/apelidos; adicione executáveis ou atalhos escolhidos por você. Não são aceitos comandos de terminal."
        )
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        self.apps = carregar_catalogo()
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(
            ["Nome", "Apelidos (vírgula)", "Caminho escolhido"]
        )
        self.tabela.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tabela)
        self.preencher()
        botoes = QHBoxLayout()
        adicionar = QPushButton("Adicionar aplicativo")
        remover = QPushButton("Remover selecionado")
        adicionar.clicked.connect(self.adicionar)
        remover.clicked.connect(self.remover)
        botoes.addWidget(adicionar)
        botoes.addWidget(remover)
        layout.addLayout(botoes)
        salvar = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        salvar.accepted.connect(self.salvar)
        salvar.rejected.connect(self.reject)
        layout.addWidget(salvar)

    def preencher(self):
        self.tabela.setRowCount(len(self.apps))
        for i, app in enumerate(self.apps):
            for j, valor in enumerate(
                (app["nome"], ", ".join(app.get("apelidos", [])), app["caminho"])
            ):
                item = QTableWidgetItem(valor)
                if j == 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tabela.setItem(i, j, item)

    def coletar(self):
        for i, app in enumerate(self.apps):
            app["nome"] = self.tabela.item(i, 0).text().strip()
            app["apelidos"] = [
                p.strip() for p in self.tabela.item(i, 1).text().split(",") if p.strip()
            ]

    def adicionar(self):
        self.coletar()
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolha o programa instalado", "", "Aplicativos (*.exe *.lnk)"
        )
        if not caminho:
            return
        nome, ok = QInputDialog.getText(
            self, "Nome", "Como deseja chamar este aplicativo?"
        )
        if not ok or not nome.strip():
            return
        self.apps.append(
            {
                "nome": nome.strip(),
                "apelidos": [nome.strip()],
                "tipo": "atalho" if caminho.casefold().endswith(".lnk") else "exe",
                "caminho": caminho,
            }
        )
        self.preencher()

    def remover(self):
        i = self.tabela.currentRow()
        if i >= 0:
            self.coletar()
            self.apps.pop(i)
            self.preencher()

    def salvar(self):
        self.coletar()
        if not all(a["nome"] for a in self.apps):
            QMessageBox.warning(
                self, "Catálogo", "Todos os aplicativos precisam de nome."
            )
            return
        try:
            salvar_catalogo(self.apps)
            self.accept()
        except (OSError, ErroFerramenta):
            QMessageBox.warning(self, "Catálogo", "Não foi possível salvar o catálogo.")


class PermissoesDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Permissões locais do Jarvis")
        self.resize(600, 480)
        layout = QVBoxLayout(self)
        self.categorias = {}
        for nome, descricao in (
            ("arquivos", "Arquivos e pastas autorizadas"),
            ("aplicativos", "Aplicativos do catálogo"),
            ("audio", "Volume e controles de mídia"),
            ("spotify", "Spotify: conta e controles locais"),
        ):
            caixa = QCheckBox(descricao)
            caixa.setChecked(config.permissoes_pc[nome])
            self.categorias[nome] = caixa
            layout.addWidget(caixa)
        aviso = QLabel(
            "Pastas pessoais padrão: "
            + (
                "; ".join(map(str, pastas_pessoais()))
                or "Nenhuma identificada neste ambiente"
            )
            + ".\nPastas adicionais autorizadas:"
        )
        aviso.setTextFormat(Qt.TextFormat.PlainText)
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        self.pastas = QListWidget()
        self.pastas.addItems(config.pastas_autorizadas)
        layout.addWidget(self.pastas)
        linha = QHBoxLayout()
        add = QPushButton("Autorizar outra pasta")
        remove = QPushButton("Remover selecionada")
        add.clicked.connect(self.adicionar_pasta)
        remove.clicked.connect(lambda: self.pastas.takeItem(self.pastas.currentRow()))
        linha.addWidget(add)
        linha.addWidget(remove)
        layout.addLayout(linha)
        self.fones = QCheckBox(
            "Uso fones: permitir escuta durante mídia externa (Spotify)"
        )
        self.fones.setChecked(config.fones_midia_externa)
        layout.addWidget(self.fones)
        info = QLabel(
            "A fala e o MP3 do Jarvis sempre pausam a captura. Sem esta opção, mídia externa iniciada pelo Jarvis também pausa a captura; controle-a pelo painel. Não habilite com som saindo perto do microfone."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        catalogo = QPushButton("Editar catálogo de aplicativos")
        catalogo.clicked.connect(self.catalogo)
        layout.addWidget(catalogo)
        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def adicionar_pasta(self):
        caminho = QFileDialog.getExistingDirectory(
            self, "Autorizar acesso aos arquivos desta pasta"
        )
        atuais = [self.pastas.item(i).text() for i in range(self.pastas.count())]
        if caminho and caminho not in atuais:
            self.pastas.addItem(caminho)

    def catalogo(self):
        try:
            CatalogoDialog(self).exec()
        except ErroFerramenta as erro:
            QMessageBox.warning(self, "Catálogo", str(erro))

    def resultado(self):
        return replace(
            self.config,
            permissoes_pc={k: c.isChecked() for k, c in self.categorias.items()},
            pastas_autorizadas=[
                self.pastas.item(i).text() for i in range(self.pastas.count())
            ],
            fones_midia_externa=self.fones.isChecked(),
        ).validar()


class ConfirmacaoDialog(QDialog):
    def __init__(self, pedido, decisoes, parent=None):
        super().__init__(parent)
        self.pedido = pedido
        self.decisoes = decisoes
        self.finalizado = False
        self.setWindowTitle("Escolha/confirmar ação local")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(620, 320)
        layout = QVBoxLayout(self)
        self.alvo = QTextBrowser()
        self.alvo.setPlainText(pedido["acao"] + "\n\nAlvo exato:\n" + pedido["alvo"])
        layout.addWidget(self.alvo)
        self.opcoes = QComboBox()
        self.opcoes.addItem("Escolha uma opção", None)
        for i, opcao in enumerate(pedido["opcoes"]):
            self.opcoes.addItem(f"{i+1}. {opcao}", i)
        self.opcoes.setVisible(bool(pedido["opcoes"]))
        layout.addWidget(self.opcoes)
        self.prazo = QLabel()
        self.prazo.setWordWrap(True)
        layout.addWidget(self.prazo)
        linha = QHBoxLayout()
        self.confirmar = QPushButton(
            "Confirmar escolha" if pedido["opcoes"] else "Confirmar ação"
        )
        cancelar = QPushButton("Cancelar")
        self.confirmar.clicked.connect(self.aprovar)
        cancelar.clicked.connect(self.close)
        linha.addWidget(self.confirmar)
        linha.addWidget(cancelar)
        layout.addLayout(linha)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.atualizar)
        self.timer.start(200)
        self.atualizar()

    def atualizar(self):
        segundos = max(0, int(self.pedido["expira"] - time.monotonic()))
        self.prazo.setText(
            f"Prazo: {segundos} s. Diga confirmar/cancelar, ou o número da opção. Use os botões se o microfone estiver pausado."
        )
        self.confirmar.setEnabled(segundos > 0)
        if time.monotonic() >= self.pedido["expira"]:
            self.finalizar()

    def aprovar(self):
        valor = self.opcoes.currentData() if self.pedido["opcoes"] else True
        if self.decisoes.responder(self.pedido["id"], valor):
            self.finalizado = True
            self.hide()

    def finalizar(self):
        self.finalizado = True
        self.timer.stop()
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if (
            not self.finalizado
            and self.decisoes.pendente
            and self.decisoes.pendente["id"] == self.pedido["id"]
        ):
            self.decisoes.cancelar()
        event.accept()
