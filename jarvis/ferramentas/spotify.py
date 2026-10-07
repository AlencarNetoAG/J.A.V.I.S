"""Spotify Web API, OAuth Authorization Code com PKCE e cofre do Windows."""

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser
import requests
from .base import ErroFerramenta, resultado
from ..cancelamento import verificar

SCOPES = "user-read-playback-state user-modify-playback-state"
REDIRECT = "http://127.0.0.1:8787/callback"


class ErroSpotify(ErroFerramenta):
    def __init__(self, mensagem, local=False):
        super().__init__(mensagem)
        self.local = local


class CofreWindows:
    SERVICO = "Jarvis.Spotify.PKCE"

    def __init__(self):
        if os.name != "nt":
            raise ErroSpotify(
                "OAuth do Spotify e armazenamento seguro requerem o seu Windows.",
                local=True,
            )
        from keyring.backends.Windows import WinVaultKeyring

        self.backend = WinVaultKeyring()

    def ler(self):
        valor = self.backend.get_password(self.SERVICO, "tokens")
        return json.loads(valor) if valor else None

    def salvar(self, dados):
        self.backend.set_password(self.SERVICO, "tokens", json.dumps(dados))

    def apagar(self):
        if self.backend.get_password(self.SERVICO, "tokens"):
            self.backend.delete_password(self.SERVICO, "tokens")


class Spotify:
    def __init__(self, decisoes, cofre=None, session=None, antes_audio=None):
        self.antes_audio = antes_audio
        self.decisoes = decisoes
        self._cofre = cofre
        self.session = session or requests.Session()
        self.tokens = None

    def cofre(self):
        if self._cofre is None:
            self._cofre = CofreWindows()
        return self._cofre

    def _client_id(self):
        valor = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
        if not valor:
            raise ErroSpotify(
                "Configure SPOTIFY_CLIENT_ID no .env e conecte sua conta no painel.",
                local=True,
            )
        return valor

    def _guardar(self, dados, anterior=None):
        if not isinstance(dados, dict):
            raise ErroSpotify("Resposta de autenticação Spotify inválida.")
        access = dados.get("access_token")
        expira = dados.get("expires_in")
        if (
            not isinstance(access, str)
            or not access
            or type(expira) not in (int, float)
            or not 0 < expira <= 86400
        ):
            raise ErroSpotify("Resposta de autenticação Spotify inválida.")
        refresh = dados.get("refresh_token") or (anterior or {}).get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise ErroSpotify("Spotify não retornou token de renovação.")
        scope = dados.get("scope", (anterior or {}).get("scope", ""))
        if not isinstance(scope, str) or not set(SCOPES.split()) <= set(scope.split()):
            raise ErroSpotify(
                "Spotify não concedeu as permissões de reprodução solicitadas."
            )
        tokens = {
            "access_token": access,
            "refresh_token": refresh,
            "expira": time.time() + expira,
            "scope": scope,
            "client_id": self._client_id(),
        }
        try:
            self.cofre().salvar(tokens)
        except ErroSpotify:
            raise
        except Exception:
            raise ErroSpotify(
                "Não consegui guardar os tokens no cofre do Windows. A conexão não foi confirmada; não há armazenamento em texto puro."
            ) from None
        self.tokens = tokens

    def _token_request(self, dados, cancelar):
        verificar(cancelar)
        try:
            r = self.session.post(
                "https://accounts.spotify.com/api/token",
                data=dados,
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise ErroSpotify(
                "Não consegui conectar à autenticação do Spotify."
            ) from None
        verificar(cancelar)
        if r.status_code != 200:
            raise ErroSpotify(
                "Spotify recusou a autenticação. Confira Client ID, redirect URI e usuários autorizados no Dashboard.",
                local=True,
            )
        try:
            return r.json()
        except ValueError:
            raise ErroSpotify("Spotify retornou autenticação inválida.") from None

    def conectar(self, cancelar):
        client = self._client_id()
        self.cofre()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        recebido = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Não registrar códigos/query de OAuth.

            def do_GET(self):
                partes = urlsplit(self.path)
                q = parse_qs(partes.query)
                valido = partes.path == "/callback" and hmac.compare_digest(
                    q.get("state", [""])[0], state
                )
                if not valido:
                    self.send_response(400)
                    self.end_headers()
                    return
                recebido.update(
                    {
                        "code": q.get("code", [None])[0],
                        "error": q.get("error", [None])[0],
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<p>Volte ao Jarvis para conferir o resultado. Pode fechar esta janela.</p>".encode()
                )

        try:
            server = HTTPServer(("127.0.0.1", 8787), Callback)
        except OSError:
            raise ErroSpotify(
                "A porta local 8787 está ocupada. Feche outro Jarvis ou aplicativo usando essa porta."
            ) from None
        server.timeout = 0.2
        url = "https://accounts.spotify.com/authorize?" + urlencode(
            {
                "client_id": client,
                "response_type": "code",
                "redirect_uri": REDIRECT,
                "scope": SCOPES,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        try:
            verificar(cancelar)
            if not webbrowser.open(url):
                raise ErroSpotify(
                    "O Windows não abriu o navegador para autorizar o Spotify."
                )
            fim = time.monotonic() + 120
            while not recebido and time.monotonic() < fim:
                verificar(cancelar)
                server.handle_request()
            verificar(cancelar)
            if not recebido.get("code"):
                raise ErroSpotify("Autorização Spotify cancelada ou prazo encerrado.")
            dados = self._token_request(
                {
                    "grant_type": "authorization_code",
                    "client_id": client,
                    "code": recebido["code"],
                    "redirect_uri": REDIRECT,
                    "code_verifier": verifier,
                },
                cancelar,
            )
            self._guardar(dados)
            # Verifica o endpoint real de dispositivos antes de declarar a conexão utilizável.
            dispositivos = self.api("GET", "/me/player/devices", cancelar)
            if not isinstance(dispositivos, dict) or not isinstance(
                dispositivos.get("devices"), list
            ):
                raise ErroSpotify(
                    "Conta autorizada, mas não consegui validar a consulta de dispositivos Spotify."
                )
            return resultado(
                "Spotify autorizado; tokens no Gerenciador de Credenciais do Windows e acesso à lista de dispositivos verificado."
            )
        finally:
            server.server_close()

    def desconectar(self):
        self.cofre().apagar()
        self.tokens = None
        return resultado(
            "Tokens locais do Spotify removidos. Para revogar no serviço, remova o acesso no site da sua conta Spotify."
        )

    def _access(self, cancelar):
        if self.tokens is None:
            try:
                self.tokens = self.cofre().ler()
            except ErroSpotify:
                raise
            except Exception:
                raise ErroSpotify(
                    "Não foi possível acessar o cofre do Windows. Conecte novamente pelo painel.",
                    local=True,
                ) from None
        if not self.tokens or self.tokens.get("client_id") != self._client_id():
            raise ErroSpotify(
                "Spotify não conectado para este Client ID. Use Conectar Spotify.",
                local=True,
            )
        if self.tokens.get("expira", 0) <= time.time() + 30:
            dados = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self.tokens["refresh_token"],
                    "client_id": self._client_id(),
                },
                cancelar,
            )
            self._guardar(dados, self.tokens)
        return self.tokens["access_token"]

    def api(self, metodo, path, cancelar, params=None, body=None):
        verificar(cancelar)
        if path not in (
            "/search",
            "/me/player",
            "/me/player/devices",
            "/me/player/play",
            "/me/player/pause",
            "/me/player/next",
            "/me/player/previous",
            "/me/player/volume",
        ):
            raise ErroSpotify("Endpoint Spotify não permitido.")
        token = self._access(cancelar)
        try:
            r = self.session.request(
                metodo,
                "https://api.spotify.com/v1" + path,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + token},
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise ErroSpotify(
                "Falha de conexão Spotify. O resultado de uma ação enviada pode não ter sido verificado; não vou repeti-la automaticamente."
            ) from None
        verificar(cancelar)
        if r.status_code in (401, 403):
            raise ErroSpotify(
                "Spotify recusou o acesso. Confira Premium, escopos, usuários autorizados e restrições atuais do aplicativo no Dashboard.",
                local=True,
            )
        if r.status_code == 429:
            raise ErroSpotify(
                "Limite da API Spotify atingido. Aguarde antes de tentar novamente."
            )
        if r.status_code == 404:
            raise ErroSpotify(
                "Spotify não encontrou dispositivo de reprodução disponível. Abra o Spotify no PC e conecte o dispositivo.",
                local=True,
            )
        if r.status_code == 204:
            return None
        if not 200 <= r.status_code < 300:
            raise ErroSpotify(
                "Spotify não concluiu a operação. Confira disponibilidade e requisitos da sua conta."
            )
        try:
            return r.json()
        except ValueError:
            raise ErroSpotify("Resposta Spotify inválida.") from None

    def atual(self, cancelar):
        dado = self.api("GET", "/me/player", cancelar)
        if dado is None:
            return resultado(
                "Não há reprodução Spotify disponível.", tocando=False, fonte="spotify"
            )
        if not isinstance(dado, dict) or type(dado.get("is_playing")) is not bool:
            raise ErroSpotify("Spotify retornou estado de reprodução inválido.")
        item = dado.get("item") or {}
        artistas = ", ".join(
            a.get("name", "") for a in item.get("artists", []) if isinstance(a, dict)
        )
        return resultado(
            f"Spotify: {item.get('name','faixa indisponível')} · {artistas or 'artista indisponível'} · dispositivo {(dado.get('device') or {}).get('name','indisponível')}",
            tocando=dado.get("is_playing") is True,
            fonte="spotify",
            uri=item.get("uri"),
            dispositivo=dado.get("device"),
            titulo=item.get("name") or "Título indisponível",
            artista=artistas or "Artista indisponível",
        )

    def _dispositivo(self, cancelar):
        dados = self.api("GET", "/me/player/devices", cancelar)
        if not isinstance(dados, dict) or not isinstance(dados.get("devices"), list):
            raise ErroSpotify("Spotify retornou lista de dispositivos inválida.")
        devices = dados["devices"]
        configurado = os.environ.get("SPOTIFY_DEVICE_ID", "").strip()
        opcoes = [
            d
            for d in devices
            if isinstance(d, dict)
            and isinstance(d.get("id"), str)
            and not d.get("is_restricted")
            and (d["id"] == configurado if configurado else d.get("type") == "Computer")
        ]
        if not opcoes:
            raise ErroSpotify(
                "Nenhum computador Spotify disponível. Abra o aplicativo e reproduza algo manualmente. SPOTIFY_DEVICE_ID permite escolher explicitamente outro dispositivo.",
                local=True,
            )
        i = self.decisoes.escolher(
            "Qual dispositivo Spotify?",
            [d.get("name", "Dispositivo") + " · " + d.get("type", "") for d in opcoes],
            cancelar,
        )
        return opcoes[i]

    def _verificar(self, predicado, cancelar):
        fim = time.monotonic() + 6
        while time.monotonic() < fim:
            try:
                dado = self.api("GET", "/me/player", cancelar)
            except ErroSpotify:
                # A mutação já foi aceita. Falha de leitura não permite fallback/reenvio.
                raise ErroSpotify(
                    "Pedido Spotify enviado, mas o estado final ficou indisponível. Confira o aplicativo antes de repetir."
                ) from None
            if isinstance(dado, dict) and predicado(dado):
                return dado
            time.sleep(0.2)
            verificar(cancelar)
        raise ErroSpotify(
            "Spotify aceitou o pedido, mas não consegui verificar o estado final. Confira o aplicativo antes de repetir."
        )

    def tocar(self, nome, artista, cancelar):
        import re

        consulta = f"track:{nome}" + (f" artist:{artista}" if artista else "")
        dados = self.api(
            "GET",
            "/search",
            cancelar,
            params={"q": consulta, "type": "track", "limit": 8},
        )
        faixas = (dados or {}).get("tracks", {}).get("items", [])
        faixas = [
            f
            for f in faixas
            if isinstance(f, dict)
            and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", f.get("uri", ""))
            and f.get("is_playable", True)
        ]
        if not faixas:
            raise ErroSpotify(
                "Nenhuma faixa reproduzível foi encontrada para esse nome/artista."
            )
        rotulos = [
            f.get("name", "Faixa")
            + " · "
            + ", ".join(a.get("name", "") for a in f.get("artists", []))
            + " · "
            + f.get("album", {}).get("name", "")
            for f in faixas
        ]
        i = self.decisoes.escolher("Qual faixa Spotify?", rotulos, cancelar)
        faixa = faixas[i]
        device = self._dispositivo(cancelar)
        if self.antes_audio:
            self.antes_audio("spotify", True)
        self.api(
            "PUT",
            "/me/player/play",
            cancelar,
            params={"device_id": device["id"]},
            body={"uris": [faixa["uri"]]},
        )
        final = self._verificar(
            lambda d: d.get("is_playing") is True
            and (d.get("item") or {}).get("uri") == faixa["uri"]
            and (d.get("device") or {}).get("id") == device["id"],
            cancelar,
        )
        return resultado(
            f"Reprodução Spotify verificada: {rotulos[i]} · {device.get('name','dispositivo escolhido')}.",
            fonte="spotify",
            tocando=True,
            titulo=(final.get("item") or {}).get("name") or "Título indisponível",
            artista=", ".join(
                a.get("name", "")
                for a in (final.get("item") or {}).get("artists", [])
                if isinstance(a, dict)
            )
            or "Artista indisponível",
        )

    def controlar(self, acao, cancelar, percentual=None):
        if acao == "atual":
            return self.atual(cancelar)
        antes = self.api("GET", "/me/player", cancelar)
        device = self._dispositivo(cancelar)
        params = {"device_id": device["id"]}
        if acao == "volume":
            params["volume_percent"] = percentual
        path = {
            "pausar": "pause",
            "retomar": "play",
            "proxima": "next",
            "anterior": "previous",
            "volume": "volume",
        }[acao]
        if acao == "retomar" and self.antes_audio:
            self.antes_audio("spotify", True)
        self.api(
            "POST" if acao in ("proxima", "anterior") else "PUT",
            "/me/player/" + path,
            cancelar,
            params=params,
        )
        uri = ((antes or {}).get("item") or {}).get("uri")

        def confirmado(d):
            if (d.get("device") or {}).get("id") != device["id"]:
                return False
            if acao == "pausar":
                return d.get("is_playing") is False
            if acao == "retomar":
                return d.get("is_playing") is True
            if acao == "volume":
                return (d.get("device") or {}).get("volume_percent") == percentual
            return (
                bool((d.get("item") or {}).get("uri"))
                and (d.get("item") or {}).get("uri") != uri
            )

        final = self._verificar(confirmado, cancelar)
        return resultado(
            f"Controle Spotify verificado: {acao}"
            + (f" em {percentual} por cento." if acao == "volume" else "."),
            fonte="spotify",
            tocando=final.get("is_playing") is True,
            titulo=(final.get("item") or {}).get("name") or "Título indisponível",
            artista=", ".join(
                a.get("name", "")
                for a in (final.get("item") or {}).get("artists", [])
                if isinstance(a, dict)
            )
            or "Artista indisponível",
        )

    def fechar(self):
        self.session.close()
