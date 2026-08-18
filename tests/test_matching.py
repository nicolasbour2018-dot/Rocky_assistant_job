from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import CandidateProfile, JobOffer


def profile():
    return CandidateProfile(
        id=1,
        profile_name="Data",
        target_job_titles=["Data Analyst"],
        preferred_contracts=["CDI"],
        preferred_locations=["Paris"],
        remote_preferences=["Hybride"],
        minimum_salary=38_000,
    )


def test_matching_is_explainable_and_above_threshold():
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities=(
            "Analyse avec Python, SQL et Power BI. "
            "Le poste demande rigueur et autonomie."
        ),
        city="Paris",
        contract_type="CDI",
        remote_policy="Hybride",
        salary_min=42_000,
    )
    skills = [
        {"skill_name": "Python", "is_core_skill": True},
        {"skill_name": "SQL", "is_core_skill": False},
        {"skill_name": "Rigueur", "is_core_skill": False},
        {"skill_name": "Autonomie", "is_core_skill": False},
    ]
    result = calculate_match(offer, profile(), skills)
    assert result.score >= 70
    assert set(result.breakdown) == {
        "skills",
        "title",
        "contract",
        "location",
        "remote",
        "salary",
    }
    assert "Python" in result.detected_job_skills
    assert result.breakdown["skills"]["raw_score"] == 80.0
    assert set(result.breakdown["skills"]["matched_skills"]) == {
        "Python",
        "SQL",
        "Rigueur",
        "Autonomie",
    }
    assert result.breakdown["skills"]["missing_skills"] == ["Power BI"]


def test_recalculation_merges_saved_and_newly_detected_skills():
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Analyse avec Python, SQL et Power BI",
        detected_skills=["Python"],
    )
    result = calculate_match(
        offer,
        profile(),
        [
            {"skill_name": "Python", "is_core_skill": True},
            {"skill_name": "SQL", "is_core_skill": True},
        ],
    )
    assert set(result.detected_job_skills) == {"Python", "SQL", "Power BI"}
    assert result.breakdown["skills"]["raw_score"] == 66.7
    assert result.breakdown["skills"]["missing_skills"] == ["Power BI"]


def test_missing_offer_salary_is_not_a_penalty():
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Python et SQL",
        city="Paris",
        contract_type="CDI",
    )
    result = calculate_match(
        offer,
        profile(),
        [
            {"skill_name": "Python", "is_core_skill": True},
            {"skill_name": "SQL", "is_core_skill": False},
        ],
    )
    assert "salary" not in result.breakdown
    assert result.score > 0


def test_short_description_is_never_used_for_skill_analysis():
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        short_description="Python",
        responsibilities="La mission complète demande uniquement SQL.",
        description_is_full=True,
    )
    result = calculate_match(
        offer,
        profile(),
        [
            {"skill_name": "Python", "is_core_skill": True},
            {"skill_name": "SQL", "is_core_skill": True},
        ],
    )
    assert "SQL" in result.detected_job_skills
    assert "Python" not in result.detected_job_skills
