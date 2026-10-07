"""Responses API oficial; envia só texto, histórico limitado e ferramentas locais."""
import json
import os
from dotenv import load_dotenv
from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

from .cancelamento import verificar
from .configuracoes import RAIZ
from .clima import consultar_clima
from .cotacao import consultar_cotacao

PERSONALIDADE = (
    "Você é Jarvis, um assistente pessoal. Responda em português brasileiro, "
    "com clareza e frases adequadas para serem faladas. Chame o usuário de senhor "
    "naturalmente. Seja cordial, direto e admita quando não souber. "
    "Prefira respostas curtas, até 120 palavras. Você não tem acesso à conta, memória "
    "ou conversas do ChatGPT do usuário. Não execute comandos. Para clima atual de "
    "Salgueiro-PE e cotação USD/BRL use as ferramentas. Para outras informações atuais, "
    "diga que não dispõe de uma fonte atual. Não invente valores nem fontes. "
    "Informe a atualização da ferramenta e trate clima como estimativa de modelo."
)
FERRAMENTAS = [{"type": "function", "name": nome, "description": descricao,
                "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                "strict": True} for nome, descricao in (
                    ("clima_salgueiro", "Consulta condições atuais estimadas de Salgueiro, Pernambuco; pode retornar indisponibilidade."),
                    ("cotacao_dolar", "Consulta última cotação de compra USD/BRL e data da fonte; não é preço de banco."))]


class ErroOpenAI(Exception):
    pass


def executar_ferramenta(nome: str, argumentos: str) -> str:
    try:
        if json.loads(argumentos) != {}:
            return json.dumps({"erro": "Argumentos não suportados."})
        if nome == "clima_salgueiro":
            dado = consultar_clima()
            resultado = {"cidade": "Salgueiro, Pernambuco, Brasil", "temperatura_celsius": str(dado.temperatura),
                         "condicao": dado.condicao, "fonte": dado.fonte, "atualizacao": dado.atualizacao.isoformat()}
        elif nome == "cotacao_dolar":
            dado = consultar_cotacao()
            resultado = {"USD_BRL": str(dado.valor), "tipo": dado.tipo, "fonte": dado.fonte, "atualizacao": dado.atualizacao.isoformat()}
        else:
            resultado = {"erro": "Ferramenta não implementada."}
        return json.dumps(resultado, ensure_ascii=False)
    except Exception:
        # Nunca repassar traceback, chave, URL autenticada ou detalhes de SDK.
        return json.dumps({"erro": "Fonte indisponível ou dados inválidos; não invente valores."})


class Conversa:
    def __init__(self):
        load_dotenv(RAIZ / ".env", override=False)
        self.historico = []
        self.client = None

    def limpar(self):
        self.historico.clear()

    def perguntar(self, pergunta: str, cancelar=None) -> str:
        verificar(cancelar)
        chave = os.environ.get("OPENAI_API_KEY", "").strip()
        if not chave:
            raise ErroOpenAI("Configure OPENAI_API_KEY no arquivo .env local. A saudação bom dia continua disponível.")
        if self.client is None:
            self.client = OpenAI(api_key=chave, timeout=20.0, max_retries=0)
        entrada = [*self.historico, {"role": "user", "content": pergunta[:4000]}]
        try:
            for _ in range(3):
                verificar(cancelar)
                resposta = self.client.responses.create(
                    model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    instructions=PERSONALIDADE, input=entrada, tools=FERRAMENTAS,
                    max_output_tokens=400, store=False,
                    parallel_tool_calls=False,
                )
                verificar(cancelar)
                chamadas = [item for item in resposta.output if item.type == "function_call"]
                if not chamadas:
                    texto = resposta.output_text.strip()
                    if not texto:
                        raise ErroOpenAI("A API não retornou texto. Tente uma pergunta mais curta.")
                    self.historico.extend([{"role": "user", "content": pergunta[:4000]}, {"role": "assistant", "content": texto}])
                    self.historico = self.historico[-12:]  # Seis pares, só nesta sessão.
                    return texto
                entrada.extend(resposta.output)
                for chamada in chamadas[:2]:
                    verificar(cancelar)
                    resultado = executar_ferramenta(chamada.name, chamada.arguments)
                    verificar(cancelar)
                    entrada.append({"type": "function_call_output", "call_id": chamada.call_id, "output": resultado})
            raise ErroOpenAI("A consulta excedeu o limite de etapas. Tente novamente.")
        except AuthenticationError:
            raise ErroOpenAI("A chave da OpenAI não foi aceita. Confira seu .env local.") from None
        except RateLimitError:
            raise ErroOpenAI("Limite ou saldo da API atingido. Confira cobrança e limites na plataforma OpenAI.") from None
        except APIConnectionError:
            raise ErroOpenAI("Não consegui conectar à OpenAI. Confira internet e tente novamente.") from None
        except APIStatusError:
            raise ErroOpenAI("A OpenAI não concluiu a solicitação. Confira o modelo e tente novamente.") from None

    def fechar(self):
        if self.client is not None:
            self.client.close()
