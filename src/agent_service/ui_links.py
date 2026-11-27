"""Bounded tracker deep links derived only from validated operator UI settings."""
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from .ui_auth import UISettings

LABEL = 'Полный результат ImpactMap (требуется вход)'


def result_url(settings: UISettings, resource_id: str) -> str | None:
    if not settings.secure:
        return None  # local QA links are not shareable tracker destinations
    url = settings.origin + '/ui/result?' + urlencode({'resource_id': resource_id})
    return validated_url(url)


def validated_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 1600:
        return None
    try:
        u = urlsplit(value)
        UISettings(Path('/unused/auth.sqlite'), u.scheme + '://' + u.netloc)
        if (u.scheme != 'https' or u.path != '/ui/result' or u.fragment
                or not re.fullmatch(r'[A-Za-z0-9.:[\]-]+', u.netloc)
                or any(c.isspace() for c in value)):
            return None
        args = parse_qs(u.query, strict_parsing=True)
        if set(args) != {'resource_id'} or len(args['resource_id']) != 1:
            return None
        resource_id = args['resource_id'][0]
        if not resource_id or any(ord(c)<32 or ord(c)==127 for c in resource_id):
            return None
        # Only the canonical encoder output; rejects extra fields, delimiters,
        # fragments and Markdown/ADF injection without interpreting analysis.
        if u.query != urlencode({'resource_id': resource_id}):
            return None
        return value
    except (ValueError, TypeError, KeyError):
        return None
