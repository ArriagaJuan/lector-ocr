# Lector de mediciones en video

Desarrollé esta aplicación para leer mediciones numéricas en videos con OCR y guardar los resultados en un archivo Excel. Tomé como referencia [`mp4-ocr-analyzer`](https://github.com/lohnjouis/mp4-ocr-analyzer) y adapté el proyecto a mi flujo de trabajo, con varias zonas de lectura, selección de intervalos, navegación por el video, evidencia por fotograma y resumen de secciones en Excel.

Reconstruí la versión actual con ayuda de IA a partir de grabaciones de pantalla, porque no tenía disponible el código fuente original. Por eso, algunos componentes son reimplementaciones.

## Requisitos

- Windows 10 o posterior.
- Python 3.10 o superior; recomiendo Python 3.11.
- Dependencias instaladas desde `requirements.txt`.

## Instalación

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Si no tienes Python 3.11, puedes usar `py -3` con Python 3.10 o superior. Si PowerShell no permite activar el entorno, ejecuta:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

También puedes iniciar el programa con `ejecutar.bat`.

## Uso básico

1. Abro un video y dibujo una zona alrededor de cada valor que quiero leer. Puedo configurar hasta cuatro zonas.
2. Pruebo la lectura de cada zona y ajusto sus parámetros.
3. Elijo el periodo de muestreo y los intervalos que quiero procesar.
4. Uso los controles para navegar por el video y marcar los tramos de interés. Los botones de −1 s, +1 s, −5 s, +5 s, −10 s y +10 s permiten ajustar la posición.
5. Inicio la generación del Excel. Junto al video se guardan el libro de resultados y las imágenes de evidencia.

En el Excel incluyo una hoja de resumen con el rango de segundos de cada sección. La franja de navegación muestra visualmente los intervalos seleccionados. La detección automática de etapas y la estabilización son funciones experimentales; reviso sus resultados antes de usarlos.

## Pruebas

Ejecuto las pruebas automatizadas con:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan OCR simulado y videos sintéticos. La precisión del OCR depende de la calidad del video, el enfoque y la legibilidad de los valores.
