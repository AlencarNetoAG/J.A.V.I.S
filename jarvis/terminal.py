"""Teste por texto da mesma saudação e cliente OpenAI, sem microfone."""
import threading
from .cancelamento import Cancelado
from .cliente_openai import Conversa, ErroOpenAI
from .comandos import interpretar
from .musica import Musica
from .voz import Voz, ErroVoz


def iniciar(config):
    from .runtime import consultar_painel
    conversa = Conversa()
    cancel = threading.Event()
    voz = None
    musica = None
    print("Jarvis iniciado. Modo texto: pergunte, diga bom dia Jarvis, limpar ou sair.")
    try:
        while True:
            texto = input("> ").strip()
            if texto.casefold() == "sair": break
            if texto.casefold() == "limpar":
                conversa.limpar(); print("Conversa limpa."); continue
            if not texto: continue
            tipo, pergunta = interpretar(texto)
            if tipo == "aguardar":
                print("Sim, senhor? Digite sua pergunta.")
                if not config.sem_voz:
                    try:
                        if voz is None: voz = Voz(config.velocidade,config.voz)
                        voz.falar_cancelavel("Sim, senhor?",cancel)
                    except ErroVoz: print("Voz indisponível. Continue digitando.")
                continue
            if tipo == "ignorar": pergunta = texto
            try:
                if tipo == "bom_dia":
                    musica = None if config.sem_musica else Musica(config.musica,config.volume)
                    if musica: musica.iniciar()
                    resposta = consultar_painel(cancel, lambda cards: print("\n".join(cards.values())))
                else:
                    resposta = conversa.perguntar(pergunta,cancel)
                print(resposta)
                if not config.sem_voz:
                    if voz is None: voz = Voz(config.velocidade,config.voz)
                    if musica: musica.abaixar_para_fala()
                    voz.falar_cancelavel(resposta,cancel)
                if musica: musica.finalizar(cancelar=cancel)
            except (ErroOpenAI,ErroVoz) as erro:
                print(str(erro))
            finally:
                if musica: musica.fechar()
                musica = None
    except (KeyboardInterrupt,EOFError,Cancelado):
        cancel.set()
    finally:
        if musica: musica.fechar()
        if voz: voz.fechar()
        conversa.fechar()
        print("Jarvis encerrado.")
    return 0
