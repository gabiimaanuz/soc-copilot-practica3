# 16 · Interfaz y respuestas multiidioma (ES/EN) — Práctica 2, mejora #6

> Roadmap #6 «Interfaz multiidioma (ES/EN)» (prioridad Baja).
> Estado: implementada. Ver [14-practica2.md](14-practica2.md).

La interfaz ya estaba traducida (ES/EN/FR en `lib/i18n.tsx`). Lo nuevo es
que **la IA responde en el idioma correcto** y que el idioma se **detecta
automáticamente**.

## 1. Interfaz

- Primera visita: el idioma se toma del navegador (`navigator.language`);
  si no es ES/EN/FR, español. Se guarda en `localStorage` (`soc:locale`).
- El selector ES/EN/FR de la barra superior sigue funcionando igual.
- Cada petición a la API envía `Accept-Language: <idioma de la interfaz>`.

## 2. Respuestas de la IA — regla de decisión

`app/services/language.py → resolve_language()`:

1. **Detección automática** del texto escrito por el analista (pregunta
   del chat, notas del informe). Detector sin dependencias por palabras
   frecuentes + acentos; si el texto es corto o ambiguo no decide.
2. Campo `language` del cuerpo (`es`/`en`/`fr`; `auto` = saltar).
3. Cabecera `Accept-Language` (= idioma de la interfaz).
4. Español por defecto.

Los **logs no se usan** para detectar: casi siempre están en inglés
técnico aunque el analista trabaje en español.

| Módulo | Idioma usado |
|---|---|
| Chat IA | idioma de la pregunta → si no, interfaz |
| Alert Explainer / Analizar con IA (Wazuh) | interfaz |
| Next Step Recommender | interfaz |
| Informe de incidente | idioma del analista en el chat/notas → si no, interfaz |

La instrucción de idioma se **añade al final** del system prompt
(`with_language`), después de las reglas de seguridad, y deja sin traducir
IDs MITRE/OWASP, comandos, rutas y valores JSON/enumeraciones (para que
`risk_level` siga siendo `high`, no `alto`). `ChatResponse` incluye el
campo `language` detectado.

## 3. Archivos

- `apps/api/app/services/language.py` (nuevo)
- `explainer.py`, `recommender.py`, `chat.py` (parámetro `language`;
  se quitó el «Responde en español» fijo del chat)
- Routers `explain`, `recommend`, `chat`, `alerts` (analyze), `reports`
- Schemas: campo opcional `language` en las peticiones
- `main.py`: `Accept-Language` permitido en CORS
- Frontend: `lib/api.ts` (cabecera), `lib/i18n.tsx` (autodetección,
  `localStorage` protegido), sugerencias del chat traducidas
- Tests: `apps/api/tests/test_language.py`

## 4. Limitaciones

- Detector heurístico: frases muy cortas («hola», «qué reviso») no
  deciden y se usa el idioma de la interfaz.
- Soporta ES, EN y FR (FR porque la interfaz ya lo tenía).
