"""Lê um PDF não confiável num processo próprio, com limite de tempo e de memória.

Roda como script, chamado por `documentos.py`, sem importar nada do projeto: o PDF entra pela
entrada padrão, e o resultado sai em JSON na saída padrão. Quem chama mede o tempo e mata o
processo. Aqui fica o limite de memória: `RLIMIT_AS` onde o sistema respeita e, em todo sistema, um
vigia do pico de memória. No macOS só o vigia vale, e uma alocação muito rápida pode passar do
limite antes de ele ver.

Texto que ninguém enxerga não entra no resultado visível: modo de renderização invisível, fonte
minúscula, transparência e letra sem contraste com o que está atrás dela na página renderizada.
Letra coberta por uma foto ainda tem contraste com a foto, e por isso passa. Só o OCR da página
inteira resolveria, e ele não roda quando o PDF tem texto.
"""

import argparse
import json
import os
import resource
import sys
import threading
import time
from ctypes import byref, c_double, c_int, c_uint
from typing import Any

import pypdfium2
import pypdfium2.raw as pdfium

MENOR_ALTURA_DE_LETRA_PT = 2.5
MENOR_CONTRASTE = 12
"""Em 255. Abaixo disso, a letra não muda o que se vê na página."""
ESCALA_DA_CONFERENCIA = 2.0
MAIOR_IMAGEM_DA_CONFERENCIA = 16_000_000
PAUSA_DO_VIGIA_S = 0.05
_MODOS_INVISIVEIS = (pdfium.FPDF_TEXTRENDERMODE_INVISIBLE, pdfium.FPDF_TEXTRENDERMODE_CLIP)
_CODIGOS_SEM_LETRA = (0, 0xFFFE, 0xFFFF)
_SAIDA_POR_MEMORIA = 3


class ErroDeLeitura(Exception):
    """Falha prevista. `codigo` é o que `documentos.py` traduz para um erro do projeto."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def _responder(dados: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(dados))
    sys.stdout.flush()


def _vigiar_memoria(limite: int) -> None:
    unidade = 1 if sys.platform == "darwin" else 1024
    while True:
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unidade > limite:
            _responder({"erro": "memoria"})
            os._exit(_SAIDA_POR_MEMORIA)
        time.sleep(PAUSA_DO_VIGIA_S)


def _limitar_memoria(limite: int) -> None:
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limite, limite))
    except (ValueError, OSError):  # o macOS recusa: fica só o vigia
        pass
    threading.Thread(target=_vigiar_memoria, args=(limite,), daemon=True).start()


def _abrir(conteudo: bytes, maximo_de_paginas: int) -> pypdfium2.PdfDocument:
    try:
        documento = pypdfium2.PdfDocument(conteudo)
    except pypdfium2.PdfiumError as erro:
        senha = "password" in str(erro).casefold()
        raise ErroDeLeitura("senha" if senha else "ilegivel") from None
    if len(documento) > maximo_de_paginas:
        raise ErroDeLeitura("paginas")
    return documento


class _ImagemDaPagina:
    """A página como aparece na tela, renderizada só se alguma letra precisar ser conferida."""

    def __init__(self, pagina: pypdfium2.PdfPage) -> None:
        self._pagina = pagina
        largura, altura = pagina.get_size()
        pixels = max(largura * altura, 1)
        reducao = (MAIOR_IMAGEM_DA_CONFERENCIA / pixels) ** 0.5
        self._escala = min(ESCALA_DA_CONFERENCIA, reducao)
        self._largura = max(int(largura * self._escala), 1)
        self._altura = max(int(altura * self._escala), 1)
        self._imagem: Any = None

    def _ponto(self, x: float, y: float) -> tuple[int, int]:
        destino_x, destino_y = c_int(), c_int()
        pdfium.FPDF_PageToDevice(
            self._pagina.raw,
            0,
            0,
            self._largura,
            self._altura,
            0,
            x,
            y,
            byref(destino_x),
            byref(destino_y),
        )
        return destino_x.value, destino_y.value

    def tem_contraste(self, esquerda: float, direita: float, baixo: float, alto: float) -> bool:
        if self._imagem is None:
            self._imagem = self._pagina.render(scale=self._escala, grayscale=True).to_pil()
        x1, y1 = self._ponto(esquerda, alto)
        x2, y2 = self._ponto(direita, baixo)
        caixa = (min(x1, x2), min(y1, y2), max(x1, x2) + 1, max(y1, y2) + 1)
        menor, maior = self._imagem.crop(caixa).getextrema()
        return maior - menor >= MENOR_CONTRASTE


def _letra_visivel(textos: Any, indice: int, imagem: _ImagemDaPagina) -> bool:
    objeto = pdfium.FPDFText_GetTextObject(textos, indice)
    if objeto and pdfium.FPDFTextObj_GetTextRenderMode(objeto) in _MODOS_INVISIVEIS:
        return False
    vermelho, verde, azul, opacidade = c_uint(), c_uint(), c_uint(), c_uint()
    if (
        pdfium.FPDFText_GetFillColor(
            textos, indice, byref(vermelho), byref(verde), byref(azul), byref(opacidade)
        )
        and opacidade.value == 0
    ):
        return False
    folgada = pdfium.FS_RECTF()
    if (
        pdfium.FPDFText_GetLooseCharBox(textos, indice, byref(folgada))
        and abs(folgada.top - folgada.bottom) < MENOR_ALTURA_DE_LETRA_PT
    ):
        return False
    esquerda, direita, baixo, alto = c_double(), c_double(), c_double(), c_double()
    if not pdfium.FPDFText_GetCharBox(
        textos, indice, byref(esquerda), byref(direita), byref(baixo), byref(alto)
    ):
        return True
    return imagem.tem_contraste(esquerda.value, direita.value, baixo.value, alto.value)


def _texto_da_pagina(pagina: pypdfium2.PdfPage, visivel: list[str], escondido: list[str]) -> None:
    pagina_de_texto = pagina.get_textpage()
    textos = pagina_de_texto.raw
    imagem = _ImagemDaPagina(pagina)
    for indice in range(pdfium.FPDFText_CountChars(textos)):
        codigo = pdfium.FPDFText_GetUnicode(textos, indice)
        if codigo in _CODIGOS_SEM_LETRA:
            continue
        letra = chr(codigo)
        if letra.isspace() or pdfium.FPDFText_IsGenerated(textos, indice) == 1:
            visivel.append(letra)
            escondido.append(letra)
        elif _letra_visivel(textos, indice, imagem):
            visivel.append(letra)
        else:
            escondido.append(letra)
    visivel.append("\n")
    escondido.append("\n")


def extrair_texto(conteudo: bytes, maximo_de_paginas: int, maximo_de_caracteres: int) -> dict:
    documento = _abrir(conteudo, maximo_de_paginas)
    visivel: list[str] = []
    escondido: list[str] = []
    for indice in range(len(documento)):
        _texto_da_pagina(documento[indice], visivel, escondido)
        if len(visivel) > maximo_de_caracteres:
            raise ErroDeLeitura("caracteres")
    return {"visivel": "".join(visivel), "escondido": "".join(escondido)}


def _ocr_da_pagina(pagina: pypdfium2.PdfPage, escala: float, idiomas: str, tempo: int) -> str:
    import pytesseract  # só quem precisa de OCR paga por esta importação

    imagem = pagina.render(scale=escala).to_pil()
    try:
        disponiveis = set(pytesseract.get_languages(config=""))
        usar = "+".join(i for i in idiomas.split("+") if i in disponiveis) or "eng"
        return pytesseract.image_to_string(imagem, lang=usar, timeout=tempo)
    except pytesseract.TesseractNotFoundError:
        raise ErroDeLeitura("sem_tesseract") from None
    except (RuntimeError, OSError, pytesseract.TesseractError):
        raise ErroDeLeitura("ilegivel") from None


def extrair_por_ocr(conteudo: bytes, argumentos: argparse.Namespace) -> dict:
    documento = _abrir(conteudo, argumentos.maximo_de_paginas)
    escala = argumentos.dpi / 72
    partes = []
    for indice in range(min(len(documento), argumentos.paginas_ocr)):
        pagina = documento[indice]
        largura, altura = pagina.get_size()
        if largura * altura * escala * escala > argumentos.maior_imagem:
            raise ErroDeLeitura("pagina_grande")
        partes.append(_ocr_da_pagina(pagina, escala, argumentos.idiomas, argumentos.tempo_ocr))
    return {"visivel": "\n".join(partes), "escondido": ""}


def _argumentos() -> argparse.Namespace:
    leitor = argparse.ArgumentParser()
    leitor.add_argument("modo", choices=("texto", "ocr"))
    leitor.add_argument("--memoria", type=int, required=True)
    leitor.add_argument("--maximo-de-paginas", type=int, required=True)
    leitor.add_argument("--maximo-de-caracteres", type=int, required=True)
    leitor.add_argument("--paginas-ocr", type=int, default=0)
    leitor.add_argument("--dpi", type=int, default=200)
    leitor.add_argument("--maior-imagem", type=int, default=0)
    leitor.add_argument("--idiomas", default="eng")
    leitor.add_argument("--tempo-ocr", type=int, default=30)
    return leitor.parse_args()


def principal() -> None:
    argumentos = _argumentos()
    _limitar_memoria(argumentos.memoria)
    conteudo = sys.stdin.buffer.read()
    try:
        if argumentos.modo == "texto":
            resposta = extrair_texto(
                conteudo, argumentos.maximo_de_paginas, argumentos.maximo_de_caracteres
            )
        else:
            resposta = extrair_por_ocr(conteudo, argumentos)
    except ErroDeLeitura as erro:
        resposta = {"erro": erro.codigo}
    except MemoryError:
        resposta = {"erro": "memoria"}
    except Exception:  # arquivo não confiável: qualquer falha do leitor é arquivo ilegível
        resposta = {"erro": "ilegivel"}
    _responder(resposta)
    os._exit(0)  # sem desmontar o que o PDF montou: o processo acaba aqui


if __name__ == "__main__":
    principal()
