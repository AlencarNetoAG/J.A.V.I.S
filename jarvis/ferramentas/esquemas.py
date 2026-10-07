"""Schemas estritos e validação independente dos argumentos do modelo."""

import json
from .base import ErroFerramenta


def texto(maximo=1000, nulo=False):
    return {"type": ["string", "null"] if nulo else "string", "maxLength": maximo}


def escolha(*valores):
    return {"type": "string", "enum": list(valores)}


def inteiro():
    return {"type": "integer", "minimum": 0, "maximum": 100}


def ferramenta(nome, descricao, categoria, campos):
    return {
        "categoria": categoria,
        "schema": {
            "type": "function",
            "name": nome,
            "description": descricao,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": campos,
                "required": list(campos),
                "additionalProperties": False,
            },
        },
    }


REGISTRO = {
    item["schema"]["name"]: item
    for item in [
        ferramenta(
            "arquivo_buscar",
            "Localiza nomes de arquivos nas pastas autorizadas, sem ler conteúdo. pasta pode ser null.",
            "arquivos",
            {"nome": texto(200), "pasta": texto(nulo=True)},
        ),
        ferramenta(
            "arquivo_listar",
            "Lista uma pasta autorizada (caminho completo ou Downloads/Documentos).",
            "arquivos",
            {"pasta": texto()},
        ),
        ferramenta(
            "arquivo_abrir",
            "Abre pasta/documento no aplicativo padrão. alvo é caminho, nome, número do último resultado ou este PDF. Não abre scripts/executáveis.",
            "arquivos",
            {"alvo": texto()},
        ),
        ferramenta(
            "arquivo_ler",
            "Somente se o usuário pediu resumo/explicação: solicita autorização local específica antes de ler/enviar texto TXT/MD/CSV/JSON/LOG/PDF à OpenAI.",
            "arquivos",
            {"alvo": texto()},
        ),
        ferramenta(
            "arquivo_criar",
            "Cria documento de texto UTF-8 solicitado pelo usuário em caminho autorizado. Confirma sobrescrita; não cria scripts.",
            "arquivos",
            {"destino": texto(), "conteudo": texto(100000)},
        ),
        ferramenta(
            "arquivo_copiar",
            "Copia um arquivo; destino deve conter nome completo. Confirma antes de sobrescrever.",
            "arquivos",
            {"origem": texto(), "destino": texto()},
        ),
        ferramenta(
            "arquivo_mover",
            "Move um arquivo; destino contém nome completo. Cancelar não desfaz passos concluídos.",
            "arquivos",
            {"origem": texto(), "destino": texto()},
        ),
        ferramenta(
            "arquivo_renomear",
            "Renomeia um arquivo; novo_nome não pode conter caminho. Confirma sobrescrita.",
            "arquivos",
            {"alvo": texto(), "novo_nome": texto(255)},
        ),
        ferramenta(
            "arquivo_excluir",
            "Solicita confirmação específica e recente antes de enviar um arquivo à Lixeira.",
            "arquivos",
            {"alvo": texto()},
        ),
        ferramenta(
            "aplicativo_abrir",
            "Abre somente aplicativo/atalho do catálogo configurado pelo usuário. Nenhum comando ou argumento de terminal.",
            "aplicativos",
            {"nome": texto(150)},
        ),
        ferramenta(
            "aplicativo_focar",
            "Traz à frente uma janela identificada do aplicativo cadastrado, se o Windows permitir.",
            "aplicativos",
            {"nome": texto(150)},
        ),
        ferramenta(
            "audio_controlar",
            "Controla a fonte local/Spotify/sistema; fonte ativa resolve ambiguidades no PC. proxima/anterior não controlam MP3 local único.",
            "audio",
            {
                "acao": escolha("pausar", "retomar", "proxima", "anterior", "atual"),
                "fonte": escolha("ativa", "local", "spotify", "sistema"),
            },
        ),
        ferramenta(
            "audio_volume",
            "Volume em porcentagem inteira. Sem fonte explícita, use sistema (volume geral Windows); local é só MP3, spotify usa Web API.",
            "audio",
            {"percentual": inteiro(), "fonte": escolha("sistema", "local", "spotify")},
        ),
        ferramenta(
            "spotify_abrir",
            "Abre o Spotify cadastrado no Windows, sem OAuth.",
            "spotify",
            {},
        ),
        ferramenta(
            "spotify_tocar",
            "Busca e toca música pela Web API com OAuth. Pergunta faixa/artista/dispositivo quando ambíguo; artista pode ser null.",
            "spotify",
            {"nome": texto(300), "artista": texto(200, nulo=True)},
        ),
        ferramenta(
            "spotify_controlar",
            "Controles Spotify; usa API oficial com verificação e sessões locais quando a API está indisponível e a ação for viável.",
            "spotify",
            {"acao": escolha("pausar", "retomar", "proxima", "anterior", "atual")},
        ),
    ]
}

# Regras para futuras ferramentas; nenhuma destas capacidades é implementada aqui.
CONFIRMACAO_OBRIGATORIA = {
    "excluir",
    "sobrescrever",
    "enviar_mensagem",
    "publicar",
    "comprar",
    "instalar",
    "alterar_seguranca",
}


def validar(nome, argumentos):
    if nome not in REGISTRO:
        raise ErroFerramenta("Ferramenta local não implementada.")
    try:
        dados = json.loads(argumentos)
    except (ValueError, TypeError):
        raise ErroFerramenta("Parâmetros inválidos: JSON necessário.") from None
    props = REGISTRO[nome]["schema"]["parameters"]["properties"]
    if not isinstance(dados, dict) or set(dados) != set(props):
        raise ErroFerramenta("Parâmetros ausentes ou não permitidos.")
    for chave, regra in props.items():
        valor = dados[chave]
        tipo = regra["type"]
        if valor is None and isinstance(tipo, list) and "null" in tipo:
            continue
        if tipo == "integer":
            if (
                type(valor) is not int
                or not regra["minimum"] <= valor <= regra["maximum"]
            ):
                raise ErroFerramenta("Porcentagem inválida: use inteiro de zero a cem.")
        elif (
            not isinstance(valor, str)
            or not valor.strip()
            or len(valor) > regra.get("maxLength", 1000)
            or "\x00" in valor
        ):
            # Conteúdo pode ser vazio para criar um arquivo vazio.
            if not (chave == "conteudo" and valor == ""):
                raise ErroFerramenta("Texto/parâmetro inválido ou longo demais.")
        if "enum" in regra and valor not in regra["enum"]:
            raise ErroFerramenta("Ação/fonte não permitida.")
    return dados
