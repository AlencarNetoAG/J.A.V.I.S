"""Catálogo confiável editado pelo usuário, nunca pelo modelo."""

import json
import os
from pathlib import Path
from .base import ErroFerramenta
from ..configuracoes import RAIZ
from ..reconhecimento import normalizar

CATALOGO = RAIZ / "aplicativos.local.json"


def padrao():
    return [
        {
            "nome": "Spotify",
            "apelidos": ["spotify"],
            "tipo": "uri",
            "caminho": "spotify:",
            "processos": ["spotify.exe"],
        },
        {
            "nome": "Navegador",
            "apelidos": ["navegador", "browser", "internet"],
            "tipo": "navegador",
            "caminho": "https://www.google.com",
            "processos": [
                "chrome.exe",
                "msedge.exe",
                "firefox.exe",
                "brave.exe",
                "opera.exe",
            ],
        },
        {
            "nome": "Bloco de Notas",
            "apelidos": ["notepad", "bloco de notas"],
            "tipo": "exe",
            "caminho": str(
                Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/notepad.exe"
            ),
        },
    ]


def validar_catalogo(dados):
    if not isinstance(dados, list) or len(dados) > 100:
        raise ValueError()
    for app in dados:
        if (
            not isinstance(app, dict)
            or app.get("tipo") not in ("exe", "atalho", "uri", "navegador")
            or not all(
                isinstance(app.get(k), str) and app[k].strip()
                for k in ("nome", "caminho")
            )
        ):
            raise ValueError()
        if not isinstance(app.get("apelidos", []), list) or not all(
            isinstance(a, str) for a in app.get("apelidos", [])
        ):
            raise ValueError()
        if "\x00" in app["caminho"]:
            raise ValueError()
        if not isinstance(app.get("processos", []), list) or not all(
            isinstance(a, str) for a in app.get("processos", [])
        ):
            raise ValueError()
        if app["tipo"] == "navegador" and not app["caminho"].startswith("https://"):
            raise ValueError()
        if app["tipo"] in ("exe", "atalho") and Path(
            app["caminho"]
        ).suffix.casefold() != (".exe" if app["tipo"] == "exe" else ".lnk"):
            raise ValueError()
    return dados


def carregar_catalogo():
    try:
        return validar_catalogo(
            json.loads(CATALOGO.read_text(encoding="utf-8"))
            if CATALOGO.exists()
            else padrao()
        )
    except (OSError, ValueError, TypeError):
        raise ErroFerramenta(
            "Catálogo de aplicativos inválido. Corrija aplicativos.local.json no painel."
        ) from None


def salvar_catalogo(dados):
    try:
        validar_catalogo(dados)
    except (ValueError, TypeError):
        raise ErroFerramenta(
            "Catálogo inválido; confira nomes, caminhos e tipos."
        ) from None
    CATALOGO.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class Aplicativos:
    def __init__(self, windows, decisoes):
        self.windows = windows
        self.decisoes = decisoes

    def resolver(self, nome, cancelar):
        apps = carregar_catalogo()
        q = normalizar(nome)
        opcoes = [
            a
            for a in apps
            if q in [normalizar(v) for v in [a["nome"], *a.get("apelidos", [])]]
        ]
        if not opcoes:
            opcoes = [a for a in apps if q and q in normalizar(a["nome"])]
        if not opcoes:
            raise ErroFerramenta(
                "Aplicativo não cadastrado. Adicione seu executável/atalho no painel do catálogo."
            )
        i = self.decisoes.escolher(
            "Qual aplicativo?", [a["nome"] for a in opcoes], cancelar
        )
        return opcoes[i]

    def abrir(self, nome, cancelar, apenas_foco=False):
        return self.windows.aplicativo(
            self.resolver(nome, cancelar), cancelar, apenas_foco
        )
