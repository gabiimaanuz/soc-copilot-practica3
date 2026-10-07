# 15 · Informe de incidente en PDF — Práctica 2, mejora #4

> Roadmap #4 «Generación automática del informe de incidente» (prioridad
> Alta). Estado: implementada. Ver [14-practica2.md](14-practica2.md).

## 1. Qué hace

Con un clic, SOC Copilot redacta un **informe formal de incidente** y lo
descarga en PDF. Usa todo lo que el analista ya ha trabajado:

| Fuente | De dónde |
|---|---|
| Conversación del Chat IA | Botón en `/chat` (envía el historial actual) |
| Alerta + análisis IA + última recomendación | Botón en `/respond?alert_id=N` (también alertas de Wazuh) |
| Log adicional | El «contexto de log» del chat |
| Título y notas del analista | Campos opcionales del botón |

## 2. Contenido del PDF

Cabecera con referencia (`INC-AAAAMMDD-A<id>`), fecha, analista, severidad,
estado, origen (manual / Wazuh + agente) y técnicas MITRE; después:

1. Resumen ejecutivo · 2. Cronología · 3. Activos afectados · 4. IOCs ·
5. Técnicas MITRE ATT&CK (enlazadas) · 6. Análisis técnico ·
7. Acciones realizadas · 8. Recomendaciones · 9. Lecciones aprendidas ·
10. Conclusión · Notas del analista · Anexo A (conversación) · Anexo B
(extracto del log).

Pie de página: «Generado por SOC Copilot con IA. Requiere revisión y
validación humana antes de su distribución» + número de página.

El idioma del informe sigue la [regla de idioma](16-multiidioma.md): el
idioma en que escribió el analista en el chat o, si no, el de la interfaz.

## 3. Arquitectura

```text
UI (IncidentReportButton) ──POST /api/reports/incident──► reports.py
                                                         │ visibilidad (alert_access)
                                                         │ resolve_language()
                                                         ▼
                                   incident_report.build_report()  → Gemini (JSON mode, schema)
                                                         ▼
                                   incident_report.render_pdf()     → ReportLab (A4)
                                                         ▼
                                   application/pdf (attachment) + audit "report.incident"
```

- **IA solo para redactar**; el PDF lo construye código determinista.
- Todo el material del analista va entre `BEGIN/END_UNTRUSTED_INCIDENT_DATA`
  (anti prompt-injection) y el prompt prohíbe inventar IOCs, horas o
  técnicas que no estén en los datos.
- Todo texto se **escapa** antes de entrar en ReportLab: un log con
  `<font>` o `<a href>` no puede alterar el documento.
- Fuente DejaVu Sans (Unicode completo; se instala `fonts-dejavu-core` en
  la imagen Docker). Sin ella, cae a Helvetica sustituyendo caracteres no
  representables.
- MITRE del LLM filtrado a `T####(.###)`.

## 4. API

`POST /api/reports/incident` (sesión, rate limit LLM, cuenta 1 llamada de cuota)

```json
{
  "alert_id": 42,
  "messages": [{"role": "user", "content": "¿Es un falso positivo?"}],
  "log_context": "…",
  "title": "Fuerza bruta SSH en web-01",
  "analyst_notes": "IP bloqueada en ufw a las 10:20",
  "include_transcript": true,
  "language": "auto"
}
```

Hace falta al menos uno de `alert_id`, `messages` o `log_context` (si no, 422).
`?format=json` devuelve el informe estructurado en vez del PDF (vista
previa / tests). Errores: 404 alerta no visible · 502 fallo de la IA ·
429 cuota/rate limit.

## 5. Archivos

- `apps/api/app/services/incident_report.py`, `app/schemas/reports.py`,
  `app/routers/reports.py`
- `apps/web/src/components/IncidentReportButton.tsx` (usado en `chat` y `respond`)
- `apps/api/requirements.txt` (`reportlab==4.2.5`), `apps/api/Dockerfile` (fuentes)
- Tests: `apps/api/tests/test_incident_report.py`
- Ejemplo: [`docs/assets/ejemplo-informe-incidente.pdf`](assets/ejemplo-informe-incidente.pdf)
