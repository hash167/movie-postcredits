from types import SimpleNamespace

from src.insight_filters import (
    article_is_about_title,
    egg_fits_overview,
    filter_eggs_to_overview,
)

TITLE = "Agent Zero"
OVERVIEW = (
    "When police officer Ilias is shot and left in a coma, Alma must reconnect "
    "with her former identity as Badh, a ruthless intelligence operative and "
    "skilled assassin. She brutally eliminates members of the Khoury family "
    "one by one, unleashing the fury of their leader Mansour, only to discover "
    "that Mansour is working with Joana her former secret service unit officer."
)

SUPERMAN_EGGS = [
    "The original design for Superman breaking out of chains is from the 1938 Superman from 'Action Comics #1'. Important for understanding the character's origins.",
    "John Cena appears as Peacemaker from the HBO Max show. A notable cameo that may be confusing for some viewers.",
    "Sean Gunn appears as Maxwell Lord, a character with ties to the Justice League. A brief cameo that may be important for the larger DCU.",
    "Frank Grillo appears as Rick Flag Sr., a complex character with connections to different media. A notable appearance that may be important for the larger DCU.",
    "The Hall of Justice is featured in the film. A significant easter egg that suggests the presence of meta-humans in the DCU.",
    "The Justice Gang (Working Title) is fighting a 'Dimensional Imp' in the background. A brief easter egg that suggests the presence of otherworldly threats in the DCU.",
]
BADH = "Badh's past is hinted at through her interactions with her husband. A subtle easter egg that suggests the consequences of her betrayal."


def test_reject_superman_listicle_for_agent_zero():
    url = "https://www.gamesradar.com/superman-2025-easter-eggs/"
    text = (
        "Superman 2025 easter eggs include John Cena as Peacemaker, "
        "the Hall of Justice, and the Justice Gang fighting a dimensional imp."
    )
    assert article_is_about_title(url, text, TITLE, 2025, "tt35526133") is False


def test_accept_fugitives_agent_zero_page():
    url = "https://fugitives.com/agent-zero-movie-ending-explained-2026/"
    text = (
        "Agent Zero follows Alma, once known as Badh, after officer Ilias is "
        "shot. She targets the Khoury family. IMDb tt35526133."
    )
    assert article_is_about_title(url, text, TITLE, 2025, "tt35526133") is True


def test_drop_superman_eggs_keep_badh():
    eggs = [SimpleNamespace(detail=d) for d in SUPERMAN_EGGS]
    eggs.append(SimpleNamespace(detail=BADH))
    kept = filter_eggs_to_overview(eggs, TITLE, OVERVIEW)
    details = [e.detail for e in kept]
    assert BADH in details
    assert len(details) == 1
    for d in SUPERMAN_EGGS:
        assert egg_fits_overview(d, TITLE, OVERVIEW) is False
