"""Contrats de l'adaptation bornée du CV."""

from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw

from dashboard.rocky import cv_tailoring
from dashboard.rocky.config import Settings
from dashboard.rocky.cv_tailoring import (
    build_tailored_cv_plan,
    build_tailored_cv_plan_from_selection,
    create_tailored_cv,
)
from dashboard.rocky.models import JobOffer, ProfileProject


def test_cv_plan_uses_only_profile_evidence(tmp_path, monkeypatch):
    settings = Settings()
    source = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_textbox(
            pymupdf.Rect(190, 35, 570, 220),
            "Expérience et formation validées. " * 35,
            fontsize=8,
        )
        document.save(source)
    template = {
        "version": 1,
        "source_sha256": cv_tailoring.file_sha256(source),
        "page_count": 1,
        "background_rgb": [255, 255, 255],
        "zones": {
            "technical": [10, 382, 176, 512],
            "transversal": [8, 657, 178, 750],
            "project_1_title": [188, 236, 312, 259],
            "project_1_body": [192, 263, 311, 423],
            "project_2_title": [320, 257, 450, 281],
            "project_2_body": [326, 286, 446, 446],
            "project_3_title": [454, 281, 590, 307],
            "project_3_body": [462, 310, 581, 466],
        },
    }
    monkeypatch.setattr(cv_tailoring, "_template", lambda _settings: template)
    offer = JobOffer(
        "Data Scientist",
        "Acme",
        "Python, SQL, machine learning, rigueur et travail en équipe",
        description_is_full=True,
    )
    skills = [
        {"skill_name": "Python", "skill_category": "technical", "is_core_skill": True},
        {"skill_name": "SQL", "skill_category": "technical", "is_core_skill": True},
        {"skill_name": "Rigueur", "skill_category": "soft", "is_core_skill": True},
    ]
    projects = [
        ProfileProject(
            "analyse_eau",
            "Analyse eau",
            "Classer la potabilité de l'eau.",
            ("Python", "Scikit-Learn"),
            "Modèle de classification.",
            skills=("Machine Learning",),
        )
    ]
    plan = build_tailored_cv_plan(offer, skills, projects)
    serialized = str(plan)
    assert "Python" in serialized and "SQL" in serialized
    assert "Kubernetes" not in serialized
    target = tmp_path / "cv.pdf"
    create_tailored_cv(source, target, plan, settings)
    with pymupdf.open(target) as document:
        assert document.page_count == 1
        text = document[0].get_text()
        assert "Analyse eau" in text
        assert "Expérience et formation validées" in text
        project_labels = document[0].search_for("Problématique")
        assert project_labels
    assert project_labels[0].y0 >= 271

    zoom = 2

    def render(path: Path) -> Image.Image:
        with pymupdf.open(path) as document:
            pixmap = document[0].get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom), alpha=False
            )
            return Image.frombytes(
                "RGB", [pixmap.width, pixmap.height], pixmap.samples
            )

    source_image = render(source)
    target_image = render(target)
    difference = ImageChops.difference(source_image, target_image)
    allowed = Image.new("L", source_image.size, 0)
    allowed_draw = ImageDraw.Draw(allowed)
    for rectangle in template["zones"].values():
        x0, y0, x1, y1 = rectangle
        allowed_draw.rectangle(
            (x0 * zoom - 2, y0 * zoom - 2, x1 * zoom + 2, y1 * zoom + 2),
            fill=255,
        )
    outside = Image.new("RGB", source_image.size)
    outside.paste(difference, mask=ImageChops.invert(allowed))
    assert outside.getbbox() is None


def test_cv_plan_limits_profile_badges_per_type_and_projects():
    offer = JobOffer("Data Analyst", "Acme", "Python SQL communication")
    skills = [
        {
            "skill_name": f"Python outil {index}",
            "skill_category": "technical",
            "is_core_skill": False,
        }
        for index in range(8)
    ] + [
        {
            "skill_name": f"Communication {index}",
            "skill_category": "soft",
            "is_core_skill": False,
        }
        for index in range(8)
    ]
    projects = [
        ProfileProject(
            f"projet-{index}",
            f"Projet {index}",
            "Projet validé issu du profil.",
            ("Python",),
            "Livrable validé.",
        )
        for index in range(4)
    ]

    plan = build_tailored_cv_plan(offer, skills, projects)

    assert all(len(values) <= 6 for _, values in plan.technical_groups)
    assert len(plan.transversal_skills) == 6
    assert len(plan.projects) == 3

    manual_plan = build_tailored_cv_plan_from_selection(
        [("Outils et méthodes", [f"Outil {index}" for index in range(8)])],
        [f"Qualité {index}" for index in range(8)],
        projects,
    )
    assert len(manual_plan.technical_groups[0][1]) == 6
    assert len(manual_plan.transversal_skills) == 6
    assert len(manual_plan.projects) == 3
