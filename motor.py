"""Motor de lectura de mediciones sobre video y exportación a Excel.

RECUPERACIÓN (2026-10-21): estructura, firmas y comportamiento contrastados
con 20261020_160730.mp4. Implementaciones entre capturas reconstruidas,
NO copia textual íntegra del fuente original.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any, Callable, Protocol

import cv2
import numpy as np
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Font, PatternFill

from estabilizacion_experimental import alinear_traslacion

_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


class Ocr(Protocol):
    def read(self, image: Any) -> list[tuple[str, float]]: ...


class ProcesamientoCancelado(Exception):
    """Indica que la persona detuvo la exportación antes de terminar."""


def _rango_muestreo(total_frames: int, fps: float, periodo_s: float,
                    inicio_s: float = 0.0, fin_s: float | None = None) -> list[int]:
    """Devuelve fotogramas de un intervalo; fin_s es inclusivo."""
    if not math.isfinite(periodo_s) or periodo_s <= 0:
        raise ValueError("El periodo de muestreo debe ser mayor que cero.")
    if not math.isfinite(inicio_s) or inicio_s < 0:
        raise ValueError("El segundo inicial no puede ser negativo.")
    if fin_s is not None and (not math.isfinite(fin_s) or fin_s < inicio_s):
        raise ValueError("El segundo final debe ser mayor o igual al inicial.")
    fps = max(float(fps), 1.0)
    salto = max(1, round(fps * periodo_s))
    inicio_frame = max(0, math.ceil(inicio_s * fps - 1e-9))
    fin_exclusivo = total_frames
    if fin_s is not None:
        fin_exclusivo = min(total_frames, math.floor(fin_s * fps + 1e-9) + 1)
    muestras = list(range(inicio_frame, max(inicio_frame, fin_exclusivo), salto))
    if fin_s is not None and total_frames:
        ultimo_permitido = min(total_frames - 1, math.floor(fin_s * fps + 1e-9))
        if ultimo_permitido >= inicio_frame and (not muestras or muestras[-1] != ultimo_permitido):
            muestras.append(ultimo_permitido)
    return muestras


@dataclass(frozen=True)
class ZonaLectura:
    nombre: str
    x: int
    y: int
    ancho: int
    alto: int
    decimales: int | None = 2
    confianza_minima: float = 0.60

    def __post_init__(self) -> None:
        if not self.nombre.strip():
            raise ValueError("Cada zona necesita un nombre.")
        if self.ancho <= 0 or self.alto <= 0:
            raise ValueError("La zona debe tener ancho y alto positivos.")
        if self.decimales is not None and self.decimales < 0:
            raise ValueError("Los decimales deben ser cero o un número positivo.")
        if not 0 <= self.confianza_minima <= 1:
            raise ValueError("La confianza mínima debe estar entre 0 y 1.")

    def recortar(self, frame: Any) -> Any:
        alto, ancho = frame.shape[:2]
        x1, y1 = max(0, self.x), max(0, self.y)
        x2 = min(ancho, self.x + self.ancho)
        y2 = min(alto, self.y + self.alto)
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"La zona '{self.nombre}' queda fuera del video.")
        return frame[y1:y2, x1:x2]


@dataclass(frozen=True)
class Lectura:
    valor: str | None
    confianza: float | None
    texto_ocr: str
    motivo: str | None = None

    @property
    def aceptada(self) -> bool:
        return self.valor is not None


class RapidOcr:
    """Adaptador perezoso: carga el modelo al iniciar la primera lectura."""
    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "Falta rapidocr-onnxruntime. Instala con: pip install rapidocr-onnxruntime"
            ) from exc
        self._modelo = RapidOCR()

    def read(self, image: Any) -> list[tuple[str, float]]:
        resultado, _ = self._modelo(image)
        if not resultado:
            return []
        return [(str(item[1]), float(item[2])) for item in resultado if len(item) >= 3]


def _normalizar(texto: str, decimales: int | None) -> str | None:
    # El OCR puede interpretar el punto decimal como dos puntos. Sólo se
    # corrige cuando está entre cifras, sin cambiar puntuación arbitraria.
    texto = re.sub(r"(?<=\d):(?=\d)", ".", texto)
    encontrado = _NUMBER.search(texto)
    if not encontrado:
        return None
    bruto = encontrado.group(0).replace(",", ".")
    if decimales is not None and decimales > 0 and "." not in bruto:
        return None
    try:
        valor = float(bruto)
    except ValueError:
        return None
    return f"{valor:.{decimales}f}" if decimales is not None else bruto


def leer_zona(ocr: Ocr, recorte: Any, zona: ZonaLectura) -> Lectura:
    """Lee una cifra aislada con margen negro para evitar mezclar renglones."""
    if recorte is None or recorte.size == 0:
        return Lectura(None, None, "", "recorte vacío")
    margen_vertical = max(16, round(recorte.shape[0] * 0.75))
    margen_horizontal = max(8, round(recorte.shape[1] * 0.05))
    preparado = cv2.copyMakeBorder(
        recorte, margen_vertical, margen_vertical,
        margen_horizontal, margen_horizontal,
        cv2.BORDER_CONSTANT, value=(0, 0, 0),
    )
    filas = ocr.read(preparado)
    candidatas = [
        (valor, confianza, texto)
        for texto, confianza in filas
        if (valor := _normalizar(texto, zona.decimales)) is not None
    ]
    if not candidatas:
        texto = " | ".join(x for x, _ in filas)
        return Lectura(None, None, texto, "no se detectó número completo")
    valor, confianza, texto = max(candidatas, key=lambda item: item[1])
    if confianza < zona.confianza_minima:
        return Lectura(None, confianza, texto, "confianza insuficiente")
    return Lectura(valor, confianza, texto)


def _guardar_imagen(destino: Path, imagen: Any) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(destino.suffix or ".png", imagen)
    if not ok:
        raise OSError(f"No se pudo codificar la imagen: {destino}")
    destino.write_bytes(buffer.tobytes())


def _anotar_fotograma(frame: Any, zonas: list[ZonaLectura], fila: dict[str, Any]) -> Any:
    """Crea una miniatura para revisar lecturas desde Excel."""
    imagen = frame.copy()
    for zona in zonas:
        valor = fila.get(zona.nombre) or "sin lectura"
        color = (0, 200, 0) if fila.get(zona.nombre) else (0, 80, 255)
        cv2.rectangle(imagen, (zona.x, zona.y),
                      (zona.x + zona.ancho, zona.y + zona.alto), color, 3)
        etiqueta = f"{zona.nombre}: {valor}"
        cv2.putText(imagen, etiqueta, (zona.x, max(28, zona.y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    alto, ancho = imagen.shape[:2]
    escala = min(360 / max(1, ancho), 220 / max(1, alto))
    return cv2.resize(imagen, (round(ancho * escala), round(alto * escala)))


def _crear_validacion_ampliada(frame: Any, zonas: list[ZonaLectura],
                               fila: dict[str, Any]) -> Any:
    """Mosaico ampliado legible en el libro Excel."""
    tarjetas = []
    for zona in zonas:
        recorte = zona.recortar(frame)
        if recorte.size == 0:
            continue
        escala = min(4.0, 600 / max(1, recorte.shape[1]))
        tarjeta = cv2.resize(recorte, None, fx=escala, fy=escala,
                             interpolation=cv2.INTER_CUBIC)
        texto = fila.get(zona.nombre) or "sin lectura"
        color = (0, 200, 0) if fila.get(zona.nombre) else (0, 130, 255)
        borde = 12
        tarjeta = cv2.copyMakeBorder(tarjeta, 42, borde, borde, borde,
                                       cv2.BORDER_CONSTANT, value=(18, 18, 18))
        cv2.putText(tarjeta, f"{zona.nombre}: {texto}",
                    (borde, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        tarjetas.append(tarjeta)
    if not tarjetas:
        return np.zeros((120, 320, 3), dtype=np.uint8)
    ancho = max(t.shape[1] for t in tarjetas)
    alto_total = sum(t.shape[0] for t in tarjetas) + 8 * (len(tarjetas) - 1)
    mosaico = np.full((alto_total, ancho, 3), 18, dtype=np.uint8)
    y = 0
    for tarjeta in tarjetas:
        mosaico[y:y + tarjeta.shape[0], :tarjeta.shape[1]] = tarjeta
        y += tarjeta.shape[0] + 8
    return mosaico


def _rellenar_hojas_excel(hoja: Any, detalle: Any, filas: list[dict[str, Any]],
                          zonas: list[ZonaLectura]) -> None:
    encabezados = ["frame", "tiempo_s"] + [zona.nombre for zona in zonas] + ["captura"]
    detalle.append(["frame", "tiempo_s", "zona", "lectura", "confianza", "estado",
                    "texto_ocr", "evidencia", "estabilizacion"])
    hoja.append(encabezados)
    relleno_verde = PatternFill("solid", fgColor="DAF2D0")
    relleno_amarillo = PatternFill("solid", fgColor="FFF2CC")
    relleno_rojo = PatternFill("solid", fgColor="FCE4D6")
    for indice, fila in enumerate(filas, start=2):
        valores: list[Any] = [fila.get("frame"), fila.get("tiempo_s")]
        for zona in zonas:
            valor = fila.get(zona.nombre)
            valores.append(float(valor) if valor is not None else None)
        valores.append("Ver captura")
        hoja.append(valores)
        aceptadas = sum(fila.get(zona.nombre) is not None for zona in zonas)
        relleno = (relleno_verde if aceptadas == len(zonas) else
                   relleno_amarillo if aceptadas else relleno_rojo)
        for celda in hoja[indice]:
            celda.fill = relleno
        for zona in zonas:
            celda = hoja.cell(indice, encabezados.index(zona.nombre) + 1)
            if zona.decimales is not None:
                celda.number_format = "0" + ("." + "0" * zona.decimales if zona.decimales else "")
            detalle.append([
                fila.get("frame"), fila.get("tiempo_s"), zona.nombre,
                float(fila[zona.nombre]) if fila.get(zona.nombre) is not None else None,
                fila.get(f"{zona.nombre}_confianza"), fila.get(f"{zona.nombre}_estado"),
                fila.get(f"{zona.nombre}_ocr"), fila.get(f"{zona.nombre}_evidencia"),
                fila.get("_estabilizacion"),
            ])
            detalle.cell(detalle.max_row, 4).number_format = "0" + (
                "." + "0" * zona.decimales if zona.decimales else "") if zona.decimales is not None else "General"
            detalle.cell(detalle.max_row, 5).number_format = "0.0%"
        captura = fila.get("_captura_excel")
        if captura and Path(captura).exists():
            imagen = ExcelImage(str(captura))
            proporcion = imagen.height / max(1, imagen.width)
            imagen.width = 460
            imagen.height = round(460 * proporcion)
            hoja.add_image(imagen, f"{hoja.cell(1, len(encabezados)).column_letter}{indice}")
            hoja.row_dimensions[indice].height = max(156, min(430, imagen.height * .75))
    for actual in (hoja, detalle):
        actual.freeze_panes = "A2"
        actual.auto_filter.ref = actual.dimensions
        for celda in actual[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F4E78")
            celda.alignment = Alignment(horizontal="center")
        for columna in actual.columns:
            letra = columna[0].column_letter
            actual.column_dimensions[letra].width = min(70, max(12, max(len(str(c.value or "")) for c in columna[:100]) + 2))
    hoja.column_dimensions[hoja.cell(1, len(encabezados)).column_letter].width = 52


def _escribir_excel(filas: list[dict[str, Any]], zonas: list[ZonaLectura],
                     salida: Path, etapas: list[int] | None = None,
                     rangos_s: dict[int, tuple[float, float]] | None = None) -> None:
    """Guarda un libro normal o un par de hojas por cada etapa."""
    etapas_detectadas = sorted({fila.get("_etapa") for fila in filas if fila.get("_etapa") is not None})
    etapas_a_exportar = etapas if etapas is not None else etapas_detectadas
    varias_etapas = len(etapas_a_exportar) > 1
    libro = Workbook()
    if not varias_etapas:
        hoja = libro.active
        hoja.title = "lecturas"
        detalle = libro.create_sheet("detalle")
        _rellenar_hojas_excel(hoja, detalle, filas, zonas)
    else:
        libro.remove(libro.active)
        for etapa in etapas_a_exportar:
            hoja = libro.create_sheet(f"etapa_{etapa}")
            detalle = libro.create_sheet(f"detalle_etapa_{etapa}")
            filas_etapa = [fila for fila in filas if fila.get("_etapa") == etapa]
            _rellenar_hojas_excel(hoja, detalle, filas_etapa, zonas)
    if rangos_s:
        resumen = libro.create_sheet("Resumen de secciones")
        resumen.append(["Sección", "Hoja de lecturas", "Inicio (s)", "Final (s)"])
        for numero, (inicio, fin) in rangos_s.items():
            nombre_hoja = f"etapa_{numero}" if varias_etapas else "lecturas"
            resumen.append([f"Sección {numero}", nombre_hoja, inicio, fin])
            enlace = resumen.cell(resumen.max_row, 2)
            enlace.hyperlink = f"#'{nombre_hoja}'!A1"
            enlace.style = "Hyperlink"
            for columna in (3, 4):
                resumen.cell(resumen.max_row, columna).number_format = "0.###"
        for celda in resumen[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F4E78")
            celda.alignment = Alignment(horizontal="center")
        for columna, ancho in (("A", 18), ("B", 24), ("C", 18), ("D", 18)):
            resumen.column_dimensions[columna].width = ancho
        resumen.freeze_panes = "A2"
        resumen.auto_filter.ref = resumen.dimensions
    salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(salida)


def procesar_video(
    video: str | Path,
    zonas: list[ZonaLectura],
    periodo_s: float,
    ocr: Ocr,
    salida_xlsx: str | Path,
    evidencia_dir: str | Path,
    inicio_s: float = 0.0,
    fin_s: float | None = None,
    intervalos: list[tuple[float, float | None]] | None = None,
    estabilizar: bool = False,
    ancla_estabilizacion: tuple[int, int, int, int] | None = None,
    anclas_estabilizacion: dict[str, tuple[int, int, int, int]] | None = None,
    progreso: Callable[[int, int, int, int], None] | None = None,
    cancelar: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Recupera medidas y evidencia, y exporta lecturas por etapa a Excel."""
    if not 1 <= len(zonas) <= 4:
        raise ValueError("Selecciona entre una y cuatro zonas de lectura.")
    if periodo_s <= 0:
        raise ValueError("El periodo de muestreo debe ser mayor que cero.")
    if estabilizar and ancla_estabilizacion is None and not anclas_estabilizacion:
        raise ValueError("Para estabilizar, primero marca un área estable en el primer fotograma.")
    video = Path(video)
    salida = Path(salida_xlsx)
    evidencia = Path(evidencia_dir)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video: {video}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        etapas = intervalos if intervalos is not None else [(inicio_s, fin_s)]
        if not etapas:
            raise ValueError("Añade al menos una etapa de lectura.")
        rangos = [_rango_muestreo(total, fps, periodo_s, inicio, fin)
                  for inicio, fin in etapas]
        total_muestras = sum(map(len, rangos))
        procesadas = 0
        filas: list[dict[str, Any]] = []
        referencia_estable = None
        if estabilizar:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, referencia_estable = cap.read()
            if not ok:
                raise ValueError("No se pudo leer el fotograma de referencia.")
        for numero_etapa, numeros in enumerate(rangos, start=1):
            for numero_frame in numeros:
                if cancelar is not None and cancelar():
                    raise ProcesamientoCancelado("Exportación cancelada por el usuario.")
                cap.set(cv2.CAP_PROP_POS_FRAMES, numero_frame)
                ok, frame = cap.read()
                if not ok:
                    continue
                fila: dict[str, Any] = {
                    "_etapa": numero_etapa, "frame": numero_frame,
                    "tiempo_s": round(numero_frame / fps, 3),
                }
                estabilizados: dict[tuple[int, int, int, int], tuple[Any, str]] = {}
                estados = []
                for zona in zonas:
                    ancla = (anclas_estabilizacion or {}).get(zona.nombre, ancla_estabilizacion)
                    frame_para_ocr = frame
                    if referencia_estable is not None and ancla is not None:
                        if ancla not in estabilizados:
                            try:
                                alineado, dx, dy, ecc = alinear_traslacion(referencia_estable, frame, ancla)
                                if ecc >= .85:
                                    estabilizados[ancla] = (alineado, f"ECC={ecc:.3f}; dx={dx:+.1f}; dy={dy:+.1f}")
                                else:
                                    estabilizados[ancla] = (frame, f"omitida; ECC baja={ecc:.3f}")
                            except cv2.error:
                                estabilizados[ancla] = (frame, "omitida; no se pudo alinear")
                        frame_para_ocr, estado = estabilizados[ancla]
                        estados.append(f"{zona.nombre}: {estado}")
                    elif estabilizar:
                        estados.append(f"{zona.nombre}: sin ancla; original")
                    recorte = zona.recortar(frame_para_ocr)
                    lectura = leer_zona(ocr, recorte, zona)
                    prefijo = f"etapa_{numero_etapa:02d}_" if len(etapas) > 1 else ""
                    archivo = evidencia / f"{prefijo}frame_{numero_frame:06d}_{zona.nombre}.png"
                    _guardar_imagen(archivo, recorte)
                    fila[zona.nombre] = lectura.valor
                    fila[f"{zona.nombre}_confianza"] = lectura.confianza
                    fila[f"{zona.nombre}_estado"] = "aceptada" if lectura.aceptada else lectura.motivo
                    fila[f"{zona.nombre}_ocr"] = lectura.texto_ocr
                    fila[f"{zona.nombre}_evidencia"] = str(archivo)
                fila["_estabilizacion"] = " | ".join(estados) if estados else "sin estabilización"
                prefijo = f"etapa_{numero_etapa:02d}_" if len(etapas) > 1 else ""
                original = evidencia / f"{prefijo}original_frame_{numero_frame:06d}.jpg"
                _guardar_imagen(original, frame)
                captura = _anotar_fotograma(frame, zonas, fila)
                captura_path = evidencia / f"{prefijo}captura_frame_{numero_frame:06d}.jpg"
                _guardar_imagen(captura_path, captura)
                validacion = _crear_validacion_ampliada(frame, zonas, fila)
                validacion_path = evidencia / f"{prefijo}validacion_frame_{numero_frame:06d}.jpg"
                _guardar_imagen(validacion_path, validacion)
                fila["_captura_excel"] = str(captura_path)
                fila["_validacion"] = str(validacion_path)
                filas.append(fila)
                procesadas += 1
                if progreso:
                    progreso(procesadas, total_muestras, numero_etapa, len(etapas))
        if cancelar is not None and cancelar():
            raise ProcesamientoCancelado("Exportación cancelada por el usuario.")
        fin_video = max(0.0, (total - 1) / fps)
        rangos_s = {
            numero: (inicio, fin_video if fin is None else min(fin, fin_video))
            for numero, (inicio, fin) in enumerate(etapas, start=1)
        }
        _escribir_excel(filas, zonas, salida, list(range(1, len(etapas) + 1)), rangos_s)
        return filas
    finally:
        cap.release()
