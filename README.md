# Jarvis para Windows

Assistente simples em Python: enquanto estiver aberto, ouve **“bom dia Jarvis”** e inicia seu MP3 local de “Highway to Hell”, do AC/DC. Consulta dólar e clima de Salgueiro-PE em paralelo e informa por voz o horário de Recife, a temperatura, a condição do tempo e a cotação. Depois reduz a música gradualmente até parar. Só esse comando está implementado. Encerre com **Ctrl+C**.

## 1. Preparar o Python

Recomendado: **Windows 10/11, Python 3.11 de 64 bits**, microfone e alto-falante/fone. Instale o Python pelo [site oficial](https://www.python.org/downloads/windows/), incluindo o Python Launcher (`py`).

Abra o **PowerShell** na pasta do projeto, onde estão `main.py` e `requirements.txt`. Se necessário, use `cd "C:\caminho\para\J.A.V.I.S"`, substituindo pelo seu caminho real. Execute:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Os comandos usam diretamente o Python do ambiente virtual. Não é necessário ativá-lo nem alterar a política de execução do PowerShell. Internet é necessária para instalar dependências e baixar o modelo; depois, reconhecimento e síntese funcionam localmente.

Se já tem o ambiente da versão anterior, **não recrie a pasta `.venv`**. Execute apenas o comando de instalação com `-r requirements.txt` para incluir `pygame` (música) e `tzdata` (fusos IANA no Windows).

## 2. Testar primeiro sem microfone

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

O primeiro uso com microfone baixa o modelo automaticamente para `modelos/`. Aguarde “Reconhecimento local pronto”; a velocidade depende da internet. Depois os arquivos são reutilizados. Se quiser preparar o modelo antes, sem abrir o microfone, execute **na pasta do projeto**:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8', cpu_threads=2, download_root='modelos'); print('Modelo pronto.')"
```

O reconhecimento funciona sem internet depois que todos os arquivos do modelo estiverem disponíveis; câmbio e clima continuam exigindo internet. Para garantir que não haja sequer uma tentativa de atualizar o modelo em rede durante a execução, depois do download você pode definir `$env:HF_HUB_OFFLINE='1'` no PowerShell. Para voltar a permitir downloads: `Remove-Item Env:HF_HUB_OFFLINE`.

Fale com clareza, em ambiente silencioso, e faça uma pausa de cerca de um segundo ao terminar a frase. A qualidade e o tempo da transcrição dependem do microfone e do processador. O modelo `base` é maior e pode melhorar a precisão; use `--modelo base` para baixá-lo e selecioná-lo. Uma pasta local de modelo convertido para faster-whisper também pode ser informada.

## 4. Executar com microfone

```powershell
.\.venv\Scripts\python.exe main.py
```

O terminal mostrará (há também uma mensagem de carregamento do modelo):

```text
Jarvis iniciado.
Aguardando: bom dia Jarvis.
Comando reconhecido.
Consultando cotação…
Consultando condições atuais de Salgueiro, Pernambuco…
```

Diga **“bom dia Jarvis”**. Espere a resposta terminar e pelo menos três segundos antes de uma nova ativação. Maiúsculas, espaços, acentos e pontuação são normalizados. Só frases completas transcritas acionam a consulta. A captura usa blocos curtos, detecta volume e encerra a frase após um segundo de silêncio ou oito segundos de áudio. Um filtro local de atividade de voz também ajuda a descartar silêncio.

O microfone é fechado antes da transcrição e permanece fechado durante **toda** a sequência: música, consultas, fala e redução final do volume. Só é reaberto após todos os áudios terminarem. O áudio anterior é descartado. Há uma janela de três segundos após a sequência para evitar ativações duplicadas. O loop executa uma saudação por vez, sem sobrepor músicas ou respostas, e não mantém escuta depois de encerrado.

Ctrl+C interrompe a fala e a música, incluindo durante a redução do volume. Se houver uma consulta em andamento, os áudios são interrompidos imediatamente, mas o processo pode levar alguns segundos para terminar enquanto a requisição em outra thread atinge seu timeout.

### Velocidade, modelo e dispositivo

```powershell
.\.venv\Scripts\python.exe main.py --velocidade 150
.\.venv\Scripts\python.exe main.py --modelo base
```

A velocidade padrão é 175; aceita de 80 a 300. Listar dispositivos de áudio:

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

**Microfone/permissão:** no Windows, habilite acesso ao microfone para aplicativos da área de trabalho em Configurações → Privacidade e segurança → Microfone. Confira o dispositivo padrão e se outro programa o está usando exclusivamente. Se houver erro, o Jarvis avisa e tenta novamente em três segundos; Ctrl+C continua disponível.

**Modelo não carrega:** confira a internet no primeiro uso e a pasta `modelos/`. Se usar `--modelo` com um caminho, ele deve conter um modelo convertido para faster-whisper, com `model.bin`, `config.json` e demais recursos. Não use um modelo Vosk nem um arquivo ZIP.

**Erro de DLL na instalação/execução:** se aparecer `DLL load failed`, confira se Python e Windows são de 64 bits e instale o [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe), pelo site da Microsoft. Reinicie o terminal e tente novamente.

**Não reconhece Jarvis:** use um ambiente silencioso e uma pausa após a frase. Confira primeiro `--texto`, que testa câmbio e fala independentemente do reconhecimento. Para voz baixa, tente `--limiar 0.005`; se o ruído disparar capturas, tente `--limiar 0.03`. O padrão é `0.01` (energia relativa, de 0 a 1). Também pode tentar `--modelo base`. Confira se o microfone suporta entrada mono a 16 kHz. Normalizar o texto não corrige palavras transcritas incorretamente.

**Sem voz/som:** instale uma voz portuguesa compatível com SAPI5, confira a lista de vozes, o volume e a saída padrão. Falhas de síntese são informadas no terminal; o programa continua e tenta iniciar a voz novamente na próxima ativação.

**Sem cotação:** confira internet, relógio do PC e acesso a `economia.awesomeapi.com.br`. HTTP 429 indica limite de consultas; aguarde antes de tentar de novo. Não desative a verificação de certificados. A frase de falha é falada quando uma voz funcional está disponível; também aparece no terminal.

**Sem clima:** confira o relógio do PC e o acesso a `geocoding-api.open-meteo.com` e `api.open-meteo.com`. Localização ambígua, resposta inválida ou dados antigos resultam em indisponibilidade; dólar e horário continuam funcionando.

**Sem música:** confira se o nome é `assets/highway_to_hell.mp3` (não `.mp3.mp3`), se o arquivo é um MP3 válido e se a saída de áudio funciona. Ajuste `--volume` se necessário. Use `--sem-musica` para isolar o teste da voz.

## Organização e testes

```text
main.py                 entrada do programa
jarvis/app.py           terminal e coordenação
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

Os testes usam respostas de rede e áudio **simulados**; isso verifica lógica e recuperação de falhas, não qualidade de reconhecimento, alto-falante nem disponibilidade real da API. As dependências diretas estão fixadas, mas este projeto ainda não tem um lockfile de dependências transitivas.

### Validação no ambiente de criação

O ambiente de criação é Linux, sem acesso ao seu microfone ou alto-falantes do Windows. As consultas HTTPS **reais** de geocodificação, clima atual e câmbio e a documentação do Open-Meteo foram verificadas. Os testes automatizados verificam dados, rejeição de clima antigo, horário de Recife, consultas paralelas, falhas parciais, centavos, duplicatas, encerramento e coordenação da música/fala com dispositivos simulados.

Também foi gerado um MP3 temporário de silêncio sintético e decodificado/reproduzido com o driver SDL `dummy`. Reprodução, ajuste de volume, redução gradual e parada passaram nesse teste **sem saída física de som**. Isso não valida alto-falantes, volume audível nem o seu arquivo de música.

O download real dos pesos Whisper foi tentado, mas o proxy deste ambiente bloqueou o servidor de arquivos `us.aws.cdn.hf.co` com HTTP 403. Portanto, não foi possível validar o carregamento/inferência do modelo aqui. O primeiro download e a transcrição real precisam ser verificados no seu PC. Os pacotes Python foram instalados aqui e os pacotes para Windows/Python 3.11 foram verificados por download; isso não equivale a executar no Windows. No Linux de criação falta também a biblioteca nativa PortAudio: use `--texto --sem-voz --sem-musica` para testar aqui; no Windows ela vem no pacote `sounddevice`.

No seu PC, coloque o MP3 e execute `--texto` para conferir a fala do Windows, a música simultânea, o volume baixo e a redução gradual. Depois execute o modo normal para conferir a transcrição real de “bom dia Jarvis”, o limiar de volume, a pausa durante toda a sequência e Ctrl+C durante fala/música. Não considere os testes simulados uma validação desses recursos físicos. Nenhum teste utilizou ou baixou a música do AC/DC. Os dados reais consultados aqui devem mudar conforme novas respostas das fontes.
