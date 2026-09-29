"""One-way sync: WebUntis timetable -> Google Calendar.

Modes:
  python sync.py --raw       print raw getTimetable entries (check teacher fields), no Google
  python sync.py --dry-run   print desired events, no Google
  python sync.py             full sync (needs all env vars)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from zoneinfo import ZoneInfo

import webuntis

TZ = "Europe/Berlin"
DAYS = 14
SERVER = os.environ.get("UNTIS_SERVER", "kas-bc.webuntis.com")
SCHOOL = os.environ.get("UNTIS_SCHOOL", "kas-bc")


def h(text):
    return hashlib.sha1(text.encode()).hexdigest()


# ---------- Untis ----------

def untis_login():
    # Fail hard on bad credentials: no retries, avoids account lockout
    return webuntis.Session(
        server=SERVER, school=SCHOOL,
        username=os.environ["UNTIS_USERNAME"],
        password=os.environ["UNTIS_PASSWORD"],
        useragent="GCalSync",
    ).login()


def fetch_raw(s):
    """Raw JSON-RPC getTimetable for the logged-in student (personal timetable,
    not the whole class), with *Fields so names come back inline."""
    today = dt.date.today()
    person_type = s.login_result["personType"]  # 5 = student
    person_id = s.login_result["personId"]
    return s._request("getTimetable", {"options": {
        "element": {"id": person_id, "type": person_type},
        "startDate": int(today.strftime("%Y%m%d")),
        "endDate": int((today + dt.timedelta(days=DAYS)).strftime("%Y%m%d")),
        "showInfo": True,
        "showSubstText": True,
        "klasseFields": ["id", "name"],
        "subjectFields": ["id", "name", "longname"],
        "roomFields": ["id", "name", "longname"],
        "teacherFields": ["id", "name", "longname"],
    }})


def names(items, prefer_long=False):
    """Extract display names from a list of element dicts; tolerate id-only entries."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        n = (it.get("longname") if prefer_long else None) or it.get("name") or it.get("longname")
        if n and n not in out:
            out.append(n)
    return out


def to_dt(date_int, time_int):
    d = dt.datetime.strptime(str(date_int), "%Y%m%d")
    return d.replace(hour=time_int // 100, minute=time_int % 100, tzinfo=ZoneInfo(TZ))


def build_desired(raw):
    """Turn raw Untis entries into {event_id: google_event_body}."""
    desired = {}
    for e in raw:
        code = e.get("code")
        if code == "cancelled":
            continue  # cancelled lessons are removed from the calendar
        start = to_dt(e["date"], e["startTime"])
        end = to_dt(e["date"], e["endTime"])
        subj = ", ".join(names(e.get("su"), prefer_long=True)) or "Event"
        rooms = names(e.get("ro"))
        teachers = names(e.get("te"), prefer_long=True)
        info = " | ".join(x for x in (e.get("substText"), e.get("info")) if x)

        eid = h(f"{start.isoformat()}|{end.isoformat()}|{subj}")  # hex is valid Google ID charset
        if eid in desired:  # parallel entries with same subject/time: merge
            prev = desired[eid]["_m"]
            prev["rooms"] = list(dict.fromkeys(prev["rooms"] + rooms))
            prev["teachers"] = list(dict.fromkeys(prev["teachers"] + teachers))
            continue
        desired[eid] = {"_m": {"subj": subj, "rooms": rooms, "teachers": teachers,
                               "info": info, "code": code, "start": start, "end": end}}

    bodies = {}
    for eid, d in desired.items():
        m = d["_m"]
        room = ", ".join(m["rooms"])
        teacher = ", ".join(m["teachers"])
        desc = []
        if teacher:
            desc.append(f"Lehrer: {teacher}")
        if room:
            desc.append(f"Raum: {room}")
        if m["info"]:
            desc.append(f"Info: {m['info']}")
        prefix = "[VERTRETUNG] " if m["code"] == "irregular" else ""
        bodies[eid] = {
            "id": eid,
            "summary": prefix + m["subj"],
            "location": room,
            "description": "\n".join(desc),
            "start": {"dateTime": m["start"].isoformat(), "timeZone": TZ},
            "end": {"dateTime": m["end"].isoformat(), "timeZone": TZ},
            "extendedProperties": {"private": {
                "src": "untis",
                "h": h(f"{m['subj']}|{room}|{teacher}|{m['code']}|{m['info']}"),
            }},
        }
    return bodies


# ---------- Google ----------

def google_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_existing(service, cal_id):
    """Only events created by this script (private extended property), paginated."""
    t0 = dt.datetime.combine(dt.date.today(), dt.time.min, tzinfo=ZoneInfo(TZ))
    t1 = t0 + dt.timedelta(days=DAYS + 1)
    out, token = {}, None
    while True:
        r = service.events().list(
            calendarId=cal_id, timeMin=t0.isoformat(), timeMax=t1.isoformat(),
            singleEvents=True, privateExtendedProperty="src=untis",
            maxResults=250, pageToken=token,
        ).execute()
        for ev in r.get("items", []):
            out[ev["id"]] = ev
        token = r.get("nextPageToken")
        if not token:
            return out


def sync_google(desired):
    from googleapiclient.errors import HttpError
    cal_id = os.environ["GOOGLE_CALENDAR_ID"]
    service = google_service()
    existing = list_existing(service, cal_id)
    ev = service.events()
    added = updated = deleted = 0

    for eid, body in desired.items():
        old = existing.get(eid)
        new_h = body["extendedProperties"]["private"]["h"]
        if old and old.get("extendedProperties", {}).get("private", {}).get("h") == new_h:
            continue  # unchanged
        try:
            if old:
                ev.update(calendarId=cal_id, eventId=eid, body=body).execute()
                updated += 1
            else:
                ev.insert(calendarId=cal_id, body=body).execute()
                added += 1
        except HttpError as err:
            if err.resp.status == 409:  # ID reserved by a previously deleted event
                ev.update(calendarId=cal_id, eventId=eid, body={**body, "status": "confirmed"}).execute()
                added += 1
            else:
                raise

    stale = set(existing) - set(desired)
    if not desired and stale:
        # Safety net: empty Untis result (error, holiday?) must not wipe the calendar
        print(f"WARNING: Untis returned 0 lessons but {len(stale)} events exist. Skipping deletes.")
    else:
        for eid in stale:
            ev.delete(calendarId=cal_id, eventId=eid).execute()
            deleted += 1

    print(f"OK: desired={len(desired)} added={added} updated={updated} deleted={deleted}")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="print raw Untis entries and exit")
    ap.add_argument("--dry-run", action="store_true", help="print desired events, no Google")
    args = ap.parse_args()

    s = untis_login()
    try:
        raw = fetch_raw(s)
    finally:
        s.logout()

    if args.raw:
        print(json.dumps(raw[:3], indent=2, ensure_ascii=False))
        has_te = any(names(e.get("te")) for e in raw)
        print(f"\n{len(raw)} entries, teacher names present: {has_te}")
        return

    desired = build_desired(raw)
    if args.dry_run:
        for b in sorted(desired.values(), key=lambda x: x["start"]["dateTime"]):
            print(b["start"]["dateTime"][:16], b["summary"], "|", b["location"], "|",
                  b["description"].replace("\n", " / "))
        print(f"\n{len(desired)} events")
        return

    sync_google(desired)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
