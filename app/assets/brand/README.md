# FOODERA brand assets (visitor badge)

Everything in this folder is **optional**. The guest badge
([`app/services/badge_service.py`](../../services/badge_service.py)) is drawn entirely from
code: if this folder holds no logo file, the badge paints its own round FOODERA emblem
(white disc, gold ring, two overlapping eight-pointed stars, `FOODERA` / `EXPO 2026`).

## Dropping in the official logo

1. Save the official FOODERA logo as **`logo.png`** in this folder (transparent PNG is what
   you want — the badge header behind it is deep azure).
2. Re-deploy. That is all: no code change, no environment variable, no database migration.
3. Check the result once with

   ```bash
   python -c "from app.database.models import Lead; from app.services.badge_service import generate_badge; \
   open('badge.png','wb').write(generate_badge(Lead(lead_code='FD000123', telegram_user_id=1, contact_name='Test Guest')))"
   ```

   (or just open `/admin/leads/<id>/badge` in the panel) — the logo has to appear centred in
   the header, on the same spot the emblem used to occupy.

Recognised file names, in this order: `logo.png`, `logo.jpg`, `logo.jpeg`, `logo.webp`,
`foodera.png`, `foodera-logo.png`, `foodera_logo.png`. The first one that exists wins.

| Rule | Value |
|---|---|
| Logo box inside the 900×1200 badge | 560 × 260 px, centred horizontally, vertically centred on the emblem slot (y = 26…258) |
| Scaling | down only, aspect ratio preserved (a 2× or 4× export is fine — the extra pixels are dropped) |
| Oversized export | anything wider than 560 or taller than 260 is scaled down; nothing is ever upscaled |
| Broken file | logged as a warning and ignored — the drawn emblem is used instead, the badge still renders |
| Translation | none: the logo is language independent, uz and ru badges behave identically |

The badge never reads the file system at import time and never writes anything: a missing or
corrupt logo can therefore never break the visitor funnel or `/beydjik`.

## Palette

The badge uses these exact colours. Keep them in sync with the constants at the top of
`app/services/badge_service.py` (there is a test that fails when this table drifts).

| Name | Hex | Where it is used |
|---|---|---|
| `PAPER` | `#FFFFFF` | page margin, emblem disc, QR talon, the white quiet zone of the QR code |
| `CREAM` | `#FAF6EE` | the card itself, behind everything |
| `CREAM_DEEP` | `#EEE7D9` | the vine pattern on the card and inside the emblem's gold ring |
| `INK` | `#0C283C` | guest name, region text, lead code, the QR modules |
| `AZURE_DARK` | `#0C3E60` | header gradient, top-left corner |
| `AZURE` | `#2A8FC7` | ribbon gradient start, map pin, QR scanner brackets |
| `AZURE_DEEP` | `#126091` | header/ribbon gradient end, the blue star, `FOODERA` in the emblem |
| `GOLD` | `#C9A96A` | card frame, header rule, ribbon edges, divider, star, perforation |
| `GOLD_DEEP` | `#A6884F` | `EXPO 2026` in the emblem, the name watermark |
| `SAND` | `#F2EBDE` | the region pill |
| `MUTED` | `#5A6976` | the footnote at the very bottom |
| `FAINT` | `#96A0AA` | reserved for the hairline details of the card |

Fonts are **not** shipped here on purpose: the badge renders with `fonts-dejavu-core`
(installed in the Dockerfile), falls back to any system font that really prints `ГОСТЬ`, and
finally to Pillow's built-in bitmap font — it never crashes for a missing file.
