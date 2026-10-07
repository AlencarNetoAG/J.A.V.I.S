"""Resultados locais e confirmações com prazo, sem participação do modelo."""

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from ..cancelamento import verificar


class ErroFerramenta(Exception):
    pass


def resultado(mensagem, status="verificado", **dados):
    return {"status": status, "mensagem": mensagem, **dados}


class Decisoes:
    PRAZO = 30

    def __init__(self, publicar, capturar=None):
        self.publicar = publicar
        self.capturar = capturar
        self.lock = threading.Lock()
        self.evento = threading.Event()
        self.pendente = None
        self.resposta = None

    def responder(self, identificador, valor):
        with self.lock:
            p = self.pendente
            if (
                not p
                or self.evento.is_set()
                or p["id"] != identificador
                or time.monotonic() >= p["expira"]
            ):
                return False
            if p["opcoes"]:
                if type(valor) is not int or not 0 <= valor < len(p["opcoes"]):
                    return False
            elif type(valor) is not bool:
                return False
            self.resposta = valor
            self.evento.set()
            return True

    def cancelar(self):
        with self.lock:
            if self.pendente:
                self.resposta = None
                self.evento.set()

    def pedir(self, acao, alvo, cancelar, opcoes=None):
        verificar(cancelar)
        p = {
            "id": uuid.uuid4().hex,
            "acao": acao,
            "alvo": alvo,
            "opcoes": opcoes or [],
            "expira": time.monotonic() + self.PRAZO,
        }
        with self.lock:
            self.pendente = p
            self.resposta = None
            self.evento.clear()
        self.publicar(p)
        try:
            while not self.evento.is_set() and time.monotonic() < p["expira"]:
                verificar(cancelar)
                if self.capturar:
                    self.capturar(p, cancelar)
                self.evento.wait(0.05)
            verificar(cancelar)
            with self.lock:
                # Uma transcrição que só terminou depois do prazo não autoriza nada.
                if time.monotonic() >= p["expira"]:
                    return None
                return self.resposta
        finally:
            with self.lock:
                if self.pendente and self.pendente["id"] == p["id"]:
                    self.pendente = None
            self.publicar({"id": p["id"], "fechado": True})

    def confirmar(self, acao, alvo, cancelar):
        if self.pedir(acao, alvo, cancelar) is not True:
            raise ErroFerramenta(
                "Ação não autorizada: cancelada ou prazo de confirmação encerrado."
            )

    def escolher(self, acao, opcoes, cancelar):
        if not opcoes:
            raise ErroFerramenta("Não há opções disponíveis.")
        if len(opcoes) == 1:
            return 0
        escolha = self.pedir(acao, "Selecione o alvo exato.", cancelar, opcoes)
        if escolha is None:
            raise ErroFerramenta("Nenhuma opção escolhida: ação cancelada.")
        return escolha


class HistoricoAcoes:
    """Somente ferramenta/categoria/status/hora. Sem argumentos, caminhos ou conteúdo."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)

    def registrar(self, ferramenta, categoria, status):
        entrada = {
            "hora": datetime.now(timezone.utc).isoformat(),
            "ferramenta": ferramenta,
            "categoria": categoria,
            "status": status,
        }
        try:
            linhas = (
                self.caminho.read_text(encoding="utf-8").splitlines()[-499:]
                if self.caminho.exists()
                else []
            )
            linhas.append(json.dumps(entrada, ensure_ascii=False))
            self.caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        except OSError:
            import logging

            logging.getLogger(__name__).warning(
                "Não foi possível gravar o histórico de ações."
            )
