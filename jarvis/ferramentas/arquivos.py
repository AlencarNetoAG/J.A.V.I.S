"""Buscas limitadas a raízes autorizadas e operações de arquivos verificadas."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
from .base import ErroFerramenta, resultado
from ..cancelamento import verificar
from ..configuracoes import RAIZ
from ..reconhecimento import normalizar

PASTAS = {
    "desktop": "Área de Trabalho",
    "downloads": "Downloads",
    "documents": "Documentos",
    "pictures": "Imagens",
    "music": "Músicas",
    "videos": "Vídeos",
}
IGNORAR = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "appdata",
    "$recycle.bin",
    "system volume information",
}
EXECUTAVEIS = {
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jse",
    ".wsf",
    ".wsh",
    ".msc",
    ".msi",
    ".msp",
    ".scr",
    ".hta",
    ".lnk",
    ".url",
    ".reg",
    ".py",
    ".pyw",
    ".sh",
}
EXTENSOES_TEXTO = {".txt", ".md", ".csv", ".json", ".log"}


def pastas_pessoais(aliases=False):
    if os.name == "nt":
        # Known Folders oficial: respeita redirecionamento/OneDrive e nomes localizados.
        import ctypes, uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("data1", wintypes.DWORD),
                ("data2", wintypes.WORD),
                ("data3", wintypes.WORD),
                ("data4", ctypes.c_ubyte * 8),
            ]

        ids = [
            "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
            "374DE290-123F-4565-9164-39C4925E467B",
            "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
            "33E28130-4E1E-4676-835A-98395C3BC3BB",
            "4BD8D571-6D19-48D3-BE97-422220080E43",
            "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
        ]
        saida = {}
        shell = ctypes.WinDLL("shell32")
        ole = ctypes.WinDLL("ole32")
        shell.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        for nome_pasta, chave in zip(PASTAS, ids):
            guid = GUID.from_buffer_copy(uuid.UUID(chave).bytes_le)
            nome = ctypes.c_wchar_p()
            if (
                shell.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(nome)
                )
                == 0
            ):
                try:
                    saida[nome_pasta] = Path(nome.value)
                finally:
                    ole.CoTaskMemFree(ctypes.cast(nome, ctypes.c_void_p))
        saida = {k: p for k, p in saida.items() if p.is_dir()}
    else:
        saida = {
            nome: Path.home() / nome.title()
            for nome in PASTAS
            if (Path.home() / nome.title()).is_dir()
        }
    return saida if aliases else list(saida.values())


def assinatura(path):
    if not path.exists():
        return None
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)


class Arquivos:
    def __init__(self, raizes, decisoes, abrir, autorizar=lambda: None):
        self.raizes = raizes
        self.decisoes = decisoes
        self.abrir_documento = abrir
        self.autorizar = autorizar
        self.encontrados = []
        self.encontrados_em = 0.0
        self.ultimo = None

    def roots(self):
        return list(
            dict.fromkeys(Path(p).resolve() for p in self.raizes() if Path(p).is_dir())
        )

    def validar(self, alvo, existente=True, alterar=False):
        if not isinstance(alvo, str) or not alvo.strip() or "\x00" in alvo:
            raise ErroFerramenta("Caminho inválido.")
        # Rejeitar ADS, nomes de dispositivos e normalizações silenciosas do Win32.
        # O drive C: é permitido; ':' em qualquer componente restante não é.
        from pathlib import PureWindowsPath

        partes = PureWindowsPath(alvo).parts
        for parte in partes[1:] if PureWindowsPath(alvo).anchor else partes:
            base = parte.split(".")[0].upper()
            if (
                ":" in parte
                or parte.endswith((" ", "."))
                or base
                in {
                    "CON",
                    "PRN",
                    "AUX",
                    "NUL",
                    *[f"COM{i}" for i in range(1, 10)],
                    *[f"LPT{i}" for i in range(1, 10)],
                }
            ):
                raise ErroFerramenta(
                    "Caminho incompatível com nomes de arquivos do Windows."
                )
        roots = self.roots()
        texto = normalizar(alvo)
        aliases = {
            "area de trabalho": "desktop",
            "documentos": "documents",
            "imagens": "pictures",
            "musicas": "music",
            "videos": "videos",
            "downloads": "downloads",
        }
        if texto in aliases:
            nome = aliases[texto]
            # Mesmo quando a pasta foi redirecionada, preservar a ordem dos Known Folders.
            pessoais = pastas_pessoais(aliases=True)
            padroes = (nome, PASTAS[nome])
            possiveis = ([pessoais[nome]] if nome in pessoais else []) + [
                p
                for p in roots
                if normalizar(p.name) in [normalizar(v) for v in padroes]
            ]
            if not possiveis:
                raise ErroFerramenta(
                    "Pasta pessoal não encontrada; configure a raiz autorizada no painel."
                )
            caminho = possiveis[0].resolve()
        else:
            caminho = Path(alvo).expanduser()
            if not caminho.is_absolute():
                raise ErroFerramenta(
                    "Informe um caminho completo dentro de uma pasta autorizada."
                )
            caminho = caminho.resolve()
        if not any(caminho == r or r in caminho.parents for r in roots):
            raise ErroFerramenta(
                "Caminho fora das pastas autorizadas. Adicione a pasta no painel de permissões."
            )
        if alterar and caminho in {
            (RAIZ / n).resolve()
            for n in (
                "config.local.json",
                "aplicativos.local.json",
                ".env",
                "acoes.local.jsonl",
            )
        }:
            raise ErroFerramenta(
                "Configuração/credenciais/histórico do Jarvis só podem ser alterados pelo usuário no painel ou manualmente, não por ferramentas do modelo."
            )
        if existente and not caminho.exists():
            raise ErroFerramenta("Arquivo ou pasta não encontrado ou inacessível.")
        return caminho

    def buscar(self, nome, pasta, cancelar):
        roots = [self.validar(pasta)] if pasta else self.roots()
        if not nome.strip():
            raise ErroFerramenta("Informe o nome ou parte do nome do arquivo.")
        inicio = time.monotonic()
        contador = 0
        encontrados = []
        limitada = False
        for root in roots:
            for atual, dirs, files in os.walk(root, followlinks=False):
                verificar(cancelar)
                contador += 1
                if contador >= 20000 or time.monotonic() - inicio >= 5:
                    limitada = True
                    break
                dirs[:] = [
                    d
                    for d in dirs
                    if d.casefold() not in IGNORAR
                    and not d.startswith(".")
                    and not (Path(atual) / d).is_symlink()
                    and not (
                        getattr((Path(atual) / d).lstat(), "st_file_attributes", 0)
                        & 0x400
                    )
                ]
                for arquivo in files:
                    verificar(cancelar)
                    contador += 1
                    if normalizar(nome) in normalizar(arquivo):
                        try:
                            p = self.validar(str(Path(atual) / arquivo))
                            if p.is_file():
                                encontrados.append(p)
                        except (ErroFerramenta, OSError):
                            pass
                    if (
                        contador >= 20000
                        or time.monotonic() - inicio >= 5
                        or len(encontrados) >= 30
                    ):
                        limitada = True
                        break
                if limitada:
                    break
            if limitada:
                break
        self.encontrados = list(dict.fromkeys(encontrados))
        self.encontrados_em = time.monotonic()
        lista = [
            {"numero": i + 1, "nome": p.name, "caminho": str(p)}
            for i, p in enumerate(self.encontrados)
        ]
        mensagem = (
            "\n".join(f"{i+1}. {p}" for i, p in enumerate(self.encontrados))
            or "Nenhum arquivo encontrado nas pastas autorizadas."
        )
        if limitada:
            mensagem += "\nBusca limitada por tempo/quantidade; indique uma pasta mais específica."
        return resultado(mensagem, arquivos=lista, limitada=limitada)

    def listar(self, pasta, cancelar):
        p = self.validar(pasta)
        if not p.is_dir():
            raise ErroFerramenta("O alvo não é uma pasta.")
        itens = []
        for f in p.iterdir():
            verificar(cancelar)
            if len(itens) >= 100:
                break
            try:
                self.validar(str(f))
            except (ErroFerramenta, OSError):
                continue
            itens.append({"nome": f.name, "pasta": f.is_dir()})
        return resultado(
            "\n".join(("[Pasta] " if f["pasta"] else "") + f["nome"] for f in itens)
            or "Pasta vazia.",
            itens=itens,
        )

    def resolver(self, alvo, cancelar):
        if normalizar(alvo) in ("este arquivo", "este pdf", "este documento"):
            if self.ultimo and (
                normalizar(alvo) != "este pdf"
                or self.ultimo.suffix.casefold() == ".pdf"
            ):
                return self.validar(str(self.ultimo))
            opcoes = [
                p
                for p in self.encontrados
                if normalizar(alvo) != "este pdf" or p.suffix.casefold() == ".pdf"
            ]
        elif alvo.isdigit() and time.monotonic() - self.encontrados_em < 600:
            indice = int(alvo) - 1
            if not 0 <= indice < len(self.encontrados):
                raise ErroFerramenta("Número de arquivo inválido.")
            return self.validar(str(self.encontrados[indice]))
        elif Path(alvo).is_absolute() or normalizar(alvo) in (
            "downloads",
            "documentos",
            "area de trabalho",
            "imagens",
            "musicas",
            "videos",
        ):
            return self.validar(alvo)
        else:
            self.buscar(alvo, None, cancelar)
            opcoes = self.encontrados
        if not opcoes:
            raise ErroFerramenta(
                "Nenhum alvo identificado. Procure o arquivo pelo nome primeiro."
            )
        escolha = self.decisoes.escolher(
            "Qual arquivo deseja usar?", [str(p) for p in opcoes], cancelar
        )
        return self.validar(str(opcoes[escolha]))

    def abrir(self, alvo, cancelar):
        p = self.resolver(alvo, cancelar)
        verificar(cancelar)
        self.autorizar()
        if p.is_file() and p.suffix.casefold() in EXECUTAVEIS:
            raise ErroFerramenta(
                "Não abro executáveis/scripts por ferramentas de arquivos. Use aplicativos previamente cadastrados, sem argumentos de terminal."
            )
        retorno = self.abrir_documento(p, cancelar)
        if p.is_file():
            self.ultimo = p
        return retorno

    def ler(self, alvo, cancelar):
        p = self.resolver(alvo, cancelar)
        if not p.is_file() or (
            p.suffix.casefold() not in EXTENSOES_TEXTO and p.suffix.casefold() != ".pdf"
        ):
            raise ErroFerramenta(
                "Leitura disponível para TXT, MD, CSV, JSON, LOG e PDF com texto. Outros formatos não são lidos."
            )
        if p.stat().st_size > 10 * 1024 * 1024:
            raise ErroFerramenta("Arquivo acima do limite de leitura de 10 MB.")
        antes = assinatura(p)
        self.decisoes.confirmar(
            "Ler e enviar até 8.000 caracteres deste arquivo à OpenAI para esta solicitação",
            str(p),
            cancelar,
        )
        verificar(cancelar)
        self.autorizar()
        self.validar(str(p))
        if assinatura(p) != antes:
            raise ErroFerramenta(
                "O arquivo mudou após a confirmação. Solicite a leitura novamente."
            )
        if p.suffix.casefold() == ".pdf":
            from pypdf import PdfReader

            leitor = PdfReader(p)
            if leitor.is_encrypted:
                raise ErroFerramenta("PDF protegido por senha; não será lido.")
            trechos = []
            for pagina in leitor.pages[:20]:
                verificar(cancelar)
                trechos.append(pagina.extract_text() or "")
                if sum(map(len, trechos)) >= 8000:
                    break
            texto = "\n".join(trechos)
        else:
            with p.open(encoding="utf-8-sig") as f:
                texto = f.read(8001)
        if not texto.strip():
            raise ErroFerramenta(
                "Não foi encontrado texto legível. PDFs de imagem exigem OCR, não incluído."
            )
        self.ultimo = p
        return resultado(
            "Conteúdo autorizado para resumo desta solicitação.",
            conteudo=texto[:8000],
            truncado=len(texto) > 8000,
            arquivo=p.name,
            envio_autorizado=True,
        )

    def _preparar_destino(self, destino, acao, cancelar):
        p = self.validar(destino, existente=False, alterar=True)
        if not p.parent.is_dir():
            raise ErroFerramenta("A pasta de destino precisa existir.")
        if p.exists() and not p.is_file():
            raise ErroFerramenta("O destino não é um arquivo.")
        antes = assinatura(p)
        if antes is not None:
            self.decisoes.confirmar(
                acao + " e sobrescrever arquivo existente", str(p), cancelar
            )
        verificar(cancelar)
        self.autorizar()
        return p, antes

    def _verificar_destino(self, p, antes, cancelar):
        verificar(cancelar)
        self.autorizar()
        self.validar(str(p), existente=False, alterar=True)
        if assinatura(p) != antes:
            raise ErroFerramenta(
                "O destino mudou durante a operação; nada será sobrescrito."
            )

    def _instalar(self, tmp, p, antes, cancelar):
        self._verificar_destino(p, antes, cancelar)
        if antes is not None:
            os.replace(tmp, p)
        elif os.name == "nt":
            # No Windows rename recusa destino existente, mesmo após a checagem.
            os.rename(tmp, p)
        else:
            # Mesmo contrato no Linux dos testes: criação atômica sem sobrescrita.
            os.link(tmp, p)

    def criar(self, destino, conteudo, cancelar):
        p, antes = self._preparar_destino(destino, "Criar", cancelar)
        if p.suffix.casefold() not in EXTENSOES_TEXTO:
            raise ErroFerramenta(
                "Criação disponível apenas para TXT, MD, CSV, JSON e LOG em UTF-8; scripts não são criados/executados."
            )
        if len(conteudo) > 100000:
            raise ErroFerramenta(
                "Conteúdo acima do limite de criação de 100 mil caracteres."
            )
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".jarvis-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(conteudo)
            self._instalar(tmp, p, antes, cancelar)
            if p.read_text(encoding="utf-8") != conteudo:
                raise ErroFerramenta("Não foi possível verificar o arquivo criado.")
        finally:
            Path(tmp).unlink(missing_ok=True)
        self.ultimo = p
        return resultado(f"Arquivo criado e conteúdo verificado: {p}")

    def copiar(self, origem, destino, cancelar, mover=False):
        src = self.resolver(origem, cancelar)
        if not src.is_file():
            raise ErroFerramenta("Cópia/movimentação disponível apenas para arquivos.")
        dst, antes = self._preparar_destino(
            destino, ("Mover " if mover else "Copiar ") + str(src) + " para", cancelar
        )
        if (
            dst.suffix.casefold() in EXECUTAVEIS
            and src.suffix.casefold() != dst.suffix.casefold()
        ):
            raise ErroFerramenta(
                "Não transformo um documento em script/executável pela troca da extensão."
            )
        if src == dst:
            raise ErroFerramenta("Origem e destino são iguais.")
        if mover:
            self.validar(str(src), alterar=True)
        fonte = assinatura(src)
        fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".jarvis-")
        digest = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as f, src.open("rb") as entrada:
                while bloco := entrada.read(1024 * 1024):
                    verificar(cancelar)
                    f.write(bloco)
                    digest.update(bloco)
            shutil.copystat(src, tmp)
            if assinatura(src) != fonte:
                raise ErroFerramenta(
                    "A origem mudou durante a cópia; operação interrompida."
                )
            self._instalar(tmp, dst, antes, cancelar)
            hash_dst = hashlib.sha256()
            with dst.open("rb") as f:
                while bloco := f.read(1024 * 1024):
                    verificar(cancelar)
                    hash_dst.update(bloco)
            if digest.digest() != hash_dst.digest():
                raise ErroFerramenta(
                    "Cópia não passou na verificação; a origem foi preservada."
                )
            if mover:
                verificar(cancelar)
                self.autorizar()
                if assinatura(src) != fonte:
                    raise ErroFerramenta(
                        "Origem alterada; cópia concluída, mas origem preservada."
                    )
                src.unlink()
                if src.exists():
                    raise ErroFerramenta(
                        "Destino copiado, mas remoção da origem não foi confirmada."
                    )
        finally:
            Path(tmp).unlink(missing_ok=True)
        self.ultimo = dst
        return resultado(
            f"Arquivo {'movido' if mover else 'copiado'} e verificado: {dst}"
        )

    def renomear(self, alvo, novo_nome, cancelar):
        if (
            not novo_nome
            or any(c in novo_nome for c in ("/", "\\", "\x00"))
            or novo_nome in (".", "..")
        ):
            raise ErroFerramenta("Novo nome inválido: use apenas o nome, sem pastas.")
        src = self.resolver(alvo, cancelar)
        return self.copiar(str(src), str(src.parent / novo_nome), cancelar, mover=True)

    def excluir(self, alvo, cancelar):
        p = self.resolver(alvo, cancelar)
        if not p.is_file():
            raise ErroFerramenta(
                "Exclusão nesta versão disponível somente para arquivos."
            )
        self.validar(str(p), alterar=True)
        antes = assinatura(p)
        self.decisoes.confirmar("Enviar arquivo à Lixeira", str(p), cancelar)
        verificar(cancelar)
        self.autorizar()
        self.validar(str(p))
        if assinatura(p) != antes:
            raise ErroFerramenta(
                "O arquivo mudou depois da confirmação; não foi excluído."
            )
        from send2trash import send2trash

        send2trash(str(p))
        if p.exists():
            raise ErroFerramenta("Não foi possível confirmar a remoção para a Lixeira.")
        if self.ultimo == p:
            self.ultimo = None
        return resultado(
            f"Arquivo enviado à Lixeira; ausência no caminho original verificada: {p}"
        )
