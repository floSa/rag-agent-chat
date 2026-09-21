"""LE GARDE QUI EMPÊCHE LE RETOUR DU NOM, ET LES DEUX PIÈGES QU'IL DOIT TENIR.

Le lot 28 a retiré le SUPPORT d'un moteur, pas seulement son nom. Ce fichier est
ce qui empêche ce lot d'être à refaire : il rougit si le nom de l'ancien moteur
réapparaît **hors des archives**.

PREMIER PIÈGE : UNE SONDE QUI CHERCHE UN NOM SE TROUVE ELLE-MÊME
-----------------------------------------------------------------

Ce dépôt l'a payé deux fois : une sonde dont *la phrase qui déclarait l'absence
ÉTAIT l'occurrence*, et un `grep` d'appelants qui trouvait sa propre citation.
Le garde voisin de `test_coherence_depot.py` ferme ce piège **par construction
de domaine** — il vit dans `tests/`, et `tests/` n'est pas balayé.

**CETTE ISSUE N'EST PAS OUVERTE ICI**, et c'est ce qui rend le piège réel :
`tests/` EST dans le domaine, parce qu'un test qui réintroduirait le dialecte
retiré dans un double est exactement ce qu'il faut attraper. Le garde ne peut
donc pas s'exclure par son emplacement.

**IL SE TIENT À DISTANCE AUTREMENT : IL N'ÉCRIT JAMAIS LE NOM EN CLAIR.** Il le
COMPOSE à l'exécution, à partir de deux moitiés dont aucune n'est le motif. Sa
propre source ne contient donc pas ce qu'il cherche, et il peut se balayer
lui-même sans se trouver. `test_la_source_de_ce_garde_ne_porte_pas_le_motif` le
tient — parce qu'une propriété qu'on obtient par une astuce d'écriture se perd au
premier refactor qui « simplifie » la composition.

SECOND PIÈGE : TROUVER N'EST PAS DISCRIMINER
---------------------------------------------

Un garde qui rend zéro parce qu'il ne lit rien ne vaut rien, et ce dépôt en a vu
neuf. Trois choses le tiennent ici :

1. **le compte de fichiers balayés est ASSERTÉ non nul**, et publié dans le
   message d'erreur : un zéro par impuissance se voit ;
2. **un CONTRÔLE POSITIF** plante le nom, une fois, dans le contenu d'un fichier
   réel du périmètre — en mémoire, jamais sur le disque — et exige que le garde
   le signale. Sans lui, un motif cassé rendrait le même zéro qu'un dépôt propre ;
3. **un CONTRÔLE DE L'EXCLUSION** : le même nom planté dans un fichier d'archive
   ne doit PAS être signalé, sans quoi l'exclusion ne serait pas là où elle est
   annoncée.

LE PÉRIMÈTRE D'EXCLUSION EST NOMMÉ, JAMAIS DEVINÉ
--------------------------------------------------

Chaque exclusion est un chemin littéral — un fichier, ou un répertoire — et
porte sa raison au site. **Aucun motif large** : une exclusion trop généreuse
rend le garde muet là où il compte, et c'est la façon dont un garde meurt sans
qu'on s'en aperçoive. `test_chaque_exclusion_designe_quelque_chose_qui_existe`
refuse en outre une exclusion qui ne désigne plus rien : une exclusion périmée
est une porte laissée ouverte sur un chemin que personne ne relit.
"""

import re
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]

# LE NOM CHERCHÉ, COMPOSÉ ET JAMAIS ÉCRIT. Les deux moitiés sont choisies pour
# qu'aucune ne soit le motif : ni `olla` ni `ma` ne se trouvent dans ce dépôt
# comme un nom de moteur. C'est ce qui permet à ce fichier d'être dans son
# propre domaine de balayage sans s'y trouver.
_NOM = "olla" + "ma"
_MOTIF = re.compile(_NOM, re.IGNORECASE)


def _nom_releve_du_depot() -> str:
    """Le nom, RELU DU DÉPÔT et non de la constante ci-dessus.

    CETTE FONCTION EXISTE PARCE QU'UNE MUTATION A SURVÉCU, et c'est la trouvaille
    de la campagne du lot 28. Le contrôle positif plantait `_NOM` puis cherchait
    `_MOTIF`, **construit depuis `_NOM`** : il confrontait la constante à
    elle-même. Casser le motif — `"olla" + "mZ"` — laissait donc les 1083 tests
    VERTS, et le garde du nom ne gardait plus rien tout en s'annonçant vert.

    La source indépendante est le NOM D'UN FICHIER d'archive, que le propriétaire
    a décidé de conserver tel quel parce que des documents le citent. Il porte le
    nom du moteur dans son quatrième segment. Si `_MOTIF` cesse de reconnaître ce
    nom-là, il ne reconnaît plus rien, et `test_le_motif_reconnait_le_nom_tel_qu_
    il_est_ecrit_ailleurs` rougit.
    """
    candidats = [
        c
        for c in _fichiers_suivis()
        if c.startswith("runs/") and c.endswith("-reference-avant-vllm-reglage.json")
    ]
    assert len(candidats) == 1, (
        f"la source indépendante du nom a disparu ou s'est dédoublée : {candidats}. "
        "Sans elle, le contrôle positif de ce garde se confronte à sa propre "
        "constante — et une mutation du motif survit."
    )
    segments = Path(candidats[0]).name.split("-")
    assert len(segments) > 3, f"le nom de fichier a changé de forme : {candidats[0]}"
    return segments[3]

# ─── LE PÉRIMÈTRE D'EXCLUSION, NOMMÉ UN PAR UN ───────────────────────────────
#
# Chaque entrée est un chemin littéral relatif à la racine, et chacune porte sa
# raison. Rien n'est exclu par un motif : un `documentation/*` excuserait tout un
# répertoire vivant sans que personne ne le voie.

_ARCHIVES = {
    # Des rapports d'audit datés, signés, versés après mesure. Les réécrire pour
    # qu'ils s'accordent avec l'état d'aujourd'hui falsifierait un rapport.
    "documentation/audits",
    # Des récits de campagne datés, avec leur protocole et leurs chiffres.
    "documentation/campagnes",
    # Les artefacts de campagne et le registre qui les décrit un par un. `mesuré`
    # le 18 septembre 2026 : sur les 20 campagnes versionnées, ZÉRO n'a été
    # produite sous le moteur servi aujourd'hui — elles décrivent donc toutes un
    # état antérieur. Le fichier de référence d'avant la bascule garde son nom,
    # décision du propriétaire : des documents le citent.
    "runs",
}

_REGISTRES_DATES = {
    # 105 mentions, dont 99 dans `## 1. Corrigé` et `## 4. Chantier ouvert le
    # 3 septembre 2026`, dont l'en-tête dit « toutes les entrées ci-dessous ont
    # été mesurées le 3 septembre 2026 ». Ce sont des constats datés, de même
    # nature que les archives. La note de tête du fichier l'écrit.
    "documentation/axes_amelioration.md",
    # Son §4 porte dans son TITRE que « chaque ligne porte SA date de mesure », et
    # son §6 est le journal des lots livrés. Même raison.
    "documentation/pilotage_du_chantier.md",
}

# ─── LES DEUX BLOCS BALISÉS, ET POURQUOI ILS NE SONT PAS DES FICHIERS EXCLUS ──
#
# Deux documents DOIVENT nommer l'ancien moteur, et en un seul endroit chacun :
# la migration du `.env` a besoin du nom EXACT des clés à retirer, et le retour
# arrière du nom exact des clés à restaurer. Sans eux, les deux gestes sont
# injouables.
#
# EXCLURE LES FICHIERS ENTIERS SERAIT LA FAUTE : ce sont deux documents vivants,
# et le garde doit continuer d'y mordre partout ailleurs. Seules les lignes
# ENTRE les balises sont retirées de la lecture.
_BALISE_DEBUT = "migration-du-lot-28:" + "début"
_BALISE_FIN = "migration-du-lot-28:" + "fin"


def _fichiers_suivis() -> list[str]:
    """Les fichiers que git suit, et eux seuls.

    `git ls-files` ET NON `rglob` : un balayage du disque ramasserait `.venv`,
    les caches et les artefacts de build — donc des occurrences que ce dépôt ne
    versionne pas, et sur lesquelles il ne peut rien. Le sujet de ce garde est
    ce qui ENTRE dans le dépôt.
    """
    sortie = subprocess.run(
        ["git", "-C", str(_RACINE), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [c for c in sortie.stdout.split("\0") if c]


def _est_exclu(chemin: str) -> bool:
    """Le chemin tombe-t-il dans le périmètre nommé ?"""
    if chemin in _REGISTRES_DATES:
        return True
    return any(chemin == d or chemin.startswith(d + "/") for d in _ARCHIVES)


def _hors_des_balises(texte: str) -> str:
    """Le texte privé de ses blocs balisés, ligne à ligne.

    LIGNE À LIGNE ET NON PAR UNE EXPRESSION SUR TOUT LE TEXTE : un motif
    `début.*?fin` en mode `DOTALL` avalerait tout ce qui sépare une balise de fin
    d'une balise de début suivante si l'une venait à manquer, et le garde
    deviendrait muet sur un document entier pour une balise oubliée. Ici une
    balise non refermée laisse le reste du document LU, ce qui est le sens sûr —
    et `test_une_balise_non_refermee_ne_rend_pas_le_garde_muet` le tient.
    """
    gardees: list[str] = []
    dedans = False
    for ligne in texte.splitlines():
        if _BALISE_DEBUT in ligne:
            dedans = True
            continue
        if _BALISE_FIN in ligne:
            dedans = False
            continue
        if not dedans:
            gardees.append(ligne)
    return "\n".join(gardees)


def _occurrences(chemin: str, texte: str) -> list[str]:
    """Les lignes de `texte` qui portent le nom, `[]` si le chemin est exclu.

    FONCTION PURE, et c'est ce qui rend les contrôles positifs possibles sans
    toucher au disque : la scène lui donne un contenu fabriqué et lit ce qu'elle
    en fait. Un garde qui ne sait s'éprouver qu'en mutant le dépôt ne s'éprouve
    pas souvent.
    """
    if _est_exclu(chemin):
        return []
    return [
        f"{chemin}:{n}: {ligne.strip()[:120]}"
        for n, ligne in enumerate(_hors_des_balises(texte).splitlines(), 1)
        if _MOTIF.search(ligne)
    ]


def _balayer() -> tuple[list[str], int]:
    """Les occurrences du dépôt, et le nombre de fichiers réellement LUS."""
    fautives: list[str] = []
    lus = 0
    for chemin in _fichiers_suivis():
        if _est_exclu(chemin):
            continue
        fichier = _RACINE / chemin
        try:
            texte = fichier.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            # Un binaire versionné n'est pas du texte : il est compté comme non
            # lu plutôt que silencieusement ignoré.
            continue
        lus += 1
        fautives.extend(_occurrences(chemin, texte))
    return fautives, lus


# ─── LE GARDE ────────────────────────────────────────────────────────────────


def test_le_nom_de_l_ancien_moteur_ne_revient_pas() -> None:
    """LE GARDE, ET IL EST LA RAISON POUR LAQUELLE CE LOT NE SERA PAS À REFAIRE.

    Le geste attendu au rouge n'est PAS d'ajouter une exclusion : c'est de dire
    ce que la phrase voulait dire. Si elle explique un choix par comparaison avec
    l'ancien moteur et que la comparaison n'apprend plus rien, elle saute ; si
    elle garde du sens, « l'ancien moteur » suffit ; si elle décrit le
    fonctionnement actuel, elle nomme vLLM.
    """
    fautives, lus = _balayer()
    assert lus > 0, (
        "aucun fichier n'a été LU : ce garde rendrait zéro par impuissance. "
        "Le dépôt n'est pas un dépôt git, ou `git ls-files` ne rend rien."
    )
    assert not fautives, (
        f"{len(fautives)} occurrence(s) du nom de l'ancien moteur hors du "
        f"périmètre d'exclusion, sur {lus} fichiers lus :\n"
        + "\n".join(fautives[:40])
        + "\n\nLe support de ce moteur a été retiré par le lot 28. N'ajoute pas "
        "une exclusion : dis ce que la phrase veut dire."
    )


def test_le_garde_atteint_reellement_le_depot() -> None:
    """PREUVE D'ATTEINTE : combien de fichiers, et les familles qu'ils couvrent.

    Un compte seul ne suffit pas — il pourrait être fait de fichiers d'une seule
    famille. Les quatre que ce lot a touchées sont exigées présentes.
    """
    _, lus = _balayer()
    assert lus >= 100, f"seulement {lus} fichiers lus : le balayage s'est rétréci"

    chemins = [c for c in _fichiers_suivis() if not _est_exclu(c)]
    for famille in ("src/", "tests/", "documentation/", "scripts/"):
        assert any(c.startswith(famille) for c in chemins), (
            f"aucun fichier de `{famille}` dans le domaine : le garde y serait "
            "muet, et c'est là qu'il compte"
        )
    assert ".env.example" in chemins and "Makefile" in chemins, (
        "les fichiers de configuration de la racine ne sont pas balayés"
    )


def test_le_motif_reconnait_le_nom_tel_qu_il_est_ecrit_ailleurs() -> None:
    """LE CONTRÔLE QUI MANQUAIT, ET UNE MUTATION L'A ÉTABLI.

    `_MOTIF` est construit depuis `_NOM`. Tout contrôle qui plante `_NOM` puis
    cherche `_MOTIF` mesure la cohérence d'une constante avec elle-même, et reste
    vert si les DEUX sont faux ensemble. La mutation `_NOM = "olla" + "mZ"` a
    survécu aux 1083 tests pour cette raison exacte.

    Ce test confronte le motif à une source que le garde ne contrôle pas : le nom
    de fichier d'une archive du dépôt. Un motif qui ne reconnaît plus ce nom-là ne
    reconnaît plus rien.
    """
    du_depot = _nom_releve_du_depot()
    assert _MOTIF.fullmatch(du_depot), (
        f"le motif du garde ne reconnaît pas le nom tel que le dépôt l'écrit "
        f"({du_depot!r}) : il ne trouvera rien, et son zéro ne voudra rien dire"
    )
    assert _NOM.lower() == du_depot.lower(), (
        f"la constante du garde ({_NOM!r}) a dérivé du nom que le dépôt porte "
        f"({du_depot!r})"
    )


def test_le_controle_positif_le_nom_plante_une_fois_fait_rougir() -> None:
    """LE ZÉRO EST DOUBLÉ, et sans ceci il ne vaudrait rien.

    Le nom est planté **une fois**, dans le contenu d'un fichier réel du
    périmètre — en mémoire, jamais sur le disque. Un motif cassé rendrait ici le
    même zéro qu'un dépôt propre, et le garde serait vert pour la mauvaise
    raison : c'est la forme de défaut que ce chantier poursuit depuis dix audits.

    **LE NOM PLANTÉ EST CELUI DU DÉPÔT, PAS `_NOM`.** Planter la constante que le
    motif est fait pour trouver ne prouve que leur accord mutuel : la mutation
    `_NOM = "olla" + "mZ"` passait ce test sans broncher, puisqu'elle changeait
    les deux côtés à la fois.
    """
    cible = "src/agent/dialecte_llm.py"
    assert cible in _fichiers_suivis(), f"{cible} n'est plus suivi : la scène a perdu sa cible"
    propre = (_RACINE / cible).read_text(encoding="utf-8")

    assert _occurrences(cible, propre) == [], (
        "le témoin inerte n'est pas inerte : ce fichier porte déjà le nom"
    )

    plante = propre.replace(
        "from .settings import settings",
        f"from .settings import settings  # repli vers {_nom_releve_du_depot()}",
        1,
    )
    assert plante != propre, "l'ancre de plantation n'existe plus dans le fichier cible"
    trouvees = _occurrences(cible, plante)
    assert len(trouvees) == 1, (
        f"le nom planté une fois a été trouvé {len(trouvees)} fois : {trouvees}"
    )


def test_le_controle_de_l_exclusion_une_archive_ne_rougit_pas() -> None:
    """L'AUTRE SENS, et il n'est pas décoratif.

    Si l'exclusion ne s'appliquait pas là où elle est annoncée, ce garde
    rougirait sur les archives — donc il serait retiré par le lot suivant, donc
    désarmé. La même ligne est plantée dans un chemin d'archive et dans un chemin
    vivant : seule la seconde doit être signalée.
    """
    ligne = f"le moteur {_nom_releve_du_depot()} servait ce modèle"
    assert _occurrences("documentation/audits/2026-09-15-audit-lot-17.md", ligne) == []
    assert _occurrences("runs/README.md", ligne) == []
    assert _occurrences("documentation/axes_amelioration.md", ligne) == []
    assert _occurrences("documentation/llm.md", ligne), (
        "un document VIVANT ne rougit pas : l'exclusion déborde de son périmètre"
    )


def test_la_source_de_ce_garde_ne_porte_pas_le_motif() -> None:
    """LE PIÈGE DE L'AUTO-DÉTECTION, TENU PLUTÔT QU'AFFIRMÉ.

    Ce fichier est DANS le domaine qu'il balaye. Il ne s'y trouve que parce qu'il
    compose le nom au lieu de l'écrire — une propriété d'écriture, donc une
    propriété qu'un refactor bien intentionné peut détruire en « simplifiant » la
    composition. Cette scène est ce qui le dira.

    Elle lit la source sur le DISQUE, jamais `_NOM` : se confronter à sa propre
    constante ne mesurerait que sa propre cohérence.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    assert not _MOTIF.search(source), (
        "la source de ce garde porte le nom qu'il cherche : il se trouvera "
        "lui-même, et son rouge ne voudra plus rien dire. Compose le nom."
    )
    assert _occurrences(
        str(Path(__file__).relative_to(_RACINE)), source
    ) == [], "ce fichier se signale lui-même"


def test_chaque_exclusion_designe_quelque_chose_qui_existe() -> None:
    """Une exclusion périmée est une porte ouverte sur un chemin que nul ne relit."""
    for chemin in sorted(_ARCHIVES | _REGISTRES_DATES):
        assert (_RACINE / chemin).exists(), (
            f"l'exclusion `{chemin}` ne désigne plus rien : retire-la, ou "
            "corrige-la. Une exclusion qui ne pointe nulle part protège un "
            "chemin qui n'existe pas et masque celui qui existe."
        )


def test_aucune_exclusion_n_est_un_motif_large() -> None:
    """LE GARDE DE L'EXCLUSION ELLE-MÊME.

    Une exclusion trop généreuse rend le garde muet là où il compte. Deux formes
    sont refusées : un joker, et un chemin qui excuserait un répertoire entier de
    documentation vivante.
    """
    for chemin in sorted(_ARCHIVES | _REGISTRES_DATES):
        assert not set(chemin) & set("*?["), (
            f"l'exclusion `{chemin}` est un motif : nomme les fichiers un par un"
        )
    assert "documentation" not in _ARCHIVES | _REGISTRES_DATES, (
        "la documentation vivante entière serait exclue"
    )
    assert "tests" not in _ARCHIVES | _REGISTRES_DATES, (
        "les tests seraient exclus, alors qu'un double qui parle le dialecte "
        "retiré est exactement ce que ce garde existe pour attraper"
    )


@pytest.mark.parametrize(
    "texte,attendu",
    [
        pytest.param(
            f"avant\n<!-- {_BALISE_DEBUT} -->\ndedans\n<!-- {_BALISE_FIN} -->\napres",
            ["avant", "apres"],
            id="bloc-refermé",
        ),
        pytest.param(
            f"avant\n<!-- {_BALISE_DEBUT} -->\ndedans\nencore",
            ["avant"],
            id="bloc-non-refermé",
        ),
        pytest.param("rien de balisé\nici", ["rien de balisé", "ici"], id="sans-balise"),
    ],
)
def test_la_lecture_des_balises_fait_ce_qu_elle_dit(texte: str, attendu: list[str]) -> None:
    """La lecture par ligne, éprouvée sur les trois formes qu'elle rencontre."""
    assert _hors_des_balises(texte).splitlines() == attendu


def test_une_balise_non_refermee_ne_rend_pas_le_garde_muet() -> None:
    """LE SENS SÛR, et il est choisi plutôt que subi.

    Une balise de début oubliée en fermeture pourrait, avec une lecture par
    expression sur tout le texte, avaler le reste du document — donc éteindre le
    garde sur ce document entier pour une faute de frappe. La lecture par ligne
    n'éteint que ce qui suit la balise, et ce test le dit.
    """
    texte = f"vivant\n<!-- {_BALISE_DEBUT} -->\nmigration\n"
    assert "vivant" in _hors_des_balises(texte)
    assert "migration" not in _hors_des_balises(texte)


def test_les_deux_blocs_balises_du_depot_sont_refermes() -> None:
    """LES BALISES RÉELLES, COMPTÉES SUR LE DÉPÔT.

    Une balise de fin manquante éteindrait le garde sur tout ce qui suit dans le
    document. Ce test compte les deux marques dans chacun des deux fichiers qui
    les portent, et refuse qu'un troisième fichier en ouvre une sans le dire.
    """
    porteurs = {
        "documentation/moteur_llm.md",
        "documentation/identite_du_code_servi.md",
    }
    ouverts: list[str] = []
    for chemin in _fichiers_suivis():
        texte_brut = (_RACINE / chemin)
        if not texte_brut.is_file():
            continue
        try:
            texte = texte_brut.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        debuts, fins = texte.count(_BALISE_DEBUT), texte.count(_BALISE_FIN)
        if debuts or fins:
            ouverts.append(chemin)
            assert debuts == fins == 1, (
                f"{chemin} porte {debuts} balise(s) de début et {fins} de fin : "
                "une seule paire par fichier, refermée"
            )
    assert set(ouverts) == porteurs, (
        f"les fichiers portant un bloc balisé sont {sorted(ouverts)}, attendu "
        f"{sorted(porteurs)}. Un bloc balisé est une exemption : il se déclare."
    )
