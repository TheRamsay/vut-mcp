from functools import lru_cache

from vut_studis import StudisClient


@lru_cache(maxsize=1)
def get_studis_client() -> StudisClient:
    return StudisClient()
