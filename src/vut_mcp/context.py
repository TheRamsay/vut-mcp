from vut_moodle import MoodleClient
from vut_studis import StudisClient


def get_studis_client() -> StudisClient:
    return StudisClient()


def get_moodle_client() -> MoodleClient:
    return MoodleClient()
