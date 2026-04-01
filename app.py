import os
import logging
import ssl
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()

import requests
from fastapi import Depends, FastAPI, HTTPException, Security
from requests.adapters import HTTPAdapter
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from urllib3.poolmanager import PoolManager
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    NoEncryption,
)
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

SVRS_URL = "https://cad.svrs.rs.gov.br/ws/cadconsultacadastro/cadconsultacadastro4.asmx"

PFX_PATH = os.getenv("SVRS_PFX_PATH", "config/certificado.pfx")
PFX_PASSWORD = os.getenv("SVRS_PFX_PASSWORD", "")
API_KEY = os.getenv("API_KEY", "")
API_KEY_HEADER_NAME = os.getenv("API_KEY_HEADER_NAME", "X-API-Key")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SHOW_DOCS = os.getenv("SHOW_DOCS", "true").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_DEBUG_ENDPOINTS = os.getenv("ENABLE_DEBUG_ENDPOINTS", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

if APP_ENV == "production":
    SHOW_DOCS = os.getenv("SHOW_DOCS", "false").strip().lower() in {"1", "true", "yes", "on"}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("api_sefaz")

UF_CODIGO_PARA_SIGLA = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF", "90": "SU",
}

api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)

app = FastAPI(
    title="API Consulta Cadastro SVRS",
    version="5.0.0",
    description="Consulta cadastro de contribuinte via SVRS",
    docs_url="/docs" if SHOW_DOCS else None,
    redoc_url="/redoc" if SHOW_DOCS else None,
    openapi_url="/openapi.json" if SHOW_DOCS else None,
)


class ConsultaRequest(BaseModel):
    uf: str = Field(..., description="Codigo numerico da UF, ex: 22, 43")
    cnpj: Optional[str] = Field(None, description="CNPJ com 14 digitos")
    ie: Optional[str] = Field(None, description="Inscricao Estadual")
    cpf: Optional[str] = Field(None, description="CPF com 11 digitos")


class ConsultaResponse(BaseModel):
    sucesso: bool
    requisicao: Dict[str, Any]
    retorno: Dict[str, Any]


def validar_api_key(api_key: Optional[str] = Security(api_key_header)) -> None:
    if not API_KEY:
        return

    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key invalida ou ausente.")


if APP_ENV == "production" and not API_KEY:
    raise RuntimeError("API_KEY obrigatoria em producao.")


def somente_digitos(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    return "".join(ch for ch in valor if ch.isdigit())


def normalizar_senha(senha: Optional[str]) -> Optional[str]:
    if senha is None:
        return None
    senha = senha.strip().strip('"').strip("'")
    return senha or None


def codigo_uf_para_sigla(cuf: str) -> str:
    sigla = UF_CODIGO_PARA_SIGLA.get(cuf)
    if not sigla:
        raise HTTPException(status_code=400, detail=f"Codigo de UF invalido: {cuf}")
    return sigla


def validar_entrada(uf: str, cnpj: Optional[str], ie: Optional[str], cpf: Optional[str]) -> None:
    docs = [bool(cnpj), bool(ie), bool(cpf)]
    if sum(docs) != 1:
        raise HTTPException(
            status_code=400,
            detail="Informe exatamente um entre cnpj, ie ou cpf."
        )

    if not uf or not uf.isdigit() or len(uf) != 2 or uf not in UF_CODIGO_PARA_SIGLA:
        raise HTTPException(
            status_code=400,
            detail="UF deve ser um codigo numerico valido com 2 digitos. Ex: 22, 43."
        )

    if cnpj and len(cnpj) != 14:
        raise HTTPException(status_code=400, detail="CNPJ deve ter 14 digitos.")

    if cpf and len(cpf) != 11:
        raise HTTPException(status_code=400, detail="CPF deve ter 11 digitos.")


def extrair_cert_e_key_do_pfx(caminho_pfx: str, senha_pfx: Optional[str]) -> tuple[bytes, bytes]:
    if not os.path.exists(caminho_pfx):
        logger.error("Certificado nao encontrado no caminho configurado.")
        raise HTTPException(
            status_code=500,
            detail="Arquivo PFX/P12 nao encontrado."
        )

    with open(caminho_pfx, "rb") as f:
        pfx_data = f.read()

    senha_normalizada = normalizar_senha(senha_pfx)

    try:
        private_key, certificate, additional_certificates = load_key_and_certificates(
            pfx_data,
            senha_normalizada.encode("utf-8") if senha_normalizada else None
        )
    except ValueError as e:
        logger.exception("Falha ao ler o certificado PFX/P12.")
        raise HTTPException(
            status_code=400,
            detail=(
                "Nao foi possivel ler o certificado PFX/P12. "
                "Verifique senha e se o arquivo contem chave privada."
            )
        ) from e
    except Exception as e:
        logger.exception("Erro inesperado ao processar o certificado PFX/P12.")
        raise HTTPException(
            status_code=500,
            detail="Erro ao processar o certificado PFX/P12."
        ) from e

    if private_key is None or certificate is None:
        logger.error("PFX/P12 sem chave privada ou certificado utilizavel.")
        raise HTTPException(
            status_code=400,
            detail="O PFX/P12 foi lido, mas nao contem chave privada e certificado utilizaveis."
        )

    cert_pem = certificate.public_bytes(Encoding.PEM)

    if additional_certificates:
        for cert in additional_certificates:
            cert_pem += cert.public_bytes(Encoding.PEM)

    key_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption()
    )

    return cert_pem, key_pem


@contextmanager
def arquivos_temporarios_certificado(cert_pem: bytes, key_pem: bytes):
    cert_file_path = None
    key_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cert_file:
            cert_file.write(cert_pem)
            cert_file_path = cert_file.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as key_file:
            key_file.write(key_pem)
            key_file_path = key_file.name

        yield cert_file_path, key_file_path
    finally:
        if cert_file_path and os.path.exists(cert_file_path):
            try:
                os.remove(cert_file_path)
            except OSError:
                pass

        if key_file_path and os.path.exists(key_file_path):
            try:
                os.remove(key_file_path)
            except OSError:
                pass


def montar_xml_consulta(cuf: str, cnpj: Optional[str], ie: Optional[str], cpf: Optional[str]) -> str:
    uf_sigla = codigo_uf_para_sigla(cuf)

    if cnpj:
        identificador = f"<CNPJ>{cnpj}</CNPJ>"
    elif ie:
        identificador = f"<IE>{ie}</IE>"
    else:
        identificador = f"<CPF>{cpf}</CPF>"

    return (
        f'<ConsCad versao="2.00" xmlns="http://www.portalfiscal.inf.br/nfe">'
        f"<infCons>"
        f"<xServ>CONS-CAD</xServ>"
        f"<UF>{uf_sigla}</UF>"
        f"{identificador}"
        f"</infCons>"
        f"</ConsCad>"
    )


def montar_soap_consulta(cuf: str, cnpj: Optional[str], ie: Optional[str], cpf: Optional[str]) -> str:
    xml_consulta = montar_xml_consulta(cuf=cuf, cnpj=cnpj, ie=ie, cpf=cpf)

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body>'
        '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/CadConsultaCadastro4">'
        f'{xml_consulta}'
        '</nfeDadosMsg>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


class SystemTrustHTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ssl_context = ssl.create_default_context()
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ssl_context,
            **pool_kwargs,
        )


def criar_sessao_svrs() -> requests.Session:
    session = requests.Session()
    adapter = SystemTrustHTTPAdapter()
    session.mount("https://", adapter)
    return session


def chamar_svrs(caminho_pfx: str, senha_pfx: Optional[str], soap_xml: str) -> str:
    logger.info("Iniciando consulta ao WS da SVRS.")
    cert_pem, key_pem = extrair_cert_e_key_do_pfx(caminho_pfx, senha_pfx)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "\"http://www.portalfiscal.inf.br/nfe/wsdl/CadConsultaCadastro4/consultaCadastro\""
    }

    with arquivos_temporarios_certificado(cert_pem, key_pem) as (cert_path, key_path):
        try:
            with criar_sessao_svrs() as session:
                response = session.post(
                    SVRS_URL,
                    data=soap_xml.encode("utf-8"),
                    headers=headers,
                    cert=(cert_path, key_path),
                    timeout=30
                )
                response.raise_for_status()
                logger.info("Consulta ao WS da SVRS concluida com sucesso.")
                return response.text

        except requests.exceptions.SSLError as e:
            logger.exception("Erro SSL/TLS ao conectar no WS da SVRS.")
            raise HTTPException(
                status_code=502,
                detail=f"Erro SSL/TLS ao conectar no WS da SVRS: {str(e)}"
            ) from e
        except requests.exceptions.Timeout as e:
            logger.exception("Timeout ao consultar o WS da SVRS.")
            raise HTTPException(
                status_code=504,
                detail="Timeout ao consultar o WS da SVRS."
            ) from e
        except requests.exceptions.HTTPError as e:
            logger.exception("Erro HTTP retornado pelo WS da SVRS.")
            body = e.response.text if e.response is not None else ""
            raise HTTPException(
                status_code=502,
                detail=f"Erro HTTP no WS da SVRS: {body[:4000]}"
            ) from e
        except requests.exceptions.RequestException as e:
            logger.exception("Erro de rede ao chamar o WS da SVRS.")
            raise HTTPException(
                status_code=502,
                detail=f"Erro ao chamar o WS da SVRS: {str(e)}"
            ) from e


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def xml_para_dict(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return element.text.strip() if element.text else ""

    result: Dict[str, Any] = {}
    for child in children:
        key = strip_ns(child.tag)
        value = xml_para_dict(child)

        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value

    return result


def buscar_primeiro(root: ET.Element, nome_tag: str) -> Optional[str]:
    for elem in root.iter():
        if strip_ns(elem.tag) == nome_tag:
            return elem.text.strip() if elem.text else None
    return None


def extrair_retorno_normalizado(xml_texto: str) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml_texto)
    except ET.ParseError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Resposta XML invalida: {str(e)}"
        ) from e

    return {
        "cStat": buscar_primeiro(root, "cStat"),
        "xMotivo": buscar_primeiro(root, "xMotivo"),
        "uf": buscar_primeiro(root, "UF"),
        "cnpj": buscar_primeiro(root, "CNPJ"),
        "cpf": buscar_primeiro(root, "CPF"),
        "ie": buscar_primeiro(root, "IE"),
        "xNome": buscar_primeiro(root, "xNome"),
        "xFant": buscar_primeiro(root, "xFant"),
        "ender": {
            "xLgr": buscar_primeiro(root, "xLgr"),
            "nro": buscar_primeiro(root, "nro"),
            "xCpl": buscar_primeiro(root, "xCpl"),
            "xBairro": buscar_primeiro(root, "xBairro"),
            "cMun": buscar_primeiro(root, "cMun"),
            "xMun": buscar_primeiro(root, "xMun"),
            "CEP": buscar_primeiro(root, "CEP"),
        },
        "xml_parseado": xml_para_dict(root)
    }


@app.get("/health")
def health():
    return {"ok": True}


if ENABLE_DEBUG_ENDPOINTS:
    @app.get("/debug-pfx")
    def debug_pfx(_: None = Depends(validar_api_key)):
        cert_pem, key_pem = extrair_cert_e_key_do_pfx(PFX_PATH, PFX_PASSWORD)
        return {
            "ok": True,
            "pfx_path": PFX_PATH,
            "cert_bytes": len(cert_pem),
            "key_bytes": len(key_pem),
        }


@app.post("/consulta-cadastro", response_model=ConsultaResponse)
def consulta_cadastro(payload: ConsultaRequest, _: None = Depends(validar_api_key)):
    uf = somente_digitos(payload.uf)
    cnpj = somente_digitos(payload.cnpj)
    ie = somente_digitos(payload.ie)
    cpf = somente_digitos(payload.cpf)

    validar_entrada(uf=uf, cnpj=cnpj, ie=ie, cpf=cpf)

    soap_xml = montar_soap_consulta(cuf=uf, cnpj=cnpj, ie=ie, cpf=cpf)

    xml_resposta = chamar_svrs(
        caminho_pfx=PFX_PATH,
        senha_pfx=PFX_PASSWORD,
        soap_xml=soap_xml
    )

    retorno = extrair_retorno_normalizado(xml_resposta)

    return ConsultaResponse(
        sucesso=True,
        requisicao={
            "uf_codigo": uf,
            "uf_sigla": codigo_uf_para_sigla(uf),
            "cnpj": cnpj,
            "ie": ie,
            "cpf": cpf,
        },
        retorno=retorno,
    )
