"""Única camada de execução local: validação, permissões, resultados e auditoria."""

import logging
from .aplicativos import Aplicativos
from .arquivos import Arquivos, pastas_pessoais
from .base import ErroFerramenta, HistoricoAcoes, resultado
from .esquemas import REGISTRO, validar
from .spotify import Spotify, ErroSpotify
from .windows import Windows
from ..cancelamento import Cancelado, Eventos, verificar
from ..configuracoes import RAIZ
from ..reconhecimento import normalizar


class ControlePC:
    def __init__(
        self,
        config,
        decisoes,
        cancelar_acao,
        local=None,
        windows=None,
        spotify=None,
        historico=None,
        publicar=None,
    ):
        self.publicar = publicar
        self.config = config
        self.decisoes = decisoes
        self.cancelar_acao = cancelar_acao
        self.local = local
        self.windows = windows or Windows()
        self.spotify = spotify or Spotify(decisoes)
        self.apps = Aplicativos(self.windows, decisoes)
        self.arquivos = Arquivos(
            lambda: [*pastas_pessoais(), *self.config().pastas_autorizadas],
            decisoes,
            self.windows.documento,
            autorizar=lambda: self.permitir("arquivos"),
        )
        self.historico = historico or HistoricoAcoes(RAIZ / "acoes.local.jsonl")

    def esquemas(self):
        return [v["schema"] for v in REGISTRO.values()]

    def permitir(self, categoria):
        c = self.config()
        if c.pc_suspenso:
            raise ErroFerramenta(
                "Controle do PC suspenso. Retome pelo botão da interface."
            )
        if not c.permissoes_pc.get(categoria, False):
            raise ErroFerramenta(
                f"Categoria {categoria} desativada no painel de permissões."
            )

    def _spotify(self, acao, cancelar):
        self.permitir("spotify")
        try:
            return self.spotify.controlar(acao, cancelar)
        except ErroSpotify as erro:
            if not erro.local:
                raise
            try:
                retorno = self.windows.midia(acao, "spotify", cancelar, self.decisoes)
            except ErroFerramenta as local:
                raise ErroSpotify(
                    str(erro) + " Controle local indisponível: " + str(local),
                    local=True,
                ) from None
            retorno["mensagem"] = (
                "Web API indisponível; usado controle local do Spotify no Windows. "
                + retorno["mensagem"]
            )
            return retorno

    def _fontes(self, cancelar, acao):
        opcoes = []
        estados = (
            ("tocando",)
            if acao == "pausar"
            else ("pausada",) if acao == "retomar" else ("tocando", "pausada")
        )
        if self.local and self.local("estado", None, cancelar).get("estado") in estados:
            opcoes.append("local")
        sessoes = self.windows.fontes_midia()

        def relevante(s):
            return (
                s["tocando"]
                if acao == "pausar"
                else (
                    s["pausada"]
                    if acao == "retomar"
                    else (s["tocando"] or s["pausada"])
                )
            )

        if any("spotify" in s["id"].casefold() and relevante(s) for s in sessoes):
            opcoes.append("spotify")
        if any("spotify" not in s["id"].casefold() and relevante(s) for s in sessoes):
            opcoes.append("sistema")
        return opcoes

    def _audio(self, acao, fonte, cancelar):
        if fonte == "ativa":
            # Não tratar uma categoria Spotify desativada como ausência de outra fonte.
            fontes = self._fontes(cancelar, acao)
            if not fontes:
                raise ErroFerramenta(
                    "Nenhuma fonte de música local identificada; diga MP3 local ou Spotify explicitamente."
                )
            fonte = fontes[
                self.decisoes.escolher(
                    "Qual fonte de música?",
                    ["MP3 da saudação" if f == "local" else f for f in fontes],
                    cancelar,
                )
            ]
        if fonte == "local":
            if not self.local:
                raise ErroFerramenta(
                    "Controles do MP3 estão disponíveis na interface desktop."
                )
            if acao in ("proxima", "anterior"):
                raise ErroFerramenta(
                    "O MP3 da saudação é uma faixa única; não há próxima/anterior."
                )
            return self.local(acao, None, cancelar)
        if fonte == "spotify":
            return self._spotify(acao, cancelar)
        return self.windows.midia(acao, "sistema", cancelar, self.decisoes)

    def executar(self, nome, argumentos, cancelar=None):
        categoria = REGISTRO.get(nome, {}).get("categoria", "desconhecida")
        evento = (
            Eventos(cancelar, self.cancelar_acao)
            if cancelar is not None
            else self.cancelar_acao
        )
        try:
            args = validar(nome, argumentos)
            verificar(evento)
            self.permitir(categoria)
            if self.publicar:
                self.publicar(
                    {
                        "ferramenta": nome,
                        "categoria": categoria,
                        "status": "em andamento",
                    }
                )
            a = self.arquivos
            if nome == "arquivo_buscar":
                r = a.buscar(args["nome"], args["pasta"], evento)
            elif nome == "arquivo_listar":
                r = a.listar(args["pasta"], evento)
            elif nome == "arquivo_abrir":
                r = a.abrir(args["alvo"], evento)
            elif nome == "arquivo_ler":
                r = a.ler(args["alvo"], evento)
            elif nome == "arquivo_criar":
                r = a.criar(args["destino"], args["conteudo"], evento)
            elif nome in ("arquivo_copiar", "arquivo_mover"):
                r = a.copiar(
                    args["origem"],
                    args["destino"],
                    evento,
                    mover=nome == "arquivo_mover",
                )
            elif nome == "arquivo_renomear":
                r = a.renomear(args["alvo"], args["novo_nome"], evento)
            elif nome == "arquivo_excluir":
                r = a.excluir(args["alvo"], evento)
            elif nome in ("aplicativo_abrir", "aplicativo_focar", "spotify_abrir"):
                self.permitir("aplicativos")
                app = self.apps.resolver(
                    "Spotify" if nome == "spotify_abrir" else args["nome"], evento
                )
                if (
                    normalizar(app["nome"]) == "spotify"
                    or app["caminho"].casefold().startswith("spotify:")
                    or "spotify.exe" in app["caminho"].casefold()
                    or any("spotify" in p.casefold() for p in app.get("processos", []))
                ):
                    self.permitir("spotify")
                r = self.windows.aplicativo(app, evento, nome == "aplicativo_focar")
            elif nome == "audio_controlar":
                r = self._audio(args["acao"], args["fonte"], evento)
            elif nome == "audio_volume":
                fonte = args["fonte"]
                if fonte == "sistema":
                    r = self.windows.volume(args["percentual"], evento)
                elif fonte == "spotify":
                    self.permitir("spotify")
                    r = self.spotify.controlar("volume", evento, args["percentual"])
                elif self.local:
                    r = self.local("volume", args["percentual"], evento)
                else:
                    raise ErroFerramenta("Volume do MP3 requer a interface desktop.")
            elif nome == "spotify_tocar":
                r = self.spotify.tocar(args["nome"], args["artista"], evento)
            elif nome == "spotify_controlar":
                r = self._spotify(args["acao"], evento)
            else:
                raise ErroFerramenta("Ferramenta não implementada.")
            verificar(evento)
        except Cancelado:
            if self.publicar:
                self.publicar(
                    {
                        "ferramenta": nome,
                        "categoria": categoria,
                        "status": "cancelado",
                        "mensagem": "Etapas futuras canceladas; alterações concluídas não foram desfeitas.",
                    }
                )
            self.historico.registrar(
                nome if nome in REGISTRO else "desconhecida", categoria, "cancelado"
            )
            raise
        except ErroFerramenta as erro:
            r = resultado(
                str(erro),
                "negado",
                audio_nao_executado=isinstance(erro, ErroSpotify) and erro.local,
            )
        except (OSError, ValueError, UnicodeError) as erro:
            logging.getLogger(__name__).warning(
                "Ferramenta %s falhou: %s",
                nome if nome in REGISTRO else "desconhecida",
                type(erro).__name__,
            )
            r = resultado(
                "Não foi possível concluir/verificar a operação. Confira acesso, formato e permissões do Windows.",
                "falha",
            )
        except Exception as erro:
            logging.getLogger(__name__).warning(
                "Integração %s indisponível: %s", categoria, type(erro).__name__
            )
            r = resultado(
                "Integração indisponível neste computador. Confira dependências do Windows e configuração; a ação não foi confirmada.",
                "falha",
            )
        if self.publicar:
            self.publicar(
                {
                    "ferramenta": nome,
                    "categoria": categoria,
                    **{
                        k: v
                        for k, v in r.items()
                        if k
                        in (
                            "status",
                            "mensagem",
                            "fonte",
                            "tocando",
                            "audio_nao_executado",
                        )
                    },
                }
            )
        self.historico.registrar(
            nome if nome in REGISTRO else "desconhecida", categoria, r["status"]
        )
        return r

    def conta_spotify(self, nome, cancelar):
        """Ações exclusivas do painel: modelo não pode iniciar consentimento OAuth."""
        if nome not in ("spotify_conectar", "spotify_desconectar"):
            raise ErroFerramenta("Ação de conta inválida.")
        evento = Eventos(cancelar, self.cancelar_acao)
        status = "falha"
        try:
            verificar(evento)
            self.permitir("spotify")
            if self.publicar:
                self.publicar(
                    {
                        "ferramenta": nome,
                        "categoria": "spotify",
                        "status": "em andamento",
                    }
                )
            r = (
                self.spotify.conectar(evento)
                if nome == "spotify_conectar"
                else self.spotify.desconectar()
            )
            verificar(evento)
            status = r["status"]
            return r
        except Cancelado:
            status = "cancelado"
            raise
        except ErroFerramenta:
            status = "negado"
            raise
        finally:
            self.historico.registrar(nome, "spotify", status)
            if self.publicar:
                self.publicar(
                    {"ferramenta": nome, "categoria": "spotify", "status": status}
                )

    def fechar(self):
        self.spotify.fechar()
