# Deploy da API

## Variaveis de ambiente

Use um arquivo `.env` no servidor com base em `.env.example`.

Campos principais:

- `SVRS_PFX_PATH`: caminho do certificado `.pfx`
- `SVRS_PFX_PASSWORD`: senha do certificado
- `API_KEY`: chave exigida na chamada da API
- `API_KEY_HEADER_NAME`: header da chave, por padrao `X-API-Key`
- `APP_ENV=production`
- `SHOW_DOCS=true`

## Subindo manualmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

## Exemplo de chamada

```bash
curl -X POST https://seu-dominio.com/consulta-cadastro \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_CHAVE_FORTE" \
  -d '{"uf":"43","cnpj":"12345678000199"}'
```

## Produção recomendada

1. Copiar projeto para `/opt/api_sefaz`
2. Criar `.venv` e instalar dependencias
3. Montar o certificado no container, por exemplo em `/app/config/certificado.pfx`
4. Ajustar `/opt/api_sefaz/.env`
5. Instalar o service `deploy/api-sefaz.service` em `/etc/systemd/system/api-sefaz.service`
6. Instalar o `deploy/nginx-api-sefaz.conf` no Nginx
7. Configurar HTTPS com Let's Encrypt

## Observacoes de seguranca

- Nao exponha `certificado.pfx` no repositorio
- Nao deixe `API_KEY` vazia em producao
- Prefira firewall liberando apenas `80` e `443`
- Se possivel, restrinja IPs de origem no Nginx ou no firewall
