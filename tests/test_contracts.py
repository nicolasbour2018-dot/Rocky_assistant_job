from dashboard.rocky.contracts import normalize_contract_details


def test_contract_and_work_schedule_are_separated():
    assert normalize_contract_details("permanent", "full_time") == (
        "CDI",
        "Temps plein",
    )
    assert normalize_contract_details("full-time", "") == (
        "",
        "Temps plein",
    )


def test_contract_can_be_recovered_from_job_description():
    assert normalize_contract_details(
        "full_time",
        "",
        "Ce poste est proposé en VIE à temps plein.",
    ) == ("VIE", "Temps plein")
    assert normalize_contract_details(
        "",
        "part-time",
        "Contrat à durée déterminée de six mois.",
    ) == ("CDD", "Temps partiel")


def test_common_word_vie_is_not_mistaken_for_vie_contract():
    assert normalize_contract_details(
        "",
        "",
        "Une entreprise où il fait bon vivre, avec un bel équilibre de vie.",
    ) == ("", "")
