# Lector de mediciones en video — Proyecto laser

Aplicación de visión por computadora para extraer mediciones de videos y documentar los resultados en Excel. El proyecto está basado en [`mp4-ocr-analyzer`](https://github.com/lohnjouis/mp4-ocr-analyzer), de lohnjouis, con funciones adaptadas y ampliadas para un flujo de lectura más específico: varias zonas de lectura, intervalos o etapas, navegación y estabilización experimental, evidencia por fotograma y reportes Excel.

El código disponible se reconstruyó con ayuda de IA a partir de tres grabaciones de pantalla, ya que no se contó con el código fuente original. Por ello, esta carpeta **no es una restauración exacta** y algunos módulos y bloques se reimplementaron. Consulte `INFORME_RECUPERACION.md` para conocer el alcance y las limitaciones de la reconstrucción.

## Atribución

Este proyecto está basado en [`lohnjouis/mp4-ocr-analyzer`](https://github.com/lohnjouis/mp4-ocr-analyzer). Se incorporaron y adaptaron funciones para un uso más específico, descritas arriba y en el informe de reconstrucción. La versión actual se reconstruyó a partir de grabaciones del código previo; no se contó con los archivos originales para hacer una comparación línea por línea.

El repositorio de referencia no muestra un archivo de licencia. Si se confirma que se conserva código fuente de ese repositorio, su publicación debe contar con la autorización o licencia correspondiente. Esta atribución documenta el origen recordado del proyecto y no afirma que el código reconstruido sea idéntico al repositorio de referencia.

## Instalación en Windows (Python 3.11 recomendado)

Abra PowerShell en esta carpeta (de preferencia fuera de la unidad institucional afectada):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Si PowerShell bloquea la activación, ejecute directamente:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Si no tiene Python 3.11, puede reemplazar `py -3.11` por `py -3` (versión 3.10 o superior).

## Uso básico

1. Elija un video; confirme que se puede navegar en él.
2. Dibuje un rectángulo en torno a cada lectura numérica; asigne un nombre y la cantidad de decimales que realmente aparecen (hasta 4 mediciones).
3. Seleccione una zona y presione **Probar lectura** antes de procesar todo el video. Requiere `rapidocr-onnxruntime`.
4. Defina el periodo de muestreo y los intervalos en segundos, por ejemplo `0-12, 23-45`. `0-` significa hasta el fin del video.
5. Para estabilizar: seleccione una zona, marque un ancla fija cercana al valor, pruebe la comparación y habilite su aplicación al generar el Excel.
6. Seleccione **Generar Excel**. El programa guarda un `.xlsx` y una carpeta de imágenes de evidencia con nombres únicos, junto al video.

El Excel incluye una última hoja **Resumen de secciones**, con el inicio y final en segundos de cada intervalo y un enlace a su hoja de lecturas. Los intervalos abiertos terminan en el último fotograma del video.

### Navegación y selección visual

- Use **−5 s** y **+5 s** para retroceder y avanzar cinco segundos.
- La franja bajo el deslizador muestra en verde los intervalos seleccionados para exportar; no indica que ya hayan sido procesados. Inicialmente está seleccionado todo el video.
- **Marcar inicio** deja una marca naranja pendiente. Navegue al final del tramo y pulse **Marcar final** para guardarlo en verde. Puede agregar más tramos sin traslaparlos.
- **Cancelar marca** descarta el inicio pendiente sin borrar los intervalos guardados.
- El indicador azul muestra la posición actual. Haga clic en la franja para navegar; sus marcas se actualizan también al editar los intervalos manualmente.

La detección automática de etapas a partir de una señal visual es experimental y las propuestas deben ser aprobadas manualmente.

## Pruebas automatizadas

```powershell
python -m unittest discover -s tests -v
```

Se ejecutan con OCR simulado y un video sintético; no validan precisión de lectura real.

## API del motor (sin interfaz)

```python
from motor import ZonaLectura, RapidOcr, procesar_video

filas = procesar_video(
    video="ejemplo.mp4",
    zonas=[ZonaLectura("Velocidad", 100, 180, 240, 70, decimales=2)],
    periodo_s=1.0,
    ocr=RapidOcr(),
    salida_xlsx="lecturas.xlsx",
    evidencia_dir="evidencias",
    intervalos=[(0.0, 10.0)],
)
print(len(filas))
```

Ajuste las coordenadas del ejemplo a las lecturas reales. La normalización descarta números sin punto decimal cuando `decimales > 0`, conforme a lo visible en la grabación original.

## Limitaciones

Los módulos auxiliares son reimplementaciones; algunas líneas de `motor.py` y `app.py` también fueron inferidas. El autor confirma que el proyecto se probó con videos reales y funcionó; no se conservaron métricas cuantitativas de esa validación. Consulte el informe para detalles de trazabilidad y riesgos.
