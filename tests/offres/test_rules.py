"""Rules of the stored offers: cross-site match key and fingerprint of the scoring inputs (C6, Q4 and Q5)."""

from __future__ import annotations

from rocky.offres.rules import match_key, scoring_inputs
from rocky.profil.rules import make_identity, make_skill, make_track
from rocky.profil.usecases import ProfileEditor
from tests.offres.fakes import NOW, posting
from tests.profil.fakes import InMemoryProfileStore


def test_two_sites_showing_the_same_posting_share_its_key() -> None:
    apec = posting("1", source="apec", title="Data analyst (H/F)", company="Jems Group")
    linkedin = posting("2", source="linkedin", title="Data Analyst", company="JEMS")

    assert match_key(apec) == match_key(linkedin) == "data analyst|jems"


def test_another_title_or_employer_gives_another_key() -> None:
    reference = match_key(posting("1", title="Data analyst", company="Jems"))

    assert match_key(posting("2", title="Data scientist", company="Jems")) != reference
    assert match_key(posting("3", title="Data analyst", company="Axa")) != reference


def test_a_posting_without_employer_has_no_key() -> None:
    assert match_key(posting("1", company=None)) is None
    assert match_key(posting("2", company="Groupe")) is None


def editor() -> ProfileEditor:
    return ProfileEditor(
        InMemoryProfileStore(), clock=lambda: NOW, account_id=1, email="a@b.fr"
    )


def test_the_fingerprint_follows_what_the_score_reads() -> None:
    profile_editor = editor()
    profile_editor.add_skill(make_skill(label_fr="Python", category="technical"))
    track = profile_editor.add_track(make_track(name="Data", titles=["Data analyst"]))
    before = scoring_inputs(profile_editor.profile()).inputs_hash

    profile_editor.save_identity(make_identity(full_name="Nicolas", headline_fr="Data"))
    assert scoring_inputs(profile_editor.profile()).inputs_hash == before

    profile_editor.update_track(
        track, make_track(name="Data", titles=["Data analyst", "BI analyst"])
    )
    after_track = scoring_inputs(profile_editor.profile()).inputs_hash
    assert after_track != before

    profile_editor.add_skill(make_skill(label_fr="SQL", category="technical"))
    assert scoring_inputs(profile_editor.profile()).inputs_hash != after_track


def test_a_paused_track_changes_the_fingerprint() -> None:
    profile_editor = editor()
    profile_editor.add_track(make_track(name="Data", titles=["Data analyst"]))
    other = profile_editor.add_track(make_track(name="IA", titles=["Data scientist"]))
    before = scoring_inputs(profile_editor.profile()).inputs_hash

    profile_editor.pause_track(other)

    assert scoring_inputs(profile_editor.profile()).inputs_hash != before
