"""APIs oficiais de janela, shell, Core Audio e sessões de mídia do Windows."""

import asyncio
import os
from pathlib import Path
import subprocess
import time
from .base import ErroFerramenta, resultado
from ..cancelamento import verificar


class Windows:
    def __init__(self, antes_audio=None):
        self.antes_audio = antes_audio

    @staticmethod
    def exigir():
        if os.name != "nt":
            raise ErroFerramenta(
                "Esta ação requer o seu Windows. Não foi executada neste ambiente."
            )

    def janelas(self):
        self.exigir()
        import ctypes
        from ctypes import wintypes

        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        saida = []

        def enumerar(hwnd, param):
            if not user.IsWindowVisible(hwnd):
                return True
            tamanho = user.GetWindowTextLengthW(hwnd)
            if not tamanho:
                return True
            titulo = ctypes.create_unicode_buffer(tamanho + 1)
            user.GetWindowTextW(hwnd, titulo, tamanho + 1)
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                nome = ctypes.create_unicode_buffer(32768)
                n = wintypes.DWORD(len(nome))
                if kernel.QueryFullProcessImageNameW(handle, 0, nome, ctypes.byref(n)):
                    saida.append(
                        {
                            "hwnd": hwnd,
                            "titulo": titulo.value,
                            "executavel": nome.value,
                            "pid": pid.value,
                        }
                    )
            finally:
                kernel.CloseHandle(handle)
            return True

        user.EnumWindows(callback(enumerar), 0)
        return saida

    def focar(self, hwnd):
        self.exigir()
        import ctypes
        from ctypes import wintypes

        u = ctypes.WinDLL("user32")
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
        return u.GetForegroundWindow() == hwnd

    def _aguardar(self, predicado, cancelar):
        prazo = time.monotonic() + 5
        while time.monotonic() < prazo:
            verificar(cancelar)
            candidatos = [j for j in self.janelas() if predicado(j)]
            if candidatos:
                return candidatos[0]
            time.sleep(0.1)
        return None

    def aplicativo(self, app, cancelar, apenas_foco=False):
        self.exigir()
        verificar(cancelar)
        tipo = app["tipo"]
        alvo = app["caminho"]
        if tipo in ("exe", "atalho"):
            p = Path(alvo)
            if not p.is_file():
                raise ErroFerramenta("O caminho do aplicativo no catálogo não existe.")
            if tipo == "exe" and p.suffix.casefold() != ".exe":
                raise ErroFerramenta(
                    "O catálogo permite executáveis .exe, sem comandos de terminal."
                )
            processos = (
                [p.name.casefold()] if tipo == "exe" else app.get("processos", [])
            )
        else:
            processos = app.get("processos", [])

        def corresponde(j):
            if tipo == "exe":
                return Path(j["executavel"]).resolve() == Path(alvo).resolve()
            return Path(j["executavel"]).name.casefold() in [
                s.casefold() for s in processos
            ]

        existentes = [j for j in self.janelas() if corresponde(j)]
        if existentes:
            foco = self.focar(existentes[0]["hwnd"])
            return resultado(
                f"{app['nome']}: janela identificada"
                + (
                    " e trazida à frente."
                    if foco
                    else "; o Windows não permitiu colocá-la em primeiro plano."
                ),
                "verificado" if foco else "solicitado",
            )
        if apenas_foco:
            raise ErroFerramenta(
                "Não encontrei uma janela identificável deste aplicativo."
            )
        if tipo == "exe":
            subprocess.Popen([str(Path(alvo))], shell=False)
        elif tipo in ("uri", "atalho", "navegador"):
            os.startfile(alvo)
        else:
            raise ErroFerramenta("Tipo de aplicativo não suportado pelo catálogo.")
        janela = self._aguardar(corresponde, cancelar) if processos else None
        if janela:
            foco = self.focar(janela["hwnd"])
            return resultado(
                f"{app['nome']}: abertura verificada pela janela e pelo processo."
                + (
                    " Janela em primeiro plano."
                    if foco
                    else " O Windows não permitiu foco."
                )
            )
        return resultado(
            f"O Windows aceitou o pedido de abrir {app['nome']}, mas não consegui verificar a janela. Confira no PC.",
            "solicitado",
        )

    def _associacao(self, extensao):
        import ctypes
        from ctypes import wintypes

        lib = ctypes.WinDLL("shlwapi")
        fn = lib.AssocQueryStringW
        fn.argtypes = [
            wintypes.DWORD,
            ctypes.c_int,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        n = wintypes.DWORD(0)
        fn(0, 2, extensao, "open", None, ctypes.byref(n))
        if not 0 < n.value <= 32768:
            return None
        buf = ctypes.create_unicode_buffer(n.value)
        return (
            buf.value if fn(0, 2, extensao, "open", buf, ctypes.byref(n)) == 0 else None
        )

    def documento(self, path, cancelar):
        self.exigir()
        verificar(cancelar)
        esperado = "explorer.exe" if path.is_dir() else self._associacao(path.suffix)
        os.startfile(str(path))
        janela = (
            self._aguardar(
                lambda j: bool(esperado)
                and Path(j["executavel"]).name.casefold()
                == Path(esperado).name.casefold()
                and path.name.casefold() in j["titulo"].casefold(),
                cancelar,
            )
            if esperado
            else None
        )
        if janela:
            return resultado(
                f"Abertura verificada pela janela do aplicativo padrão: {path}"
            )
        return resultado(
            f"O Windows aceitou abrir {path} com o aplicativo padrão; não consegui confirmar a janela.",
            "solicitado",
        )

    def volume(self, percentual, cancelar):
        self.exigir()
        verificar(cancelar)
        import comtypes
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        comtypes.CoInitialize()
        try:
            dispositivo = AudioUtilities.GetSpeakers()
            if hasattr(dispositivo, "EndpointVolume"):
                volume = dispositivo.EndpointVolume
            else:
                interface = dispositivo.Activate(
                    IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None
                )
                volume = cast(interface, POINTER(IAudioEndpointVolume))
            verificar(cancelar)
            volume.SetMasterVolumeLevelScalar(percentual / 100, None)
            lido = round(volume.GetMasterVolumeLevelScalar() * 100)
            if abs(lido - percentual) > 1:
                raise ErroFerramenta("O Windows não confirmou o volume solicitado.")
            return resultado(f"Volume geral do Windows verificado em {lido} por cento.")
        finally:
            comtypes.CoUninitialize()

    async def _sessoes(self):
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )

        gestor = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        return list(gestor.get_sessions())

    def fontes_midia(self):
        self.exigir()

        async def consultar():
            saida = []
            for sessao in await self._sessoes():
                info = sessao.get_playback_info()
                status = getattr(
                    info.playback_status, "name", str(info.playback_status)
                ).casefold()
                saida.append(
                    {
                        "id": sessao.source_app_user_model_id,
                        "tocando": "playing" in status,
                        "pausada": "paused" in status,
                    }
                )
            return saida

        return asyncio.run(asyncio.wait_for(consultar(), timeout=3))

    def midia(self, acao, fonte, cancelar, decisoes):
        self.exigir()

        async def controlar():
            sessoes = await self._sessoes()
            # 'sistema' significa outras sessões; Spotify tem permissão própria.
            candidatos = (
                [
                    s
                    for s in sessoes
                    if fonte.casefold() in s.source_app_user_model_id.casefold()
                ]
                if fonte != "sistema"
                else [
                    s
                    for s in sessoes
                    if "spotify" not in s.source_app_user_model_id.casefold()
                ]
            )
            if not candidatos:
                raise ErroFerramenta(
                    "Não encontrei uma sessão de mídia acessível deste aplicativo no Windows."
                )
            i = decisoes.escolher(
                "Qual aplicativo de mídia?",
                [s.source_app_user_model_id for s in candidatos],
                cancelar,
            )
            sessao = candidatos[i]
            verificar(cancelar)
            antes = await sessao.try_get_media_properties_async()
            if acao == "atual":
                status = getattr(
                    sessao.get_playback_info().playback_status, "name", ""
                ).casefold()
                return resultado(
                    f"Mídia local: {antes.title or 'título indisponível'} · {antes.artist or 'artista indisponível'}.",
                    fonte=fonte,
                    tocando="playing" in status,
                )
            funcoes = {
                "pausar": "try_pause_async",
                "retomar": "try_play_async",
                "proxima": "try_skip_next_async",
                "anterior": "try_skip_previous_async",
            }
            if acao == "retomar" and self.antes_audio:
                self.antes_audio(fonte, True)
            if not await getattr(sessao, funcoes[acao])():
                raise ErroFerramenta("O aplicativo não aceitou este controle de mídia.")
            for _ in range(15):
                verificar(cancelar)
                info = sessao.get_playback_info()
                status = getattr(
                    info.playback_status, "name", str(info.playback_status)
                ).casefold()
                depois = await sessao.try_get_media_properties_async()
                confirmado = (
                    (acao == "pausar" and ("paused" in status or "stopped" in status))
                    or (acao == "retomar" and "playing" in status)
                    or (
                        acao in ("proxima", "anterior")
                        and (antes.title, antes.artist) != (depois.title, depois.artist)
                    )
                )
                if confirmado:
                    return resultado(
                        f"Controle local verificado: {acao}. {depois.title or ''} {depois.artist or ''}".strip(),
                        fonte=fonte,
                        tocando="playing" in status,
                    )
                await asyncio.sleep(0.1)
            return resultado(
                "O aplicativo aceitou o controle, mas não consegui verificar a mudança da reprodução.",
                "solicitado",
            )

        return asyncio.run(controlar())
