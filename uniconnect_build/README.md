# UniConnect

**Design and Implementation of a University-Based Social Networking Platform**

A fresh Django project. This milestone covers **student identity/registration/login**
(the `accounts` app) plus the **post-login app shell** (the `feed` app) — the left
navigation sidebar, the right sidebar widgets (search, Events, quick links, Who to
follow), and a working light/dark mode toggle. The center feed itself is intentionally
left minimal for now — posting and the full social feed are the next milestone.

## Tech stack

- Django 6.1
- django-crispy-forms + crispy-bootstrap5 (form rendering)
- django-formtools (the multi-step registration wizard)
- Bootstrap 5 — CDN only, not pip-installed
- Bootstrap Icons — CDN only. Used exclusively for every icon in the project (no
  emoji, no Font Awesome — this was a deliberate later decision to standardize on
  one icon system)
- jQuery 3.7 (latest 3.x) — CDN only
- Pillow (for `ImageField`s: university logos, student profile photos)
- SQLite for local development

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_universities   # populates ~20 real Nigerian universities
python manage.py createsuperuser
python manage.py runserver
```

Then visit:
- `http://127.0.0.1:8000/register/` — the 6-step registration wizard
- `http://127.0.0.1:8000/login/` — email+password login (with a registration-number fallback tab)
- `http://127.0.0.1:8000/home/` — the post-login home shell (redirected here after login)
- `http://127.0.0.1:8000/admin/` — Django admin

## The `feed` app — what's real vs. placeholder

Two new models back the right-sidebar widgets honestly rather than faking them
with hardcoded HTML:

- **`Event`** (title, location, date, category) — powers the "Events" widget and
  the full `/events/` list page. A handful of demo events ship in `db.sqlite3`.
- **`Follow`** (follower, following) — a simple, direct follow relationship (no
  approval step) powering "Who to follow". The subtitle shown for each suggested
  student is their department + level, not a fake `@handle` — students don't have
  handles in this system, and this is more relevant in a university context anyway.
  "Who to follow" suggests other verified students at *your own* university,
  excluding yourself and anyone you already follow — click Follow/Unfollow and
  watch it update live (AJAX, no page reload).

**Nav items without a built feature yet** (Communities, Profile, Messages,
Notifications, Bookmarks, Settings, Marketplace, Bookshop, Groups, Top Stories) all
route to a real page — a shared "coming soon" template — rather than a dead link
or a 404. This keeps navigation whole and honest: nothing pretends to work that
doesn't yet.

**Sidebar data consistency:** the Events and Who-to-follow widgets are supplied by
a context processor (`feed/context_processors.py`), not fetched per-view — this is
deliberate. Early in building this, the widgets only had data on the Home page and
silently went empty everywhere else, since each view would've needed to fetch and
pass that data individually. The context processor makes it available shell-wide
automatically, the same pattern used for notification/message badge counts in the
earlier UnifyApp project.

## Light / dark mode

Dark mode is a direct copy of UnifyApp's palette. Light mode is modeled on the
reference UI you provided (white cards, soft box-shadows, blue accent). The toggle
itself uses the same mechanism as UnifyApp: a `light-mode` class on `<body>`,
persisted in `localStorage`, applied via an early inline script (right after
`<body>` opens) so there's no flash of the wrong theme on page load.

## A note on login

Login is **email + password** by default, since every student's university email
is already enforced globally unique at registration. There's also a "Registration
Number" tab for students who can't remember their email — just registration number
and password, no university selection needed. Because registration numbers are
only unique *within* a university, the login view checks the entered password
against every matching account across all universities and signs in whichever one
actually matches; in the vanishingly rare case two different students at different
schools also happen to share a password, the student is asked to sign in with
email instead.

## How verification actually works (and its honest limits)

"Verification" means confirming the student controls a real inbox at their
university's official email domain — **it is not a live check against each
university's actual student records system**. See the in-app note on this (and the
earlier conversation about it) for the full honest breakdown of what this system
does and doesn't prove.

## What's next

Per the project build plan: the full social feed (posts, likes, comments), real
Communities, Resources, Marketplace, and the Django Channels real-time layer — each
building on the `StudentProfile` and app-shell foundation established here.
