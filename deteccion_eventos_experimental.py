"""Detección de intervalos propuesta para la interfaz recuperada.

Reconstrucción sustitutiva: no se pudo ver el contenido del módulo original.
Las propuestas deben revisarse visualmente antes de exportar mediciones.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import cv2
import numpy as np


def preparar_referencia(imagen: np.ndarray, zona: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Crea una referencia BGR recortada y preprocesada para comparar."""
    if zona:
        x, y, ancho, alto = map(int, zona)
        # Puede recibir el fotograma completo o un recorte ya seleccionado.
        if imagen.shape[1] != ancho or imagen.shape[0] != alto:
            imagen = imagen[max(0,y):max(0,y)+alto, max(0,x):max(0,x)+ancho]
    if imagen.size == 0:
        raise ValueError("La región usada para referencia está vacía.")
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    return cv2.GaussianBlur(gris, (5, 5), 0)


def proponer_periodos_en_video(
    video: str | Path,
    zona: tuple[int, int, int, int],
    referencia: np.ndarray | None = None,
    umbral: float = 0.12,
    muestreo_s: float = 0.2,
    minimo_s: float = 0.5,
    *args: Any, **kwargs: Any,
) -> list[tuple[float, float]]:
    """Propone segmentos cuyo contenido difiere de la referencia.

    No debe asumirse que detecta los eventos exactamente igual al código perdido.
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir {video}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        saltar = max(1, int(round(fps * muestreo_s)))
        ref = preparar_referencia(referencia, zona) if referencia is not None else None
        actividad: list[tuple[float, bool]] = []
        for frame_idx in range(0, total, saltar):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok:
                continue
            muestra = preparar_referencia(frame, zona)
            if ref is None:
                ref = muestra
            if muestra.shape != ref.shape:
                muestra = cv2.resize(muestra, (ref.shape[1], ref.shape[0]))
            diferencia = float(cv2.absdiff(muestra, ref).mean() / 255.0)
            actividad.append((frame_idx / fps, diferencia >= umbral))
        segmentos: list[tuple[float, float]] = []
        inicio: float | None = None
        anterior = 0.0
        for tiempo, encendido in actividad:
            if encendido and inicio is None:
                inicio = tiempo
            if not encendido and inicio is not None:
                if anterior - inicio >= minimo_s:
                    segmentos.append((round(inicio, 3), round(anterior, 3)))
                inicio = None
            anterior = tiempo
        if inicio is not None and anterior - inicio >= minimo_s:
            segmentos.append((round(inicio, 3), round(anterior, 3)))
        return segmentos
    finally:
        cap.release()
