"""Interfaz para seleccionar zonas de medición y exportar videos a Excel.

RECUPERACIÓN 2026-10-21 desde 20261020_160824_parte_01/02.mp4.
La estructura y la mayoría de los controles se ven en los videos, pero las
secciones faltantes se han reimplementado (no es copia exacta del original).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import cv2
from PIL import Image, ImageTk

from deteccion_eventos_experimental import preparar_referencia, proponer_periodos_en_video
from estabilizacion_experimental import alinear_traslacion
from motor import ProcesamientoCancelado, RapidOcr, ZonaLectura, leer_zona, procesar_video


def fraccion_scroll_para_ancla(punto_original: float, escala_nueva: float,
                               punto_visor: float, medida_visible: int,
                               medida_contenido: int) -> float:
    """Conserva un píxel bajo el cursor después de redibujar un Canvas."""
    recorrido = max(0, medida_contenido - medida_visible)
    if recorrido == 0:
        return 0.0
    destino = punto_original * escala_nueva - punto_visor
    return max(0.0, min(1.0, destino / recorrido))


def rutas_de_exportacion(video: Path) -> tuple[Path, Path]:
    """Genera rutas únicas para el Excel y la evidencia, sin sobrescribir."""
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = video.with_name(f"lecturas_{video.stem}_{marca}.xlsx")
    evidencia = video.with_name(f"evidencia_{video.stem}_{marca}")
    indice = 2
    while salida.exists() or evidencia.exists():
        salida = video.with_name(f"lecturas_{video.stem}_{marca}_{indice}.xlsx")
        evidencia = video.with_name(f"evidencia_{video.stem}_{marca}_{indice}")
        indice += 1
    return salida, evidencia


def parsear_etapas(texto: str) -> list[tuple[float, float | None]]:
    """Convierte '1-12, 23-45' en intervalos sin traslape."""
    limpio = (texto.replace("–", "-").replace("—", "-")
              .replace(";", ",").replace("\n", ","))
    etapas: list[tuple[float, float | None]] = []
    for fragmento in (parte.strip() for parte in limpio.split(",")):
        if not fragmento:
            continue
        if fragmento.count("-") != 1:
            raise ValueError(f'La etapa "{fragmento}" debe tener formato inicio-fin, por ejemplo 1-12.')
        inicio_texto, fin_texto = (valor.strip() for valor in fragmento.split("-", 1))
        if not inicio_texto:
            raise ValueError("Cada etapa debe indicar el segundo inicial.")
        inicio = float(inicio_texto)
        fin = float(fin_texto) if fin_texto else None
        if inicio < 0 or (fin is not None and fin < inicio):
            raise ValueError(f'La etapa "{fragmento}" no tiene un intervalo válido.')
        etapas.append((inicio, fin))
    ordenadas = sorted(etapas, key=lambda etapa: etapa[0])
    for anterior, actual in zip(ordenadas, ordenadas[1:]):
        if anterior[1] is None or actual[0] <= anterior[1]:
            raise ValueError("Las etapas no deben traslaparse.")
    return etapas


def agregar_etapa_marcada(texto_actual: str, inicio: float, fin: float) -> str:
    nueva = f"{inicio:g}-{fin:g}"
    combinado = f"{texto_actual.strip()}, {nueva}" if texto_actual.strip() else nueva
    parsear_etapas(combinado)
    return combinado


class Aplicacion(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Lector de mediciones de video · Recuperación")
        self.geometry("1370x880")
        self.minsize(1030, 620)
        self._video: Path | None = None
        self._frame = None
        self._foto = None
        self._escala = 1.0
        self._zoom = 1.0
        self._zonas: list[ZonaLectura] = []
        self._inicio: tuple[int, int] | None = None
        self._rectangulo: int | None = None
        self._modo_ancla = False
        self._zona_ancla: str | None = None
        self._anclas_estabilizacion: dict[str, tuple[int, int, int, int]] = {}
        self._procesando = False
        self._cancelar_proceso = threading.Event()
        self._resultados: queue.Queue[tuple[str, object]] = queue.Queue()
        self._fps_video = 1.0
        self._duracion_video_s = 0.0
        self._tiempo_navegador_s = 0.0
        self._inicio_etapa_marcada: float | None = None
        self._actualizando_deslizador = False
        self._asistente_senal_visible = False
        self._modo_senal = False
        self._zona_senal: tuple[int, int, int, int] | None = None
        self._referencia_senal_presente = None
        self._referencia_senal_ausente = None
        self._resultados_senal: queue.Queue[tuple[str, object]] = queue.Queue()
        self._pan_inicio = None
        self._crear_interfaz()
        self.after(100, self._revisar_resultados)

    def _crear_interfaz(self) -> None:
        barra = ttk.Frame(self, padding=8)
        barra.pack(fill="x")
        self._seleccionar_btn = ttk.Button(barra, text="Seleccionar video...", command=self._abrir_video)
        self._seleccionar_btn.pack(side="left")
        self._video_label = ttk.Label(barra, text="Aún no se ha seleccionado un video")
        self._video_label.pack(side="left", padx=10)
        ttk.Label(barra, text="Rueda: zoom en el cursor · Botón central: mover · Mayús+rueda: desplazar").pack(side="left", padx=10)
        ttk.Button(barra, text="− Zoom", command=lambda: self._cambiar_zoom(1 / 1.25)).pack(side="right")
        self._zoom_texto = tk.StringVar(value="100 %")
        ttk.Label(barra, textvariable=self._zoom_texto).pack(side="right", padx=10)
        ttk.Button(barra, text="+ Zoom", command=lambda: self._cambiar_zoom(1.25)).pack(side="right")
        ttk.Button(barra, text="Ajustar", command=self._ajustar_zoom).pack(side="right", padx=6)

        contenido = ttk.Frame(self, padding=(8, 0, 8, 8))
        contenido.pack(fill="both", expand=True)
        contenido.columnconfigure(0, weight=1)
        contenido.rowconfigure(0, weight=1)

        visor = ttk.Frame(contenido)
        visor.grid(row=0, column=0, sticky="nsew")
        visor.rowconfigure(0, weight=1)
        visor.columnconfigure(0, weight=1)
        self._lienzo = tk.Canvas(visor, background="#15191f", cursor="crosshair", highlightthickness=0)
        self._lienzo.grid(row=0, column=0, sticky="nsew")
        barra_y = ttk.Scrollbar(visor, orient="vertical", command=self._lienzo.yview)
        barra_y.grid(row=0, column=1, sticky="ns")
        barra_x = ttk.Scrollbar(visor, orient="horizontal", command=self._lienzo.xview)
        barra_x.grid(row=1, column=0, sticky="ew")
        self._lienzo.configure(xscrollcommand=barra_x.set, yscrollcommand=barra_y.set)
        self._lienzo.bind("<ButtonPress-1>", self._empezar_rectangulo)
        self._lienzo.bind("<B1-Motion>", self._arrastrar_rectangulo)
        self._lienzo.bind("<ButtonRelease-1>", self._terminar_rectangulo)
        self._lienzo.bind("<MouseWheel>", self._zoom_con_rueda)
        self._lienzo.bind("<Shift-MouseWheel>", self._desplazar_horizontal_con_rueda)
        self._lienzo.bind("<ButtonPress-2>", self._empezar_pan)
        self._lienzo.bind("<B2-Motion>", self._arrastrar_pan)
        self._lienzo.bind("<ButtonRelease-2>", self._terminar_pan)
        self._lienzo.bind("<Button-4>", lambda e: self._cambiar_zoom(1.25, (e.x, e.y)))
        self._lienzo.bind("<Button-5>", lambda e: self._cambiar_zoom(1 / 1.25, (e.x, e.y)))

        navegador = ttk.LabelFrame(visor, text="Navegador del video", padding=6)
        navegador.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        navegador.columnconfigure(0, weight=1)
        self._tiempo_texto = tk.StringVar(value="0.00 s / 0.00 s")
        self._deslizador = ttk.Scale(navegador, from_=0, to=1, orient="horizontal",
                                    command=self._mover_deslizador)
        self._deslizador.grid(row=0, column=0, sticky="ew")
        ttk.Label(navegador, textvariable=self._tiempo_texto).grid(row=0, column=1, padx=6)
        botones_tiempo = ttk.Frame(navegador)
        botones_tiempo.grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        self._linea_etapas = tk.Canvas(navegador, height=46, background="#f1f5f9",
                                       highlightthickness=0)
        self._linea_etapas.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._linea_etapas.bind("<Configure>", lambda e: self._dibujar_etapas())
        self._linea_etapas.bind("<Button-1>", self._navegar_en_etapas)
        ttk.Label(navegador, text="Verde: seleccionado · Naranja: inicio pendiente · Azul: posición actual"
                  ).grid(row=2, column=0, columnspan=2, sticky="w")
        botones_tiempo.grid_configure(row=3)
        for texto, desplazamiento in (("−10 s", -10), ("−5 s", -5), ("−1 s", -1), ("−1 frame", "-f"),
                                      ("+1 frame", "+f"), ("+1 s", 1), ("+5 s", 5), ("+10 s", 10)):
            ttk.Button(botones_tiempo, text=texto,
                       command=lambda delta=desplazamiento: self._mover_tiempo(delta)).pack(side="left", padx=2)
        marcas = ttk.Frame(navegador)
        marcas.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Button(marcas, text="Marcar inicio", command=self._marcar_inicio).pack(side="left", padx=2)
        self._marcar_final_btn = ttk.Button(marcas, text="Marcar final", command=self._marcar_fin,
                                           state="disabled")
        self._marcar_final_btn.pack(side="left", padx=2)
        self._cancelar_marca_btn = ttk.Button(marcas, text="Cancelar marca", command=self._cancelar_marca,
                                             state="disabled")
        self._cancelar_marca_btn.pack(side="left", padx=2)
        self._ayuda_marca = ttk.Label(marcas, text="Marca el inicio y luego el final del tramo.")
        self._ayuda_marca.pack(side="left", padx=8)

        lateral = ttk.Frame(contenido, width=330)
        lateral.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        lateral.grid_propagate(False)
        scroll_container = tk.Canvas(lateral, width=330, highlightthickness=0)
        scroll_y = ttk.Scrollbar(lateral, orient="vertical", command=scroll_container.yview)
        scroll_y.pack(side="right", fill="y")
        scroll_container.pack(fill="both", expand=True)
        scroll_container.configure(yscrollcommand=scroll_y.set)
        panel = ttk.Frame(scroll_container, padding=2)
        win = scroll_container.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda e: scroll_container.configure(scrollregion=scroll_container.bbox("all")))
        scroll_container.bind("<Configure>", lambda e: scroll_container.itemconfigure(win, width=e.width))

        mediciones = ttk.LabelFrame(panel, text="1. Mediciones (máximo 4)", padding=8)
        mediciones.pack(fill="x", pady=(0, 8))
        ttk.Label(mediciones, text="Dibuja un rectángulo sobre cada número y asígnale un nombre.",
                  wraplength=300).pack(anchor="w", pady=5)
        self._tabla = ttk.Treeview(mediciones, columns=("nombre", "decimales"),
                                   show="headings", height=5)
        self._tabla.heading("nombre", text="Nombre en Excel")
        self._tabla.heading("decimales", text="Decimales")
        self._tabla.column("nombre", width=185, minwidth=110)
        self._tabla.column("decimales", width=90, anchor="center")
        self._tabla.pack(fill="x", pady=(4, 8))
        self._tabla.bind("<<TreeviewSelect>>", self._al_elegir_zona)
        acciones_medicion = ttk.Frame(mediciones)
        acciones_medicion.pack(fill="x")
        self._editar_btn = ttk.Button(acciones_medicion, text="Editar", command=self._editar_zona)
        self._editar_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._quitar_btn = ttk.Button(acciones_medicion, text="Quitar", command=self._quitar_zona)
        self._quitar_btn.pack(side="left", expand=True, fill="x")
        self._probar_btn = ttk.Button(mediciones, text="Probar lectura de la medición elegida",
                                      command=self._probar_zona)
        self._probar_btn.pack(fill="x", pady=(7, 0))

        estabilizacion = ttk.LabelFrame(panel, text="2. Estabilización opcional", padding=8)
        estabilizacion.pack(fill="x", pady=(0, 8))
        self._ancla_btn = ttk.Button(estabilizacion, text="Marcar área fija de la medición elegida",
                                     command=self._marcar_ancla)
        self._ancla_btn.pack(fill="x", pady=3)
        self._probar_estabilizacion_btn = ttk.Button(
            estabilizacion, text="Ver prueba antes / después", command=self._probar_estabilizacion)
        self._probar_estabilizacion_btn.pack(fill="x", pady=3)
        self._usar_estabilizacion = tk.BooleanVar(value=False)
        self._usar_estabilizacion_btn = ttk.Checkbutton(estabilizacion,
            text="Aplicar al generar Excel", variable=self._usar_estabilizacion)
        self._usar_estabilizacion_btn.pack(anchor="w", pady=5)
        self._estado_ancla = ttk.Label(estabilizacion, text="Opcional: marca un ancla fuera de la lectura.",
                                        wraplength=305)
        self._estado_ancla.pack(anchor="w")

        asistencia = ttk.LabelFrame(panel, text="3. Asistente de periodos", padding=8)
        asistencia.pack(fill="x", pady=(0, 8))
        ttk.Label(asistencia, text="Detectar cambios de una señal visible para sugerir intervalos.",
                  wraplength=300).pack(anchor="w")
        self._buscar_senal_btn = ttk.Button(asistencia, text="Marcar área de señal",
                                            command=self._marcar_senal)
        self._buscar_senal_btn.pack(fill="x", pady=3)
        self._referencia_presente_btn = ttk.Button(asistencia, text="Fijar señal presente",
                                                  command=lambda: self._guardar_referencia_senal(True))
        self._referencia_presente_btn.pack(fill="x", pady=2)
        self._referencia_ausente_btn = ttk.Button(asistencia, text="Fijar señal ausente",
                                                 command=lambda: self._guardar_referencia_senal(False))
        self._referencia_ausente_btn.pack(fill="x", pady=2)
        self._analizar_btn = ttk.Button(asistencia, text="Proponer etapas automáticamente",
                                       command=self._detectar_etapas)
        self._analizar_btn.pack(fill="x", pady=3)
        self._estado_senal = ttk.Label(asistencia, text="La detección es experimental; revisar propuestas.",
                                       wraplength=305)
        self._estado_senal.pack(anchor="w")

        exportacion = ttk.LabelFrame(panel, text="4. Exportación", padding=8)
        exportacion.pack(fill="x")
        frecuencia = ttk.Frame(exportacion)
        frecuencia.pack(fill="x", pady=(0, 8))
        ttk.Label(frecuencia, text="Tomar una lectura cada (s):").pack(side="left")
        self._periodo = tk.StringVar(value="1")
        ttk.Entry(frecuencia, textvariable=self._periodo, width=8).pack(side="left", padx=6)
        ttk.Label(exportacion, text="Periodos a leer (inicio-fin)").pack(anchor="w")
        self._etapas_s = tk.StringVar(value="0-")
        entrada = ttk.Entry(exportacion, textvariable=self._etapas_s)
        entrada.pack(fill="x", pady=(2, 5))
        entrada.bind("<FocusOut>", lambda e: self._actualizar_resumen_etapas())
        ttk.Button(exportacion, text="Todo el video", command=lambda: self._usar_etapas_rapidas("0-")) .pack(anchor="w")
        self._resumen_etapas = ttk.Label(exportacion, wraplength=300, justify="left")
        self._resumen_etapas.pack(anchor="w", pady=(0, 8))
        self._etapas_s.trace_add("write", lambda *_: self._actualizar_resumen_etapas())
        self._periodo.trace_add("write", lambda *_: self._actualizar_resumen_etapas())
        acciones = ttk.Frame(exportacion)
        acciones.pack(fill="x")
        self._generar = ttk.Button(acciones, text="Generar Excel", command=self._generar_excel)
        self._generar.pack(side="left", fill="x", expand=True)
        self._cancelar_exportacion_btn = ttk.Button(acciones, text="Cancelar exportación",
                                                      command=self._cancelar_exportacion, state="disabled")
        self._cancelar_exportacion_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Label(exportacion, text="Puedes usar decimales: 0.02 s toma cada fotograma disponible (según FPS).",
                  wraplength=300).pack(anchor="w", pady=(5, 0))
        self._progreso_texto = tk.StringVar(value="Preparando exportación...")
        ttk.Label(exportacion, textvariable=self._progreso_texto).pack(anchor="w", pady=(6, 2))
        self._barra_progreso = ttk.Progressbar(exportacion, mode="determinate", maximum=100)
        self._barra_progreso.pack(fill="x")
        self._estado = ttk.Label(panel, text="Paso 1: selecciona un video. Paso 2: dibuja una zona.",
                                  wraplength=320)
        self._estado.pack(anchor="w", pady=9)
        self._actualizar_resumen_etapas()
        self._actualizar_tabla()

    def _usar_etapas_rapidas(self, texto: str) -> None:
        self._etapas_s.set(texto)

    def _actualizar_resumen_etapas(self) -> None:
        self._dibujar_etapas()
        try:
            etapas = parsear_etapas(self._etapas_s.get())
            periodo = float(self._periodo.get())
            if periodo <= 0:
                raise ValueError("periodo inválido")
            descripcion = ", ".join(f"{inicio:g}–{fin:g}" if fin is not None else f"{inicio:g}–final"
                                     for inicio, fin in etapas)
            self._resumen_etapas.configure(text=f"{len(etapas)} etapa(s): {descripcion or 'ninguna'}")
        except ValueError as exc:
            self._resumen_etapas.configure(text=f"Revisar intervalos: {exc}")

    def _dibujar_etapas(self) -> None:
        lienzo = self._linea_etapas
        lienzo.delete("all")
        ancho = max(1, lienzo.winfo_width() - 20)
        lienzo.create_rectangle(10, 8, 10 + ancho, 26, fill="#cbd5e1", outline="")
        duracion = self._duracion_video_s
        if self._video is None or duracion <= 0:
            return
        def x(t):
            return 10 + ancho * max(0, min(duracion, t)) / duracion
        try:
            etapas = parsear_etapas(self._etapas_s.get())
        except ValueError:
            etapas = []
        for inicio, fin in etapas:
            if inicio > duracion:
                continue
            final = duracion if fin is None else fin
            lienzo.create_rectangle(x(inicio), 8, x(final), 26, fill="#15803d", outline="")
            for tiempo in (inicio, min(final, duracion)):
                lienzo.create_line(x(tiempo), 5, x(tiempo), 29, fill="#166534", width=2)
            lienzo.create_text((x(inicio) + x(final)) / 2, 37,
                               text=f"{inicio:g}–{min(final, duracion):g} s", fill="#166534")
        if self._inicio_etapa_marcada is not None:
            posicion = x(self._inicio_etapa_marcada)
            lienzo.create_line(posicion, 2, posicion, 30, fill="#c2410c", width=3)
        posicion = x(self._tiempo_navegador_s)
        lienzo.create_polygon(posicion - 5, 0, posicion + 5, 0, posicion, 7, fill="#2563eb")
        lienzo.create_line(posicion, 7, posicion, 28, fill="#2563eb", width=2)

    def _navegar_en_etapas(self, evento) -> None:
        ancho = max(1, self._linea_etapas.winfo_width() - 20)
        self._ir_a_tiempo((evento.x - 10) / ancho * self._duracion_video_s)

    def _cancelar_marca(self) -> None:
        self._inicio_etapa_marcada = None
        self._marcar_final_btn.configure(state="disabled")
        self._cancelar_marca_btn.configure(state="disabled")
        self._ayuda_marca.configure(text="Marca el inicio y luego el final del tramo.")
        self._dibujar_etapas()

    def _abrir_video(self) -> None:
        ruta = filedialog.askopenfilename(title="Seleccionar video",
            filetypes=[("Videos", "*.mp4 *.avi *.mov *.mkv *.m4v"), ("Todos", "*.*")])
        if ruta:
            self.abrir_video(Path(ruta))

    def abrir_video(self, ruta: Path) -> None:
        cap = cv2.VideoCapture(str(ruta))
        try:
            if not cap.isOpened():
                raise ValueError("No se pudo abrir el video seleccionado.")
            self._fps_video = float(cap.get(cv2.CAP_PROP_FPS) or 1.0)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._duracion_video_s = max(0, (total - 1) / self._fps_video)
            ok, frame = cap.read()
            if not ok:
                raise ValueError("El video no tiene un primer fotograma legible.")
        except Exception as exc:
            messagebox.showerror("Video", str(exc))
            return
        finally:
            cap.release()
        self._video = Path(ruta)
        self._video_label.configure(text=self._video.name)
        self._zonas.clear()
        self._anclas_estabilizacion.clear()
        self._usar_estabilizacion.set(False)
        self._inicio_etapa_marcada = None
        self._ayuda_marca.configure(text="Marca el inicio y luego el final del tramo.")
        self._marcar_final_btn.configure(state="disabled")
        self._cancelar_marca_btn.configure(state="disabled")
        self._tiempo_navegador_s = 0
        self._zoom = 1
        self._deslizador.configure(to=max(.01, self._duracion_video_s))
        self._etapas_s.set("0-")
        self._mostrar_frame(frame)
        self._ir_a_tiempo(0)
        self._actualizar_tabla()
        self._estado.configure(text="Video seleccionado. Dibuja un rectángulo alrededor de una lectura.")

    def _leer_frame_en(self, tiempo_s: float):
        if self._video is None:
            return None
        cap = cv2.VideoCapture(str(self._video))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, round(max(0, tiempo_s) * self._fps_video))
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            cap.release()

    def _mover_deslizador(self, value: str) -> None:
        if self._video is None or self._actualizando_deslizador:
            return
        try:
            tiempo = float(value)
        except ValueError:
            return
        self._ir_a_tiempo(tiempo)

    def _ir_a_tiempo(self, tiempo: float) -> None:
        if self._video is None:
            return
        tiempo = max(0.0, min(self._duracion_video_s, tiempo))
        frame = self._leer_frame_en(tiempo)
        if frame is None:
            return
        self._tiempo_navegador_s = tiempo
        self._actualizando_deslizador = True
        try:
            self._deslizador.set(tiempo)
        finally:
            self._actualizando_deslizador = False
        self._mostrar_frame(frame)
        self._tiempo_texto.set(f"{tiempo:.2f} s / {self._duracion_video_s:.2f} s")
        self._dibujar_etapas()

    def _mover_tiempo(self, delta: int | str) -> None:
        cambio = (-1 if delta == "-f" else 1) / self._fps_video if isinstance(delta, str) else delta
        self._ir_a_tiempo(self._tiempo_navegador_s + cambio)

    def _marcar_inicio(self) -> None:
        if self._video is None:
            messagebox.showinfo("Etapa", "Primero selecciona un video.")
            return
        self._inicio_etapa_marcada = self._tiempo_navegador_s
        self._marcar_final_btn.configure(state="normal")
        self._cancelar_marca_btn.configure(state="normal")
        self._ayuda_marca.configure(text=f"Inicio: {self._inicio_etapa_marcada:.2f} s. Ahora marca el final.")
        self._dibujar_etapas()
        self._estado.configure(text=f"Inicio de etapa marcado en {self._inicio_etapa_marcada:.2f} s.")

    def _marcar_fin(self) -> None:
        inicio = self._inicio_etapa_marcada
        if inicio is None:
            messagebox.showinfo("Etapa", "Primero marca el inicio.")
            return
        fin = self._tiempo_navegador_s
        try:
            base = "" if self._etapas_s.get().strip() == "0-" else self._etapas_s.get()
            self._etapas_s.set(agregar_etapa_marcada(base, inicio, fin))
            self._cancelar_marca()
            self._estado.configure(text=f"Tramo seleccionado: {inicio:.2f}–{fin:.2f} s. Puedes marcar otro.")
        except ValueError as exc:
            messagebox.showerror("Etapa", str(exc))

    def _mostrar_frame(self, frame: Any) -> None:
        self._frame = frame
        if not self._lienzo.winfo_exists():
            return
        alto, ancho = frame.shape[:2]
        self._lienzo.update_idletasks()
        limite_ancho = max(100, self._lienzo.winfo_width() - 12)
        limite_alto = max(100, self._lienzo.winfo_height() - 12)
        self._escala = min(limite_ancho / ancho, limite_alto / alto) * self._zoom
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (max(1, round(ancho * self._escala)),
                               max(1, round(alto * self._escala))),
                         interpolation=cv2.INTER_AREA if self._escala < 1 else cv2.INTER_LINEAR)
        self._foto = ImageTk.PhotoImage(Image.fromarray(img))
        self._lienzo.delete("all")
        self._lienzo.create_image(0, 0, image=self._foto, anchor="nw", tags="frame")
        for zona in self._zonas:
            x1, y1 = zona.x * self._escala, zona.y * self._escala
            x2, y2 = (zona.x + zona.ancho) * self._escala, (zona.y + zona.alto) * self._escala
            self._lienzo.create_rectangle(x1, y1, x2, y2, outline="#00d070", width=2)
            self._lienzo.create_text(x1, max(0, y1 - 4), text=zona.nombre,
                                     fill="#00ff88", anchor="sw")
        for nombre, (x, y, w, h) in self._anclas_estabilizacion.items():
            self._lienzo.create_rectangle(x * self._escala, y * self._escala,
                (x + w) * self._escala, (y + h) * self._escala,
                outline="#ffcf4e", width=2, dash=(5, 3))
        if self._zona_senal:
            x, y, w, h = self._zona_senal
            self._lienzo.create_rectangle(x * self._escala, y * self._escala,
                (x + w) * self._escala, (y + h) * self._escala,
                outline="#60cfff", width=2)
        self._lienzo.configure(scrollregion=(0, 0, img.shape[1], img.shape[0]))
        self._zoom_texto.set(f"{round(self._zoom * 100)} %")

    def _coordenadas_video(self, event: tk.Event) -> tuple[int, int]:
        if self._frame is None:
            return 0, 0
        x = round(self._lienzo.canvasx(event.x) / max(1e-6, self._escala))
        y = round(self._lienzo.canvasy(event.y) / max(1e-6, self._escala))
        alto, ancho = self._frame.shape[:2]
        return max(0, min(ancho - 1, x)), max(0, min(alto - 1, y))

    def _empezar_rectangulo(self, event: tk.Event) -> None:
        if self._frame is None or self._procesando:
            return
        self._inicio = self._coordenadas_video(event)
        x, y = self._inicio
        self._rectangulo = self._lienzo.create_rectangle(
            x * self._escala, y * self._escala,
            x * self._escala, y * self._escala, outline="#ffbf47", width=2)

    def _arrastrar_rectangulo(self, event: tk.Event) -> None:
        if self._rectangulo is None or self._inicio is None:
            return
        a, b = self._inicio
        x, y = self._coordenadas_video(event)
        self._lienzo.coords(self._rectangulo,
            a * self._escala, b * self._escala, x * self._escala, y * self._escala)

    def _terminar_rectangulo(self, event: tk.Event) -> None:
        if self._inicio is None:
            return
        x1, y1 = self._inicio
        x2, y2 = self._coordenadas_video(event)
        self._inicio = None
        if self._rectangulo is not None:
            self._lienzo.delete(self._rectangulo)
        self._rectangulo = None
        x, y = min(x1, x2), min(y1, y2)
        ancho, alto = abs(x2 - x1), abs(y2 - y1)
        if ancho < 5 or alto < 5:
            return
        if self._modo_ancla:
            self._modo_ancla = False
            if self._zona_ancla:
                self._anclas_estabilizacion[self._zona_ancla] = (x, y, ancho, alto)
                self._estado_ancla.configure(text=f"Ancla guardada para {self._zona_ancla}.")
            self._zona_ancla = None
        elif self._modo_senal:
            self._zona_senal = (x, y, ancho, alto)
            self._modo_senal = False
            self._estado_senal.configure(text=f"Señal seleccionada: {ancho} × {alto} px.")
        else:
            if len(self._zonas) >= 4:
                messagebox.showwarning("Zonas", "Máximo cuatro zonas de lectura.")
                return
            nombre = simpledialog.askstring("Nueva medición", "Nombre de la columna en Excel:", parent=self)
            if not nombre:
                return
            if nombre in (zona.nombre for zona in self._zonas):
                messagebox.showwarning("Nombre", "Ya existe una medición con ese nombre.")
                return
            decimales = simpledialog.askinteger("Decimales", "Decimales esperados:",
                                               initialvalue=2, minvalue=0, maxvalue=12, parent=self)
            if decimales is None:
                return
            self._zonas.append(ZonaLectura(nombre, x, y, ancho, alto, decimales))
            self._actualizar_tabla()
        self._mostrar_frame(self._frame)

    def _actualizar_tabla(self) -> None:
        if not hasattr(self, "_tabla"):
            return
        seleccion_actual = self._tabla.selection()
        indice_anterior = int(seleccion_actual[0]) if seleccion_actual else None
        for item in self._tabla.get_children():
            self._tabla.delete(item)
        for i, zona in enumerate(self._zonas):
            self._tabla.insert("", "end", iid=str(i), values=(zona.nombre, zona.decimales))
        if indice_anterior is not None and indice_anterior < len(self._zonas):
            self._tabla.selection_set(str(indice_anterior))
        self._al_elegir_zona()

    def _zona_elegida(self) -> ZonaLectura | None:
        seleccion = self._tabla.selection()
        if not seleccion:
            return None
        indice = int(seleccion[0])
        return self._zonas[indice] if indice < len(self._zonas) else None

    def _al_elegir_zona(self, event: Any = None) -> None:
        activa = self._zona_elegida() is not None
        estado = "normal" if activa and not self._procesando else "disabled"
        for boton in (self._probar_btn, self._quitar_btn, self._editar_btn, self._ancla_btn):
            boton.configure(state=estado)
        zona = self._zona_elegida()
        self._probar_estabilizacion_btn.configure(state=(
            "normal" if zona and zona.nombre in self._anclas_estabilizacion
            and not self._procesando else "disabled"))
        self._usar_estabilizacion_btn.configure(state=(
            "normal" if self._anclas_estabilizacion and not self._procesando else "disabled"))

    def _quitar_zona(self) -> None:
        zona = self._zona_elegida()
        if zona:
            self._zonas.remove(zona)
            self._anclas_estabilizacion.pop(zona.nombre, None)
            self._actualizar_tabla()
            if self._frame is not None:
                self._mostrar_frame(self._frame)

    def _editar_zona(self) -> None:
        zona = self._zona_elegida()
        if zona is None:
            return
        nombre = simpledialog.askstring("Editar medición", "Nombre de columna:",
                                       initialvalue=zona.nombre, parent=self)
        if not nombre:
            return
        if nombre != zona.nombre and any(z.nombre == nombre for z in self._zonas):
            messagebox.showerror("Nombre", "Ya existe ese nombre de columna.")
            return
        decimales = simpledialog.askinteger("Decimales", "Decimales esperados:",
                                           initialvalue=zona.decimales or 0,
                                           minvalue=0, maxvalue=12, parent=self)
        if decimales is None:
            return
        idx = self._zonas.index(zona)
        self._zonas[idx] = ZonaLectura(nombre, zona.x, zona.y,
                                      zona.ancho, zona.alto, decimales, zona.confianza_minima)
        if zona.nombre in self._anclas_estabilizacion:
            self._anclas_estabilizacion[nombre] = self._anclas_estabilizacion.pop(zona.nombre)
        self._actualizar_tabla()
        self._mostrar_frame(self._frame)

    def _probar_zona(self) -> None:
        zona = self._zona_elegida()
        if zona is None or self._frame is None:
            self._estado.configure(text="Selecciona una zona de la lista.")
            return
        try:
            lectura = leer_zona(RapidOcr(), zona.recortar(self._frame), zona)
            texto = lectura.valor if lectura.aceptada else "sin lectura"
            detalle = (f"Prueba de {zona.nombre}\nValor: {texto}\n"
                       f"Confianza: {lectura.confianza if lectura.confianza is not None else '-'}\n"
                       f"Texto OCR: {lectura.texto_ocr}")
            if lectura.motivo:
                detalle += f"\nEstado: {lectura.motivo}"
            if lectura.texto_ocr.strip().isdigit() and zona.decimales and not lectura.aceptada:
                detalle += ("\n\nSugerencia: el OCR leyó un entero. Si la pantalla no muestra "
                            "punto decimal, edita los decimales a cero.")
            self._estado.configure(text=detalle.replace("\n", " · "))
            messagebox.showinfo("Resultado de la prueba", detalle)
        except Exception as exc:
            messagebox.showerror("Prueba", str(exc))

    def _marcar_ancla(self) -> None:
        zona = self._zona_elegida()
        if self._frame is None or zona is None:
            return
        self._zona_ancla = zona.nombre
        self._modo_ancla = True
        self._modo_senal = False
        self._lienzo.configure(cursor="crosshair")
        self._estado_ancla.configure(text=f"Arrastra un área fija cercana a '{zona.nombre}': marco, botones o texto.")

    def _probar_estabilizacion(self) -> None:
        zona = self._zona_elegida()
        if self._video is None or zona is None:
            return
        ancla = self._anclas_estabilizacion.get(zona.nombre)
        if ancla is None:
            return
        cap = cv2.VideoCapture(str(self._video))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            indice = min(total - 1, max(1, round(float(fps))))
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, referencia = cap.read()
            cap.set(cv2.CAP_PROP_POS_FRAMES, indice)
            ok2, actual = cap.read()
            if not (ok and ok2):
                raise ValueError("No se pudieron leer fotogramas para la comparación.")
            estabilizado, dx, dy, ecc = alinear_traslacion(referencia, actual, ancla)
            a = zona.recortar(actual)
            b = zona.recortar(estabilizado)
            alto = max(a.shape[0], b.shape[0])
            ancho = max(a.shape[1], b.shape[1])
            max_ancho = 800
            escala = min(4, max_ancho / (2 * ancho))
            a = cv2.resize(a, (round(ancho * escala), round(alto * escala)))
            b = cv2.resize(b, (round(ancho * escala), round(alto * escala)))
            comparacion = cv2.hconcat([a, b])
            cv2.putText(comparacion, "ORIGINAL", (8, 25), cv2.FONT_HERSHEY_SIMPLEX,
                        .7, (0, 255, 255), 2)
            cv2.putText(comparacion, "ESTABILIZADO", (a.shape[1] + 8, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 255), 2)
            ventana = tk.Toplevel(self)
            ventana.title(f"Comparación {zona.nombre} - ECC {ecc:.3f}")
            ventana.geometry(f"{min(comparacion.shape[1] + 30, 1100)}x{comparacion.shape[0] + 75}")
            rgb = cv2.cvtColor(comparacion, cv2.COLOR_BGR2RGB)
            foto = ImageTk.PhotoImage(Image.fromarray(rgb))
            etiqueta = tk.Label(ventana, image=foto)
            etiqueta.image = foto
            etiqueta.pack(pady=8)
            ttk.Label(ventana, text=f"ECC={ecc:.3f} · desplazamiento dx={dx:+.1f}, dy={dy:+.1f}").pack()
        except Exception as exc:
            messagebox.showerror("Estabilización", str(exc))
        finally:
            cap.release()

    def _marcar_senal(self) -> None:
        if self._frame is None:
            return
        self._modo_senal = True
        self._modo_ancla = False
        self._estado_senal.configure(text="Dibuja un rectángulo sobre la señal que aparece y desaparece.")

    def _guardar_referencia_senal(self, presente: bool) -> None:
        if self._frame is None or self._zona_senal is None:
            messagebox.showwarning("Referencia", "Primero selecciona el área de señal.")
            return
        x, y, w, h = self._zona_senal
        copia = self._frame[y:y+h, x:x+w].copy()
        if presente:
            self._referencia_senal_presente = copia
        else:
            self._referencia_senal_ausente = copia
        self._estado_senal.configure(text=("Referencia de señal PRESENTE guardada." if presente else
                                           "Referencia de señal AUSENTE guardada."))

    def _detectar_etapas(self) -> None:
        if self._video is None or self._zona_senal is None:
            messagebox.showwarning("Asistente", "Selecciona un video y el área de la señal.")
            return
        if self._procesando:
            return
        # Las propuestas se calculan fuera del hilo Tk, sin tocar widgets.
        self._estado_senal.configure(text="Buscando intervalos. No se modificarán las etapas hasta confirmar.")
        video, zona = self._video, self._zona_senal
        referencia = self._referencia_senal_ausente
        def trabajo():
            try:
                propuestos = proponer_periodos_en_video(
                    video, zona, referencia=referencia, umbral=.12)
                self._resultados.put(("propuestas", propuestos))
            except Exception as exc:
                self._resultados.put(("error_senal", str(exc)))
        threading.Thread(target=trabajo, daemon=True).start()

    def _ajustar_zoom(self) -> None:
        self._zoom = 1.0
        self._zoom_texto.set("100 %")
        if self._frame is not None:
            self._mostrar_frame(self._frame)
            self._lienzo.xview_moveto(0.0)
            self._lienzo.yview_moveto(0.0)

    def _cambiar_zoom(self, factor: float,
                     punto_visor: tuple[int, int] | None = None) -> None:
        if self._frame is None:
            return
        if punto_visor is None:
            punto_visor = (self._lienzo.winfo_width() // 2,
                           self._lienzo.winfo_height() // 2)
        punto_original = (
            self._lienzo.canvasx(punto_visor[0]) / self._escala,
            self._lienzo.canvasy(punto_visor[1]) / self._escala,
        )
        nueva = min(4.0, max(.5, self._zoom * factor))
        if nueva == self._zoom:
            return
        self._zoom = nueva
        self._mostrar_frame(self._frame)
        self._reposicionar_ancla(punto_original, punto_visor)

    def _reposicionar_ancla(self, punto_original: tuple[float, float],
                           punto_visor: tuple[int, int] | None) -> None:
        if self._frame is None or punto_visor is None:
            return
        self.update_idletasks()
        alto, ancho = self._frame.shape[:2]
        ancho_contenido, alto_contenido = (round(ancho * self._escala),
                                           round(alto * self._escala))
        self._lienzo.xview_moveto(fraccion_scroll_para_ancla(
            punto_original[0], self._escala, punto_visor[0],
            self._lienzo.winfo_width(), ancho_contenido))
        self._lienzo.yview_moveto(fraccion_scroll_para_ancla(
            punto_original[1], self._escala, punto_visor[1],
            self._lienzo.winfo_height(), alto_contenido))

    def _zoom_con_rueda(self, evento: tk.Event) -> str:
        if self._frame is None or getattr(evento, "delta", 0) == 0:
            return "break"
        self._cambiar_zoom(1.25 if evento.delta > 0 else 1 / 1.25,
                           (evento.x, evento.y))
        return "break"

    def _desplazar_horizontal_con_rueda(self, evento: tk.Event) -> str:
        self._lienzo.xview_scroll(-1 if evento.delta > 0 else 1, "units")
        return "break"

    def _empezar_pan(self, evento: tk.Event) -> None:
        self._lienzo.scan_mark(evento.x, evento.y)
        self._lienzo.configure(cursor="fleur")

    def _arrastrar_pan(self, evento: tk.Event) -> None:
        self._lienzo.scan_dragto(evento.x, evento.y, gain=1)

    def _terminar_pan(self, evento: tk.Event) -> None:
        self._lienzo.configure(cursor="crosshair")

    def _generar_excel(self) -> None:
        if self._video is None or not self._zonas:
            self._estado.configure(text="Selecciona un video y añade al menos una zona.")
            return
        if self._procesando:
            return
        try:
            periodo = float(self._periodo.get())
            if periodo <= 0:
                raise ValueError("La frecuencia de lectura debe ser positiva.")
            etapas = parsear_etapas(self._etapas_s.get())
            if not etapas:
                raise ValueError("Indica al menos una etapa, por ejemplo 0-12.")
            for inicio, fin in etapas:
                if inicio > self._duracion_video_s:
                    raise ValueError(f"La etapa que empieza en {inicio} s excede la duración.")
                if fin is not None and fin > self._duracion_video_s + 1 / self._fps_video:
                    raise ValueError(f"La etapa que termina en {fin} s excede la duración.")
            if self._usar_estabilizacion.get() and not self._anclas_estabilizacion:
                raise ValueError("Marca al menos un área estable antes de activar la estabilización.")
            salida, evidencia = rutas_de_exportacion(self._video)
            self._iniciar_proceso(periodo, salida, evidencia,
                                  self._usar_estabilizacion.get(), etapas)
        except Exception as exc:
            messagebox.showerror("Generar Excel", str(exc))

    def _iniciar_proceso(self, periodo: float, salida: Path, evidencia: Path,
                         estabilizar: bool, etapas: list[tuple[float, float | None]]) -> None:
        if self._video is None:
            return
        self._procesando = True
        self._cancelar_proceso.clear()
        self._generar.configure(state="disabled")
        self._cancelar_exportacion_btn.configure(state="normal")
        self._progreso_texto.set("Cargando OCR y preparando exportación...")
        self._barra_progreso["value"] = 0
        self._al_elegir_zona()
        video, zonas, anclas = self._video, list(self._zonas), dict(self._anclas_estabilizacion)
        resultados = self._resultados
        def notificar(actual: int, total: int, etapa: int, num_etapas: int) -> None:
            resultados.put(("progreso", (actual, total, etapa, num_etapas)))
        def trabajo() -> None:
            try:
                filas = procesar_video(
                    video=video, zonas=zonas, periodo_s=periodo,
                    ocr=RapidOcr(), salida_xlsx=salida, evidencia_dir=evidencia,
                    intervalos=etapas, estabilizar=estabilizar,
                    anclas_estabilizacion=anclas if estabilizar else None,
                    progreso=notificar, cancelar=self._cancelar_proceso.is_set)
                resultados.put(("terminado", (salida, evidencia, len(filas))))
            except ProcesamientoCancelado:
                resultados.put(("cancelado", (salida, evidencia)))
            except Exception as exc:
                resultados.put(("error", str(exc)))
        threading.Thread(target=trabajo, daemon=True).start()

    def _cancelar_exportacion(self) -> None:
        if self._procesando:
            self._cancelar_proceso.set()
            self._progreso_texto.set("Cancelando al finalizar el fotograma actual...")
            self._cancelar_exportacion_btn.configure(state="disabled")

    def _revisar_resultados(self) -> None:
        try:
            while True:
                tipo, dato = self._resultados.get_nowait()
                if tipo == "progreso":
                    actual, total, etapa, num_etapas = dato
                    self._barra_progreso["value"] = 100 * actual / max(1, total)
                    self._progreso_texto.set(f"Etapa {etapa}/{num_etapas}: {actual}/{total} lecturas")
                elif tipo in ("terminado", "cancelado", "error"):
                    self._procesando = False
                    self._generar.configure(state="normal")
                    self._cancelar_exportacion_btn.configure(state="disabled")
                    self._al_elegir_zona()
                    if tipo == "terminado":
                        salida, evidencia, n = dato
                        self._barra_progreso["value"] = 100
                        self._progreso_texto.set(f"Terminado: {n} fotogramas")
                        self._estado.configure(text=f"Excel guardado: {salida}")
                        messagebox.showinfo("Exportación lista",
                                            f"Excel: {salida}\nEvidencia: {evidencia}\nFotogramas: {n}")
                    elif tipo == "cancelado":
                        self._progreso_texto.set("Exportación cancelada. No se guardó un Excel final.")
                    else:
                        self._progreso_texto.set("Error en la exportación")
                        messagebox.showerror("Exportación", str(dato))
                elif tipo == "propuestas":
                    propuestas = dato
                    if not propuestas:
                        self._estado_senal.configure(text="No se detectaron intervalos con el umbral actual.")
                    else:
                        vista = ", ".join(f"{a:g}-{b:g}" for a, b in propuestas)
                        self._estado_senal.configure(text=f"Propuestas: {vista}")
                        if messagebox.askyesno("Revisar etapas propuestas",
                                               f"Estos intervalos son aproximados:\n{vista}\n\n¿Aplicarlos?"):
                            self._etapas_s.set(vista)
                elif tipo == "error_senal":
                    self._estado_senal.configure(text=f"Falló detección: {dato}")
                    messagebox.showerror("Detectar señal", str(dato))
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._revisar_resultados)


if __name__ == "__main__":
    Aplicacion().mainloop()
