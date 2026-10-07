# Diagramas del sistema

Todos los diagramas usan **Mermaid**. GitHub, VS Code (con la extensión
"Markdown Preview Mermaid Support") y la mayoría de viewers Markdown
modernos los renderizan en línea. Si tu visor no, copia el bloque a
<https://mermaid.live>.

Índice:

1. [Contexto](#1-contexto-del-sistema)
2. [Arquitectura de despliegue (Docker Compose)](#2-arquitectura-de-despliegue-docker-compose)
3. [Componentes internos del backend](#3-componentes-internos-del-backend)
4. [Esquema de base de datos](#4-esquema-de-base-de-datos)
5. [Casos de uso por rol](#5-casos-de-uso-por-rol)
6. [Flujo de login y emisión del JWT](#6-flujo-de-login-y-emisión-del-jwt)
7. [Flujo de Alert Explainer](#7-flujo-de-alert-explainer)
8. [Flujo de Chat con RAG](#8-flujo-de-chat-con-rag)
9. [Flujo de reset de contraseña + invalidación de sesiones](#9-flujo-de-reset-de-contraseña--invalidación-de-sesiones)
10. [Flujo del analizador de logs](#10-flujo-del-analizador-de-logs-logs)
11. [Ciclo de vida de una alerta](#11-ciclo-de-vida-de-una-alerta)
12. [Pipeline de ingesta de la KB (Chroma)](#12-pipeline-de-ingesta-de-la-kb-chroma)
13. [Resolución de permisos (RBAC dinámico)](#13-resolución-de-permisos-rbac-dinámico)

---

## 1. Contexto del sistema

```mermaid
graph TB
    subgraph Externos
        ANALYST[Analista SOC junior]
        ADMIN[Admin SOC]
        GEMINI[(Google Gemini API<br>chat + embeddings)]
        MITRE[MITRE ATT&CK<br>STIX bundle]
        OWASP[OWASP Top 10 2025<br>dataset interno]
    end

    SOC[SOC Copilot<br>Frontend + API + DB + KB]

    ANALYST -->|HTTPS<br>cookie httpOnly| SOC
    ADMIN -->|HTTPS<br>cookie httpOnly| SOC
    SOC -->|chat / embed| GEMINI
    MITRE -->|ingest_kb.py| SOC
    OWASP -->|ingest_kb.py| SOC
```

**Lectura rápida**: SOC Copilot es un sistema cerrado al que dos perfiles
acceden por web; el sistema delega la inferencia a Gemini y se nutre de
dos fuentes externas para su KB (que se ingesta una sola vez por
deploy).

---

## 2. Arquitectura de despliegue (Docker Compose)

```mermaid
graph LR
    subgraph host[PC del usuario / VPS]
        subgraph net[red bridge interna]
            WEB[web<br>Next.js 15<br>:3000]
            API[api<br>FastAPI 0.115<br>:8080]
            PG[(postgres:16<br>:5432)]
            CH[(chroma:0.5.23<br>:8000)]
        end
        WEB -. host:13500 .-> WEB
        API -. host:8080 .-> API
        PG -. host:55432 .-> PG
        CH -. host:8001 .-> CH
    end

    BROWSER[Browser]
    GEMINI[(Gemini API)]

    BROWSER -->|http://localhost:13500| WEB
    WEB -->|/api/* fetch SSR or CSR| API
    API --> PG
    API --> CH
    API --> GEMINI
```

Volúmenes persistentes: `postgres-data`, `chroma-data`. Bind-mounts
read-write para hot-reload de `apps/api/app` y `apps/web/src`. En
producción se sustituye `web` y `api` por imágenes inmutables y se
añade Caddy delante para TLS automático.

---

## 3. Componentes internos del backend

```mermaid
graph TB
    subgraph routers[app/routers/]
        AUTH_R[auth.py]
        ADMIN_R[admin.py]
        EXPLAIN_R[explain.py]
        REC_R[recommend.py]
        CHAT_R[chat.py]
        ALERT_R[alerts.py]
        KB_R[kb.py]
        LLM_R[llm.py]
        HEALTH_R[health.py]
    end

    subgraph mw[app/middleware/]
        AUTH_DEP["get_current_user<br>(valida JWT y pv)"]
        REQ_PERM["require_perm()<br>fábrica de Depends"]
        RL[ratelimit]
    end

    subgraph services[app/services/]
        EXPL[explainer]
        REC[recommender]
        CHAT_S[chat]
        RAG[rag.Retriever]
        LLM[llm.GeminiAdapter]
        AUTH_S[auth: bcrypt + JWT]
        AUDIT[audit.log_audit]
        PERM[permissions.is_allowed]
    end

    subgraph data[Datos]
        PG[(PostgreSQL)]
        CH[(Chroma soc_kb)]
        GEM[(Gemini)]
    end

    AUTH_R --> AUTH_S
    ADMIN_R --> REQ_PERM
    ADMIN_R --> AUDIT
    REQ_PERM --> PERM
    PERM --> PG
    AUTH_DEP --> PG
    EXPLAIN_R --> AUTH_DEP
    EXPLAIN_R --> RL
    EXPLAIN_R --> EXPL
    EXPL --> LLM
    REC_R --> REC
    REC --> LLM
    CHAT_R --> CHAT_S
    CHAT_S --> RAG
    CHAT_S --> LLM
    RAG --> CH
    LLM --> GEM
    EXPL --> PG
    REC --> PG
    AUDIT --> PG
    ALERT_R --> PG
```

`require_perm("clave")` y `get_current_user` son las dos puertas que
todo router de negocio cruza. `services/llm` aísla al proveedor: añadir
otro LLM es escribir un sibling de `GeminiAdapter`.

---

## 4. Esquema de base de datos

```mermaid
erDiagram
    USERS ||--o{ ALERTS : creates
    USERS ||--o{ AUDIT_LOGS : actor_of
    ALERTS ||--o{ RECOMMENDATIONS : has

    USERS {
        int id PK
        string email UK
        string name
        string last_name
        string hashed_password
        int password_version
        enum role "analyst|admin"
        timestamptz created_at
    }
    ALERTS {
        int id PK
        text log
        string source
        text summary
        string risk_level
        text_array mitre_techniques
        text reasoning
        int user_id FK "nullable, ON DELETE SET NULL"
        timestamptz created_at
    }
    RECOMMENDATIONS {
        int id PK
        int alert_id FK "ON DELETE CASCADE"
        jsonb actions
        string priority
        text learning_notes
        timestamptz created_at
    }
    AUDIT_LOGS {
        int id PK
        timestamptz created_at "indexed"
        int actor_id FK "nullable, ON DELETE SET NULL"
        string actor_email
        string action "indexed"
        string target_type
        int target_id
        string target_label
        jsonb details
        string ip
    }
    ROLE_PERMISSIONS {
        int id PK
        enum role
        string permission_key
        bool allowed
        timestamptz updated_at
    }
```

Reglas:

- `users.email` único e indexado.
- `alerts.user_id` nullable: alertas pre-fase-4 quedan ownerless y solo
  son visibles para `admin`.
- `recommendations.alert_id` cascade-deletes al borrar la alerta padre.
- `audit_logs` y `role_permissions` no tienen FKs a recursos arbitrarios
  para preservar el rastro tras eliminaciones.
- `role_permissions` solo guarda **deviaciones** del default; tabla
  vacía = política original de la registry.

---

## 5. Casos de uso por rol

```mermaid
graph LR
    ANALYST((Analyst))
    ADMIN((Admin))

    UC1[Iniciar sesión / cerrar sesión]
    UC2[Editar perfil propio]
    UC3[Pegar log y obtener explicación]
    UC4[Solicitar recomendación de respuesta]
    UC5[Ver histórico propio]
    UC6[Subir fichero a /logs y filtrar]
    UC7[Chatear con la KB]
    UC8[Ver histórico de cualquier usuario]
    UC9[Listar / crear / borrar usuarios]
    UC10[Cambiar rol de un usuario]
    UC11[Resetear contraseña ajena]
    UC12[Editar matriz de permisos]
    UC13[Auditar acciones admin]

    ANALYST --- UC1
    ANALYST --- UC2
    ANALYST --- UC3
    ANALYST --- UC4
    ANALYST --- UC5
    ANALYST --- UC6
    ANALYST --- UC7

    ADMIN --- UC1
    ADMIN --- UC2
    ADMIN --- UC3
    ADMIN --- UC4
    ADMIN --- UC6
    ADMIN --- UC7
    ADMIN --- UC8
    ADMIN --- UC9
    ADMIN --- UC10
    ADMIN --- UC11
    ADMIN --- UC12
    ADMIN --- UC13
```

Cada caso de uso admin es un permiso individual en
`services/permissions.py` y por tanto puede delegarse al rol analyst
desde la matriz de permisos sin tocar código.

---

## 6. Flujo de login y emisión del JWT

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant W as Frontend Next.js
    participant API as FastAPI
    participant DB as PostgreSQL

    U->>W: rellena email + password<br>en /login
    W->>API: POST /api/auth/login {email, password}
    API->>DB: SELECT * FROM users WHERE email=?
    DB-->>API: row o NULL
    alt credenciales inválidas
        API-->>W: 401 invalid credentials
        W-->>U: error "credenciales inválidas"
    else credenciales válidas
        API->>API: verify_password(bcrypt)<br>issue_token(sub, role, pv)
        API-->>W: 200 + Set-Cookie soc_session<br>HttpOnly; SameSite=Lax
        W->>W: setUser(res.user)<br>localStorage broadcast
        W-->>U: redirect a /
    end
    Note over W,API: Cookie viaja en todas las requests<br>posteriores como Bearer-equivalent
```

El claim `pv` (password_version) se embebe en el JWT y se compara en
cada request protegida; si la BD lo bumpea, el token vigente queda
inválido al instante.

---

## 7. Flujo de Alert Explainer

```mermaid
sequenceDiagram
    autonumber
    actor U as Analyst
    participant W as /alerts (Next.js)
    participant API as FastAPI
    participant MW as get_current_user + ratelimit
    participant E as services/explainer
    participant L as GeminiAdapter
    participant DB as PostgreSQL

    U->>W: pega log + (opc) source + model
    W->>API: POST /api/explain
    API->>MW: cookie soc_session
    MW->>DB: SELECT user WHERE id=sub
    MW->>MW: assert payload.pv == user.password_version
    MW-->>API: User
    API->>API: rate-limit por IP (sliding window)
    API->>E: explain(log, source, model)
    E->>E: construye prompt con<br>BEGIN/END_UNTRUSTED_LOG
    E->>L: chat JSON-mode (response_schema)
    L->>L: respuesta estructurada<br>summary / risk / techniques / reasoning
    L-->>E: dict validado
    E->>DB: INSERT INTO alerts (user_id, ...)
    DB-->>E: id de la alerta
    E-->>API: ExplainResponse(id, ...)
    API-->>W: 200
    W-->>U: badge de riesgo + MITRE pills + reasoning
```

El log nunca llega al modelo como instrucción: queda envuelto entre
delimitadores `BEGIN_UNTRUSTED_LOG` / `END_UNTRUSTED_LOG`.

---

## 8. Flujo de Chat con RAG

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant W as /chat
    participant API as FastAPI
    participant CH as services/chat
    participant R as Retriever (Chroma)
    participant L as GeminiAdapter

    U->>W: mensaje + (opc) log_context
    W->>API: POST /api/chat {messages, log_context, model}
    API->>CH: chat(messages, log_context, model)
    CH->>L: embed(last_user_message)
    L-->>CH: vector
    CH->>R: query(vector, top_k=5)
    R-->>CH: docs [{id, text, metadata}]
    CH->>CH: prompt =<br>system anti-injection<br>+ BEGIN/END_UNTRUSTED_KB(docs)<br>+ BEGIN/END_UNTRUSTED_LOG(log_context)<br>+ messages
    CH->>L: chat(prompt)
    L-->>CH: reply
    CH-->>API: {reply, sources: [mitre:T1110, owasp:A07:2025, ...]}
    API-->>W: 200
    W-->>U: respuesta con pills clicables<br>(linkean a attack.mitre.org / owasp.org)
```

`sources` se renderiza en el front como pills y enlaza a los doc
oficiales para que el junior compruebe la cita.

---

## 9. Flujo de reset de contraseña + invalidación de sesiones

```mermaid
sequenceDiagram
    autonumber
    actor A as Admin
    actor V as Víctima del reset
    participant W as /admin
    participant API as FastAPI
    participant MW as require_perm("users.update_password")
    participant PERM as services/permissions
    participant DB as PostgreSQL
    participant AU as services/audit

    A->>W: clic "Cambiar Password" sobre usuario V
    W->>API: PUT /api/admin/users/{id}/password<br>{new_password}
    API->>MW: cookie de A
    MW->>PERM: is_allowed(role=A.role, key="users.update_password")
    PERM->>DB: SELECT role_permissions WHERE...
    PERM-->>MW: True (si admin)
    MW-->>API: User=A
    API->>DB: SELECT users WHERE id=V.id
    API->>API: V.hashed_password = bcrypt(new)<br>V.password_version += 1
    API->>AU: log_audit(action="user.password_reset", target=V)
    AU->>DB: INSERT INTO audit_logs (...) -- flush
    API->>DB: COMMIT (todo atómico)
    API-->>W: 200 ok
    W-->>A: feedback de éxito

    Note over V,API: Próximo request de V con su JWT viejo:
    V->>API: GET /api/auth/me (cookie con pv viejo)
    API->>MW: ...
    MW->>DB: SELECT users WHERE id=V.id
    MW->>MW: payload.pv (viejo) != V.password_version (nuevo)
    MW-->>API: 401 session invalidated
    API-->>V: 401 → frontend redirige a /login
```

Misma mecánica para `users.update_role` (cambiar rol también bumpea
`password_version` para que el nuevo rol aplique al instante).

---

## 10. Flujo del analizador de logs (`/logs`)

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant L as /logs (cliente)
    participant SS as sessionStorage
    participant A as /alerts
    participant API as FastAPI

    U->>L: clic "Subir archivo" → .log/.txt/.csv
    L->>L: FileReader.readAsText
    L->>L: split("\n") + parseLine() por línea<br>extrae src/dst IP, src/dst port,<br>MAC, proto, timestamp
    L-->>U: visor paginado + filtros
    U->>L: ajusta filtros (IP, puerto, MAC, proto, ...)
    L->>L: useMemo recomputa filteredLines<br>cada 300ms (debounced search)
    U->>L: selecciona N líneas + clic "Enviar a Alert Explainer"
    L->>SS: setItem("soc_copilot_imported_logs", joined)
    L->>A: router.push("/alerts?import=true")
    A->>SS: getItem("soc_copilot_imported_logs")
    SS-->>A: log seleccionado
    A->>A: setLog(...) + setSource("imported_logs")
    U->>A: (opc) edita y envía
    A->>API: POST /api/explain
```

Todo el parsing y filtrado ocurre en el navegador: el log no sale del
cliente hasta que el usuario decide enviarlo al explainer.

---

## 11. Ciclo de vida de una alerta

```mermaid
stateDiagram-v2
    [*] --> Submitted : POST /api/explain
    Submitted --> Explained : Gemini OK + INSERT alerts
    Submitted --> Failed : 502 LLM error
    Failed --> [*] : usuario reintenta
    Explained --> Recommended : POST /api/recommend (con alert_id)
    Recommended --> Recommended : nueva recomendación<br>(la última gana en UI)
    Explained --> [*] : descartada
    Recommended --> [*] : descartada

    note right of Explained
        Persistido en alerts:
        summary, risk_level,
        mitre_techniques, reasoning
    end note

    note right of Recommended
        Persistido en recommendations:
        actions[], priority,
        learning_notes
    end note
```

Nunca borramos alertas ni recomendaciones desde la UI. Si se borra el
usuario propietario, sus alertas pasan a `user_id NULL` (visibles solo
para admins).

---

## 12. Pipeline de ingesta de la KB (Chroma)

```mermaid
flowchart TB
    A[scripts/ingest_kb.py] --> B[Descarga STIX bundle<br>MITRE ATT&CK Enterprise]
    A --> C[Carga dataset interno<br>OWASP Top 10 2025]
    B --> D[Extrae técnicas vigentes<br>~691 entries]
    C --> E[10 entries A01..A10]
    D --> F[Normaliza a {id, text, metadata}]
    E --> F
    F --> G{Batches de 100}
    G --> H[Gemini embed-001<br>3072 dim]
    H --> I[Backoff exponencial<br>si rate-limit]
    I --> G
    G --> J[Chroma collection soc_kb<br>upsert]
    J --> K[(volumen<br>chroma-data)]

    style A fill:#1e293b,stroke:#475569,color:#e2e8f0
    style K fill:#0f172a,stroke:#475569,color:#e2e8f0
```

Idempotente: cada run puede re-ejecutarse sin duplicar (upsert por `id`).

---

## 13. Resolución de permisos (RBAC dinámico)

```mermaid
flowchart TD
    REQ[Request a /api/admin/foo] --> DEP[require_perm key=foo]
    DEP --> AUTH[get_current_user]
    AUTH -->|401 si falla| END_401([401 unauth])
    AUTH --> CHECK[is_allowed db, user.role, key]
    CHECK --> LOCKED{registry.locked?}
    LOCKED -->|sí| DEFAULT[devuelve registry default<br>NUNCA consulta tabla]
    LOCKED -->|no| QUERY[SELECT role_permissions<br>WHERE role=? AND permission_key=?]
    QUERY --> ROW{¿existe row?}
    ROW -->|sí| USE_ROW[allowed = row.allowed]
    ROW -->|no| FALLBACK[allowed = registry default]
    DEFAULT --> EVAL{allowed?}
    USE_ROW --> EVAL
    FALLBACK --> EVAL
    EVAL -->|true| HANDLER[handler ejecuta]
    EVAL -->|false| END_403([403 permission denied: foo])
```

`permissions.manage` está marcada como `locked=True` en la registry: la
pestaña Permisos del UI muestra sus checkboxes en gris y el backend
rechaza cualquier intento de update sobre esa clave. Eso garantiza que
un admin nunca puede deshabilitar la gestión de permisos para todos.
