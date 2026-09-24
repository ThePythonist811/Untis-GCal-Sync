import os
import webuntis

s = webuntis.Session(
    server=os.environ["UNTIS_SERVER"],
    school=os.environ["UNTIS_SCHOOL"],
    username=os.environ["UNTIS_USERNAME"],
    password=os.environ["UNTIS_PASSWORD"],
    useragent="GCalSync",
).login()
try:
    # Print name and longname so you can spot the exact value
    for k in s.klassen():
        print(repr(k.name), "|", k.long_name)
finally:
    s.logout()
