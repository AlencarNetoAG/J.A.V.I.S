"""Responses SDK com transporte simulado; nenhuma chamada real ou chave real."""
from datetime import datetime
from decimal import Decimal
import json
import os
import threading
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from jarvis.cancelamento import Cancelado
from jarvis.cliente_openai import Conversa, ErroOpenAI, executar_ferramenta
from jarvis.comandos import interpretar
from jarvis.cotacao import Cotacao, BRASILIA


def resposta(texto="Sim, senhor."):
    return {"id":"resp_teste","object":"response","created_at":0,"model":"gpt-4.1-mini",
            "output":[{"type":"message","id":"msg_teste","role":"assistant","status":"completed",
                       "content":[{"type":"output_text","text":texto,"annotations":[]}]}]}


class ComandosTests(unittest.TestCase):
    def test_prioridade_e_palavra_inteira(self):
        self.assertEqual(interpretar("JARVIS, explique uma função"), ("pergunta","explique uma função"))
        self.assertEqual(interpretar("Jarvis!"),("aguardar",""))
        self.assertEqual(interpretar("Bom dia, Jarvis! explique uma função"),("bom_dia",""))
        for texto in ("jarvisinho explique", "superjarvis", "o que é uma função?"):
            self.assertEqual(interpretar(texto)[0],"ignorar")


class OpenAITests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"OPENAI_API_KEY":"chave-sintetica-de-teste","OPENAI_MODEL":"gpt-4.1-mini"})
        self.env.start();self.addCleanup(self.env.stop)
        p=patch("jarvis.cliente_openai.load_dotenv");p.start();self.addCleanup(p.stop)

    def criar(self, handler):
        conversa=Conversa()
        conversa.client=OpenAI(api_key="chave-sintetica-de-teste",max_retries=0,
                              http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(conversa.fechar)
        return conversa

    def test_sdk_responses_e_historico_limitado(self):
        corpos=[]
        def handler(request):
            self.assertEqual(request.url.path,"/v1/responses")
            corpos.append(json.loads(request.content))
            return httpx.Response(200,json=resposta())
        c=self.criar(handler)
        for i in range(8):self.assertEqual(c.perguntar(f"Pergunta {i}"),"Sim, senhor.")
        self.assertEqual(len(c.historico),12)
        self.assertEqual(c.historico[0]["content"],"Pergunta 2")
        self.assertFalse(corpos[-1]["store"])
        self.assertEqual(corpos[-1]["max_output_tokens"],400)
        self.assertIn("não tem acesso",corpos[-1]["instructions"])
        c.limpar();self.assertEqual(c.historico,[])

    def test_function_call_usa_cotacao_real_do_modulo(self):
        contador=[]
        def handler(request):
            body=json.loads(request.content);contador.append(body)
            if len(contador)==1:
                return httpx.Response(200,json={"id":"resp_tool","object":"response","created_at":0,"model":"gpt-4.1-mini",
                    "output":[{"type":"function_call","id":"fc1","call_id":"call1","name":"cotacao_dolar","arguments":"{}"}]})
            resultado=next(i for i in body["input"] if i.get("type")=="function_call_output")
            self.assertEqual(json.loads(resultado["output"])["USD_BRL"],"5.25")
            return httpx.Response(200,json=resposta("Cotação da fonte, senhor."))
        c=self.criar(handler)
        with patch("jarvis.cliente_openai.consultar_cotacao",return_value=Cotacao(Decimal("5.25"),datetime(2026,10,7,tzinfo=BRASILIA))) as consulta:
            self.assertIn("Cotação",c.perguntar("Qual o dólar?"))
        consulta.assert_called_once();self.assertEqual(len(contador),2)

    def test_chave_ausente_sem_rede(self):
        c=Conversa()
        with patch.dict(os.environ,{"OPENAI_API_KEY":""}),self.assertRaises(ErroOpenAI):c.perguntar("Olá")
        self.assertIsNone(c.client)

    def test_erros_nao_expoem_chave_ou_corpo(self):
        for status in (401,429,500):
            c=self.criar(lambda request:httpx.Response(status,json={"error":{"message":"detalhes sensíveis não devem aparecer","type":"error"}}))
            with self.subTest(status=status),self.assertRaises(ErroOpenAI) as ctx:c.perguntar("Olá")
            self.assertNotIn("sensíveis",str(ctx.exception))
            self.assertNotIn("chave-sintetica",str(ctx.exception))
            self.assertFalse(c.historico)
        def sem_internet(request):raise httpx.ConnectError("falha",request=request)
        with self.assertRaises(ErroOpenAI):self.criar(sem_internet).perguntar("Olá")

    def test_cancelamento_descarta_resposta_e_historico(self):
        cancel=threading.Event()
        def handler(request):
            cancel.set();return httpx.Response(200,json=resposta())
        c=self.criar(handler)
        with self.assertRaises(Cancelado):c.perguntar("Olá",cancel)
        self.assertFalse(c.historico)

    def test_ferramenta_nao_executa_comando(self):
        self.assertIn("não implementada",executar_ferramenta("executar_terminal","{}"))
        self.assertIn("não suportados",json.loads(executar_ferramenta("cotacao_dolar",'{"comando":"echo teste"}'))["erro"])


if __name__=="__main__":unittest.main()
