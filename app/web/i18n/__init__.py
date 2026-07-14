"""Small server-side translation layer for the operator interface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jinja2 import pass_context

from app.web.i18n.kk import TRANSLATIONS as KK
from app.web.i18n.ru import TRANSLATIONS as RU

DEFAULT_LOCALE = "kk"
SUPPORTED_LOCALES = frozenset(("kk", "ru"))
TRANSLATIONS: Mapping[str, Mapping[str, str]] = {"kk": KK, "ru": RU}


def translate(key: str, locale: str = DEFAULT_LOCALE, **values: Any) -> str:
    """Return the requested string; a missing key is visibly safe and deterministic."""
    dictionary = TRANSLATIONS.get(locale, TRANSLATIONS[DEFAULT_LOCALE])
    message = dictionary.get(key) or TRANSLATIONS[DEFAULT_LOCALE].get(key) or key
    return message.format(**values)


@pass_context
def t(context: Any, key: str, **values: Any) -> str:
    request = context.get("request")
    locale = getattr(getattr(request, "state", None), "locale", DEFAULT_LOCALE)
    return translate(key, locale, **values)
