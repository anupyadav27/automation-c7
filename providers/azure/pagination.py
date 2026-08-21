"""Azure pagination helpers with retry-on-rate-limit.

Standardizes Azure SDK ItemPaged iterators into flat lists of dicts.
Handles HTTP 429 throttling with exponential backoff.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2.0    # seconds
MAX_DELAY = 30.0    # seconds


def azure_list_all(
    client_method: Callable,
    serializer: Optional[Callable] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Iterate an Azure SDK ItemPaged result into a flat list of dicts.

    Handles:
    - Lazy pagination (SDK fetches pages automatically on iteration)
    - HTTP 429 rate limit with exponential backoff (MAX_RETRIES=3)
    - Per-item serialization via .as_dict() or custom serializer
    - Partial results returned on non-retryable errors (logged, not raised)

    Args:
        client_method: Azure SDK list method to call, e.g.::

            client.virtual_machines.list_all
            client.storage_accounts.list

        serializer: Optional custom item serializer. Defaults to item.as_dict().
        **kwargs: Additional keyword arguments forwarded to client_method.

    Returns:
        Flat list of resource dicts. Empty list on total failure.
    """
    results: List[Dict[str, Any]] = []
    attempt = 0

    while attempt <= MAX_RETRIES:
        try:
            pager = client_method(**kwargs)
            for item in pager:
                if serializer is not None:
                    results.append(serializer(item))
                elif hasattr(item, "as_dict"):
                    results.append(item.as_dict())
                else:
                    results.append(vars(item))
            return results

        except HttpResponseError as exc:
            if exc.status_code == 429:
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                logger.warning(
                    "Azure rate limit (429) — retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, MAX_RETRIES,
                )
                time.sleep(delay)
                attempt += 1
            else:
                logger.error(
                    "Azure API error (HTTP %s): %s — returning %d partial results",
                    exc.status_code, exc.message, len(results),
                )
                return results

    logger.error(
        "Azure rate limit exceeded after %d retries — returning %d partial results",
        MAX_RETRIES, len(results),
    )
    return results
