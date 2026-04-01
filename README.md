# API Consulta Cadastro SVRS

API em `FastAPI` para consultar cadastro de contribuinte via SVRS, usando certificado digital A1 em formato `.pfx/.p12`.

O objetivo deste projeto e expor uma interface HTTP simples para sistemas internos ou integracoes externas enviarem dados como `uf` e `cnpj`, enquanto a API faz a comunicacao SOAP com o webservice da SEFAZ/SVRS.

## O que este projeto faz

- Recebe requisicoes HTTP JSON
- Valida os dados de entrada
- Monta o XML de consulta no padrao esperado pela SEFAZ
- Usa certificado digital cliente para autenticacao mutual TLS
- Envia a solicitacao ao endpoint da SVRS
- Normaliza a resposta XML em JSON

## Quando esse modelo de sistema faz sentido

Esse tipo de API e util quando voce quer:

- centralizar o uso de um certificado digital em um unico servico
- evitar que cada sistema cliente tenha que implementar SOAP e leitura de `.pfx`
- expor uma interface moderna REST/JSON para sistemas web, ERP, integradores ou automacoes
- controlar seguranca, logs e deploy em um unico ponto

## Arquitetura resumida

Fluxo da consulta:

1. O cliente chama `POST /consulta-cadastro`
2. A API valida `uf` e um documento (`cnpj`, `ie` ou `cpf`)
3. A API le o certificado `.pfx`
4. A API extrai certificado e chave temporariamente em `.pem`
5. A API chama o webservice da SVRS via `requests`
6. A API recebe o XML da resposta
7. A API devolve um JSON com os dados relevantes

## Stack usada

- Python
- FastAPI
- Uvicorn
- Requests
- Cryptography
- Certifi
- Truststore

## Estrutura do projeto

```text
.
|-- app.py
|-- requirements.txt
|-- Dockerfile
|-- .env.example
|-- .gitignore
|-- .dockerignore
|-- DEPLOY.md
|-- deploy/
|   |-- api-sefaz.service
|   |-- nginx-api-sefaz.conf
|-- config/
|   |-- certificado.pfx  # local apenas, nao vai para o Git
```

## Requisitos

- Python 3.11+ ou 3.12
- Certificado digital A1 `.pfx` ou `.p12`
- Senha do certificado
- Acesso de rede ao endpoint da SVRS

## Configuracao de ambiente

Crie um `.env` com base em [.env.example](/c:/Users/Ora-083326/Documents/Ora/api_sefaz/.env.example).

Exemplo:

```env
SVRS_PFX_PATH=config/certificado.pfx
SVRS_PFX_PASSWORD=troque_aqui
SVRS_CA_BUNDLE=certs/svrs-chain.pem
API_KEY=troque_por_uma_chave_longa_e_forte
API_KEY_HEADER_NAME=X-API-Key
APP_ENV=development
SHOW_DOCS=true
```

## Significado das variaveis

- `SVRS_PFX_PATH`: caminho do certificado digital
- `SVRS_PFX_PASSWORD`: senha do certificado
- `API_KEY`: chave exigida para acessar a API
- `API_KEY_HEADER_NAME`: nome do header da autenticacao
- `SVRS_CA_BUNDLE`: bundle CA usado para validar o SSL da SVRS
- `APP_ENV`: ambiente da aplicacao, por exemplo `development` ou `production`
- `SHOW_DOCS`: controla se `/docs`, `/redoc` e `/openapi.json` ficam ativos
- `ENABLE_DEBUG_ENDPOINTS`: habilita endpoints temporarios de diagnostico
- `LOG_LEVEL`: nivel de log da aplicacao, por exemplo `INFO` ou `DEBUG`

## Como rodar localmente

### 1. Criar ambiente virtual

No Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

No Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Ajustar o `.env`

Configure:

- caminho do certificado
- senha do certificado
- `API_KEY`

### 4. Iniciar a API

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Se `SHOW_DOCS=true`, a documentacao estara disponivel em:

- `http://127.0.0.1:8000/docs`

## Endpoints

### `GET /health`

Usado para verificar se a aplicacao esta de pe.

Resposta:

```json
{
  "ok": true
}
```

### `POST /consulta-cadastro`

Endpoint principal da API.

Requer header de autenticacao:

```http
X-API-Key: SUA_CHAVE
```

Body JSON:

```json
{
  "uf": "43",
  "cnpj": "12345678000199"
}
```

Regras:

- `uf` deve ser codigo numerico de 2 digitos
- envie exatamente um entre `cnpj`, `ie` ou `cpf`
- `cnpj` deve ter 14 digitos
- `cpf` deve ter 11 digitos

### `GET /debug-pfx`

Endpoint opcional de diagnostico do certificado.

Ele so existe quando:

- `ENABLE_DEBUG_ENDPOINTS=true`

Ele tambem exige `X-API-Key`.

Uso recomendado:

- habilitar temporariamente em investigacoes
- desabilitar em producao normal

## Exemplo de uso com cURL

```bash
curl -X POST http://127.0.0.1:8000/consulta-cadastro \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_CHAVE" \
  -d "{\"uf\":\"43\",\"cnpj\":\"12345678000199\"}"
```

## Exemplo de resposta

```json
{
  "sucesso": true,
  "requisicao": {
    "uf_codigo": "43",
    "uf_sigla": "RS",
    "cnpj": "12345678000199",
    "ie": null,
    "cpf": null
  },
  "retorno": {
    "cStat": "111",
    "xMotivo": "Consulta cadastro com uma ocorrencia",
    "uf": "RS",
    "cnpj": "12345678000199",
    "cpf": null,
    "ie": "1234567890",
    "xNome": "EMPRESA EXEMPLO LTDA",
    "xFant": "EMPRESA EXEMPLO",
    "ender": {
      "xLgr": "RUA EXEMPLO",
      "nro": "100",
      "xCpl": "",
      "xBairro": "CENTRO",
      "cMun": "4305108",
      "xMun": "CAXIAS DO SUL",
      "CEP": "95000000"
    },
    "xml_parseado": {}
  }
}
```

## Exemplo de integracao em Python

```python
import requests

url = "https://api.seudominio.com/consulta-cadastro"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "SUA_CHAVE",
}
payload = {
    "uf": "43",
    "cnpj": "12345678000199",
}

response = requests.post(url, json=payload, headers=headers, timeout=30)
print(response.status_code)
print(response.json())
```

## Comportamento de seguranca implementado

- autenticacao por `API_KEY`
- falha na inicializacao se `APP_ENV=production` e `API_KEY` estiver vazia
- docs desativaveis em producao
- endpoint de diagnostico desligado por padrao
- certificado fora do Git
- `.env` fora do Git
- endpoint `/health` enxuto
- resposta publica sem XML bruto da SEFAZ

## O que nao deve ir para o repositorio

Nunca suba:

- `.env`
- `config/certificado.pfx`
- chaves privadas
- certificados `.pem` ou `.key`

O projeto ja possui `.gitignore` para ajudar nisso.

## Deploy

Voce pode publicar em:

- VPS propria
- Nginx + systemd
- Docker
- EasyPanel

Arquivos de apoio:

- [DEPLOY.md](/c:/Users/Ora-083326/Documents/Ora/api_sefaz/DEPLOY.md)
- [deploy/api-sefaz.service](/c:/Users/Ora-083326/Documents/Ora/api_sefaz/deploy/api-sefaz.service)
- [deploy/nginx-api-sefaz.conf](/c:/Users/Ora-083326/Documents/Ora/api_sefaz/deploy/nginx-api-sefaz.conf)
- [Dockerfile](/c:/Users/Ora-083326/Documents/Ora/api_sefaz/Dockerfile)

## Deploy no EasyPanel

Fluxo recomendado:

1. Subir o projeto via GitHub
2. Criar um `App Service`
3. Escolher `Dockerfile`
4. Configurar porta `8000`
5. Definir variaveis de ambiente
6. Montar o certificado no container em `/app/config/certificado.pfx`
7. Configurar dominio e HTTPS

Exemplo de variaveis em producao:

```env
SVRS_PFX_PATH=/app/config/certificado.pfx
SVRS_PFX_PASSWORD=troque_aqui
SVRS_CA_BUNDLE=/app/certs/svrs-chain.pem
API_KEY=troque_por_uma_chave_forte
API_KEY_HEADER_NAME=X-API-Key
APP_ENV=production
SHOW_DOCS=true
```

## Erros comuns

### `401 API key invalida ou ausente`

Causa:

- header nao enviado
- chave incorreta
- nome do header diferente do configurado

### `Arquivo PFX/P12 nao encontrado`

Causa:

- caminho incorreto em `SVRS_PFX_PATH`
- arquivo nao montado no container

### `Nao foi possivel ler o certificado PFX/P12`

Causa:

- senha errada
- arquivo invalido
- `.pfx` sem chave privada

### `Timeout ao consultar o WS da SVRS`

Causa:

- instabilidade de rede
- indisponibilidade do endpoint externo

## Boas praticas para sistemas desse tipo

- isole o certificado em um servico central
- proteja a API com autenticacao
- use HTTPS sempre
- limite quem pode chamar a API
- mantenha logs, mas sem vazar segredos
- nao devolva XML bruto ao cliente final sem necessidade
- trate erro de configuracao como falha de inicializacao
- mantenha o certificado fora do repositorio

## Limites e observacoes

- a consulta depende da disponibilidade do servico da SVRS
- o layout e as regras do webservice podem mudar com o tempo
- o retorno pode variar conforme a UF e o tipo de documento consultado
- para alta demanda, vale considerar rate limit, cache e observabilidade

## Licenca

Defina a licenca conforme a necessidade do projeto.
