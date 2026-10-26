# Informe de reconstrucción de código — Proyecto laser

**Fecha:** 21 de octubre de 2026  
**Fuente:** grabaciones originales del 20 de octubre de 2026, disponibles en la carpeta `Ocr` de Google Drive.  
**Propósito:** reconstruir un entorno funcional de lectura OCR de mediciones en videos tras la pérdida de acceso al proyecto.

## Origen y atribución del proyecto

El proyecto previo del autor se considera basado en [`lohnjouis/mp4-ocr-analyzer`](https://github.com/lohnjouis/mp4-ocr-analyzer), al que se agregaron y adaptaron funciones para un flujo de lectura más específico. El equipo donde estaba el código original sufrió un incidente de seguridad y no fue posible recuperar sus archivos fuente; la versión de esta carpeta se reconstruyó con ayuda de IA a partir de las grabaciones enumeradas abajo. No se realizó una comparación línea por línea con el repositorio de referencia ni con los archivos originales, por lo que este informe documenta el origen recordado y el método de reconstrucción, no una equivalencia exacta entre códigos.

El repositorio de referencia no muestra un archivo de licencia. Si se confirma que la versión reconstruida conserva código fuente de ese repositorio, la publicación debe contar con la autorización o licencia correspondiente.

## Grabaciones examinadas

| Grabación | Duración | Archivo que aparece en VS Code |
|---|---:|---|
| `20261020_160730.mp4` | 34.27 s | `motor.py` |
| `20261020_160824_parte_01.mp4` | 47.25 s | `app.py` |
| `20261020_160824_parte_02.mp4` | 46.97 s | `app.py` |

Las grabaciones son fotografías en video de un monitor que desplaza las líneas con rapidez; algunas secciones están parcialmente tapadas, repetidas o desenfocadas. No disponemos de los archivos `.py` originales ni de su historial de versiones. **Lo recuperado NO es una transcripción íntegra idéntica al original.**

## Componentes entregados

| Archivo | Origen y confianza de reconstrucción | Función |
|---|---|---|
| `motor.py` | Firmas, nombres y partes del flujo contrastados con `160730`; bloques ocultos reimplementados | OCR, validación, captura de evidencia y Excel |
| `app.py` | Diseño, métodos y estados contrastados con ambas partes de `160824`; detalles faltantes reimplementados | Interfaz Tkinter, zonas, navegación, zoom, estabilización, propuestas de etapas, exportación asíncrona |
| `estabilizacion_experimental.py` | **Reimplementación no transcrita**; el video solo muestra importación e invocación | Estabilización por OpenCV ECC (traslación) |
| `deteccion_eventos_experimental.py` | **Reimplementación no transcrita**; el video muestra importación y uso | Propone intervalos con detección de cambios en señal visual |
| `tests/test_recuperacion.py` | Código nuevo de verificación | Pruebas funcionales con datos sintéticos |

## Elementos identificados directamente en pantalla

- `ZonaLectura` admite un nombre, coordenadas `x, y`, ancho, alto, decimales esperados y confianza mínima.
- `RapidOcr` está asociado con `rapidocr_onnxruntime`.
- La función `procesar_video` acepta periodos, intervalos, hasta cuatro zonas, una o varias anclas de estabilización, callbacks de progreso y cancelación.
- Las imágenes de cada lectura, del fotograma original, de la captura anotada y de validación ampliada forman parte de la auditoría.
- Se usan `openpyxl`, hojas `lecturas`/`detalle` o un par de hojas por etapa.
- La interfaz original permite marcación de etapas, prueba de zona, selección de ROI para estabilización, zoom y un asistente de detección de señal.

## Qué no está garantizado

1. No se recuperó el código fuente literal de los archivos auxiliares `estabilizacion_experimental.py` ni `deteccion_eventos_experimental.py`.
2. No se pudo verificar el reconocimiento OCR sobre un video de calibración del usuario por falta del modelo OCR original y de sus datos medidos esperados; el entorno de prueba no tenía `rapidocr-onnxruntime` instalado.
3. Los criterios de umbral de la detección automática de intervalos se sustituyeron por una propuesta aproximada y requieren evaluación en datos reales.
4. La precisión de ECC depende de elegir un ancla fija con textura suficiente y de cambios pequeños entre fotogramas.
5. La posición, colores y algunas etiquetas de la interfaz pueden variar frente a la versión original.
6. No se recuperaron otros documentos, pruebas de laboratorio, configuraciones institucionales ni archivos fuera de las tres grabaciones.

## Verificación realizada

- `python -m py_compile` sobre los cuatro archivos: **correcto**.
- Pruebas automáticas con video sintético y OCR de prueba: **7/7 pasadas**.
- Inicio de aplicación Tkinter bajo Xvfb: **correcto**.
- Apertura de video sintético, vista previa, selección de zona, navegación de tiempo y zoom: **correcto**.
- Creación de dos etapas Excel con lecturas y archivos evidencia: **correcto**.
- Cancelación antes de procesar que no deja Excel final: **correcto**.
- **Pendiente:** instalar el OCR real en equipo controlado y validar contra videos/datos de referencia.

## Seguridad y conservación

El código recuperado no contiene conexiones de red, credenciales ni funciones que alteren las grabaciones fuente. La evidencia y el Excel se guardan al lado del video seleccionado y no sustituyen el archivo original. Dada la incidencia de seguridad mencionada, **ejecutar únicamente en un equipo/entorno autorizado y confiable**, fuera de carpetas sincronizadas que puedan seguir afectadas. Conservar los videos originales como prueba y revisar las rutas antes de exportar.

## Siguiente validación recomendada

Usar un video de prueba corto con tres o cuatro lecturas cuya referencia esté registrada. Comparar manualmente cada OCR con el valor visible, revisar porcentaje de lecturas aceptadas y errores, verificar los recortes y evaluar si la estabilización mejora los resultados antes de usar en calibraciones reales.
