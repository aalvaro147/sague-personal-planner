# Project Map - Personal Planner (`planner`)

> **Descripción general:**  
> Aplicación de gestión y planificación personal de tareas y eventos para terminal con interfaz gráfica TUI basada en [Textual](https://textual.textualize.io/) y un núcleo de dominio en Python con persistencia en archivos JSON.

---

## 1. Árbol limpio de código fuente y tests

```text
sage/
├── planner/                         # Paquete principal de la aplicación
│   ├── __init__.py
│   ├── __main__.py                  # Punto de entrada para ejecución como módulo (`python -m planner`)
│   ├── cli.py                       # Interfaz de línea de comandos clásica / legacy
│   ├── core.py                      # API y lógica central de dominio (modelos, persistencia JSON)
│   ├── history.py                   # Gestión del historial de tareas y eventos completados
│   ├── recurrence.py                # Reglas y cálculo de recurrencias (diarias, semanales, mensuales)
│   ├── review.py                    # Lógica de revisión diaria (planificar mañana, cerrar día)
│   └── tui/                         # Interfaz gráfica de terminal con Textual
│       ├── __init__.py
│       ├── app.py                   # Aplicación principal Textual y entry point `planificador`
│       ├── styles.tcss              # Hoja de estilos de la interfaz (Textual CSS)
│       └── screens/                 # Pantallas y vistas modales de la TUI
│           ├── __init__.py
│           ├── agenda.py            # Pantalla de agenda diaria
│           ├── week.py              # Pantalla de agenda semanal
│           ├── tasks.py             # Pantalla de listado y gestión de tareas
│           ├── task_detail.py       # Vista detallada de una tarea
│           ├── task_form.py         # Formulario de creación y edición de tareas
│           ├── events.py            # Pantalla de listado de eventos y próximas ocurrencias
│           ├── event_form.py        # Formulario de creación y edición de eventos
│           ├── block_form.py        # Formulario para asignar bloques de tiempo a tareas
│           ├── review.py            # Pantalla de flujos de revisión diaria
│           ├── recurrence_form.py   # Formulario de configuración de recurrencias
│           ├── recurrence_scope.py  # Modal para alcance de cambios en series recurrentes
│           └── confirm_dialog.py    # Modales de confirmación general
├── test_core.py                     # Tests unitarios del núcleo (core.py)
├── test_history.py                  # Tests unitarios del módulo de historial (history.py)
├── test_review.py                   # Tests unitarios de la lógica de revisión (review.py)
├── test_review_tui.py               # Tests de integración TUI para las pantallas de revisión
└── test_tui.py                      # Tests de integración TUI para la interfaz general Textual
```

---

## 2. Descripción de directorios y componentes

Según los archivos de configuración (`pyproject.toml`, `requirements.txt`) y documentación (`README.md`, `CONTRIBUTING.md`):

| Directorio / Módulo | Descripción estimada |
| :--- | :--- |
| **`planner/`** | Paquete raíz del código fuente de la aplicación. Contiene la separación entre la lógica de negocio y la interfaz. |
| **`planner/tui/`** | Capa de interfaz de usuario de terminal (TUI) implementada con Textual. Mantiene la UI desacoplada del dominio. |
| **`planner/tui/screens/`** | Colección de pantallas interactivas, vistas de agenda/calendario y diálogos modales para la captura y visualización de datos. |
| **Raíz (`./`) [Tests]** | Suite de pruebas automatizadas con `pytest` que cubren tanto las funciones del núcleo y modelos (`test_core.py`, `test_history.py`, `test_review.py`) como el comportamiento de los componentes visuales e interactivos (`test_tui.py`, `test_review_tui.py`). |

---

## 3. Puntos de entrada y configuración clave

- **Entrada TUI principal**: `planificador` comando registrado en `pyproject.toml` apuntando a `planner.tui.app:main`.
- **Entrada módulo**: `python -m planner` ejecuta `planner/__main__.py`.
- **Modo CLI**: `planificador --cli` ejecuta `planner/cli.py`.
- **Ejecución de tests**: `pytest`
