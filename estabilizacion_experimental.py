"""Reconstrucción funcional del alineador de traslación usado por motor.py.

El archivo original no aparece desplegado en las grabaciones. El contrato de
alinear_traslacion se dedujo de su invocación en motor.py y app.py.
"""
from __future__ import annotations
import cv2
import numpy as np


def alinear_traslacion(referencia: np.ndarray, actual: np.ndarray,
                       ancla: tuple[int, int, int, int]) -> tuple[np.ndarray, float, float, float]:
    """Alinea el cuadro actual contra el primero usando ECC en un área estable.

    Devuelve (fotograma_alineado, dx, dy, coeficiente_ECC). No gira ni escala.
    Las coordenadas del ancla son (x, y, ancho, alto) del video original.
    """
    x, y, ancho, alto = map(int, ancla)
    if ancho <= 4 or alto <= 4:
        raise ValueError("El ancla es demasiado pequeña para estabilizar.")
    if referencia.shape[:2] != actual.shape[:2]:
        raise ValueError("Los fotogramas deben tener iguales dimensiones.")
    h, w = referencia.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + ancho), min(h, y + alto)
    if x2 - x1 < 5 or y2 - y1 < 5:
        raise ValueError("El ancla está fuera del video.")
    a = cv2.cvtColor(referencia[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(actual[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    a = cv2.GaussianBlur(a, (5, 5), 0).astype(np.float32) / 255.0
    b = cv2.GaussianBlur(b, (5, 5), 0).astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    criterios = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
    ecc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_TRANSLATION,
                                    criterios, None, 5)
    alineado = cv2.warpAffine(actual, warp, (w, h),
                             flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_REPLICATE)
    return alineado, float(warp[0, 2]), float(warp[1, 2]), float(ecc)
