"""Process-wide bounded LRU cache for tub images.

TubRecord historically kept every loaded image on the record itself
(``self._image``) with no capacity limit, so one training epoch over a
large tub left the entire tub resident in RAM (a 20k-frame 320x240 tub
is ~4.4GB of uint8 arrays — enough to OOM the 7.1GB AidLux board, see
CHANGELOG 2026-10-09). This module replaces that unbounded per-record
slot with a single process-wide cache bounded by a total byte budget:
entries are evicted least-recently-used first once the budget is
exceeded.

The cache is keyed by the image's absolute path and stores whatever the
caller put there (decoded uint8 ndarray for CachePolicy.ARRAY, encoded
bytes for CachePolicy.BINARY, PIL images for the as_nparray=False path),
mirroring the per-record slot semantics of the old implementation while
keeping residency bounded.

The budget is a soft cap: a single entry larger than the whole budget is
still retained (and everything else evicted) rather than dropped, so a
too-small budget degrades to "cache one image", never to a loop.
"""
import logging
import sys
import threading
from collections import OrderedDict
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 256MiB default: ~1194 frames of 320x240x3 (230400B). Big enough to keep
# small tubs (< ~1200 records) fully hot across epochs, small enough that
# training coexists with the ~3GB desktop/AI-tool baseline on a 7.1GB
# board. Measured decode cost of a miss is ~0.55ms/frame (2026-10-09,
# AidLux A1), so eviction is cheap compared to per-epoch compute.
DEFAULT_CACHE_MAX_BYTES = 256 * 1024 * 1024

_UNKNOWN_SIZE_WARNED = False


def _estimate_bytes(value: Any) -> int:
    """Best-effort in-memory size of a cached value.

    numpy arrays and bytes are exact; PIL images are w*h*channels which
    ignores header/object overhead but is the dominant term. Unknown
    types fall back to sys.getsizeof with a one-time warning.
    """
    global _UNKNOWN_SIZE_WARNED
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return int(value.nbytes)
    except ImportError:  # pragma: no cover - numpy is a hard dep elsewhere
        pass
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    try:
        from PIL import Image
        if isinstance(value, Image.Image):
            return value.width * value.height * len(value.mode)
    except ImportError:  # pragma: no cover
        pass
    if not _UNKNOWN_SIZE_WARNED:
        logger.warning('Caching object of unknown type %s; byte budget '
                       'accounting falls back to sys.getsizeof and may be '
                       'inaccurate.', type(value))
        _UNKNOWN_SIZE_WARNED = True
    return sys.getsizeof(value)


class BoundedImageCache:
    """Thread-safe LRU cache with a total byte budget."""

    def __init__(self, max_bytes: int = DEFAULT_CACHE_MAX_BYTES) -> None:
        self._lock = threading.RLock()
        self._max_bytes = int(max_bytes)
        self._entries: "OrderedDict[str, Any]" = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def curr_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._entries

    def configure(self, max_bytes: int) -> bool:
        """Set the byte budget (evicting if it shrank).

        :return: True if the budget changed.
        """
        new = int(max_bytes)
        if new <= 0:
            raise ValueError(f'CACHE_MAX_BYTES must be > 0, got {new}')
        with self._lock:
            changed = new != self._max_bytes
            self._max_bytes = new
            self._evict_to_budget()
        return changed

    def get(self, key: str, default: Any = None) -> Any:
        """Return the cached value, refreshing LRU order, or `default`."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return self._entries[key]
            self.misses += 1
            return default

    def put(self, key: str, value: Any) -> None:
        """Insert/replace `key` and evict LRU entries over budget."""
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= _estimate_bytes(old)
            self._entries[key] = value
            self._bytes += _estimate_bytes(value)
            self._evict_to_budget()

    def _evict_to_budget(self) -> None:
        while self._bytes > self._max_bytes and len(self._entries) > 1:
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= _estimate_bytes(evicted)
            self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                'entries': len(self._entries),
                'curr_bytes': self._bytes,
                'max_bytes': self._max_bytes,
                'hits': self.hits,
                'misses': self.misses,
                'evictions': self.evictions,
            }


_GLOBAL_CACHE = None
_GLOBAL_CACHE_LOCK = threading.Lock()


def get_global_image_cache() -> BoundedImageCache:
    """The process-wide cache shared by all TubRecords.

    Created lazily on first use; the budget is (re)configured from
    CACHE_MAX_BYTES every time a TubRecord is constructed, so the most
    recently loaded config wins.
    """
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        with _GLOBAL_CACHE_LOCK:
            if _GLOBAL_CACHE is None:
                _GLOBAL_CACHE = BoundedImageCache()
    return _GLOBAL_CACHE
