"""A fictional profile with a full master CV, reference of the rendering tests (public repository: no real person)."""

from __future__ import annotations

from datetime import date

from rocky.profil.model import (
    CvLayout,
    Experience,
    ExperienceDraft,
    ExperienceKind,
    Hobby,
    Identity,
    Language,
    LanguageDraft,
    LanguageLevel,
    Link,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    Skill,
    SkillCategory,
    SkillDraft,
    SkillGroup,
    Text,
)

TODAY = date(2026, 9, 29)


def _skill(skill_id: int, fr: str, en: str, category: SkillCategory) -> Skill:
    return Skill(skill_id, SkillDraft(label=Text(fr, en), category=category))


SKILLS = (
    _skill(1, "Python", "Python", SkillCategory.TECHNICAL),
    _skill(2, "SQL", "SQL", SkillCategory.TECHNICAL),
    _skill(3, "Pandas", "Pandas", SkillCategory.TECHNICAL),
    _skill(4, "Apprentissage automatique", "Machine learning", SkillCategory.TECHNICAL),
    _skill(
        5,
        "Traitement du langage (NLP)",
        "Natural language processing",
        SkillCategory.TECHNICAL,
    ),
    _skill(6, "Docker", "Docker", SkillCategory.TECHNICAL),
    _skill(7, "FastAPI", "FastAPI", SkillCategory.TECHNICAL),
    _skill(8, "Curiosité", "Curiosity", SkillCategory.SOFT),
    _skill(9, "Gestion de projet", "Project management", SkillCategory.BUSINESS),
    _skill(10, "Pédagogie", "Teaching", SkillCategory.SOFT),
)


def sample_profile(*, english: bool = True) -> Profile:
    """Camille Martin, data scientist; ``english=False`` leaves the English of one experience unwritten."""
    return Profile(
        id=1,
        account_id=1,
        identity=Identity(
            full_name="Camille Martin",
            contact_email="camille.martin@example.org",
            phone="06 00 00 00 00",
            city="Lyon",
            links=(
                Link("LinkedIn", "https://www.linkedin.com/in/camille-martin-exemple"),
                Link("GitHub", "https://github.com/camille-exemple"),
            ),
            headline=Text(
                "Data scientist issue de la **logistique**, je transforme des données "
                "opérationnelles en **outils de décision** utilisés au quotidien.",
                "Data scientist with a **logistics** background, I turn operational data "
                "into **decision tools** used every day.",
            ),
            title=Text("Data Scientist", "Data Scientist"),
            birth_date=date(1990, 5, 2),
            show_age=True,
        ),
        preferences=Preferences(),
        onboarding=OnboardingState(),
        skills=SKILLS,
        languages=(
            Language(1, LanguageDraft("fr", LanguageLevel.NATIVE)),
            Language(2, LanguageDraft("en", LanguageLevel.C1)),
        ),
        experiences=(
            Experience(
                1,
                ExperienceDraft(
                    kind=ExperienceKind.JOB,
                    title=Text("Data scientist", "Data scientist"),
                    organisation="Transports Exemple",
                    start=date(2023, 1, 1),
                    place="Lyon",
                    bullets_fr=(
                        "Prévision de la demande par entrepôt : erreur réduite de 18 %.",
                        "Tableau de bord des retards, utilisé par 40 exploitants.",
                    ),
                    bullets_en=(
                        "Demand forecast per warehouse: error cut by 18%.",
                        "Delay dashboard used by 40 operators.",
                    )
                    if english
                    else (),
                ),
            ),
            Experience(
                2,
                ExperienceDraft(
                    kind=ExperienceKind.JOB,
                    title=Text("Responsable d'exploitation", "Operations manager"),
                    organisation="Entrepôts Fictifs",
                    start=date(2016, 9, 1),
                    end=date(2022, 6, 1),
                    bullets_fr=("Équipe de 25 personnes, 3 sites.",),
                    bullets_en=("Team of 25 people, 3 sites.",),
                ),
            ),
            Experience(
                3,
                ExperienceDraft(
                    kind=ExperienceKind.EDUCATION,
                    title=Text("Master en science des données", "MSc in data science"),
                    organisation="Université Exemple",
                    start=date(2021, 9, 1),
                    end=date(2022, 9, 1),
                ),
            ),
        ),
        projects=(
            Project(
                1,
                ProjectDraft(
                    name=Text("Tri des messages clients", "Customer message triage"),
                    problem=Text(
                        "Des milliers de messages à orienter chaque jour.",
                        "Thousands of messages to route every day.",
                    ),
                    work=Text(
                        "Classifieur de texte et API de service.",
                        "Text classifier and serving API.",
                    ),
                    results=Text(
                        "85 % des messages orientés sans intervention.",
                        "85% of messages routed unattended.",
                    ),
                    stack=("Python", "FastAPI", "Docker"),
                    stack_en=("Python", "FastAPI", "Docker"),
                ),
            ),
            Project(
                2,
                ProjectDraft(
                    name=Text("Prévision des stocks", "Stock forecasting"),
                    problem=Text(
                        "Ruptures fréquentes en fin de mois.",
                        "Frequent stock-outs at month end.",
                    ),
                    work=Text(
                        "Modèle de prévision hebdomadaire.", "Weekly forecasting model."
                    ),
                    stack=("Python", "Pandas"),
                    stack_en=("Python", "Pandas"),
                ),
            ),
        ),
        cv=CvLayout(
            groups=(
                SkillGroup(
                    Text("Langages et données", "Languages and data"), (1, 2, 3)
                ),
                SkillGroup(Text("Science des données", "Data science"), (4, 5)),
                SkillGroup(Text("Déploiement", "Deployment"), (6, 7)),
            ),
            transversal=(8, 9, 10),
            projects=(1, 2),
            hobbies=(
                Hobby(Text("Randonnée", "Hiking")),
                Hobby(Text("Échecs", "Chess")),
            ),
        ),
    )
