"""Teste por texto da mesma saudação e cliente OpenAI, sem microfone."""

import threading
import os
from .ferramentas.base import Decisoes, ErroFerramenta
from .ferramentas.controle import ControlePC
from .cancelamento import Cancelado
from .cliente_local import ConversaLocal as Conversa
from .comandos import interpretar
from .musica import Musica
from .voz import Voz, ErroVoz


def decisoes_terminal():
    """Entrada local com prazo, sem thread concorrente lendo stdin."""

    def publicar(p):
        if p.get("fechado"):
            return
        print(f"\n{p['acao']}\nAlvo: {p['alvo']}")
        for i, item in enumerate(p["opcoes"], 1):
            print(f"{i}. {item}")
        print("Em até 30 s, digite confirmar/cancelar ou o número e Enter:")

    buffer = []

    def capturar(p, cancelar):
        texto = None
        if os.name == "nt":
            import msvcrt

            while msvcrt.kbhit():
                char = msvcrt.getwch()
                if char == "\x03":
                    raise KeyboardInterrupt()
                if char in ("\r", "\n"):
                    texto = "".join(buffer)
                    buffer.clear()
                    print()
                    break
                if char == "\b":
                    if buffer:
                        buffer.pop()
                        print("\b \b", end="", flush=True)
                elif char not in ("\x00", "\xe0"):
                    buffer.append(char)
                    print(char, end="", flush=True)
        else:
            import select, sys

            if select.select([sys.stdin], [], [], 0)[0]:
                texto = sys.stdin.readline().strip() or "cancelar"
        if texto is not None:
            valor = (
                (int(texto) - 1 if texto.isdigit() else None)
                if p["opcoes"]
                else texto.casefold() == "confirmar"
            )
            decisoes.responder(p["id"], valor)

    decisoes = Decisoes(publicar, capturar)
    return decisoes


def iniciar(config):
    from .runtime import consultar_painel

    cancel = threading.Event()
    controle = ControlePC(lambda: config, decisoes_terminal(), threading.Event())
    conversa = Conversa(controle)
    voz = None
    musica = None
    print("Jarvis iniciado. Modo texto: pergunte, diga bom dia Jarvis, limpar ou sair.")
    try:
        while True:
            texto = input("> ").strip()
            if texto.casefold() == "sair":
                break
            if texto.casefold() == "limpar":
                conversa.limpar()
                print("Conversa limpa.")
                continue
            if not texto:
                continue
            tipo, pergunta = interpretar(texto)
            if tipo == "aguardar":
                print("Sim, senhor? Digite sua pergunta.")
                if not config.sem_voz:
                    try:
                        if voz is None:
                            voz = Voz(config.velocidade, config.voz)
                        voz.falar_cancelavel(
                            "Sim, senhor?", cancel, volume=lambda: config.volume_voz
                        )
                    except ErroVoz:
                        print("Voz indisponível. Continue digitando.")
                continue
            if tipo == "ignorar":
                pergunta = texto
            try:
                if tipo == "bom_dia":
                    musica = (
                        None
                        if config.sem_musica
                        else Musica(config.musica, config.volume)
                    )
                    if musica:
                        musica.iniciar()
                    resposta = consultar_painel(
                        cancel, lambda cards: print("\n".join(cards.values()))
                    )
                else:
                    resposta = conversa.perguntar(pergunta, cancel)
                print(resposta)
                if not config.sem_voz:
                    if voz is None:
                        voz = Voz(config.velocidade, config.voz)
                    if musica:
                        musica.abaixar_para_fala()
                    voz.falar_cancelavel(
                        resposta, cancel, volume=lambda: config.volume_voz
                    )
                if musica:
                    musica.finalizar(cancelar=cancel)
            except (ErroFerramenta, ErroVoz) as erro:
                print(str(erro))
            finally:
                if musica:
                    musica.fechar()
                musica = None
    except (KeyboardInterrupt, EOFError, Cancelado):
        cancel.set()
    finally:
        if musica:
            musica.fechar()
        if voz:
            voz.fechar()
        conversa.fechar()
        controle.fechar()
        print("Jarvis encerrado.")
    return 0
