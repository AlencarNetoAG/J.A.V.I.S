# Jarvis para Windows

![Painel desktop do Jarvis, renderizado em teste Qt offscreen](assets/painel.png)

Aplicação desktop em Python/PySide6 com painel escuro, anéis animados, relógio de Salgueiro, cartões de clima/dólar e histórico de conversa. O reconhecimento Whisper é local. A API da OpenAI recebe texto somente após uma pergunta aceita.

- **“Jarvis, explique uma função de segundo grau”**: pergunta na mesma frase.
- **“Jarvis”**: responde “Sim, senhor?” e espera a pergunta. O prazo e a duração máxima da captura são configuráveis.
- **“bom dia Jarvis”**: tem prioridade depois de concluir a frase; música local, clima, horário de Recife e dólar. Funciona **sem chave da OpenAI**.
- Perguntas por texto funcionam no painel e no terminal. “Limpar conversa” remove o contexto local desta sessão; não apaga dados do serviço externo.

A música toca apenas na saudação. O reconhecimento permanece pausado enquanto o próprio Jarvis fala ou toca música. O botão **Parar** desativa o microfone, interrompe áudios e descarta resultados cancelados. Uma chamada de rede ou inferência já em andamento pode terminar até seu timeout; não aparecerá como resposta depois do cancelamento.

## 1. Preparar o Python

Recomendado: **Windows 10/11, Python 3.11 de 64 bits**, microfone e alto-falante/fone. Instale o Python pelo [site oficial](https://www.python.org/downloads/windows/), incluindo o Python Launcher (`py`).

Abra o **PowerShell** na pasta do projeto, onde estão `main.py` e `requirements.txt`. Se necessário, use `cd "C:\caminho\para\J.A.V.I.S"`, substituindo pelo seu caminho real. Execute:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Os comandos usam diretamente o Python do ambiente virtual. Não é necessário ativá-lo nem alterar a política de execução do PowerShell. Internet é necessária para instalar dependências e baixar o modelo; depois, reconhecimento e síntese funcionam localmente.

Se já tem o ambiente da versão anterior, **não recrie a pasta `.venv`**. Execute apenas o comando de instalação com `-r requirements.txt` para incluir as novas dependências, incluindo PySide6, SDK OpenAI e python-dotenv. Use Python **3.11 x64**, como na versão que já funcionou; Python 3.14 não é suportado por estas versões de dependências.

## 2. Abrir o painel

Depois de instalar, dê dois cliques em **`iniciar_jarvis.bat`**, ou execute na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe main.py
```

O microfone começa **desativado**. Digite `bom dia Jarvis` e clique em **Enviar** para testar a saudação. O modelo só é carregado após uma frase com energia suficiente ser capturada, inclusive no teste do microfone. Os cartões mostram “Ainda não consultado”, “Consultando” ou “Indisponível”, sem números fictícios. O histórico mostra pergunta e resposta; o medidor usa a energia captada de verdade no microfone, e fica zerado durante a reprodução local. Ele não mede amplitude dos alto-falantes.

**Configurações** permite listar/selecionar microfone e voz instalados, velocidade, música, volume, modelo Whisper, limiar, duração máxima, espera pela pergunta e reduzir movimento. A enumeração dos dispositivos roda fora da thread da interface. As preferências ficam em `config.local.json` (ignorado no Git), sem chave da API. Ao aplicar configurações, o microfone fica desligado; ative-o de novo quando desejar.

As animações são leves e podem ser desligadas com **Reduzir movimento**. O campo de texto e os botões ficam fixos no rodapé; o painel superior tem rolagem quando a janela é pequena. Durante uma consulta, Enviar é bloqueado para evitar operações simultâneas; Parar e Limpar permanecem disponíveis. A palavra de ativação é verificada como palavra inteira; `jarvisinho` não ativa. Aguarde três segundos depois de uma sequência por voz para evitar duplicatas.

## Conversa com a OpenAI: configurar localmente

A assinatura do **ChatGPT não inclui automaticamente créditos da API**. Você precisa de uma conta/chave de API e cobrança/saldo disponíveis na [plataforma OpenAI](https://platform.openai.com/). Confira os [preços da API](https://openai.com/api/pricing/), habilite limites adequados e não compartilhe a chave.

Na pasta do projeto, crie seu `.env` a partir do exemplo:

```powershell
Copy-Item .env.example .env
notepad .env
```

Faça essa cópia uma vez; se `.env` já existir, abra-o sem sobrescrever. Preencha **somente no seu PC**:

```dotenv
OPENAI_API_KEY=sua_chave_local
OPENAI_MODEL=gpt-4.1-mini
```

O exemplo acima é um marcador, não uma chave funcional. Salve como `.env` (não `.env.txt`) e reinicie o Jarvis. O programa também aceita variáveis já configuradas no processo, que têm prioridade sobre `.env`. A chave não aparece no painel ou nas preferências e os erros da API são resumidos sem detalhes sensíveis. **Nunca envie sua chave pelo chat, publique `.env` ou inclua-o em um ZIP.** `.env` e arquivos similares estão ignorados no Git.

Escolhemos `gpt-4.1-mini`, um modelo geral com suporte a ferramentas, com bom equilíbrio entre custo e respostas curtas; o identificador consta nos tipos oficiais do SDK. A disponibilidade para sua conta precisa ser confirmada por uma chamada real. Troque `OPENAI_MODEL` se necessário. Usamos o [SDK oficial](https://github.com/openai/openai-python) e a [Responses API](https://developers.openai.com/api/reference/resources/responses), sem reaproveitar automaticamente conversas/memória de sua conta ChatGPT.

O histórico enviado fica limitado aos **seis últimos pares** de pergunta/resposta; perguntas são limitadas a 4.000 caracteres e cada chamada a **400 tokens de saída**. Não há reenvio automático em erros (`max_retries=0`); timeout de SDK de 20 segundos. Uma resposta com ferramentas pode precisar de até três chamadas, com cobrança de entrada/saída em cada etapa. Dados da rotina bom dia usam as APIs públicas e não consomem OpenAI.

As únicas ferramentas permitidas à OpenAI são clima atual de Salgueiro e cotação de compra USD/BRL, reutilizando validações/fontes deste projeto. Elas são consultadas quando o modelo solicita esses dados. Não há busca geral na web nem execução de comandos de terminal. Para outros assuntos que exijam atualização, o assistente recebe instrução para admitir falta de fonte atual. Resultados meteorológicos antigos são rejeitados; datas da cotação são fornecidas com o resultado. O modelo pode cometer erros: fontes e timestamps da saudação estão nos cartões.

`store=False` desativa o armazenamento de respostas para recuperação via API; não significa ausência de retenção no provedor. Consulte as [políticas de dados da API](https://platform.openai.com/docs/guides/your-data). Perguntas/transcrições e histórico limitado são enviados à OpenAI; o áudio ambiente **não é enviado**, não é gravado em disco e não existe transcrição externa nesta versão. Sem chave, o painel, reconhecimento e a saudação continuam disponíveis; perguntas gerais mostram aviso de configuração.

## Testar primeiro sem microfone

Instale uma voz **Português (Brasil)** nas configurações de idioma/fala do Windows. No Windows 11, procure **Configurações → Hora e idioma → Fala → Gerenciar vozes → Adicionar vozes**. Os nomes dos menus variam conforme a versão. O projeto usa as vozes locais **SAPI5**, acessíveis ao Python; algumas vozes “naturais” exclusivas de outros aplicativos podem não aparecer. Reinicie o Jarvis depois da instalação.

```powershell
.\.venv\Scripts\python.exe main.py --texto
```

Digite `bom dia Jarvis` e pressione Enter. O Jarvis executa a sequência de música, consultas e fala. Digite `sair` ou use Ctrl+C para encerrar. Esse modo não carrega Whisper nem abre o microfone. Para testar só horário, consultas e terminal, **sem nenhum áudio**:

```powershell
.\.venv\Scripts\python.exe main.py --texto --sem-voz --sem-musica
```

Os dados nunca são inventados. Quando um serviço falha, o Jarvis informa o horário e os dados disponíveis, acrescentando um aviso para o serviço indisponível. A mensagem da cotação continua sendo:

> Bom dia, senhor. Não consegui consultar a cotação do dólar agora. Tente novamente em instantes.

Na saudação completa, “Bom dia, senhor” aparece uma só vez. Uma falha do clima não impede a cotação, e uma falha da cotação não impede o clima.

## Música local

Coloque seu arquivo, obtido legitimamente, em:

```text
J.A.V.I.S/
  assets/
    highway_to_hell.mp3
```

**O projeto não inclui nem baixa a música.** O MP3 é ignorado pelo Git. Se estiver ausente, inválido ou a saída de áudio falhar, haverá um aviso no terminal e a saudação continuará.

Para mudar o caminho e o volume:

```powershell
.\.venv\Scripts\python.exe main.py --texto --musica "C:\Musicas\highway_to_hell.mp3" --volume 0.15
```

O volume vai de `0` (mudo) a `1` (máximo); o padrão é `0.12`, ou 12%. Durante a fala, cai para 35% do volume escolhido, limitado a 8% do máximo. Após a resposta completa, o volume reduz gradualmente por até 1,5 segundo até parar. A música toca em paralelo às consultas e à voz; não é necessário esperar a faixa inteira. Não há repetição automática da faixa.

Para executar sem música, use `--sem-musica`. **`--sem-voz` desativa somente a fala**, preservando a música. O caminho padrão é relativo à pasta do projeto; um caminho personalizado relativo é resolvido a partir da pasta onde você executa o comando.

## 3. Modelo de reconhecimento local

Usamos **Whisper multilíngue**, executado no próprio PC pelo [faster-whisper](https://github.com/SYSTRAN/faster-whisper), sem enviar áudio a um serviço externo. O modelo padrão é `tiny`, com pesos de aproximadamente 75 MB, disponível em [Systran/faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny). Reserve algumas centenas de MB para modelo e dependências e, de preferência, ao menos 4 GB de RAM no PC. Não precisa de placa de vídeo: usamos CPU e cálculo `int8`.

A primeira transcrição baixa o modelo automaticamente para `modelos/`. Durante o download, a captura permanece fechada; a velocidade depende da internet. Depois os arquivos são reutilizados. Se quiser preparar o modelo antes, sem abrir o microfone, execute **na pasta do projeto**:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8', cpu_threads=2, download_root='modelos'); print('Modelo pronto.')"
```

O reconhecimento funciona sem internet depois que todos os arquivos do modelo estiverem disponíveis; câmbio e clima continuam exigindo internet. Para garantir que não haja sequer uma tentativa de atualizar o modelo em rede durante a execução, depois do download você pode definir `$env:HF_HUB_OFFLINE='1'` no PowerShell. Para voltar a permitir downloads: `Remove-Item Env:HF_HUB_OFFLINE`.

Fale com clareza, em ambiente silencioso, e faça uma pausa de cerca de um segundo ao terminar a frase. A qualidade e o tempo da transcrição dependem do microfone e do processador. O modelo `base` é maior e pode melhorar a precisão; use `--modelo base` para baixá-lo e selecioná-lo. Uma pasta local de modelo convertido para faster-whisper também pode ser informada.

## 4. Executar com microfone

```powershell
.\.venv\Scripts\python.exe main.py
```

Na janela, clique **Ativar microfone**. Fique em silêncio por um segundo durante a calibração e aguarde o estado **Ouvindo**. A primeira transcrição pode demorar para baixar/carregar o modelo. Você pode dizer “Jarvis, explique uma função”, apenas “Jarvis” para ouvir “Sim, senhor?”, ou “bom dia Jarvis” para a saudação prioritária.

Diga **“bom dia Jarvis”**. Espere a resposta terminar e pelo menos três segundos antes de uma nova ativação. Maiúsculas, espaços, acentos e pontuação são normalizados. Só frases completas transcritas acionam a consulta. A captura usa blocos curtos, detecta volume e encerra a frase após um segundo de silêncio ou a duração máxima configurada (padrão: 12 segundos de áudio). Um filtro local de atividade de voz também ajuda a descartar silêncio.

O microfone é fechado antes da transcrição e permanece fechado durante **toda** a sequência: música, consultas, fala e redução final do volume. Só é reaberto após todos os áudios terminarem. O áudio anterior é descartado. Há uma janela de três segundos após a sequência para evitar ativações duplicadas. O worker executa uma operação por vez, sem sobrepor músicas ou respostas, e não mantém escuta depois de encerrado. Na janela use Parar; no terminal, Ctrl+C.

Ctrl+C interrompe a fala e a música, incluindo durante a redução do volume. Se houver uma consulta em andamento, os áudios são interrompidos imediatamente, mas o processo pode levar alguns segundos para terminar enquanto a requisição em outra thread atinge seu timeout.

### Velocidade, modelo e dispositivo

```powershell
.\.venv\Scripts\python.exe main.py --velocidade 150
.\.venv\Scripts\python.exe main.py --modelo base
```

A velocidade padrão da versão desktop é 150; aceita de 80 a 300. Listar dispositivos de áudio:

```powershell
.\.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"
```

Use o índice de um dispositivo com entrada de áudio:

```powershell
.\.venv\Scripts\python.exe main.py --microfone 1
```

Listar vozes que o Python consegue usar:

```powershell
.\.venv\Scripts\python.exe -c "import pyttsx3; e=pyttsx3.init('sapi5'); [print(v.id, v.name, v.languages) for v in e.getProperty('voices')]; e.stop()"
```

O Jarvis prioriza português brasileiro; se só houver outra voz portuguesa, usará essa voz. Para escolher explicitamente, copie um identificador da lista:

```powershell
.\.venv\Scripts\python.exe main.py --texto --voz "IDENTIFICADOR_DA_VOZ" --velocidade 150
```

## Horário, clima e fontes

**Horário:** o Jarvis usa `ZoneInfo("America/Recife")`, com `tzdata` instalado para Windows. Usa o relógio do PC como referência e converte para o fuso de Salgueiro independentemente do fuso escolhido no Windows. Mantenha a data/hora do PC sincronizada. Fala horas/minutos por extenso, incluindo “uma hora”, “duas horas”, “meio-dia” e “meia-noite”. O horário é calculado imediatamente antes de montar a resposta, após as consultas.

**Clima:** [Open-Meteo](https://open-meteo.com/en/docs), API pública sem chave para uso pessoal não comercial. A cada ativação:

1. Consulta a [API de geocodificação](https://open-meteo.com/en/docs/geocoding-api) e seleciona a **cidade** `Salgueiro`, estado `Pernambuco`, país `BR`, fuso `America/Recife`. Exclui aeroporto e localidades homônimas. A consulta real confirmou a cidade em latitude **−8,07417** e longitude **−39,11917**.
2. Usa essas coordenadas na API `https://api.open-meteo.com/v1/forecast`, solicitando **`current=temperature_2m,weather_code`**, em Celsius. Apesar do nome `forecast` no endereço, utiliza os campos de condições **atuais**, sem consultar máximas, mínimas ou previsão diária.
3. Valida localização da célula da grade, unidades, temperatura, código WMO e timestamp. Códigos são traduzidos para português. Dados com mais de **90 minutos** ou mais de **5 minutos no futuro** são rejeitados; não são apresentados como clima atual. Nenhum dado em cache é usado como reserva.

As condições atuais do Open-Meteo são **estimativas de modelos meteorológicos**, baseadas em dados de intervalos de 15 minutos; não são uma medição direta de termômetro/estação em Salgueiro. O horário exibido é o instante meteorológico representado em `current.time`, não o momento em que baixamos a resposta nem o horário de emissão do modelo. A célula da grade pode diferir um pouco das coordenadas centrais da cidade.

O terminal exibe cidade/estado/país confirmados, coordenadas, temperatura, condição traduzida, fonte e data/hora dos dados em `America/Recife`. Temperatura é pronunciada com até uma casa decimal, arredondada pelo critério comercial. O timestamp Unix é interpretado em UTC e convertido para Recife.

**Consultas paralelas:** dólar e clima são executados em duas threads. Confirmar a cidade e buscar o clima são etapas sequenciais da thread meteorológica. Câmbio mantém timeout de conexão de 5 segundos e leitura de 10; cada requisição de clima/geocodificação usa 3 e 5 segundos. Esses limites restringem conexão e espera pela leitura, não um prazo absoluto de toda a sequência. HTTPS e verificação de certificados permanecem habilitados.

## Cotação e privacidade

- Fonte: **AwesomeAPI**, [documentação pública de moedas](https://docs.awesomeapi.com.br/api-de-moedas).
- Requisição: `GET https://economia.awesomeapi.com.br/json/last/USD-BRL` a cada ativação aceita, sem cache ou valor de reserva.
- Campo usado: **`bid` (compra)** do par `USDBRL`. É uma referência de mercado, não o preço final que um banco cobra ao vender dólar. Spread, IOF e tarifas não são calculados.
- O terminal mostra o valor original, fonte, tipo e data/hora da fonte. O campo Unix `timestamp` é convertido para horário de Brasília (UTC−03:00); a data é comparada com o dia atual nesse fuso.
- A voz arredonda para dois centavos decimais pelo critério comercial (`ROUND_HALF_UP`) e fala reais e centavos por extenso. Se a fonte não tiver atualização do dia, também fala a data da última atualização. Isso pode acontecer em fins de semana/feriados. O programa não inventa uma cotação atual nem afirma ser uma taxa garantida para negociação.
- HTTPS e verificação TLS permanecem habilitados; há timeout de conexão de 5 segundos e de leitura de 10 segundos. Respostas HTTP inesperadas, JSON inválido, moeda errada, valores não positivos/não finitos e datas inválidas são tratados como falha. O timeout de leitura limita a espera por dados, não um prazo absoluto de toda a execução.
- Internet é necessária **para câmbio e clima**. Nenhum áudio é enviado às APIs ou a um serviço de reconhecimento. Pequenos blocos de áudio ficam temporariamente em memória e são descartados; não são criados arquivos de gravação. A música é lida somente do arquivo local indicado.

## Problemas comuns

**Microfone/permissão:** no Windows, habilite acesso ao microfone para aplicativos da área de trabalho em Configurações → Privacidade e segurança → Microfone. Confira o dispositivo padrão e se outro programa o está usando exclusivamente. Se o dispositivo falhar ou for desconectado, a escuta é desativada com aviso; reconecte, atualize a lista, selecione e clique em Ativar microfone novamente. Falhas das consultas não desativam a escuta. O botão Parar continua disponível.

**Modelo não carrega:** confira a internet no primeiro uso e a pasta `modelos/`. Se usar `--modelo` com um caminho, ele deve conter um modelo convertido para faster-whisper, com `model.bin`, `config.json` e demais recursos. Não use um modelo Vosk nem um arquivo ZIP.

**Erro de DLL na instalação/execução:** se aparecer `DLL load failed`, confira se Python e Windows são de 64 bits e instale o [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe), pelo site da Microsoft. Reinicie o terminal e tente novamente.

**Não reconhece Jarvis:** use um ambiente silencioso e uma pausa após a frase. Confira primeiro `--texto`, que testa câmbio e fala independentemente do reconhecimento. Para voz baixa, tente `--limiar 0.005`; se o ruído disparar capturas, tente `--limiar 0.03`. O piso padrão é `0.01` (RMS relativo, de 0 a 1); a detecção usa o maior entre esse piso e 2,5 vezes o ruído calibrado. Também pode tentar `--modelo base`. A entrada usa uma taxa e um número de canais verificados no dispositivo; o PCM float32 é convertido em memória para mono a 16 kHz antes do Whisper. Normalizar o texto não corrige palavras transcritas incorretamente.

**Sem voz/som:** instale uma voz portuguesa compatível com SAPI5, confira a lista de vozes, o volume e a saída padrão. Falhas de síntese são informadas no terminal; o programa continua e tenta iniciar a voz novamente na próxima ativação.

**Sem cotação:** confira internet, relógio do PC e acesso a `economia.awesomeapi.com.br`. HTTP 429 indica limite de consultas; aguarde antes de tentar de novo. Não desative a verificação de certificados. A frase de falha é falada quando uma voz funcional está disponível; também aparece no terminal.

**Sem clima:** confira o relógio do PC e o acesso a `geocoding-api.open-meteo.com` e `api.open-meteo.com`. Localização ambígua, resposta inválida ou dados antigos resultam em indisponibilidade; dólar e horário continuam funcionando.

**Sem música:** confira se o nome é `assets/highway_to_hell.mp3` (não `.mp3.mp3`), se o arquivo é um MP3 válido e se a saída de áudio funciona. Ajuste `--volume` se necessário. Use `--sem-musica` para isolar o teste da voz.

## Organização e testes

```text
main.py                 entrada do programa
jarvis/app.py           funções legadas da versão de terminal
jarvis/interface.py     janela PySide6 e desenho dos anéis
jarvis/runtime.py       worker serial e sinais para a interface
jarvis/cliente_openai.py Responses API e ferramentas permitidas
jarvis/comandos.py      prioridade e ativação por palavra inteira
jarvis/configuracoes.py preferências locais sem segredos
jarvis/terminal.py      teste de conversa e saudação por texto
jarvis/reconhecimento.py reconhecimento local e normalização
jarvis/cotacao.py        API, validação, data e valor por extenso
jarvis/clima.py          cidade, condições atuais e tradução WMO
jarvis/horario.py        fuso America/Recife e horário por extenso
jarvis/saudacao.py       resposta única e falhas parciais
jarvis/musica.py         reprodução, volume e redução final
jarvis/voz.py            voz local e velocidade
assets/                 coloque seu MP3 local aqui
tests/                  testes sem hardware e sem consultas externas
requirements.txt        dependências diretas com versões fixadas
```

Rodar os testes automatizados, sem instalar dependência adicional:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes usam respostas de rede e áudio **simulados**, e widgets Qt reais com plataforma offscreen; isso verifica lógica e recuperação de falhas, não qualidade de reconhecimento, alto-falante nem disponibilidade real da API. As dependências diretas estão fixadas, mas este projeto ainda não tem um lockfile de dependências transitivas.

### Validação no ambiente de criação

O ambiente de criação é Linux, sem acesso ao seu microfone ou alto-falantes do Windows. As consultas HTTPS **reais** de geocodificação, clima atual e câmbio e a documentação do Open-Meteo foram verificadas. Os testes automatizados verificam dados, rejeição de clima antigo, horário de Recife, consultas paralelas, falhas parciais, centavos, duplicatas, encerramento e coordenação da música/fala com dispositivos simulados.

Também foi gerado um MP3 temporário de silêncio sintético e decodificado/reproduzido com o driver SDL `dummy`. Reprodução, ajuste de volume, redução gradual e parada passaram nesse teste **sem saída física de som**. Isso não valida alto-falantes, volume audível nem o seu arquivo de música.

O download real dos pesos Whisper foi tentado, mas o proxy deste ambiente bloqueou o servidor de arquivos `us.aws.cdn.hf.co` com HTTP 403. Portanto, não foi possível validar o carregamento/inferência do modelo aqui. O primeiro download e a transcrição real precisam ser verificados no seu PC. Os pacotes Python foram instalados aqui e os pacotes para Windows/Python 3.11 foram verificados por download; isso não equivale a executar no Windows. No Linux de criação falta também a biblioteca nativa PortAudio: use `--texto --sem-voz --sem-musica` para testar aqui; no Windows ela vem no pacote `sounddevice`.

No seu PC, coloque o MP3 e execute `--texto` para conferir a fala do Windows, a música simultânea, o volume baixo e a redução gradual. Depois execute o modo normal para conferir a transcrição real de “bom dia Jarvis”, o limiar de volume, a pausa durante toda a sequência e Ctrl+C durante fala/música. Não considere os testes simulados uma validação desses recursos físicos. Nenhum teste utilizou ou baixou a música do AC/DC. Os dados reais consultados aqui devem mudar conforme novas respostas das fontes.


### Validação da versão desktop

A janela foi criada, renderizada e inspecionada em Linux com Qt **offscreen**, incluindo controles reais, redimensionamento, seleção de preferências, animação reduzida, limpeza, prevenção de tarefas duplicadas e cancelamento. Os 45 testes automatizados passaram. O transporte da Responses API foi testado com o SDK oficial e **HTTP simulado**: ferramentas, contexto limitado, chave ausente, autenticação, limite, conexão e cancelamento. O README atual do repositório oficial do SDK foi consultado e recomenda Responses; páginas completas da documentação OpenAI foram bloqueadas pela rede deste ambiente.

**Não havia chave configurada**, portanto não foi realizada chamada real à OpenAI. Não há arquivo AC/DC fornecido, logo não foi testada essa faixa. O modelo Whisper ainda exige download no primeiro uso; seu carregamento/transcrição real não foi validado aqui por causa do bloqueio de rede documentado acima. Fala SAPI5 cancelável em thread, seleção de dispositivos e reprodução audível precisam de teste no **seu Windows**. Teste primeiro por texto e depois pelo microfone, inclusive Parar durante a fala e durante a música. Não consideramos simulações uma validação desses dispositivos.


## Diagnóstico do microfone no Windows

Correções feitas sem trocar as bibliotecas de reconhecimento: o código anterior abria sempre mono/16 kHz, sem verificar compatibilidade; persistia somente um índice de dispositivo; usava apenas um limiar fixo e anunciava a escuta antes de abrir o stream. Essas são causas identificadas no código, não um diagnóstico do seu hardware. O código também desativava a escuta após erros da API e podia capturar uma pergunta pelo microfone após uma ativação digitada; esses fluxos foram corrigidos.

1. Abra `iniciar_jarvis.bat`. Na lista **Microfones**, escolha sua entrada, por exemplo o microfone USB, distinguindo a interface MME/WASAPI pelo nome. Clique **Atualizar microfones** após conectar ou remover dispositivos. Se o driver não atualizar a lista, feche e reabra o Jarvis. A seleção é salva em `config.local.json` pelo nome e interface de áudio. Se houver duas entradas indistinguíveis, escolha outra interface ou remova a duplicata. Não há troca automática para outro microfone quando o escolhido desaparece. **Padrão do Windows** é uma escolha explícita e é resolvida como entrada antes de abrir cada captura.
2. Clique **Testar microfone**. Fique em silêncio por um segundo na calibração; quando aparecer **Ouvindo**, diga “bom dia Jarvis” e deixe um segundo de silêncio. O teste dá até oito segundos para começar a falar e usa a duração máxima das configurações. Ele não executa a saudação nem chama a OpenAI.
3. Compare **Captura** e **Reconhecimento**. “Captura: Sim” confirma chegada de PCM, mesmo quando o volume é zero. O indicador e pico RMS mostram a energia desse áudio. “Reconhecimento: Sim” e **Texto reconhecido** mostram a transcrição local. Captura confirmada com reconhecimento ausente pode significar silêncio, voz baixa, ruído ou limiar alto. Captura confirmada com falha do modelo é reportada separadamente. O primeiro modelo precisa de internet.
4. Se não capturar, em **Configurações do Windows → Privacidade e segurança → Microfone** (Windows 10: **Privacidade → Microfone**), habilite acesso ao dispositivo e aos aplicativos da área de trabalho. Confira em **Sistema → Som → Entrada** se o medidor do próprio Windows responde. Feche programas usando modo exclusivo. Um erro do driver nem sempre permite distinguir permissão, dispositivo ocupado e desconexão; o aviso informa essas possibilidades sem inventar o motivo.
5. Para voz baixa, reduza **Limiar do microfone** nas Configurações, por exemplo `0.005`. Faça a calibração sem falar; clique em **Testar microfone** novamente para recalibrar. Evite música externa e ventiladores próximos. O teste sempre recalibra; a escuta normal reaproveita a calibração para não descartar o começo de cada frase.
6. Clique **Ativar microfone**. Confira no texto reconhecido “Jarvis”, “Jarvis, que horas são?” e “bom dia Jarvis”. A saudação tem prioridade mesmo se “Jarvis” aparecer antes dela. “Jarvisinho” não ativa o assistente. O Whisper usa idioma `pt`, modelo multilíngue e contexto de português brasileiro; a qualidade real depende do PC e do microfone.
7. Faça a saudação com MP3 e voz ligados. O indicador deve zerar durante reconhecimento, consultas, música e fala, voltando a responder ao reabrir a captura. Teste também uma falha de consulta: a escuta deve retomar. Clique **Parar** durante fala/música: esse botão desativa a escuta de propósito; para retomar clique **Ativar microfone**. Trocar configurações também desativa de propósito. Desconexão exige reconectar e ativar novamente, sem tentativas infinitas ou seleção silenciosa de outro dispositivo.

A captura é controlada apenas pelo worker `jarvis-runtime`; o botão de teste usa o mesmo worker, fecha a captura anterior e retoma a escuta se ela estava ativa. A enumeração não abre streams. O stream fecha antes da inferência e antes de qualquer áudio do Jarvis. O estado **Ouvindo** só é emitido depois de um stream ativo e nunca durante inferência. PCM nativo float32 usa canais/taxa aceitos pelo PortAudio; downmix para mono e reamostragem filtrada via PyAV (já incluído pelo faster-whisper) preparam áudio de 16 kHz. Silêncio de um segundo encerra a frase; pré-captura de até 500 ms preserva o início após calibração. Perda de blocos, desconexão e ausência de entrega de áudio são erros visíveis.

Logs ficam no terminal com hora, nome do módulo, dispositivo/taxa/canais, calibração RMS e tipo de falha do reconhecedor. Não são criados arquivos de log ou gravações automaticamente, nem registradas credenciais, perguntas ou texto transcrito nos logs. O texto reconhecido aparece na interface para diagnóstico. Para ver os logs desde o início:

```powershell
.\.venv\Scripts\python.exe main.py
```

Validação desta correção: **55 testes passaram**; as dependências passaram em `pip check`, a janela foi renderizada em Qt offscreen e o modo texto foi executado. Testes automatizados usam PCM sintético e backend de microfone simulado, incluindo formato nativo estéreo/48 kHz, reamostragem real PyAV, calibração, silêncio, permissão, perda de blocos, fechamento antes da transcrição, cancelamento, identificação persistente, prioridade dos comandos, teste pela interface e retomada após música/fala/falha de API. Não houve teste de microfone físico, permissões reais do Windows ou transcrição real do Whisper nesta correção. Os passos acima são necessários no seu computador.


## Controles independentes de música e voz

Os controles ficam no rodapé da janela e continuam disponíveis durante consultas e respostas. Em janelas estreitas, os painéis e controles do microfone se empilham; o painel superior usa rolagem vertical sem cortar conteúdo horizontalmente. O visual atual mantém o desenho original em Qt; **o vídeo de referência do TikTok não pôde ser visualizado neste ambiente**, portanto este painel não é apresentado como reprodução dele. Para adaptar composição, formas, cores e animações à referência, ainda é necessário fornecer o vídeo ou capturas.

| Controle | Comportamento |
| --- | --- |
| **Pausar música / Retomar música** | Alterna conforme o estado real do SDL. Usa `pause`/`unpause`, preservando a posição da faixa, sem `play` ou recarga ao retomar. |
| **Parar música** | Encerra somente o MP3. A próxima saudação carrega a faixa desde o início. Não interrompe a voz. |
| **Volume MP3** | Ajusta apenas a música, de 0 a 100%; a redução automática durante a saudação continua protegendo a compreensão da voz. |
| **Interromper fala** | Purga a fila da fala atual. Mantém o texto no histórico e não cancela o MP3 nem as consultas. Só é habilitado durante a fala. |
| **Responder por voz** | Desmarcar interrompe uma fala ativa e mantém futuras respostas escritas. Marcar habilita a voz para novas respostas; não relê a anterior. |
| **Volume da voz** | Independente do MP3. No Windows ajusta o volume do SAPI5 durante a fala pela própria thread de síntese. |
| **Parar todos os áudios** | Para MP3 e fala, preserva consultas e histórico e impede novos áudios da sequência em andamento. A próxima ativação pode usar áudio novamente. |
| **Parar** | Continua cancelando a operação e desativando o microfone, como nas versões anteriores. |

Volume do MP3, volume da voz (`volume_voz`) e opção de resposta por voz são salvos em `config.local.json`, sem credenciais. As configurações completas também permitem ajustar os dois volumes. Os sliders afetam o Jarvis, sem alterar o volume geral do Windows.

O MP3 continua sendo um arquivo local fornecido por você, em `assets/highway_to_hell.mp3`, ou o caminho escolhido nas Configurações. Depois da saudação, a música reduz gradualmente até parar. **Se a faixa estiver pausada ao terminar a saudação, sua posição fica preservada; o fade é adiado até você retomar.** Você também pode escolher Parar música para encerrar essa faixa pausada.

A síntese SAPI5 permanece no worker que inicializou o COM. A interrupção usa um evento separado do cancelamento de consultas; a fala verifica esse evento e purga o áudio enfileirado, confirmando o término antes da reabertura do microfone. Se o driver não confirmar o fim da fala, o aplicativo bloqueia a escuta e pede reinicialização. A mudança de volume durante uma fala usa o driver da versão fixa `pyttsx3==2.99`, pois o `engine.setProperty` comum pode enfileirar essa mudança depois da fala; esse caminho ainda requer validação física no Windows.

O player tem uma thread para os controles e operações curtas protegidas por lock, de modo que pausar/parar/ajustar o MP3 não aguarda as consultas. Há apenas um capturador de microfone. Retomar a música interrompe e fecha qualquer captura antes de voltar a tocar; não espera pelo download/inferência do modelo quando o stream já está fechado. Se o player não confirmar stop nem encerramento do mixer, a captura é bloqueada e um aviso pede reinicialização. A escuta pode continuar enquanto o MP3 está pausado, mas fica suspensa durante sua reprodução, durante a fala e durante o fade. Ao parar os áudios, a escuta volta se o microfone continua habilitado e a operação em andamento já terminou. Uma consulta ainda em execução mantém a captura pausada até devolver seu resultado.

Os anéis do painel são desenhados pela aplicação e mudam a velocidade conforme os estados reais: aguardando, ouvindo/calibrando, processando e falando. O medidor continua mostrando **somente o RMS do microfone capturado**, e não uma onda de áudio de saída inventada. Não há vídeo no fundo.

### Validação dos novos controles no seu PC

1. Coloque o MP3 e envie “bom dia Jarvis”. Durante a consulta ou fala, pause e retome: confirme que a faixa continua do mesmo ponto. Se estiver pausada ao final da saudação, retome para verificar o fade adiado.
2. Durante a resposta, clique **Parar música**: a voz deve continuar. Faça outra saudação e clique **Interromper fala**: o texto deve permanecer, a voz não deve continuar nem tocar trechos pendentes, e o MP3 segue seu fluxo de finalização.
3. Ajuste cada volume separadamente enquanto os áudios tocam. Desmarque **Responder por voz** e envie outra pergunta: deve aparecer texto sem fala. Marque novamente para habilitar as próximas respostas.
4. Com o microfone habilitado, teste **Parar todos os áudios** durante a fala e durante a consulta. A consulta deve concluir por texto, sem iniciar nova fala, e a escuta deve retornar depois, sem detectar os áudios do Jarvis. **Parar** continua exigindo ativação manual do microfone depois.
5. Redimensione a janela e confirme que os controles continuam legíveis. Feche o aplicativo com MP3/fala ativos e verifique que o áudio para e o microfone é liberado.

**67 testes passaram**, assim como `pip check` e a renderização Qt em 1000×760 e 580×420. Testes automatizados cobrem pause/unpause sem recarga, volume independente, fade pausado, limpeza da fila de fala, purga que falha, controles durante consulta, texto preservado, resposta sem voz, retomada da captura e sincronização ao retomar MP3, além dos testes anteriores. Houve também reprodução real de **um MP3 sintético de teste** no SDL com saída `dummy`: posição estável na pausa (116/116 ms), avanço ao retomar (246 ms), volume, stop, reinício e fade. Isso não valida som audível, a faixa AC/DC, SAPI5 do Windows ou seu microfone físico. Esses recursos e o visual do vídeo permanecem sujeitos às validações acima.
