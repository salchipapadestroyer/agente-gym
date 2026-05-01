# agente-gym

Bot de Telegram que actúa como coach de adherencia fitness y nutrición para un grupo pequeño de usuarios. Usa Claude para generar planes diarios, parsear check-ins y armar reportes; usa Google Sheets como base viva.

No es un médico ni nutriólogo. Es un coach que prioriza que el usuario cumpla más días seguidos, no el plan más sofisticado.

## Stack

- **Telegram** (`python-telegram-bot`): canal con cada usuario.
- **Claude** (Anthropic API): genera planes, parsea check-ins, hace reportes.
  - Onboarding y reportes semanales: `claude-opus-4-7`.
  - Plan diario, ajustes y lista de súper: `claude-sonnet-4-6`.
  - Parser de check-ins: `claude-haiku-4-5`.
- **Google Sheets** (`gspread`): persistencia de usuarios, check-ins, planes y resúmenes.
- **APScheduler**: dispara el plan matutino, recordatorio de check-in y reporte semanal.

## Comandos del bot

| Comando | Qué hace |
|---|---|
| `/start` | Onboarding: 15 preguntas y genera perfil + macros + rutina base. |
| `/hoy` | Plan del día (rutina + comidas + macros). |
| `/checkin` | Cierre del día: 9 preguntas. Acepta respuestas largas o cortas. |
| `/super` | Lista de súper semanal. |
| `/resumen` | Tu estado actual (perfil + macros + métricas 7d). |
| `/semana` | Reporte semanal. |
| `/ayuda` | Lista de comandos. |

## Estructura de hojas (Google Sheets)

- `Usuarios` — perfil de cada usuario (19 columnas).
- `Checkins_Diarios` — un row por check-in (16 columnas).
- `Resumen_Usuarios` — estado compacto vivo de cada usuario (18 columnas).
- `Planes_Diarios` — plan generado cada día (6 columnas).

`scripts/setup_sheet.py` las crea/verifica con sus headers.

## Setup local

### 1. Requisitos

- Python 3.11+ (probado en 3.14).
- Cuenta en Anthropic con créditos.
- Bot de Telegram (token de [@BotFather](https://t.me/BotFather)).
- Google Cloud project con **Sheets API** y **Drive API** habilitadas.
- Service Account con JSON de credenciales descargado.
- Google Sheet **compartido como editor** con el `client_email` del service account.

### 2. Variables de entorno

Copia `.env.example` a `.env` y llena:

```env
TELEGRAM_TOKEN=          # de BotFather
ANTHROPIC_API_KEY=       # de console.anthropic.com
GOOGLE_SHEETS_ID=        # ID del Sheet (entre /d/ y /edit en la URL)
GOOGLE_CREDS_PATH=./google_credentials.json
TIMEZONE=America/Mexico_City
MORNING_HOUR=6
CHECKIN_HOUR=21
CHECKIN_MINUTE=30
WEEKLY_DAY=6             # 0=lunes ... 6=domingo
WEEKLY_HOUR=20
```

Coloca el JSON del service account en la raíz del repo como `google_credentials.json` (está en `.gitignore`).

### 3. Instalar dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Inicializar el Google Sheet

```bash
python -m scripts.setup_sheet
```

Crea las 4 hojas con sus headers y borra `Sheet1` por defecto.

### 5. Probar el pipeline sin Telegram (dryrun)

Antes de exponer el bot, valida que Claude + Sheets responden:

```bash
# onboarding con perfil de ejemplo
python -m scripts.dryrun onboard --chat-id test_001 --file scripts/perfil_ejemplo.json

# plan del día (lee del Sheet)
python -m scripts.dryrun plan --chat-id test_001

# check-in con respuesta corta
python -m scripts.dryrun checkin --chat-id test_001 "sí entrené, comidas 80%, energía 7, dormí 7h"

# reporte semanal (requiere check-ins previos en el Sheet)
python -m scripts.dryrun semana --chat-id test_001
```

Cada subcomando pregunta antes de escribir a Sheets.

### 6. Levantar el bot

```bash
python -m bot.main
```

Mientras este proceso corra, el bot responde en Telegram y los jobs cron disparan en los horarios configurados.

## Estructura del repo

```
bot/
  main.py            entry point: registra handlers y arranca scheduler
  handlers.py        comandos /start, /hoy, /checkin, etc. + lógica de onboarding
  scheduler.py       jobs cron (mañana, noche, semanal)
  prompts.py         prompts de Claude (system + user templates)
  claude_client.py   wrapper sobre Anthropic SDK con prompt caching
  sheets.py          lectura/escritura a Google Sheets
  metrics.py         agregaciones 7d (adherencia, energía, etc.)
  config.py          carga de .env

scripts/
  setup_sheet.py     crea las 4 hojas con headers
  dryrun.py          CLI para probar el pipeline sin Telegram
  perfil_ejemplo.json   perfil ficticio para dryrun

instrucciones_agente.md   spec original del proyecto
prompts_claude.md         versión humana de los prompts
```

## Notas

- El bot usa **long polling**, así que necesita un proceso vivo. Para producción se recomienda Railway, Fly.io o un VPS con `systemd`.
- Los modelos de Claude usan **prompt caching** (`cache_control: ephemeral`) en los bloques de identidad/reglas — abarata las llamadas repetidas dentro de la ventana de 5 min.
- El check-in nocturno acepta tanto respuesta numerada larga como frase corta tipo "sí entrené, comidas 80%, energía 7". Un parser con Haiku lo estructura.
