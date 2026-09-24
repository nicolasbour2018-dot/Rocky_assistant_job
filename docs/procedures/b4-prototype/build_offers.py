"""Build the 30 offers of the B4 triage prototype from the A1 archive (read-only).

Usage, from the repository root:

    python3 docs/procedures/b4-prototype/build_offers.py

Reads ``backups/rocky-v1-20260924/exports/csv/`` (offers and the active profile), writes
``rocky/offres/prototype_offers.json``. Standard library only; deterministic (same archive, same output).

The scores computed here are a **mock-up of the C4 format** (components, quoted evidence, confidence), so that the
prototype can display a "Pourquoi ?". They are not the C4 scoring and must never be reused as such.
"""

from __future__ import annotations

import csv
import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "backups" / "rocky-v1-20260924" / "exports" / "csv"
OUTPUT = ROOT / "rocky" / "offres" / "prototype_offers.json"
REFERENCE_DAY = date(2026, 9, 24)  # day of the archive
THRESHOLD = 60
PROFILE_ID = "1"
# Near-duplicates the title check misses (same employer spelled "Jems Group" / "JEMS"); see plan §8, C6.
EXCLUDED_IDS = {1240}

TRACKS = {
    "ai_ml": {
        "label": "IA / Machine learning",
        "pattern": r"\b(?:ia|ai|machine learning|ml|mlops|nlp|llm|deep learning|intelligence artificielle|genai)\b",
    },
    "data_analyst": {
        "label": "Data analyst",
        "pattern": r"data analyst|analyste (?:de )?donn[ée]es|analyste data|data analyste",
    },
}

# Skills looked for in the text of an offer, beyond those of the profile.
MARKET_SKILLS = [
    "Python", "SQL", "R", "Spark", "PySpark", "Scala", "Java", "Power BI", "Tableau", "Looker", "Qlik",
    "Excel", "VBA", "dbt", "Airflow", "Databricks", "Snowflake", "BigQuery", "AWS", "GCP", "Azure", "Docker",
    "Kubernetes", "Git", "PyTorch", "TensorFlow", "Keras", "Scikit-learn", "Pandas", "NumPy", "LLM", "NLP",
    "RAG", "LangChain", "Hugging Face", "MLOps", "MLflow", "Machine Learning", "Deep Learning", "SAS",
    "Statistiques", "A/B Testing", "ETL", "FastAPI", "Streamlit", "Alteryx", "DAX", "Power Query", "Stata",
    "Terraform", "Kafka", "Go", "C++", "Computer Vision", "Reinforcement Learning",
]

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}")
LONG_EXPERIENCE = re.compile(r"\b(?:[7-9]|1\d)\s*(?:\+\s*)?ans?\s+(?:d['’]\s?exp[ée]rience|minimum)", re.I)
INTERNSHIP = re.compile(r"\b(?:stage|stagiaire|alternance|alternant|apprenti|intern|internship)\b", re.I)
SENIORITY = re.compile(
    r"\b(?:senior|lead|principal|manager|responsable|head|directeur|directrice|exp[ée]riment[ée]|confirm[ée])\b", re.I
)
# Soft skills and spoken languages say nothing about the fit: only technical and business skills count.
COUNTED_CATEGORIES = {"technical", "business"}
MINIMUM_EVIDENCE = 4
PER_TRACK = {"above": 9, "below": 6}
MAX_PER_SOURCE = 10
MIN_INCOMPLETE = 5
REMOTE = re.compile(r"t[ée]l[ée]travail|full[- ]remote|remote", re.I)
PARIS = re.compile(r"paris|[iî]le[- ]de[- ]france|hauts-de-seine|la d[ée]fense|boulogne|issy|levallois|neuilly|92|75|93|94", re.I)
DAY_RATE_MAX = 2000
ANNUAL_MINIMUM = 35000


def read(name: str) -> list[dict[str, str]]:
    with (ARCHIVE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = EMAIL.sub("[adresse retirée]", text)
    text = PHONE.sub("[téléphone retiré]", text)
    return re.sub(r"[ \t]+", " ", text).strip()


SOURCE_NAMES = {
    "indeed": "Indeed",
    "hellowork": "Hellowork",
    "free-work": "Free-Work",
    "croix-rouge": "Croix-Rouge",
    "cadremploi": "Cadremploi",
    "efinancialcareers": "eFinancialCareers",
}


def source_name(raw: str) -> str:
    """Readable source name; the archive sometimes stored a URL or a domain (finding C1)."""
    lowered = raw.lower()
    for fragment, name in SOURCE_NAMES.items():
        if fragment in lowered:
            return name
    return raw


def tracks_of(title: str) -> list[str]:
    lowered = title.lower()
    return [key for key, track in TRACKS.items() if re.search(track["pattern"], lowered)]


def quote(text: str, needle: str, width: int = 70) -> str:
    """Short excerpt of ``text`` around ``needle`` (the evidence shown to the user)."""
    match = re.search(re.escape(needle), text, re.I)
    if match is None:
        return ""
    start, end = max(0, match.start() - width), min(len(text), match.end() + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def skill_in(skill: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(skill)}(?![\w-])", text, re.I) is not None


def number(value: str) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def component(key: str, label: str, verdict: str, summary: str, evidence: str = "") -> dict[str, str]:
    return {"key": key, "label": label, "verdict": verdict, "summary": summary, "evidence": evidence}


def assess(offer: dict[str, str], profile_skills: list[str], track_keys: list[str], text: str) -> dict[str, object]:
    title = clean(offer["job_title"])
    components = []
    weights = {"title": 25, "skills": 35, "location": 15, "contract": 10, "salary": 15}
    earned = 0.0

    labels = ", ".join(TRACKS[key]["label"] for key in track_keys)
    seniority = SENIORITY.search(title)
    if seniority:
        summary = f"Correspond à : {labels} ; niveau « {seniority.group(0)} » au-dessus de ta cible"
        components.append(component("title", "Intitulé ↔ pistes", "partial", summary, title))
        earned += weights["title"] * 0.5
    else:
        components.append(component("title", "Intitulé ↔ pistes", "good", f"Correspond à : {labels}", title))
        earned += weights["title"]

    detected = [s for s in dict.fromkeys(profile_skills + MARKET_SKILLS) if skill_in(s, text)]
    found = [s for s in detected if s in profile_skills]
    missing = [s for s in detected if s not in profile_skills]
    if not detected:
        components.append(component("skills", "Compétences", "unknown", "Aucune compétence repérée dans l'annonce"))
        earned += weights["skills"] * 0.3
    else:
        ratio = len(found) / len(detected)
        # Minimal evidence: a few skills are not enough for a full component.
        ratio *= min(1.0, len(detected) / MINIMUM_EVIDENCE)
        verdict = "good" if ratio >= 0.7 else "partial" if ratio >= 0.35 else "bad"
        summary = f"{len(found)} sur {len(detected)} dans ton profil"
        if len(detected) < MINIMUM_EVIDENCE:
            summary += " (trop peu d'indices pour conclure)"
        evidence = quote(text, (missing or found)[0])
        components.append(component("skills", "Compétences", verdict, summary, evidence))
        earned += weights["skills"] * ratio

    city = clean(offer["city"])
    remote = offer["remote_policy"] or ""
    remote_text = quote(text, REMOTE.search(text).group(0)) if REMOTE.search(text) else ""
    if PARIS.search(city):
        components.append(component("location", "Lieu et télétravail", "good", f"{city} : zone de Paris", city))
        earned += weights["location"]
    elif remote.lower() in {"full", "full_remote", "télétravail total"} or "full-remote" in text.lower():
        components.append(component("location", "Lieu et télétravail", "good", "Télétravail complet", remote_text))
        earned += weights["location"]
    elif city:
        verdict = "partial" if remote_text else "bad"
        summary = f"{city} : hors de la zone de Paris" + (", télétravail possible" if remote_text else "")
        components.append(component("location", "Lieu et télétravail", verdict, summary, remote_text or city))
        earned += weights["location"] * (0.5 if remote_text else 0)
    else:
        components.append(component("location", "Lieu et télétravail", "unknown", "Lieu non précisé"))
        earned += weights["location"] * 0.5

    contract = offer["contract_type"] or ""
    if contract in {"CDI", "CDD", "VIE"}:
        components.append(component("contract", "Contrat", "good", f"{contract} : dans tes préférences", contract))
        earned += weights["contract"]
    elif contract:
        components.append(component("contract", "Contrat", "bad", f"{contract} : hors de tes préférences", contract))
    else:
        components.append(component("contract", "Contrat", "unknown", "Contrat non précisé"))
        earned += weights["contract"] * 0.5

    low, high = number(offer["salary_min"]), number(offer["salary_max"])
    top = high or low
    if top is not None and top < DAY_RATE_MAX:
        components.append(
            component("salary", "Salaire ou TJM", "unknown", f"TJM de {top:.0f} € par jour : pas un salaire annuel")
        )
        earned += weights["salary"] * 0.5
    elif top is not None:
        verdict = "good" if top >= ANNUAL_MINIMUM else "bad"
        shown = f"{low:.0f}–{high:.0f} €" if low and high else f"{top:.0f} €"
        components.append(component("salary", "Salaire ou TJM", verdict, f"{shown} par an (minimum souhaité : 35 000 €)"))
        earned += weights["salary"] * (1 if verdict == "good" else 0)
    else:
        components.append(component("salary", "Salaire ou TJM", "unknown", "Salaire non précisé"))
        earned += weights["salary"] * 0.5

    eliminatory = []
    if INTERNSHIP.search(title) or contract.lower() in {"stage", "alternance", "apprentissage"}:
        eliminatory.append({"label": "Stage ou alternance", "evidence": title})
    long_xp = LONG_EXPERIENCE.search(text)
    if long_xp:
        eliminatory.append({"label": "Expérience exigée très élevée", "evidence": quote(text, long_xp.group(0))})

    score = round(earned)
    if eliminatory:
        score = min(score, 40)
    full = offer["description_is_full"].lower() == "true"
    if full and len(detected) >= 5:
        confidence = "high"
    elif full or len(detected) >= 3:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "score": score,
        "confidence": confidence,
        "components": components,
        "eliminatory": eliminatory,
        "skills_found": found,
        "skills_missing": missing,
    }


def build() -> dict[str, object]:
    profile = next(p for p in read("candidate_profiles.csv") if p["id"] == PROFILE_ID)
    profile_skills = [
        s["skill_name"]
        for s in read("candidate_skills.csv")
        if s["profile_id"] == PROFILE_ID and s["skill_category"] in COUNTED_CATEGORIES
    ]
    candidates = []
    for offer in read("job_offers.csv"):
        track_keys = tracks_of(offer["job_title"])
        text = clean(offer["responsibilities"] or offer["short_description"])
        if not track_keys or len(text) < 150 or int(offer["id"]) in EXCLUDED_IDS:
            continue
        salary_min, salary_max = number(offer["salary_min"]), number(offer["salary_max"])
        top = salary_max or salary_min
        entry = {
            "id": int(offer["id"]),
            "title": clean(offer["job_title"]),
            "company": clean(offer["company_name"]) or None,
            "city": clean(offer["city"]) or None,
            "remote": offer["remote_policy"] or None,
            "contract": offer["contract_type"] or None,
            "salary": None
            if top is None
            else {
                "min": salary_min,
                "max": salary_max,
                "period": "day" if top < DAY_RATE_MAX else "year",
            },
            "source": source_name(offer["source_name"]),
            "url": offer["source_url"] or offer["application_url"] or None,
            "published_on": offer["publication_date"] or None,
            "deadline": offer["application_deadline"][:10] or None,
            "description": text,
            "description_is_full": offer["description_is_full"].lower() == "true",
            "tracks": track_keys,
            **assess(offer, profile_skills, track_keys, text),
        }
        candidates.append(entry)
    return {
        "note": "Prototype B4 : offres réelles de l'archive A1 ; scores provisoires, maquette du format C4.",
        "threshold": THRESHOLD,
        "reference_day": REFERENCE_DAY.isoformat(),
        "tracks": [{"key": key, "label": track["label"]} for key, track in TRACKS.items()],
        "profile": {
            "target_titles": json.loads(profile["target_job_titles"] or "[]"),
            "locations": json.loads(profile["preferred_locations"] or "[]"),
            "contracts": json.loads(profile["preferred_contracts"] or "[]"),
            "minimum_salary": number(profile["minimum_salary"]),
            "skills": profile_skills,
        },
        "offers": select(candidates),
    }


def select(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    """30 offers covering the hard cases, in quotas per track and side of the threshold; deterministic."""
    seen: set[str] = set()
    pool = []
    for offer in sorted(candidates, key=lambda o: o["id"]):  # type: ignore[arg-type, return-value]
        where = offer["company"] or offer["city"]
        key = re.sub(r"\W+", "", f"{offer['title']}{where}".lower())
        if key not in seen:  # the same offer published on two sources counts once
            seen.add(key)
            pool.append(offer)

    chosen: list[dict[str, object]] = []
    filled = {(track, side): 0 for track in TRACKS for side in PER_TRACK}

    def bucket(offer: dict[str, object]) -> tuple[str, str]:
        side = "above" if offer["score"] >= THRESHOLD else "below"  # type: ignore[operator]
        return offer["tracks"][0], side  # type: ignore[index]

    def fits(offer: dict[str, object]) -> bool:
        track, side = bucket(offer)
        per_source = sum(1 for o in chosen if o["source"] == offer["source"])
        return offer not in chosen and filled[(track, side)] < PER_TRACK[side] and per_source < MAX_PER_SOURCE

    def take(predicate, count: int) -> None:  # type: ignore[no-untyped-def]
        for offer in sorted(pool, key=lambda o: sum(1 for c in chosen if c["source"] == o["source"])):
            if count == 0:
                return
            if predicate(offer) and fits(offer):
                chosen.append(offer)
                filled[bucket(offer)] += 1
                count -= 1

    old_limit = date(REFERENCE_DAY.year, REFERENCE_DAY.month - 2, REFERENCE_DAY.day).isoformat()
    take(lambda o: len(o["tracks"]) == 2, 2)
    take(lambda o: o["salary"] and o["salary"]["period"] == "day", 1)
    take(lambda o: o["published_on"] and o["published_on"] < old_limit, 1)
    take(lambda o: o["eliminatory"], 2)
    take(lambda o: not o["description_is_full"], MIN_INCOMPLETE)
    take(lambda o: o["deadline"] is not None, 4)
    take(lambda o: o["confidence"] == "low", 2)
    take(lambda o: True, 30 - len(chosen))
    return sorted(chosen, key=lambda o: -o["score"])  # type: ignore[operator]


def main() -> None:
    data = build()
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    offers = data["offers"]
    below = sum(1 for offer in offers if offer["score"] < THRESHOLD)  # type: ignore[union-attr]
    print(f"{len(offers)} offres écrites dans {OUTPUT.relative_to(ROOT)} ; {below} sous le seuil {THRESHOLD}.")


if __name__ == "__main__":
    main()
