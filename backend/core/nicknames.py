"""Nickname families for the given-name feature (English and common Spanish forms).

Written independently of the generator's table (evaluation plan section 2, anti-tautology):
W1 must not import this and we must not import theirs. Every entry is a set of folded tokens
that may stand for one person; the canonical name is just another member.
"""

from __future__ import annotations

_FAMILIES: tuple[tuple[str, ...], ...] = (
    # English
    ("robert", "bob", "rob", "bobby", "robbie", "bert"),
    ("william", "bill", "will", "billy", "willie", "liam"),
    ("richard", "rick", "dick", "rich", "richie", "ricky"),
    ("elizabeth", "liz", "beth", "betty", "eliza", "lisa", "lizzie", "betsy"),
    ("margaret", "maggie", "peggy", "meg", "marge", "margie"),
    ("james", "jim", "jimmy", "jamie"),
    ("john", "jack", "johnny", "jon"),
    ("michael", "mike", "mikey", "mick"),
    ("charles", "chuck", "charlie", "chas"),
    ("thomas", "tom", "tommy"),
    ("katherine", "catherine", "kate", "kathy", "katie", "kat", "cathy", "kay"),
    ("joseph", "joe", "joey"),
    ("edward", "ed", "eddie", "ted", "teddy", "ned"),
    ("anthony", "tony"),
    ("daniel", "dan", "danny", "dani"),
    ("christopher", "chris", "kit"),
    ("matthew", "matt"),
    ("patricia", "pat", "patty", "trish", "tricia", "paty"),
    ("jennifer", "jen", "jenny"),
    ("susan", "sue", "susie", "suzy"),
    ("david", "dave", "davey"),
    ("steven", "stephen", "steve"),
    ("andrew", "andy", "drew"),
    ("nicholas", "nick"),
    ("benjamin", "ben", "benny"),
    ("alexander", "alex", "al", "xander"),
    ("samuel", "sam", "sammy"),
    ("jonathan", "jon", "jonny"),
    ("timothy", "tim", "timmy"),
    ("kenneth", "ken", "kenny"),
    ("ronald", "ron", "ronnie"),
    ("donald", "don", "donnie"),
    ("barbara", "barb", "barbie"),
    ("deborah", "debra", "deb", "debbie"),
    ("rebecca", "becky", "becca"),
    ("jessica", "jess", "jessie"),
    ("dorothy", "dot", "dottie"),
    ("abigail", "abby"),
    ("victoria", "vicky", "tori"),
    ("edward", "eduardo"),
    # Spanish
    ("francisco", "paco", "pancho", "curro", "fran", "frank", "frankie", "kiko"),
    ("jose", "pepe", "chepe", "joe"),
    ("guadalupe", "lupe", "lupita"),
    ("maria", "ma", "mari", "mary", "marie"),
    ("jesus", "chuy", "chucho"),
    ("ignacio", "nacho"),
    ("eduardo", "lalo"),
    ("alberto", "beto"),
    ("roberto", "beto", "robert"),
    ("alfonso", "poncho"),
    ("concepcion", "concha", "conchita"),
    ("dolores", "lola", "loli"),
    ("enrique", "quique", "kike", "henry"),
    ("antonio", "tono", "toni", "anthony"),
    ("manuel", "manolo", "manu"),
    ("rosario", "charo"),
    ("mercedes", "meche"),
    ("luis", "lucho", "louis"),
    ("ramon", "moncho", "ray"),
    ("santiago", "santi", "chago"),
    ("sebastian", "sebas"),
    ("alejandro", "alex", "ale", "jandro"),
    ("alejandra", "ale", "alex"),
    ("fernando", "fer", "nando"),
    ("guillermo", "memo", "william"),
    ("jorge", "coco", "george"),
    ("josefina", "pina", "chepina", "fina"),
    ("isabel", "chabela", "isa", "chabe"),
    ("graciela", "chela"),
    ("teresa", "tere"),
    ("rosa", "rosita"),
    ("gabriel", "gabi", "gabo"),
    ("gabriela", "gabi", "gaby"),
    ("cristina", "cris", "tina"),
    ("carolina", "caro"),
    ("lorenzo", "lencho"),
    ("ana", "anita"),
    ("juan", "juanito", "john"),
    ("pedro", "perico", "peter"),
    ("consuelo", "chelo"),
    ("salvador", "chava"),
    ("vicente", "chente"),
    ("javier", "javi"),
    ("rafael", "rafa"),
    ("ricardo", "richi", "ricky"),
    ("miguel", "mike", "michael"),
    ("carlos", "charlie", "charles"),
)

NICKNAME_FAMILIES: dict[str, frozenset[int]] = {}
for _idx, _family in enumerate(_FAMILIES):
    for _name in _family:
        NICKNAME_FAMILIES.setdefault(_name, frozenset())
        NICKNAME_FAMILIES[_name] = NICKNAME_FAMILIES[_name] | {_idx}


def same_nickname_family(a: str, b: str) -> bool:
    """True when two folded given-name tokens may name the same person (``paco`` / ``francisco``)."""
    if a == b:
        return True
    return bool(NICKNAME_FAMILIES.get(a, frozenset()) & NICKNAME_FAMILIES.get(b, frozenset()))
