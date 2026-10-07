import argparse
from jarvis.configuracoes import carregar


def main():
    parser = argparse.ArgumentParser(description="Jarvis desktop ou teste por texto.")
    parser.add_argument("--texto", action="store_true")
    parser.add_argument("--sem-voz", action="store_true")
    parser.add_argument("--sem-musica", action="store_true")
    parser.add_argument("--voz")
    parser.add_argument("--velocidade", type=int)
    parser.add_argument("--musica")
    parser.add_argument("--volume", type=float)
    parser.add_argument("--modelo")
    parser.add_argument("--microfone", type=int)
    parser.add_argument("--limiar", type=float)
    args = parser.parse_args()
    config = carregar()
    for nome in ("voz","velocidade","musica","volume","modelo","microfone","limiar"):
        valor = getattr(args,nome)
        if valor is not None: setattr(config,nome,valor)
    if args.sem_voz: config.sem_voz = True
    if args.sem_musica: config.sem_musica = True
    try: config.validar()
    except (ValueError,TypeError): parser.error("Configuração inválida. Confira limites no README.")
    if args.texto:
        from jarvis.terminal import iniciar
    else:
        from jarvis.interface import iniciar
    return iniciar(config)

if __name__ == "__main__":
    raise SystemExit(main())
