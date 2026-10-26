# Lector de mediciones en video

Aplicación de visión por computadora para extraer mediciones numéricas de videos mediante OCR y guardar los resultados en Excel. El proyecto toma como referencia [`mp4-ocr-analyzer`](https://github.com/lohnjouis/mp4-ocr-analyzer) y adapta su propósito a un flujo de trabajo con varias zonas de lectura, selección de intervalos, navegación por el video, evidencia por fotograma y resumen de secciones.

La versión disponible se reconstruyó con ayuda de IA a partir de grabaciones de pantalla, ya que no se contó con el código fuente original. Algunos componentes son reimplementaciones.

## Requisitos

- Windows 10 o posterior.
- Python 3.10 o superior (se recomienda Python 3.11).
- Dependencias indicadas en `requirements.txt`.

## Instalación

Abra PowerShell en la carpeta del proyecto y ejecute:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Si Python 3.11 no está instalado, puede utilizar `py -3` con Python 3.10 o superior. Si PowerShell no permite activar el entorno, ejecute:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

También puede iniciar la aplicación con `ejecutar.bat`.

## Uso básico

1. Abra un video y dibuje una zona alrededor de cada valor que se desea leer. Se pueden configurar hasta cuatro zonas.
2. Pruebe la lectura de cada zona y ajuste sus parámetros.
3. Defina el periodo de muestreo y los intervalos que se procesarán.
4. Navegue por el video y marque los tramos de interés. Los controles de −1 s, +1 s, −5 s, +5 s, −10 s y +10 s permiten ajustar la posición.
5. Genere el archivo Excel. El libro y las imágenes de evidencia se guardan junto al video.

El libro incluye una hoja de resumen con el rango de segundos de cada sección. La franja de navegación muestra los intervalos seleccionados. La detección automática de etapas y la estabilización son funciones experimentales; sus resultados deben revisarse.

## Pruebas

Para ejecutar las pruebas automatizadas:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas utilizan OCR simulado y videos sintéticos. La precisión del OCR depende de la calidad del video, el enfoque y la legibilidad de los valores.
