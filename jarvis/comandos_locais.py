"""Regras de português para ferramentas locais; nenhum modelo decide ações."""

import re
from pathlib import Path, PureWindowsPath
from .cotacao import numero_por_extenso
from .reconhecimento import normalizar
from .ferramentas.base import ErroFerramenta

PASTAS = {"downloads", "documentos", "area de trabalho", "imagens", "musicas", "videos"}


def limpar_alvo(texto):
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in ('"', "'"):
        return texto[1:-1]
    texto = re.sub(
        r"^(?:o|a|um|uma)\s+(?:arquivo|documento|pasta|aplicativo|programa)\s+|^(?:arquivo|documento|pasta|aplicativo|programa)\s+",
        "",
        texto,
        flags=re.I,
    ).strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in ('"', "'"):
        texto = texto[1:-1]
    return texto


def interpretar_local(texto):
    """Retorna (ferramenta, parâmetros). Frases não reconhecidas nunca viram shell."""
    s = re.sub(r"^\s*jarvis\b[\s,;:!?-]*", "", texto, flags=re.I).strip()
    s = re.sub(r"^por favor[,\s]+", "", s, flags=re.I)
    n = normalizar(s)
    if n in {
        "abra o google",
        "abrir o google",
        "abre o google",
        "entre no google",
        "entrar no google",
        "acesse o google",
        "abra google",
        "abra o navegador",
        "abrir navegador",
        "abra navegador",
    }:
        return "google_abrir", {}
    m = re.fullmatch(
        r"(?:pesquise|pesquisar|pesquisa|busque|buscar|procure|procurar)\s+(.+)",
        s,
        re.I | re.S,
    )
    if m:
        q = m[1].strip()
        # Nomes de arquivos têm precedência sobre pesquisa da web.
        if re.match(r"(?:o\s+)?arquivo\s+", q, re.I):
            return "arquivo_buscar", {"nome": limpar_alvo(q), "pasta": None}
        q = re.sub(r"^(?:no google|na internet)\s*(?:por|sobre)?\s*", "", q, flags=re.I)
        q = re.sub(r"\s+(?:no google|na internet)[.!?]*$", "", q, flags=re.I)
        if not q.strip():
            raise ErroFerramenta(
                "Diga o assunto: Jarvis, pesquise como fazer um currículo."
            )
        return "google_pesquisar", {"consulta": q}
    if n in {"pesquise", "pesquisar", "pesquise no google", "busque no google"}:
        raise ErroFerramenta(
            "Diga o assunto: Jarvis, pesquise como fazer um currículo."
        )
    m = re.fullmatch(
        r"(?:encontre|encontrar|localize|localizar)\s+(.+)", s, re.I | re.S
    )
    if m:
        nome = limpar_alvo(m[1])
        pasta = None
        if '"' not in nome and "'" not in nome:
            partes = re.split(r"\s+(?:na pasta|em)\s+", nome, maxsplit=1, flags=re.I)
            if len(partes) == 2:
                nome, pasta = partes
        return "arquivo_buscar", {
            "nome": limpar_alvo(nome),
            "pasta": limpar_alvo(pasta) if pasta else None,
        }
    m = re.fullmatch(
        r"(?:liste|listar|mostre os arquivos (?:da|na) pasta)\s+(.+)", s, re.I | re.S
    )
    if m:
        return "arquivo_listar", {"pasta": limpar_alvo(m[1])}
    m = re.fullmatch(
        r"(?:leia|ler|resuma|resumir|explique|explicar)\s+(.+)", s, re.I | re.S
    )
    if m and (
        re.search(r"\b(?:arquivo|pdf|documento)\b", m[1], re.I)
        or re.search(r"\.(?:txt|md|csv|json|log|pdf)[\"']?$", m[1], re.I)
    ):
        return (
            "arquivo_explicar"
            if n.startswith(("explique ", "explicar "))
            else "arquivo_ler"
        ), {"alvo": limpar_alvo(m[1])}
    m = re.fullmatch(
        r"(?:copie|copiar|mova|mover)\s+(\"[^\"]+\"|'[^']+'|.+?)\s+para\s+(.+)",
        s,
        re.I | re.S,
    )
    if m:
        return (
            "arquivo_mover" if n.startswith(("mova ", "mover ")) else "arquivo_copiar"
        ), {"origem": limpar_alvo(m[1]), "destino": limpar_alvo(m[2])}
    m = re.fullmatch(
        r"(?:renomeie|renomear)\s+(\"[^\"]+\"|'[^']+'|.+?)\s+para\s+(.+)",
        s,
        re.I | re.S,
    )
    if m:
        return "arquivo_renomear", {
            "alvo": limpar_alvo(m[1]),
            "novo_nome": limpar_alvo(m[2]),
        }
    m = re.fullmatch(r"(?:exclua|excluir|apague|apagar)\s+(.+)", s, re.I | re.S)
    if m:
        return "arquivo_excluir", {"alvo": limpar_alvo(m[1])}
    m = re.fullmatch(
        r"(?:crie|criar)\s+(?:um\s+)?(?:arquivo\s+)?(\"[^\"]+\"|'[^']+'|.+?)\s+com (?:o )?(?:texto|conte[uú]do)\s*[:\s]\s*(.*)",
        s,
        re.I | re.S,
    )
    if m:
        alvo = m[1]
        pasta = None
        partes = re.split(r"\s+(?:na pasta|em)\s+", alvo, maxsplit=1, flags=re.I)
        if len(partes) == 2:
            alvo, pasta = partes
        destino = limpar_alvo(alvo)
        if pasta:
            destino = limpar_alvo(pasta).rstrip("/\\") + "/" + destino
        elif (
            not Path(destino).is_absolute()
            and not PureWindowsPath(destino).is_absolute()
            and not re.search(r"[\\/]", destino)
        ):
            destino = "Documentos/" + destino
        return "arquivo_criar", {"destino": destino, "conteudo": m[2]}
    m = re.fullmatch(
        r"(?:coloque|ajuste|defina|mude)\s+(?:o\s+)?volume(?:\s+(?:do|da)\s+(spotify|mp3|m[uú]sica local|windows|sistema))?\s+(?:em|para)\s+(.+?)(?:\s*%|\s+por cento|\s+porcento)?[.!?]*",
        s,
        re.I,
    )
    if m:
        fontes = {"spotify": "spotify", "mp3": "local", "musica local": "local"}
        valor = normalizar(m[2])
        numeros = {normalizar(numero_por_extenso(i)): i for i in range(101)}
        percentual = int(valor) if valor.isdigit() else numeros.get(valor)
        if percentual is None or not 0 <= percentual <= 100:
            raise ErroFerramenta("Use um volume entre zero e cem por cento.")
        return "audio_volume", {
            "percentual": percentual,
            "fonte": fontes.get(normalizar(m[1] or ""), "sistema"),
        }
    m = re.fullmatch(
        r"(?:toque|tocar|reproduza|reproduzir)\s+(.+?)\s+no spotify[.!?]*", s, re.I
    )
    if m:
        partes = re.split(r"\s+(?:de|do|da|por)\s+", m[1], maxsplit=1, flags=re.I)
        return "spotify_tocar", {
            "nome": limpar_alvo(partes[0]),
            "artista": limpar_alvo(partes[1]) if len(partes) == 2 else None,
        }
    fonte = (
        "spotify"
        if re.search(r"\bspotify\b", n)
        else (
            "local"
            if re.search(r"\bmp3\b|musica local", n)
            else "sistema" if re.search(r"\bsistema\b", n) else "ativa"
        )
    )
    base = re.sub(r"\s+(?:no|do|da)\s+(?:spotify|mp3|sistema|musica local)$", "", n)
    midia = {
        "pause a musica": "pausar",
        "pausar a musica": "pausar",
        "pause musica": "pausar",
        "pause": "pausar",
        "pausar": "pausar",
        "retome a musica": "retomar",
        "retomar a musica": "retomar",
        "continue a musica": "retomar",
        "retome": "retomar",
        "proxima musica": "proxima",
        "proxima faixa": "proxima",
        "musica anterior": "anterior",
        "faixa anterior": "anterior",
        "qual musica esta tocando": "atual",
        "musica atual": "atual",
        "qual e a musica atual": "atual",
    }
    if base in midia:
        return "audio_controlar", {"acao": midia[base], "fonte": fonte}
    m = re.fullmatch(
        r"(?:abra|abrir|abre|acesse|acessar|foque|focar|traga para frente)\s+(.+)",
        s,
        re.I | re.S,
    )
    if m:
        alvo = limpar_alvo(m[1])
        alvo = re.sub(r"^(?:o|a)\s+", "", alvo, flags=re.I)
        if normalizar(alvo) == "spotify":
            return "spotify_abrir", {}
        if n.startswith(("foque ", "focar ", "traga para frente ")):
            return "aplicativo_focar", {"nome": alvo}
        if (
            normalizar(alvo) in PASTAS
            or re.search(r"\b(?:arquivo|pdf|documento|pasta)\b", m[1], re.I)
            or re.search(r"\.[a-z0-9]{1,5}[\"']?$", m[1], re.I)
            or re.match(r"^[a-z]:[\\/]", alvo, re.I)
        ):
            return "arquivo_abrir", {"alvo": alvo}
        return "aplicativo_abrir", {"nome": alvo}
    return None
