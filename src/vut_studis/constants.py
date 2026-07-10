from datetime import timedelta

ELECTRONIC_INDEX_PATH = "/studis/student.phtml?sn=el_index"
PERSONAL_SCHEDULE_PATH = "/studis/student.phtml?sn=osobni_rozvrh"
COURSE_UPDATES_PATH = "/studis/student.phtml?sn=aktuality_predmet"
GRADES_CACHE_TTL = timedelta(minutes=30)
COURSE_DETAIL_CACHE_TTL = timedelta(minutes=30)
SCHEDULE_CACHE_TTL = timedelta(minutes=30)
COURSE_UPDATES_CACHE_TTL = timedelta(minutes=30)
