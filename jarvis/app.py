"""Interface de terminal e coordenação do único comando do Jarvis."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from .clima import consultar_clima
from .cotacao import consultar_cotacao
from .horario import agora_recife
from .musica import Musica
from .reconhecimento import ErroMicrofone, ErroReconhecedor, Ouvinte, eh_ativacao
from .saudacao import montar_saudacao
from .voz import ErroVoz, Voz


def atender() -> str:
    print("Comando reconhecido.", flush=True)
    print("Consultando cotação…", flush=True)
    print("Consultando condições atuais de Salgueiro, Pernambuco…", flush=True)
    # Um trabalho consulta câmbio; o outro confirma a cidade e consulta clima.
    # Não usamos o context manager: em Ctrl+C ele aguardaria a rede antes de
    # devolver controle ao finally que interrompe os dispositivos de áudio.
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-consulta")
    resultados = {"dólar": None, "clima": None}
    try:
        tarefas = {"dólar": executor.submit(consultar_cotacao), "clima": executor.submit(consultar_clima)}
        for nome, tarefa in tarefas.items():
            try:
                resultados[nome] = tarefa.result()
            except Exception as erro:
                print(f"Consulta de {nome} indisponível: {erro}", flush=True)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    cotacao, clima = resultados["dólar"], resultados["clima"]
    if cotacao is not None:
        print(f"Cotação USD/BRL: R$ {cotacao.valor} | Tipo: {cotacao.tipo}", flush=True)
        print(f"Fonte: {cotacao.fonte} | https://economia.awesomeapi.com.br/json/last/USD-BRL", flush=True)
        print(f"Atualização: {cotacao.atualizacao:%d/%m/%Y %H:%M:%S} (Brasília, UTC-03:00)", flush=True)
    if clima is not None:
        local = clima.localizacao
        print(f"Localização confirmada: {local.nome}, {local.estado}, {local.pais} ({local.latitude}, {local.longitude})", flush=True)
        print(f"Temperatura atual: {clima.temperatura} °C | Condição: {clima.condicao}", flush=True)
        print(f"Fonte: {clima.fonte} | https://api.open-meteo.com/v1/forecast (campo current)", flush=True)
        print(f"Atualização: {clima.atualizacao:%d/%m/%Y %H:%M:%S} (America/Recife)", flush=True)
    agora = agora_recife()
    print(f"Horário de Salgueiro: {agora:%d/%m/%Y %H:%M:%S} (America/Recife)", flush=True)
    return montar_saudacao(agora, clima, cotacao)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Jarvis: bom dia Jarvis informa hora, clima de Salgueiro e dólar, com música local.")
    parser.add_argument("--texto", action="store_true", help="Digite o comando, sem usar microfone/modelo.")
    parser.add_argument("--sem-voz", action="store_true", help="Desativa a fala e mostra a resposta no terminal; a música permanece habilitada.")
    parser.add_argument("--sem-musica", action="store_true", help="Desativa a música de fundo.")
    parser.add_argument("--musica", default=str(Path(__file__).resolve().parent.parent / "assets" / "highway_to_hell.mp3"), help="Caminho do MP3 local fornecido por você.")
    parser.add_argument("--volume", type=float, default=0.12, help="Volume da música entre 0 e 1; padrão 0.12. Reduzido durante a fala.")
    parser.add_argument("--modelo", default="tiny", help="Modelo Whisper: tiny (padrão), base ou pasta local compatível.")
    parser.add_argument("--limiar", type=float, default=0.01, help="Limiar de volume para detectar fala (0.001 a 0.5).")
    parser.add_argument("--microfone", type=int, help="Índice do dispositivo de entrada (padrão: o do Windows).")
    parser.add_argument("--voz", help="Identificador de uma voz instalada, listado pelo pyttsx3.")
    parser.add_argument("--velocidade", type=int, default=175, help="Velocidade da fala, padrão 175 (80 a 300).")
    args = parser.parse_args(argv)
    if not 80 <= args.velocidade <= 300:
        parser.error("--velocidade deve estar entre 80 e 300.")
    if not 0.001 <= args.limiar <= 0.5:
        parser.error("--limiar deve estar entre 0.001 e 0.5.")
    if not 0 <= args.volume <= 1:
        parser.error("--volume deve estar entre 0 e 1.")

    voz = None
    ouvinte = None
    musica = None if args.sem_musica else Musica(args.musica, args.volume)
    ultima_ativacao = float("-inf")
    print("Jarvis iniciado.", flush=True)
    if args.sem_voz:
        print("Diagnóstico sem voz: fala exibida no terminal. --sem-musica desativa também o MP3.")
    if args.texto:
        print("Modo texto: digite o comando e pressione Enter. Digite sair ou use Ctrl+C para encerrar.")
    try:
        while True:
            print("Aguardando: bom dia Jarvis.", flush=True)
            if args.texto:
                comando = input("> ")
                if comando.strip().casefold() == "sair":
                    break
                if not eh_ativacao(comando):
                    print("Comando não reconhecido. Use: bom dia Jarvis.")
                    continue
            else:
                try:
                    if ouvinte is None:
                        print("Carregando reconhecimento local (o primeiro uso baixa o modelo)…", flush=True)
                        ouvinte = Ouvinte(args.modelo, args.microfone, args.limiar)
                        print("Reconhecimento local pronto. Diga: bom dia Jarvis.", flush=True)
                    ouvinte.aguardar_ativacao()
                except (ErroMicrofone, ErroReconhecedor) as erro:
                    print(f"Problema de reconhecimento: {erro}")
                    print("Tentando novamente em 3 segundos. Ctrl+C encerra; --texto dispensa o microfone.", flush=True)
                    time.sleep(3)
                    continue

            if time.monotonic() - ultima_ativacao < 3:
                print("Ativação repetida ignorada; aguarde 3 segundos.")
                continue
            # Ouvinte fecha o microfone antes de retornar. Uma só sequência
            # ocupa este loop; retoma a escuta apenas após fala E fade da música.
            try:
                if musica is not None:
                    musica.iniciar()
                resposta = atender()
                print(resposta, flush=True)
                if not args.sem_voz:
                    try:
                        if voz is None:
                            voz = Voz(args.velocidade, args.voz)
                        if musica is not None:
                            musica.abaixar_para_fala()
                        voz.falar(resposta)
                    except ErroVoz as erro:
                        print(f"Problema de voz: {erro} A resposta está no terminal.", flush=True)
                        if voz is not None:
                            voz.fechar()
                        voz = None
                if musica is not None:
                    musica.finalizar()
            finally:
                if musica is not None:
                    musica.parar()
            # Janela contada após a resposta evita repetir uma ativação residual.
            ultima_ativacao = time.monotonic()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if musica is not None:
            musica.fechar()
        if voz is not None:
            voz.fechar()
        print("Jarvis encerrado.", flush=True)
    return 0
