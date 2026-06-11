"""
services/unicorn_service.py - Unicorn Company Lookup Service

Loads unicorn data from ``data/unicorns_seed.json`` and provides
search / filter / detail-lookup helpers.

Usage:
    results = await search_unicorns(query='AI', country='US', limit=5)
    company = await get_company('SpaceX')
"""

import json
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Internal data cache
# ---------------------------------------------------------------------------

_unicorn_data: Optional[list[dict]] = None


def _load_unicorns() -> list[dict]:
    """Load and cache the unicorn seed data from disk.

    The file is expected at ``<project_root>/data/unicorns_seed.json``.
    Each entry should be a dict with at least: name, valuation, country,
    sector, founded_year, description.
    """
    global _unicorn_data
    if _unicorn_data is None:
        path = Path(__file__).parent.parent / 'data' / 'unicorns_seed.json'
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _unicorn_data = json.load(f)
        except FileNotFoundError:
            _unicorn_data = []
        except json.JSONDecodeError:
            _unicorn_data = []
    return _unicorn_data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_unicorns(
    query: str = None,
    sector: str = None,
    country: str = None,
    limit: int = 5,
) -> list[dict]:
    """Search and filter unicorn companies.

    Parameters
    ----------
    query : str, optional
        Free-text search applied to name, sector, and description.
    sector : str, optional
        Exact or substring match on the sector field.
    country : str, optional
        Exact or substring match on the country field.
    limit : int
        Maximum number of results to return (default 5).

    Returns
    -------
    list[dict]
        Matching unicorn entries, up to *limit* items.
    """
    data = _load_unicorns()
    results: list[dict] = []

    for company in data:
        # --- Apply filters ---------------------------------------------------
        if sector:
            company_sector = (company.get('sector') or '').lower()
            if sector.lower() not in company_sector:
                continue

        if country:
            company_country = (company.get('country') or '').lower()
            if country.lower() not in company_country:
                continue

        if query:
            q = query.lower()
            searchable = ' '.join([
                (company.get('name') or ''),
                (company.get('sector') or ''),
                (company.get('description') or ''),
            ]).lower()
            if q not in searchable:
                continue

        results.append(company)
        if len(results) >= limit:
            break

    return results


async def get_company(name: str) -> Optional[dict]:
    """Get a specific company by name (case-insensitive partial match).

    Parameters
    ----------
    name : str
        Full or partial company name.

    Returns
    -------
    dict or None
        The first matching company, or ``None`` if no match is found.
    """
    if not name:
        return None

    data = _load_unicorns()
    name_lower = name.lower()

    # Try exact match first
    for company in data:
        if (company.get('name') or '').lower() == name_lower:
            return company

    # Fall back to partial / substring match
    for company in data:
        if name_lower in (company.get('name') or '').lower():
            return company

    return None
