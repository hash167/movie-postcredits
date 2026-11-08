"""Fixtures for egg validation — Wrecking Crew swap must fail; real eggs pass."""

from types import SimpleNamespace

from src.egg_validation import (
    CastMember,
    cast_from_tmdb,
    check_cast_grounding,
    check_source_grounding,
    looks_like_plot_bio,
    validate_egg,
    validate_eggs,
)
from src.insight_filters import egg_fits_overview, filter_eggs_to_overview

# --- The Wrecking Crew (TMDB 1168190) ---
WRECKING_TITLE = "The Wrecking Crew"
WRECKING_OVERVIEW = (
    "Estranged half-brothers Jonny and James reunite after their father's "
    "mysterious death. As they search for the truth, buried secrets reveal a "
    "conspiracy threatening to tear their family apart."
)
WRECKING_CAST = cast_from_tmdb(
    [
        {"name": "Dave Bautista", "character": "James Hale"},
        {"name": "Jason Momoa", "character": "Jonny Hale"},
        {"name": "Temuera Morrison", "character": "Governor Peter Mahoe"},
        {"name": "Morena Baccarin", "character": "Valentina"},
        {"name": "Stephen Root", "character": "Detective Rennert"},
    ]
)

# Bad eggs that shipped in production (actor↔role swap + invented significance)
BAD_MOMOA = (
    "Jason Momoa's character, James, is a US Navy SEAL who returns home "
    "after their father's death."
)
BAD_MOMOA_SIG = "A nod to Aquaman's military connections in the DCEU."
BAD_BAUTISTA = (
    "Dave Bautista's character, Jonny, is a suspended police detective "
    "searching for the truth about his family."
)
BAD_BAUTISTA_SIG = "A subtle Guardians of the Galaxy reference to his tough-guy roles."

ARTICLE_CORRECT = (
    "https://example.com/wrecking-crew-easter-eggs",
    (
        "The Wrecking Crew easter eggs: Jason Momoa plays Jonny Hale, a "
        "suspended police detective in Honolulu. Dave Bautista portrays James "
        "Hale, a US Navy SEAL. In the mid-credits scene, Detective Rennert "
        "opens a second envelope revealing a photo of their father with "
        "Governor Peter Mahoe — a hidden detail that sets up a sequel. "
        "A blink-and-you'll-miss-it cameo poster of a 1970s Hawaiian surfing "
        "competition hangs in Jonny's apartment."
    ),
)

LEGIT_EGG = (
    "In the mid-credits scene, Detective Rennert opens a second envelope "
    "revealing a photo of their father with Governor Peter Mahoe — a hidden "
    "detail that sets up a sequel."
)

LEGIT_CAMEO_POSTER = (
    "A blink-and-you'll-miss-it cameo poster of a 1970s Hawaiian surfing "
    "competition hangs in Jonny's apartment."
)


def _egg(detail, significance="", confidence="medium", source_url=None):
    return SimpleNamespace(
        detail=detail,
        significance=significance,
        confidence=confidence,
        source_url=source_url,
    )


def test_wrecking_crew_cast_grounding_rejects_swap():
    ok, reason, _ = check_cast_grounding(BAD_MOMOA, WRECKING_CAST)
    assert ok is False
    assert "cast mismatch" in (reason or "")

    ok, reason, _ = check_cast_grounding(BAD_BAUTISTA, WRECKING_CAST)
    assert ok is False
    assert "cast mismatch" in (reason or "")


def test_wrecking_crew_correct_pairing_passes_cast():
    good = "Jason Momoa as Jonny Hale appears in a mid-credits stinger."
    ok, reason, _ = check_cast_grounding(good, WRECKING_CAST)
    assert ok is True, reason


def test_overview_filter_keeps_james_jonny_names():
    # Reproduces why overview filters alone were insufficient
    assert egg_fits_overview(BAD_MOMOA, WRECKING_TITLE, WRECKING_OVERVIEW) is True
    assert egg_fits_overview(BAD_BAUTISTA, WRECKING_TITLE, WRECKING_OVERVIEW) is True


def test_validate_eggs_drops_wrecking_crew_bad_eggs():
    eggs = [
        _egg(BAD_MOMOA, BAD_MOMOA_SIG),
        _egg(BAD_BAUTISTA, BAD_BAUTISTA_SIG),
        _egg(LEGIT_EGG),
        _egg(LEGIT_CAMEO_POSTER),
    ]
    result = validate_eggs(
        eggs,
        title=WRECKING_TITLE,
        overview=WRECKING_OVERVIEW,
        cast=WRECKING_CAST,
        articles=[ARTICLE_CORRECT],
        prefer_eggs=True,
    )
    details = [e.detail for e in result.kept]
    assert BAD_MOMOA not in details
    assert BAD_BAUTISTA not in details
    assert LEGIT_EGG in details
    assert LEGIT_CAMEO_POSTER in details
    assert len(result.dropped) >= 2


def test_source_grounding_strips_unsupported_significance_fluff():
    detail = (
        "A blink-and-you'll-miss-it cameo poster of a 1970s Hawaiian surfing "
        "competition hangs in Jonny's apartment."
    )
    ok, reason, sig, url = check_source_grounding(
        detail,
        "A subtle Aquaman / Guardians of the Galaxy nod.",
        [ARTICLE_CORRECT],
    )
    assert ok is True, reason
    assert "aquaman" not in sig.lower()
    assert "guardian" not in sig.lower()
    assert url == ARTICLE_CORRECT[0]


def test_source_grounding_rejects_invented_detail():
    invented = (
        "Thanos snaps in the post-credits scene while surfing with Aquaman "
        "and the Guardians of the Galaxy."
    )
    ok, reason, _, _ = check_source_grounding(
        invented, "", [ARTICLE_CORRECT]
    )
    assert ok is False


def test_plot_bio_rejected_real_egg_kept():
    bio = (
        "Jason Momoa's character, Jonny, is a suspended police detective "
        "who reunites with his half-brother."
    )
    assert looks_like_plot_bio(bio) is True
    assert looks_like_plot_bio(LEGIT_EGG) is False

    kept, reason, _ = validate_egg(
        _egg(bio),
        title=WRECKING_TITLE,
        overview=WRECKING_OVERVIEW,
        cast=WRECKING_CAST,
        articles=[ARTICLE_CORRECT],
        prefer_eggs=True,
    )
    assert kept is None
    assert "bio" in (reason or "")


def test_legit_egg_persists_source_url():
    egg = _egg(LEGIT_EGG)
    kept, reason, _ = validate_egg(
        egg,
        title=WRECKING_TITLE,
        overview=WRECKING_OVERVIEW,
        cast=WRECKING_CAST,
        articles=[ARTICLE_CORRECT],
        prefer_eggs=True,
    )
    assert kept is not None, reason
    assert kept.source_url == ARTICLE_CORRECT[0]


def test_existing_off_title_filters_still_work():
    # Sanity: prior Agent Zero / Superman fixtures still apply via insight_filters
    from src.insight_filters import article_is_about_title

    assert (
        article_is_about_title(
            "https://www.gamesradar.com/superman-2025-easter-eggs/",
            "Superman 2025 easter eggs include John Cena as Peacemaker.",
            "Agent Zero",
            2025,
            "tt35526133",
        )
        is False
    )


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all ok")
