# FOODERA EXPO 2026 — Telegram Lead Qualification Bot

A production Telegram bot that interviews exhibitor prospects after the event, scores them
with a **deterministic** rule model (no LLM), posts a clean HTML card into the private sales
group, and lets managers move the lead through the pipeline with inline buttons.

Runs on **Python 3.11+ · aiogram 3.x · SQLAlchemy 2 (async) · PostgreSQL or SQLite · Alembic**.

```
visitor / exhibitor                private sales group                database
─────────────────                  ───────────────────                ────────
10 questions  ──►  score+classify ─►  🔥 lead card ──► 👤 manager ───►  leads
   (one per screen)                    (status buttons)                lead_events
   ◄── thanks, no score shown          ◄── card edited in place        bot_users
```

---

## Contents

- [What it does](#what-it-does) · [What it deliberately does not do](#what-it-deliberately-does-not-do)
- [The conversation](#the-conversation)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Finding `SALES_GROUP_ID`](#finding-sales_group_id)
- [The lead card](#the-lead-card)
- [Qualification model](#qualification-model)
- [Pipeline statuses](#pipeline-statuses)
- [Commands and callbacks](#commands-and-callbacks)
- [Data model](#data-model)
- [Deployment](#deployment)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## What it does

- **Qualifies exhibitors** with 10 short questions (buttons wherever possible, free text only
  where a button would be silly), one question per screen, resumable at any point.
- **Separates visitors from leads.** Someone who taps “I want to visit” walks a 4-question
  funnel and never enters the exhibitor funnel, never gets a score pushed to the sales group,
  and (optionally) lands in a separate `VISITOR_GROUP_ID` chat.
- **Attributes every lead**: `t.me/foodera_bot?start=tgads_foodera_uz_01` deep links from
  Telegram Ads, QR posters or a landing page are parsed into `source / campaign / creative`
  and stored on both the user and the lead.
- **Scores deterministically** (0–100) and classifies into `HOT / WARM / COLD / LOW`.
- **Posts a card into the sales group** with the answers, contacts, links, source, a lead code
  (`FD000042`) and four status buttons; the card is edited in place as the status changes.
- **Keeps the funnel honest**: `lead_events` records every step, so `/stats` shows real
  conversion numbers (starts → language → intent → … → done), source performance, and stale drafts.
- **Survives restarts**: drafts are re-opened from the database (`DRAFT_TTL_HOURS`), stale button
  presses are answered politely, and one broken update never kills the process.

## What it deliberately does not do

- **No AI/LLM in qualification.** Every point comes from a rule in
  [`app/services/scoring.py`](app/services/scoring.py) and the same input always gives the same
  output (there is a test for every weight).
- **Never shows a score, a classification or the word “qualified” to the person filling the
  form.** Users get one question per screen and a thank-you message; scoring is internal.
- **Never rejects a lead for missing a website.** The links question is optional, and online
  presence is worth at most 10 of 100 points — it can never decide the outcome on its own.
- **Never blocks an international number** — `+44…`, `+1…` are stored as-is; only `+998` numbers
  are normalised into the local display format.
- **Never logs the bot token** (see [`app/utils/logging.py`](app/utils/logging.py)) and escapes
  every user-supplied string before it reaches an HTML message.

---

## The conversation

| Funnel | Questions | Notes |
|---|---|---|
| Exhibitor (`stand`, `pricing`) | 10 | intent → company type → category → company name → region → online presence → links → contact person → phone → stand size → readiness |
| Partner | 9 | exhibitor funnel without the stand-size question |
| Visitor | 4 | name → phone → region → “why are you coming” |

Two questions are unlocked by the answers, so the progress pill only counts questions that will
actually be asked (`Savol 3/10`):

- **“outside Uzbekistan”** → a follow-up *country* question (+1 total).
- **“I have a website / Instagram / both”** → a follow-up *send your links* question (+1 total).

Buttons that are optional carry a `⏭ Skip` button; every screen after the first has `⬅️ Back`,
which re-asks the previous question with the previous answer pre-selected (`✓`).

Preview all of it offline — copy, keyboards, scoring and cards — without a token or a database:

```bash
python scripts/demo_run.py                 # exhibitor, uz + ru
python scripts/demo_run.py --lang ru
python scripts/demo_run.py --intent visitor
```

---

## Quick start

```bash
git clone <this repo> && cd fooderaleadbot

# 1. interpreter + dependencies
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. configuration
cp .env.example .env          # then edit .env

# 3. a local database (SQLite is enough to try the bot)
#    .env already points at sqlite+aiosqlite:///./foodera_bot.db

# 4. schema
alembic upgrade head          # or AUTO_CREATE_TABLES=true for a throwaway DB

# 5. the bot token from @BotFather  →  BOT_TOKEN in .env
#    create the private group for sales, add the bot as admin → SALES_GROUP_ID

python -m app.main
```

`python -m app.main` uses **long polling**: no public URL, no TLS certificates, no reverse proxy.

Then, in Telegram: open the bot, tap **🇺🇿 O‘zbekcha / 🇷🇺 Русский**, then **Boshlash**, and answer.
The card appears in the sales group the moment the last question is answered.

---

## Configuration

Everything is read from the environment or `.env` (pydantic-settings, [`app/config.py`](app/config.py)).
Unknown variables are ignored; there are **no hardcoded secrets**. A unit test checks that every
setting below is documented in [`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | **Required.** Token from @BotFather. Refuses to start without it. |
| `BOT_USERNAME` | – | Used in help text / deep-link examples. |
| `DATABASE_URL` | `sqlite+aiosqlite:///./foodera_bot.db` | `postgresql+asyncpg://…` in production. |
| `AUTO_CREATE_TABLES` | `true` | Create the schema on startup. Set `false` in production and use Alembic. |
| `SQL_ECHO` | `false` | Log SQL (development only). |
| `REDIS_URL` | – | FSM storage in Redis; empty = in-memory (single instance). |
| `SALES_GROUP_ID` | – | Negative chat id of the private sales group. Without it leads are only stored, never forwarded. |
| `SALES_GROUP_TOPIC_ID` | – | Optional forum-topic id when the group uses Topics. |
| `VISITOR_GROUP_ID` / `VISITOR_GROUP_TOPIC_ID` | – | Optional separate chat for visitor registrations. |
| `SALES_CARD_LANGUAGE` | `auto` | `auto` = language of the lead, or force `uz` / `ru` on the cards. |
| `ADMIN_USER_IDS` | *(empty)* | Comma/space separated **numeric** ids (`111,222`). Usernames are rejected. |
| `ALLOW_GROUP_MANAGERS` | `true` | Any member of the (private) sales group may tap the status buttons. `false` → admins only. |
| `DEFAULT_LANGUAGE` | `uz` | Language for users who never picked one; also the fallback for admin output. |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | `LOG_JSON=true` for journald/ELK friendly output. |
| `SUPPORT_USERNAME` | – | Shown as the “questions?” contact in user messages. |
| `DISPLAY_TIMEZONE` | `Asia/Tashkent` | Only affects the timestamp printed on the card; invalid values fall back to UTC. |
| `LEAD_CODE_PREFIX` | `FD` | Lead codes look like `FD000042`. |
| `HOT_MIN_SCORE` / `WARM_MIN_SCORE` / `COLD_MIN_SCORE` | `75 / 55 / 35` | Classification thresholds (0–100). |
| `QUALIFY_MIN_CLASSIFICATION` | `warm` | Lowest class that is pushed to `SALES_GROUP_ID` (`hot` \| `warm` \| `cold`). |
| `REQUIRE_PHONE_FOR_SALES` | `true` | No phone → no push (the record is still saved). |
| `REQUIRE_COMPANY_NAME_FOR_SALES` | `true` | Same for the company name. |
| `RECENT_APPLICATION_HOURS` | `24` | Within this window a second application becomes “update your existing one”. |
| `DRAFT_TTL_HOURS` | `72` | How long an unfinished application can be resumed. |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per-user flood control (admins are exempt). |

---

## Finding `SALES_GROUP_ID`

Telegram group ids are negative and start with `-100` when the group is a supergroup — which is
what every group with 1 000+ members or with “Topics” enabled becomes.

1. Create the **private** group, add the bot, promote it to admin (it needs *post messages*).
2. Enable **Topics** only if you want `SALES_GROUP_TOPIC_ID`.
3. Send anything in the group, then forward that message to `@userinfobot` — it replies with the
   chat id (`-1001234567890`). Or run the bot once with `ADMIN_USER_IDS` set and use `/chatid`
   (send `/chatid` in the group: the bot answers with the id it sees).
4. Put the id into `.env`. Restart. `/stats` now counts real leads and cards arrive.

The bot never writes to a chat that is not `SALES_GROUP_ID` / `VISITOR_GROUP_ID` / the user's
own private chat.

---

## The lead card

Exactly what the sales group receives — verbatim output of `python scripts/demo_run.py`,
shown with the HTML tags that Telegram turns into formatting:

```text
🔥 FOODERA — YANGI LEAD

Status: 🔥 HOT
Score: 100/100
🔥 HIGH INTENT

🏢 Kompaniya:
<b>Chirchik Juice Plant</b>

👤 Kontakt:
<b>Dilshod Rahimov</b>
Head of Sales

📱 Telefon:
<a href="tel:+998901234567">+998901234567</a>

📍 Hudud:
Toshkent

🏭 Kompaniya turi:
Ishlab chiqaruvchi

🍴 Yo‘nalish:
Alkogolsiz ichimliklar

📐 Stend:
27 m²

🎯 Holati:
Stend bron qilishga tayyormiz

🌐 Instagram:
<a href="https://instagram.com/chirchik_juice">@chirchik_juice</a>

🌐 Sayt:
<a href="https://chirchikjuice.uz">chirchikjuice.uz</a>

📢 Manba:
Telegram Ads

📣 Kampaniya:
foodera

🎨 Kreativ:
uz_01

Telegram:
<a href="https://t.me/demo_user">@demo_user</a>

🆔 User ID:
<code>4242</code>

🔖 Lead ID:
<code>#FD000042</code>

⏱ Yuborilgan:
17.09.2026 14:36

📌 Holat: 🆕 NEW

[📞 Aloqaga chiqildi] [💬 Muzokarada]
[✅ Stend bron qilindi] [❌ Mos emas]
```

After a manager taps a button the card is **edited in place** and the footer becomes
`📌 Holat: 📞 CONTACTED · @sales_manager · 17.09.2026 09:40` — who moved it, when, no separate
"lead updated" spam in the group.

Cards are built at `MAX_MESSAGE_LENGTH = 3800` characters (Telegram's hard limit is 4096): long
company names and free-text answers are truncated rather than dropped, so a card is never lost
because someone pasted a paragraph.

Visitor cards (when `VISITOR_GROUP_ID` is set) are compact: name, phone, region, why they are
coming, source and lead id — no score, no stand data, and never posted to the exhibitor group.

---

## Qualification model

`score_lead()` (0–100, capped at `MAX_SCORE`), stored together with the per-component
breakdown so a decision can always be audited:

| Signal | Points |
|---|---|
| Intent: `stand` 30 · `pricing` 25 · `partner` 10 · `visitor` 0 | up to 30 |
| Company type: manufacturer 20 · ingredient / equipment 18 · distributor / importer 15 · logistics 12 · retail 8 · HoReCa 5 · other 3 | up to 20 |
| Product category: any real FOODERA direction 10 · “other” 2 | 10 / 2 |
| Online presence verified from the actual links: site + Instagram 10 · one channel 8 · none or skipped 0 | up to 10 |
| Phone number provided | 10 |
| Stand size: 36 m²+ 10 · 27 m² 8 · 18 m² 6 · 9 m² 4 · undecided 2 | up to 10 |
| Readiness: ready to book 20 · review options 15 · want a call 10 · just interested 2 | up to 20 |
| Named contact person (name, not just `@handle`) | 5 |

Classification: `HOT ≥ 75`, `WARM ≥ 55`, `COLD ≥ 35`, else `LOW` — and **always** `VISITOR` for
the visitor funnel, whatever the arithmetic says.

`is_high_intent` (a separate 🔥 flag on the card) is `stand size chosen` **and** `ready to book`
**and** `phone present` — such leads jump the threshold:

```python
push_to_sales = (rank >= QUALIFY_MIN_CLASSIFICATION or is_high_intent)
                and (phone or not REQUIRE_PHONE_FOR_SALES)
                and (company_name or not REQUIRE_COMPANY_NAME_FOR_SALES)
                and classification != "VISITOR"
```

A lead that does not qualify is still saved (and visible via `/leads`); nothing is silently
dropped, and the user is still thanked.

---

## Pipeline statuses

```
NEW ──► CONTACTED ──► NEGOTIATION ──► BOOKED ──► CLOSED
 │           │              │                        ▲
 └───────────┴──────────────┴──► NOT_QUALIFIED ──────┘
```

- Managers tap `📞 contacted / 💬 negotiation / ✅ booked / ❌ not_qualified` on the card.
- Forward steps are allowed; **skipping is not** (`NEW → BOOKED` is refused with an alert that
  explains what is possible) — that keeps the funnel analytics meaningful.
- Repeating the same status is a polite no-op (“this lead is already in that status”).
- Two managers tapping the same card at the same moment: the update is a **compare-and-set** on
  the status they both read, so exactly one wins and the other is told the status changed.
- `CLOSED` is terminal and **locks the card**: the buttons are replaced by an info button.
- Who may tap: `ADMIN_USER_IDS`, plus — while `ALLOW_GROUP_MANAGERS=true` — anyone in the
  `SALES_GROUP_ID` chat. Because the group is private, membership *is* the permission; the bot
  checks the callback's chat id, so a forwarded card in another chat cannot be driven.
- Admins may bypass the table with `/setstatus FD000042 BOOKED` (audit-logged as an admin action).
- Rules live in [`app/services/statuses.py`](app/services/statuses.py) and are fully covered by
  [`tests/test_statuses.py`](tests/test_statuses.py).

---

## Commands and callbacks

**User** (private chat): `/start [payload]` · `/help` · `/restart`
**Admin** (any chat, restricted to `ADMIN_USER_IDS`): `/stats` · `/leads [n]` · `/hot [n]` ·
`/warm [n]` · `/today` · `/source` · `/lead <id|FD000042>` · `/setstatus <id|FD000042> <STATUS>` ·
`/chatid`

Callback data (small, stable grammar — every handler is idempotent):

| Pattern | Meaning |
|---|---|
| `lang:uz` / `lang:ru` | store the language, then the welcome message |
| `flow:start` / `flow:resume` / `flow:new` / `flow:update` / `flow:cancel` | open, resume, restart, update or abandon the application |
| `q:<step>:<value>` | one inline answer, e.g. `q:company_type:manufacturer` |
| `cat:page:<n>` | paginate the 16 product categories |
| `nav:back` / `nav:skip` / `nav:manual` | go back · skip an optional step · type the answer instead of using the phone button |
| `lead:<id>:<action>` | manager status button on a card (`contacted`, `negotiation`, `booked`, `not_qualified`) |
| `noop` | disabled button on a locked card |

---

## Data model

Three tables (see [`app/database/models.py`](app/database/models.py), migration
[`alembic/versions/20260917_0001_initial_schema.py`](alembic/versions/20260917_0001_initial_schema.py)):

- **`bot_users`** — one row per Telegram account: `language`, `language_explicit`, profile
  fields, and the attribution (`start_payload`, `source`, `campaign`, `creative`) that is copied
  onto every lead they open.
- **`leads`** — the answers as typed columns (queryable, no JSON blob), `is_draft` +
  `current_step` for resume, `score` + `score_breakdown` + `classification` + `is_high_intent`,
  `lead_status` + `manager_user_id` + `status_changed_at`, `notify_chat_id` + `notify_message_id`
  (which card message to edit), and a unique `lead_code`.
- **`lead_events`** — append-only funnel log (`STARTED`, `LANGUAGE_SELECTED`, `INTENT_SELECTED`
  … `COMPLETED`, `NOTIFICATION_SENT` / `NOTIFICATION_FAILED`, `STATUS_CHANGED`,
  `ALREADY_APPLIED`, `ABANDONED`, …) used for the funnel report.

Indices cover the paths the queries actually take: `telegram_user_id` + `bot_user_id`
(user lookups), `classification`, `lead_status`, `is_draft`, `intent`, unique `lead_code`
(admin listings), the composites `(classification, created_at)`, `(campaign, created_at)`,
`(telegram_user_id, completed_at)` (reporting, anti-spam) and `(event, created_at)` on
`lead_events`. Timestamps are stored in UTC; `DISPLAY_TIMEZONE` only affects rendering.

---

## Deployment

### systemd (single box, recommended)

```bash
sudo useradd --system --home /opt/foodera-bot --shell /usr/sbin/nologin foodera
sudo -u foodera mkdir -p /opt/foodera-bot
# copy the project to /opt/foodera-bot, then:
sudo -u foodera python3.11 -m venv /opt/foodera-bot/.venv
sudo -u foodera /opt/foodera-bot/.venv/bin/pip install -r requirements.txt
sudo -u foodera cp .env.example /opt/foodera-bot/.env   # edit it
sudo -u foodera /opt/foodera-bot/.venv/bin/alembic upgrade head
sudo install -m 0644 deploy/foodera-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now foodera-bot
journalctl -u foodera-bot -f
```

[`deploy/foodera-bot.service`](deploy/foodera-bot.service) sandboxes the process
(`ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`, only `/var/lib/foodera-bot` writable)
and restarts it on failure. Telegram Ads traffic is bursty: the bot is stateless enough that a
restart costs nothing — an interrupted answer is simply re-asked, and a lead that was already
saved is never saved twice.

### Checklist for production

- `DATABASE_URL=postgresql+asyncpg://…`, `AUTO_CREATE_TABLES=false`, migrations via Alembic.
- `REDIS_URL=redis://127.0.0.1:6379/1` **only** if you run more than one instance or you want
  FSM state to survive restarts (drafts resume from the DB either way).
- `ADMIN_USER_IDS` set, otherwise `/stats` and friends stay unreachable.
- `SALES_GROUP_ID` set, `ALLOW_GROUP_MANAGERS=true` is fine for a private group; switch it to
  `false` and rely on `ADMIN_USER_IDS` if the group ever gains external people.
- `LOG_JSON=true` if the logs go into a collector. The bot token is redacted in every log line.
- Backup: `pg_dump` daily; `leads` + `lead_events` are the whole product.

### Scaling

One process is enough for an event-sized crowd: the work per update is a couple of indexed
queries and one message send, and Telegram polling already smooths bursts. To scale anyway,
set `REDIS_URL` and run N instances behind shared Redis; nothing else changes
(status buttons use a compare-and-set update, so two managers tapping at once cannot corrupt the
card). Webhooks are not enabled on purpose: polling needs no public ingress and no TLS renewal
job, which is fewer ways to lose leads during the campaign.

---

## Development

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m pytest tests -q      # 364 tests, SQLite in-process, no network
python -m pytest tests/test_journey.py -q   # the end-to-end conversation
ruff check . && ruff format --check .   # both clean; CI can run exactly these
python scripts/demo_run.py --lang ru        # look at the copy without Telegram
alembic upgrade head && alembic downgrade base   # the migration is reversible
```

Layout (each layer depends only on the one below it):

```
app/
  config.py            pydantic-settings, .env, validation, masking
  flow.py              the question flow as data (steps, validation, progress)
  options.py           every answer option (enums) + labels
  i18n/                t() + uz/ru catalogs (parity enforced by tests)
  keyboards/           inline + reply keyboards
  states.py            FSM state group
  filters/             AdminFilter, IsOwnerOrAdmin, PrivateChat
  middlewares/         DatabaseMiddleware (session/repo/services), Throttling, UserContext
  database/            models, session factory, LeadRepository (all SQL lives here)
  services/            lead_service (use cases), scoring, statuses, notification (cards),
                       parsing (contact line, links), phone, source_tracking
  handlers/            engine.py (ask/advance/back/skip/finish) + start, language,
                       qualification, visitor, admin, fallback
  bot.py / main.py     assembly and entry point
alembic/               one reversible migration
scripts/demo_run.py    offline preview of copy, scoring and cards
tests/                 unit tests + test_journey.py (real updates through the real routers)
```

`tests/test_journey.py` is the interesting one: it builds the real `Dispatcher`, feeds raw
Telegram `Update` objects into it and asserts on the messages the bot tried to send — the
language gate, ten answers, anti-spam, the card in the group, a manager booking a lead, an
outsider being refused, back/skip/retry, a photo sent mid-form, and the `/stats` numbers.
Only the HTTP layer is faked.

Adding a question means editing data, not code: add the option to `app/options.py`, the step to
`app/flow.py`, the labels to both catalogs, and (if it should count) a weight in
`app/services/scoring.py`. The flow tests fail if any of those four are out of sync.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `BOT_TOKEN is empty` at startup | `BOT_TOKEN` missing in `.env`, or the working directory is not the project root. |
| Leads saved, but nothing in the group | `SALES_GROUP_ID` unset, or the bot is not an admin of that group. The log then contains `lead notification skipped: group is not configured` and `/stats` still counts the leads. |
| `bot must be an member of the supergroup chat` | Add the bot to the group (it needs *Post messages*). |
| Cards land in the general chat instead of a topic | Set `SALES_GROUP_TOPIC_ID`, and enable Topics in the group. |
| `database schema is not ready` | Run `alembic upgrade head`, or set `AUTO_CREATE_TABLES=true` locally. |
| `/stats` says “not for you” | Your numeric id is not in `ADMIN_USER_IDS` (usernames are rejected on purpose). |
| A user is stuck on an old question | `nav:back` re-asks with the stored answer; `/restart` starts a new draft (the old one stays in the DB); after a bot restart the draft is loaded from `current_step`. |
| Manager taps a button, sees an alert | Either the transition is not allowed (see the pipeline above) or `ALLOW_GROUP_MANAGERS=false` and their id is not an admin. |
| “Please slow down” to a user | `RATE_LIMIT_PER_MINUTE` reached (default 30/min) — raise it only if you have a good reason. |

---

## Security and privacy notes

- Secrets come from the environment only; `.env` is git-ignored; logs run the token through a
  redaction filter (`SecretStr` in the settings model, so even `repr(settings)` hides it).
- All user input is HTML-escaped before it is rendered, so a company called `<b>x</b>` cannot
  break or spoof a card.
- Status buttons are checked against the callback's chat and user id, not just the presence of a
  button; `/setstatus` is admin-only; the funnel refuses foreign ids with `err.lead_not_found`.
- The bot stores exactly what a person volunteers in the conversation (name, company, contact,
  links) — no scraping, no third-party enrichment, no analytics scripts. Deleting a lead's row
  deletes the record; `lead_events` rows for a lead cascade with it.
- Rate limiting and “one active application per user” keep the group free of duplicate cards
  when the same person taps the same ad twice.
