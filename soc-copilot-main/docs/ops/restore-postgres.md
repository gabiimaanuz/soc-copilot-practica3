# Restaurar un backup de Postgres

Los backups viven en `/var/backups/soc-copilot/{daily,weekly}/` cifrados con
[age](https://age-encryption.org). Solo se pueden descifrar con la clave
privada que generaste al instalar el sistema (`~/.age-key.txt`).

⚠️ **Haz un drill al menos una vez** — un backup que nunca se ha restaurado
no es un backup, es un deseo.

## 1) Listar lo disponible

```bash
ls -lh /var/backups/soc-copilot/daily/
```

## 2) Descifrar + descomprimir

```bash
BACKUP=/var/backups/soc-copilot/daily/postgres-YYYYMMDD-HHMMSS.sql.gz.age
age -d -i ~/.age-key.txt "$BACKUP" | gunzip > /tmp/restore.sql
```

## 3) Restaurar

### Opción A — Reemplazar la BD entera (downtime)

```bash
cd /opt/soc-copilot
docker compose -f infra/docker-compose.prod.yml stop api web
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;"
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /tmp/restore.sql
docker compose -f infra/docker-compose.prod.yml start api web
```

### Opción B — Restaurar a una BD paralela para inspección

```bash
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE soc_copilot_restore;"
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d soc_copilot_restore < /tmp/restore.sql
```

Inspeccionas, copias lo que necesites, y al final:

```bash
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE soc_copilot_restore;"
```

## 4) Limpiar

```bash
shred -u /tmp/restore.sql
```

## Si pierdes la clave age

Sin la clave privada los backups **no se pueden descifrar**. Guarda
`~/.age-key.txt` en al menos dos sitios seguros (gestor de contraseñas
del equipo + USB cifrado offline). Sin ella, los backups son ruido.
