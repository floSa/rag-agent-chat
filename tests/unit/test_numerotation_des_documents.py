"""Les numéros des deux documents de pilotage, et l'asymétrie qui les sépare.

**LE DÉFAUT QUE CE FICHIER EXISTE POUR RENDRE BRUYANT : DEUX COLLISIONS EN DEUX
JOURS, TOUTES DEUX INVISIBLES À TOUT CODE DE RETOUR.** Une ligne `38` en double
dans le journal des conversations le 8 septembre 2026 — trouvée par
l'utilisateur, sur une question de quatre mots, ni par un garde, ni par un
audit, ni par le pilote —, et une seconde collision de section dans le registre
le 9. Aucun test, aucun linter, aucune CI ne pouvait les voir : ce sont des
documents Markdown, et un doublon de numéro y est du texte parfaitement valide.

**L'ASYMÉTRIE, ET ELLE DÉCIDE DE TOUT.** Les deux documents numérotent, mais pas
sous la même règle :

- le **JOURNAL** (`documentation/pilotage_du_chantier.md`, §6.1) est
  **CHRONOLOGIQUE**. `mesuré` le 9 septembre 2026, son ordre de fichier est
  `20 21 22 23 24 25 26 20-bis 27 28 … 43` : `20-bis` est délibérément placé
  entre `26` et `27`, parce que la conversation de reprise a parlé à ce
  moment-là. **Asserter l'ordre du fichier sur le journal produirait donc un
  FAUX ROUGE sur une ligne juste**, et c'est mesuré ici par
  `test_appliquer_la_regle_du_registre_au_journal_serait_un_faux_rouge` ;
- le **REGISTRE** (`documentation/axes_amelioration.md`) est **NUMÉRIQUE**, et
  c'est précisément son désordre — `4.28 4.30 4.29 4.31`, né d'une fusion sans
  conflit — qui a été corrigé le 8 septembre 2026.

Un garde qui prendrait ces deux règles à l'envers manquerait le défaut réel et
rougirait sur un document sain. Les deux ordres ont été **mesurés** avant que la
moindre assertion ne soit écrite, et non déduits.

**CE QUE CE GARDE NE VISE PAS, ET C'EST LA LEÇON DES COMPTES DE CE DÉPÔT.** Il
ne compte rien. Le §4.35 a retiré un compte de relevés qu'on ne pouvait pas
reconstruire ; le lot 6 a refusé d'asserter un compte exact de fichiers au
profit d'un plancher monotone. Ici, **l'ajout d'une ligne est l'événement
normal** : un garde qui rougirait à chaque conversation ajoutée enseignerait le
geste « monter le chiffre », qui est exactement celui qui desserre un garde.
Ce fichier vise donc le **DOUBLON** et le **TROU** — des propriétés — et jamais
le volume.

**LA PREUVE D'ATTEINTE EST DANS `git`, ET ELLE EST DATÉE.** Un garde de dérive
documentaire qui ne rougit pas sur la dérive réelle du dépôt ne garde rien. Les
trois dérives ci-dessous sont retrouvées à leur révision, par `git show`, et
chacune fait rougir la règle qui la vise :

| révision | document | dérive | règle qui rougit |
|---|---|---|---|
| `2bb511c` | journal | ligne `38` en DOUBLE | le doublon |
| `2bb511c` | journal | « prochain numéro libre : 41 » pour un maximum de 39 | le prochain libre |
| `2bb511c` | registre | `4.28 4.30 4.29 4.31` | l'ordre numérique |

**ET UNE MESURE CONTRE LE CADRAGE DE CE LOT.** Il annonçait la seconde collision
— deux sections de même numéro dans le registre — comme disponible à `a92e78a`.
`mesuré` le 9 septembre 2026 : `a92e78a` porte **UNE SEULE** section de ce
numéro, et sa suite `4.1 … 4.35` est complète et ordonnée. Le balayage de
**toute** l'histoire (`git rev-list --all`) ne trouve **aucune** révision du
registre portant un doublon de titre. La collision a bien eu lieu, mais elle a
été attrapée AVANT d'être commitée — par l'`assert` d'ancre unique d'un script
d'édition, ce que le rapport du pilote écrit lui-même. Elle n'est donc pas dans
`git`, et on ne l'invente pas : la règle du doublon côté registre est éprouvée
sur un cas **CONSTRUIT à partir du document réel de `a92e78a`**, et le fait que
l'histoire est propre est lui-même asserté ci-dessous.
"""

import re
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]

_JOURNAL = "documentation/pilotage_du_chantier.md"
_REGISTRE = "documentation/axes_amelioration.md"

# Le titre qui ouvre le journal, et la borne qui le ferme. LE SCOPE EST
# NÉCESSAIRE, ET C'EST MESURÉ : `pilotage_du_chantier.md` porte D'AUTRES
# tableaux dont la première colonne est un numéro en gras — le plan de lots
# (`1 2 3 4 5`) et la table des exigences (`1 … 7`). Un extracteur qui
# balaierait tout le fichier lirait la suite que voici, et le garde rougirait au
# premier `make test` sur un document parfaitement sain.
#
# **LES DEUX NOMBRES DE CE COMMENTAIRE ÉTAIENT FAUX, ET C'EST LA CORRECTION DU
# 9 SEPTEMBRE 2026.** Il annonçait « onze doublons et un trou de 7 à 20 ». Les
# deux sont démentis par la suite que le commentaire écrit lui-même — `7` et
# `20` y sont l'un et l'autre PRÉSENTS. Le mécanisme est juste et le scope reste
# nécessaire ; seuls les chiffres mentaient, sous l'étiquette `mesuré`. Ils ont
# de plus été repris tels quels dans le prompt de l'audit, ce qui est
# exactement le geste que le §4.6 de ce dépôt refuse.
#
# `mesuré` le 9 septembre 2026 — commande : `_NUMERO_DU_JOURNAL.finditer()` sur
# le fichier ENTIER, puis `collections.Counter` sur les jetons :
#
#     suite lue : 1 2 3 4 5 1 2 3 4 5 6 7 20 21 … 20-bis … 43
#     doublons  : **5** (les jetons `1` à `5`, chacun deux fois)
#     trou      : **10 à 19** — dix entiers absents (`8 à 19` avant que le
#                 plan de lots porte ses rangs 8 et 9), `7` et `20` présents
#
# La propriété est gardée par `test_le_scope_du_journal_est_porteur`, qui
# reproduit la lecture non bornée et exige qu'elle soit fautive : un scope dont
# le retrait ne changerait rien serait un scope décoratif.
_DEBUT_DU_JOURNAL = "### 6.1 Le journal des conversations"

# La ligne d'autorité, et il y en a DEUX dans ce fichier. Celle du §6.1 est
# l'état ; l'autre, au §12, RACONTE la faute du 8 septembre 2026 (« Prochain
# numéro libre : 41 » écrit depuis l'arithmétique d'un script).
#
# **CE COMMENTAIRE AFFIRMAIT QUE LE SCOPE EST CE QUI EMPÊCHE DE LIRE LE RÉCIT.
# C'ÉTAIT FAUX, ET C'EST LA CORRECTION DU 9 SEPTEMBRE 2026.** Ce qui protégeait
# était l'ORDRE DU FICHIER — le §6.1 précède le §12 — et rien d'autre. `mesuré`
# ce jour-là, sur une COPIE, le fichier réel intact : en remontant le paragraphe
# du récit juste sous le titre du §6.1, il entre DANS le scope, `search()` rend
# la première occurrence de la fenêtre, et `prochain_numero_annonce` lit **41**
# — le faux nombre de la faute du 8 septembre — au lieu de **44**.
#
# Un garde dont la justesse dépend de l'ordre de deux paragraphes est un garde
# qu'une réorganisation de document casse en silence. La discrimination porte
# donc désormais sur la FORME de la ligne, qui est la seule chose qui distingue
# vraiment un état d'un récit :
#
# - l'état est une ligne À ELLE SEULE, ouverte par le gras : `**Prochain numéro
#   libre : 44.**` ;
# - le récit CITE le nombre au milieu d'une phrase, entre guillemets français,
#   derrière une puce et un autre gras.
#
# `^\*\*` avec `re.M` sépare les deux sans rien devoir à l'ordre. Et
# l'AMBIGUÏTÉ EST UNE ERREUR, PAS UN PREMIER-ARRIVÉ : si deux lignes d'autorité
# apparaissaient un jour dans le scope, `prochain_numero_annonce` refuse de
# choisir. Un extracteur qui tranche en silence entre deux vérités possibles est
# précisément ce qui a produit la faute du 8 septembre.
#
# Gardé dans les deux sens par `test_le_recit_remonte_au_dessus_du_journal_ne_
# fait_plus_lire_le_faux_nombre`.
_LIGNE_DU_PROCHAIN = re.compile(r"^\*\*Prochain num[ée]ro libre\s*:\s*(\d+)", re.M)

# `| **20-bis** |` — le numéro EST la première colonne, en gras. La forme `-bis`
# est admise : elle nomme une reprise, elle est légitime, et sa tolérance ne
# doit pas ouvrir de porte — deux `20-bis` restent un doublon, parce que le
# jeton comparé est le jeton COMPLET.
_NUMERO_DU_JOURNAL = re.compile(r"^\|\s*\*\*(\d+(?:-bis)?)\*\*\s*\|", re.M)

# `### 4.23 bis` — même tolérance, écrite avec une espace de ce côté-ci. Les
# deux orthographes sont celles que les deux documents portent réellement.
_NUMERO_DU_REGISTRE = re.compile(r"^###\s+4\.(\d+(?:\s+bis)?)\b", re.M)


def _git_show(revision: str, chemin: str) -> str:
    """Le document tel qu'il était à `revision`. La preuve d'atteinte vit là."""
    acheve = subprocess.run(
        ["git", "show", f"{revision}:{chemin}"],
        cwd=_RACINE,
        capture_output=True,
        text=True,
        check=False,
    )
    if acheve.returncode != 0:
        pytest.fail(
            f"`git show {revision}:{chemin}` a rendu rc={acheve.returncode} : "
            f"{acheve.stderr.strip()}. Ces révisions sont les DÉRIVES DATÉES du "
            "dépôt, et elles sont la seule preuve que ce garde mord sur autre "
            "chose qu'un cas inventé. Si elles ne sont plus atteignables — clone "
            "superficiel, historique réécrit — ce fichier ne prouve plus rien : "
            "remesure, ne neutralise pas."
        )
    return acheve.stdout


def _extraire(texte: str, motif: re.Pattern[str]) -> list[str]:
    """Les jetons, DANS L'ORDRE DU FICHIER — l'ordre est une donnée ici."""
    return [trouve.group(1) for trouve in motif.finditer(texte)]


def numeros_du_journal(texte: str) -> list[str]:
    """Les numéros du tableau du §6.1, et de lui seul.

    Le scope est la moitié du travail : voir `_DEBUT_DU_JOURNAL`, dont le
    commentaire porte la mesure qui l'exige.
    """
    debut = texte.find(_DEBUT_DU_JOURNAL)
    if debut < 0:
        pytest.fail(
            f"le titre {_DEBUT_DU_JOURNAL!r} a disparu de {_JOURNAL} : l'extracteur "
            "balaierait alors tout le fichier, y compris deux autres tableaux "
            "numérotés, et ce garde se mettrait à rougir sur un document sain"
        )
    fin = texte.find("\n## ", debut)
    return _extraire(texte[debut : fin if fin > 0 else len(texte)], _NUMERO_DU_JOURNAL)


def numeros_du_registre(texte: str) -> list[str]:
    """Les numéros de section du registre, dans l'ordre du fichier."""
    return _extraire(texte, _NUMERO_DU_REGISTRE)


def prochain_numero_annonce(texte: str) -> int | None:
    """Le « prochain numéro libre » du §6.1, `None` s'il n'y est plus.

    L'AMBIGUÏTÉ REND `None`, ELLE NE TRANCHE PAS. Voir le commentaire de
    `_LIGNE_DU_PROCHAIN` : deux lignes d'autorité dans le scope signifient que
    la forme ne discrimine plus, et choisir la première est exactement le geste
    qui a produit la faute du 8 septembre 2026. Le `None` fait rougir
    `test_le_prochain_numero_libre_est_le_maximum_plus_un`, qui nomme alors la
    cause — un silence aurait laissé le garde lire un récit pour un état.
    """
    debut = texte.find(_DEBUT_DU_JOURNAL)
    if debut < 0:
        return None
    fin = texte.find("\n## ", debut)
    trouves = _LIGNE_DU_PROCHAIN.findall(texte[debut : fin if fin > 0 else len(texte)])
    if len(trouves) != 1:
        return None
    return int(trouves[0])


# ─── Les quatre défauts, en fonctions PURES ───────────────────────────────────
#
# Pures pour une raison : chacune est éprouvée contre les dérives datées du
# dépôt ET contre des cas construits, sans lire aucun fichier. Un défaut qui ne
# s'éprouve que sur l'état courant du dépôt n'est éprouvé que le jour où il est
# présent, c'est-à-dire jamais.


def doublons(jetons: list[str]) -> list[str]:
    """Les jetons qui apparaissent plus d'une fois, dans l'ordre d'apparition.

    Sur le jeton COMPLET, `-bis` compris : `20` et `20-bis` sont deux entrées
    distinctes et légitimes, deux `20-bis` sont un doublon. C'est ainsi que la
    tolérance du `bis` n'ouvre pas de porte.
    """
    vus: set[str] = set()
    repetes: list[str] = []
    for jeton in jetons:
        if jeton in vus:
            repetes.append(jeton)
        else:
            vus.add(jeton)
    return repetes


def _entiers(jetons: list[str]) -> list[int]:
    return [int(jeton.split("-")[0].split()[0]) for jeton in jetons]


def trous(jetons: list[str]) -> list[int]:
    """Les entiers manquants entre le minimum et le maximum présents.

    Le `bis` ne compte pas comme un numéro à part : `20-bis` retombe sur `20`,
    qui doit donc exister par ailleurs — vérifié par `bis_orphelins`.
    """
    presents = set(_entiers(jetons))
    if not presents:
        return []
    return [n for n in range(min(presents), max(presents) + 1) if n not in presents]


def bis_orphelins(jetons: list[str]) -> list[str]:
    """Les `-bis` dont le numéro de base n'existe pas.

    Un `20-bis` sans `20` est un numéro inventé, et c'est l'autre façon dont la
    tolérance du `bis` pourrait devenir une porte : y échapper suffirait à
    contourner la règle du trou.
    """
    bases = {int(j) for j in jetons if j.isdigit()}
    return [j for j in jetons if not j.isdigit() and int(j.split("-")[0].split()[0]) not in bases]


def desordre_numerique(jetons: list[str]) -> list[tuple[str, str]]:
    """Les couples consécutifs qui descendent. Vide = ordre numérique tenu.

    **CETTE RÈGLE NE S'APPLIQUE QU'AU REGISTRE**, et le motif est mesuré dans
    `test_appliquer_la_regle_du_registre_au_journal_serait_un_faux_rouge`.
    """
    entiers = _entiers(jetons)
    return [
        (jetons[i], jetons[i + 1])
        for i in range(len(entiers) - 1)
        if entiers[i] > entiers[i + 1]
    ]


# ─── Les deux documents vivants ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def journal() -> str:
    return (_RACINE / _JOURNAL).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registre() -> str:
    return (_RACINE / _REGISTRE).read_text(encoding="utf-8")


def test_le_journal_ne_porte_aucun_doublon(journal: str) -> None:
    """L'ASSERTION QUI AURAIT ATTRAPÉ LA COLLISION DU 8 SEPTEMBRE 2026.

    Une ligne `38` en double, trouvée par l'utilisateur sur une question de
    quatre mots. Un numéro réutilisé fait perdre le fil d'une conversation : le
    §6.1 s'ouvre sur le fait que ce journal est le seul état du chantier qui ne
    vive pas dans `git`, donc le seul qui puisse être perdu — et il l'a été.
    """
    jetons = numeros_du_journal(journal)
    assert len(jetons) >= 20, (
        f"seulement {len(jetons)} numéros extraits du §6.1 : l'extracteur ne lit "
        "plus le tableau, et un garde qui ne lit rien ne rougit sur rien"
    )
    assert not doublons(jetons), (
        f"le journal des conversations réutilise un numéro : {doublons(jetons)}. "
        "« Un numéro ne se réutilise JAMAIS » est le titre même du §6.1 : la "
        "correction est de renuméroter la ligne la plus récente, jamais de "
        "fusionner les deux"
    )


def test_le_journal_ne_porte_aucun_trou(journal: str) -> None:
    """Un trou dit qu'une conversation a existé et n'a pas été consignée."""
    jetons = numeros_du_journal(journal)
    assert not trous(jetons), (
        f"le journal saute des numéros : {trous(jetons)}. Soit une conversation "
        "n'a pas été consignée, soit un numéro a été attribué puis abandonné — "
        "dans les deux cas la ligne manquante s'écrit, avec son état de sortie"
    )
    assert not bis_orphelins(jetons), (
        f"un `-bis` du journal n'a pas de numéro de base : {bis_orphelins(jetons)}. "
        "Une reprise reprend quelque chose ; sans sa base, c'est un numéro inventé"
    )


def test_le_prochain_numero_libre_est_le_maximum_plus_un(journal: str) -> None:
    """« Un numéro est une mesure comme une autre » — §12 du pilotage.

    Cette ligne a été écrite depuis l'arithmétique d'un script au lieu d'être
    COMPTÉE, et elle est partie à 41 pour un maximum de 39. Elle est désormais
    comptée ici.
    """
    jetons = numeros_du_journal(journal)
    annonce = prochain_numero_annonce(journal)
    attendu = max(_entiers(jetons)) + 1
    assert annonce == attendu, (
        f"le §6.1 annonce « Prochain numéro libre : {annonce} » quand le maximum "
        f"consigné est {max(_entiers(jetons))}, donc {attendu}. C'est la faute du "
        "8 septembre 2026, et elle avait été écrite depuis l'arithmétique d'un "
        "script d'édition : compte, ne calcule pas"
    )


def test_le_registre_ne_porte_aucun_doublon(registre: str) -> None:
    """L'ASSERTION QUI AURAIT ATTRAPÉ LA SECONDE COLLISION, celle du pilote.

    Deux sections de même numéro dans le registre le 9 septembre 2026. Elle a
    été attrapée avant d'être commitée — voir le bandeau de ce fichier — donc
    elle n'est pas dans `git`, et le mordant de cette règle est établi sur un
    cas construit à partir du document réel.
    """
    jetons = numeros_du_registre(registre)
    assert len(jetons) >= 30, (
        f"seulement {len(jetons)} sections extraites du registre : l'extracteur "
        "ne lit plus les titres"
    )
    assert not doublons(jetons), (
        f"le registre porte deux sections de même numéro : {doublons(jetons)}. "
        "Deux sections d'un même numéro se citent l'une pour l'autre : tout renvoi "
        "au numéro devient ambigu, et c'est irréparable une fois cité ailleurs"
    )


def test_le_registre_ne_porte_aucun_trou(registre: str) -> None:
    """Un trou dans le registre dit qu'un axe cité nulle part n'existe pas."""
    jetons = numeros_du_registre(registre)
    assert not trous(jetons), f"le registre saute des sections : {trous(jetons)}"
    assert not bis_orphelins(jetons), (
        f"un ` bis` du registre n'a pas de section de base : {bis_orphelins(jetons)}"
    )


def test_le_registre_est_dans_l_ordre_numerique(registre: str) -> None:
    """LA RÈGLE QUI NE VAUT QUE POUR CE DOCUMENT-CI.

    Le désordre `4.28 4.30 4.29 4.31` est né d'une **fusion sans conflit** : les
    deux branches ajoutaient leur section à la même place, git les a empilées, et
    rien n'a rougi. C'est le mode de dérive que ce document connaît, et le seul
    contre lequel un ordre de fichier soit une assertion juste.
    """
    jetons = numeros_du_registre(registre)
    assert not desordre_numerique(jetons), (
        f"le registre n'est plus dans l'ordre numérique : {desordre_numerique(jetons)}. "
        "C'est la signature d'une fusion sans conflit, que rien d'autre ne signale — "
        "réordonne les sections, ne renumérote pas"
    )


def test_appliquer_la_regle_du_registre_au_journal_serait_un_faux_rouge(journal: str) -> None:
    """L'ASYMÉTRIE, ASSERTÉE PLUTÔT QUE SEULEMENT ÉCRITE.

    C'est le test qui empêche un lot suivant d'« harmoniser » les deux règles.
    Le journal est CHRONOLOGIQUE : `20-bis` est placé entre `26` et `27` parce
    que la conversation de reprise a parlé à ce moment-là. Appliquer au journal
    la règle d'ordre du registre rougirait donc sur une ligne JUSTE.

    Ce test le MESURE au lieu de l'affirmer : il montre que le désordre existe
    réellement dans le journal courant, et il nomme le couple fautif. Si un jour
    le journal devient numériquement ordonné, ce test rougit — et le rouge dit
    d'aller relire l'asymétrie avant d'ajouter une assertion d'ordre, ce qui est
    exactement le service attendu.
    """
    jetons = numeros_du_journal(journal)
    descentes = desordre_numerique(jetons)
    assert descentes, (
        "le journal est désormais dans l'ordre numérique du fichier. Ce n'était "
        "PAS le cas le 9 septembre 2026 (`20-bis` entre `26` et `27`), et l'ordre "
        "chronologique était délibéré. Avant d'asserter l'ordre du fichier sur ce "
        "document, relis le bandeau de ce fichier : la règle du registre n'est pas "
        "transposable, et ce test est la borne qui le dit"
    )
    assert any("bis" in avant or "bis" in apres for avant, apres in descentes), (
        f"le journal descend sur un couple qui ne doit rien à une reprise : "
        f"{descentes}. L'asymétrie est justifiée par les `-bis` chronologiques ; "
        "une descente entre deux numéros pleins n'est pas de la chronologie, c'est "
        "un désordre — et celui-là, il faut le corriger"
    )


# ─── LA PREUVE D'ATTEINTE, RETOURNÉE CONTRE LES DÉRIVES DATÉES DU DÉPÔT ───────


class TestLesQuatreReglesMordentSurLaDeriveReelleDuDepot:
    """LE PIÈGE DE MORDANT PROPRE À CE GARDE, ET IL EST ENTIER.

    Le dépôt est SAIN aujourd'hui sur les quatre points ci-dessus. Une batterie
    qui ne lirait que l'état courant serait donc **verte sans rien garder** —
    c'est la famille de défaut que ce chantier a trouvée sept fois sur huit
    bloquantes, et jamais une régression fonctionnelle.

    Les trois dérives réelles sont retrouvées dans `git`, à leur révision, et
    chacune fait rougir la règle qui la vise. La quatrième — le trou — n'a jamais
    eu lieu dans ce dépôt, et son cas est construit, ce qui est dit.
    """

    _DERIVE_JOURNAL = "2bb511c"
    _REGISTRE_PROPRE = "a92e78a"

    def test_la_ligne_en_double_du_8_septembre_fait_rougir_la_regle_du_doublon(self) -> None:
        """LA COLLISION QUE L'UTILISATEUR A TROUVÉE, en quatre mots."""
        jetons = numeros_du_journal(_git_show(self._DERIVE_JOURNAL, _JOURNAL))
        assert jetons, "l'extracteur ne lit rien à cette révision : la sonde n'atteint pas son cas"
        trouves = doublons(jetons)
        assert trouves == ["38"], (
            f"la dérive datée du {self._DERIVE_JOURNAL} n'est plus vue comme un "
            f"doublon : {trouves!r} au lieu de ['38']. Ce garde ne rougit donc plus "
            "sur la collision réelle du 8 septembre 2026 — et un garde de dérive "
            "documentaire qui ne rougit pas sur la dérive du dépôt ne garde rien"
        )

    def test_le_prochain_numero_faux_du_8_septembre_fait_rougir_sa_regle(self) -> None:
        """LA SECONDE DÉRIVE DE LA MÊME RÉVISION, ET ELLE EST INDÉPENDANTE.

        `mesuré` le 9 septembre 2026 : à cette révision, le journal annonce
        « Prochain numéro libre : 41 » pour un maximum consigné de **39**. La
        ligne avait été écrite depuis l'arithmétique d'un script au lieu d'être
        comptée — ce que le §12 du pilotage consigne comme leçon.
        """
        texte = _git_show(self._DERIVE_JOURNAL, _JOURNAL)
        jetons = numeros_du_journal(texte)
        annonce = prochain_numero_annonce(texte)
        maximum = max(_entiers(jetons))
        assert (maximum, annonce) == (39, 41), (
            f"la dérive datée n'est plus celle qui est écrite ici : maximum={maximum}, "
            f"annoncé={annonce}, attendu (39, 41). Remesure avant de corriger le test"
        )
        assert annonce != maximum + 1, (
            "la règle du prochain numéro libre ne rougit plus sur la dérive réelle "
            f"du {self._DERIVE_JOURNAL}"
        )

    def test_le_desordre_du_8_septembre_fait_rougir_la_regle_d_ordre(self) -> None:
        """LE DÉSORDRE NÉ D'UNE FUSION SANS CONFLIT, à sa révision.

        `4.28 4.30 4.29 4.31` : deux branches ont ajouté leur section à la même
        place, git a empilé, et rien n'a rougi.
        """
        jetons = numeros_du_registre(_git_show(self._DERIVE_JOURNAL, _REGISTRE))
        assert jetons, "l'extracteur ne lit rien : la sonde n'atteint pas son cas"
        descentes = desordre_numerique(jetons)
        assert descentes == [("30", "29")], (
            f"le désordre daté du {self._DERIVE_JOURNAL} n'est plus vu : {descentes!r} "
            "au lieu de [('30', '29')]. La règle d'ordre du registre ne mord plus sur "
            "la dérive réelle du dépôt"
        )
        # ET LA MÊME RÉVISION EST SANS DOUBLON NI TROU : la mesure discrimine les
        # quatre règles au lieu de rougir en bloc sur un vieux document.
        assert not doublons(jetons), f"doublon inattendu à cette révision : {doublons(jetons)}"
        assert not trous(jetons), f"trou inattendu à cette révision : {trous(jetons)}"

    def test_le_registre_de_a92e78a_est_propre_contrairement_au_cadrage(self) -> None:
        """LA MESURE CONTRE LE CADRAGE DE CE LOT, ET ELLE EST GARDÉE ICI.

        Le prompt du lot 7 annonçait `a92e78a` comme portant « deux `4.34` ».
        `mesuré` le 9 septembre 2026 : cette révision porte **une seule** section
        de ce numéro, sa suite est complète, ordonnée et sans doublon. Le
        balayage de toute l'histoire ne trouve aucune révision du registre avec
        un doublon de titre : la collision a été attrapée par l'`assert` d'ancre
        unique d'un script d'édition, AVANT d'être commitée.

        Ce test tient ce fait pour que personne ne parte le chercher dans `git`
        une seconde fois.
        """
        jetons = numeros_du_registre(_git_show(self._REGISTRE_PROPRE, _REGISTRE))
        assert jetons.count("34") == 1, (
            f"contrairement à la mesure du 9 septembre 2026, {self._REGISTRE_PROPRE} "
            f"porte {jetons.count('34')} sections `4.34`. Remesure : c'est le cadrage "
            "du lot 7 qui aurait alors eu raison, et ce fichier doit être réécrit"
        )
        assert not doublons(jetons), f"doublon à {self._REGISTRE_PROPRE} : {doublons(jetons)}"
        assert not desordre_numerique(jetons), f"désordre : {desordre_numerique(jetons)}"
        assert not trous(jetons), f"trou : {trous(jetons)}"

    def test_le_doublon_de_section_construit_sur_le_document_reel_fait_rougir(self) -> None:
        """LA COLLISION DU PILOTE, RECONSTRUITE PUISQU'ELLE N'EST PAS DANS `git`.

        Elle est plantée **par programme** sur le document réel de `a92e78a`, en
        renumérotant sa dernière section sur l'avant-dernière — c'est-à-dire le
        geste exact qui a failli être commité. Le cas n'est pas inventé : seul
        son support l'est, et le test ci-dessus asserte pourquoi.
        """
        texte = _git_show(self._REGISTRE_PROPRE, _REGISTRE)
        avant = numeros_du_registre(texte)
        assert avant[-2:] == ["34", "35"], (
            f"le document réel ne finit plus par 4.34 puis 4.35 : {avant[-3:]}. "
            "La mutation ci-dessous ne planterait pas le cas qu'elle prétend planter"
        )

        # Le geste du pilote : la section suivante prend le numéro de la
        # précédente. Une seule substitution, sur le dernier titre.
        derniere = "### 4.35"
        assert texte.count(derniere) == 1, f"ancre `{derniere}` : {texte.count(derniere)} fois"
        mute = texte.replace(derniere, "### 4.34", 1)

        apres = numeros_du_registre(mute)
        assert doublons(apres) == ["34"], (
            f"le doublon planté n'est pas vu : {doublons(apres)!r}. La règle du "
            "doublon côté registre ne garde rien, et c'est la seule preuve de son "
            "mordant qui existe — l'histoire du dépôt étant propre sur ce point"
        )
        # ET LA MUTATION NE DÉCLENCHE QUE LA RÈGLE DU DOUBLON — sans cela, un
        # rouge ne dirait pas laquelle des quatre règles a mordu. `mesuré` en
        # écrivant ce test, et l'attente initiale était FAUSSE : renuméroter la
        # dernière section sur l'avant-dernière ne creuse **aucun** trou, le
        # maximum descendant de 35 à 34. C'est ce qui rend ce cas le bon : la
        # collision réelle du pilote était exactement de cette forme, et le
        # doublon est le SEUL signal qu'elle émet.
        assert not desordre_numerique(apres), "la mutation déclenche aussi l'ordre"
        assert not trous(apres), (
            f"la mutation creuse un trou : {trous(apres)}. Elle ne discrimine plus "
            "la règle du doublon, et son rouge ne prouverait plus laquelle des "
            "quatre règles a mordu"
        )
        assert max(_entiers(apres)) == 34, "le maximum ne descend plus : la mutation a changé"

    def test_le_trou_construit_fait_rougir_sa_regle(self) -> None:
        """LA QUATRIÈME RÈGLE, ET SON CAS EST CONSTRUIT — ce qui est dit.

        Aucune révision de ce dépôt n'a jamais porté de trou : `mesuré` le
        9 septembre 2026 sur le journal et sur le registre à `2bb511c`,
        `a92e78a` et l'état courant. Un cas construit est donc la seule preuve
        disponible, et l'écrire est préférable à laisser croire à une dérive
        datée qui n'existe pas.
        """
        texte = _git_show(self._REGISTRE_PROPRE, _REGISTRE)
        ancre = "### 4.20"
        assert texte.count(ancre) == 1, f"ancre `{ancre}` : {texte.count(ancre)} fois"
        mute = texte.replace(ancre, "### 4.99", 1)

        apres = numeros_du_registre(mute)
        assert 20 in trous(apres), (
            f"le trou planté en 4.20 n'est pas vu : {trous(apres)}. La règle du trou "
            "ne garde rien"
        )

    def test_deux_bis_du_meme_numero_restent_un_doublon(self) -> None:
        """LA PORTE QUE LA TOLÉRANCE DU `bis` NE DOIT PAS OUVRIR.

        `20` et `20-bis` sont deux entrées légitimes ; deux `20-bis` sont un
        doublon. C'est le jeton COMPLET qui est comparé, et c'est ce qui empêche
        « ajoute un `bis` » de devenir le geste qui desserre ce garde.
        """
        assert doublons(["20", "20-bis", "21"]) == []
        assert doublons(["20", "20-bis", "20-bis", "21"]) == ["20-bis"]
        assert doublons(["4.23", "4.23 bis", "4.23 bis"]) == ["4.23 bis"]
        # Et un `bis` sans base est un numéro inventé, pas une reprise.
        assert bis_orphelins(["20", "20-bis", "27-bis"]) == ["27-bis"]
        assert bis_orphelins(["20", "20-bis"]) == []


# ─── LE SCOPE ET LA FORME, QUE RIEN NE GARDAIT ────────────────────────────────


class TestLeScopeEtLaFormeSontPorteursEtNonDecoratifs:
    """DEUX BORNES QUE CE FICHIER AFFIRMAIT SANS LES GARDER.

    **LA PREMIÈRE.** Le commentaire de `_DEBUT_DU_JOURNAL` écrit que le scope est
    nécessaire, et il a raison — mais rien ne le mesurait. Un scope dont le
    retrait ne changerait rien serait décoratif, et c'est la famille de défaut
    dominante de ce chantier : un garde vert sous une scène que le défaut ne
    rencontre jamais.

    **LA SECONDE, ET ELLE ÉTAIT UNE PHRASE FAUSSE.** Le commentaire de
    `_LIGNE_DU_PROCHAIN` affirmait que le scope est ce qui empêche de lire le
    RÉCIT du §12 au lieu de l'état du §6.1. `mesuré` le 9 septembre 2026 : ce qui
    protégeait était l'ORDRE DU FICHIER, le §6.1 précédant le §12. En remontant le
    paragraphe du récit sous le titre du §6.1, il entre dans le scope et le garde
    lit **41** — le faux nombre de la faute du 8 septembre — au lieu de **44**.

    *Un garde dont la justesse dépend de l'ordre de deux paragraphes est un garde
    qu'une réorganisation de document casse en silence.*

    Les scènes sont construites sur le document RÉEL, par programme : aucun
    document d'essai n'est inventé, et le fichier du dépôt n'est jamais touché.
    """

    _RECIT = "Prochain numéro libre : 41"

    def test_le_scope_du_journal_est_porteur(self, journal: str) -> None:
        """SANS SCOPE, LA LECTURE EST FAUTIVE — et voici de combien.

        La suite non bornée est celle que le commentaire de `_DEBUT_DU_JOURNAL`
        écrit, et ses deux chiffres y sont désormais exacts : **5** doublons, et
        un trou de **10 à 19** — `8 à 19` au relevé du lot 7, remesuré le
        10 septembre 2026. Le commentaire annonçait « onze doublons et un
        trou de 7 à 20 », et les deux étaient faux sous l'étiquette `mesuré`.
        """
        bornee = numeros_du_journal(journal)
        non_bornee = _extraire(journal, _NUMERO_DU_JOURNAL)

        # PREUVE D'ATTEINTE — les deux lectures diffèrent réellement. Sans cette
        # assertion, tout ce qui suit pourrait mesurer deux fois la même chose.
        assert len(non_bornee) > len(bornee), (
            "la lecture non bornée ne ramène plus rien de plus que la lecture "
            f"bornée ({len(non_bornee)} contre {len(bornee)}) : les autres "
            "tableaux numérotés du journal ont disparu, et le scope est devenu "
            "décoratif. Retire-le, ou remesure ce qui le justifie"
        )

        # LA LECTURE BORNÉE EST SAINE, et c'est la moitié qui rend l'autre lisible.
        assert doublons(bornee) == [], f"le journal borné porte des doublons : {bornee}"
        assert trous(bornee) == [], f"le journal borné porte des trous : {trous(bornee)}"

        # LA LECTURE NON BORNÉE EST FAUTIVE, et ses deux chiffres sont EXACTS.
        assert doublons(non_bornee) == ["1", "2", "3", "4", "5"], (
            f"les doublons de la lecture non bornée ne sont plus les cinq attendus : "
            f"{doublons(non_bornee)}. Le commentaire de `_DEBUT_DU_JOURNAL` porte ce "
            "chiffre : remesure-le AVANT de le réécrire — il a déjà été faux une fois"
        )
        # REMESURÉ le 10 septembre 2026 : le trou vaut 10→19 depuis que le plan
        # de lots porte ses rangs 8 et 9. Il valait 8→19 quand le lot 7 l'a
        # épinglé, et « 7 à 20 » dans un commentaire qui était faux.
        #
        # RÉSERVE ÉCRITE, ET ELLE EST UNE DETTE DE CE GARDE : épingler le trou
        # EXACT fait rougir ce test à chaque rang ajouté au plan de lots, qui
        # est un acte éditorial normal — c'est le geste « monter le chiffre »
        # que le §4.35 désapprouve, appliqué ici à une mesure de document. Ce
        # qui rend le scope porteur n'est pas la VALEUR du trou, c'est qu'une
        # lecture non bornée en ait UN, plus des doublons : la forme, pas
        # l'instantané. Un lot doit porter cette assertion sur la propriété.
        assert trous(non_bornee) == list(range(10, 20)), (
            f"le trou de la lecture non bornée n'est plus 10→19 : {trous(non_bornee)}. "
            "Le commentaire annonçait « 7 à 20 », et c'était faux : `7` et `20` sont "
            "tous deux présents dans la suite. Remesure avant de réécrire"
        )

    def test_le_recit_remonte_au_dessus_du_journal_ne_fait_plus_lire_le_faux_nombre(
        self, journal: str
    ) -> None:
        """LA SCÈNE EXACTE DE L'AUDIT, ET ELLE EST DÉSORMAIS VERTE POUR LA BONNE
        RAISON.

        Le paragraphe du récit est remonté sous le titre du §6.1 — donc DANS le
        scope. Avant la correction du 9 septembre 2026, `search()` rendait la
        première occurrence de la fenêtre et le garde lisait 41. La
        discrimination porte désormais sur la FORME de la ligne, qui ne doit rien
        à l'ordre.
        """
        etat = prochain_numero_annonce(journal)
        assert etat == max(int(j.split("-")[0]) for j in numeros_du_journal(journal)) + 1

        lignes = journal.splitlines(keepends=True)
        i_titre = next(
            k for k, ligne in enumerate(lignes) if ligne.startswith(_DEBUT_DU_JOURNAL)
        )
        i_recit = next(k for k, ligne in enumerate(lignes) if self._RECIT in ligne)

        # PREUVE D'ATTEINTE 1 — le récit est bien APRÈS le titre dans le document
        # réel : c'est cet ordre, et lui seul, qui protégeait.
        assert i_recit > i_titre, (
            "le récit du §12 précède désormais le §6.1 dans le document réel. La "
            "scène de ce test est alors l'état normal du fichier, et c'est le test "
            "voisin qu'il faut relire"
        )

        recit = lignes[i_recit]
        mute = "".join(
            lignes[: i_titre + 1]
            + [recit]
            + lignes[i_titre + 1 : i_recit]
            + lignes[i_recit + 1 :]
        )

        # PREUVE D'ATTEINTE 2 — le récit est bien ENTRÉ dans le scope. Sans elle,
        # un déplacement raté rendrait ce test vert sans rien mesurer.
        debut = mute.find(_DEBUT_DU_JOURNAL)
        fin = mute.find("\n## ", debut)
        assert self._RECIT in mute[debut : fin if fin > 0 else len(mute)], (
            "le récit n'est pas entré dans le scope du §6.1 : la scène n'atteint "
            "pas son cas, et ce test ne mesure rien"
        )

        # PREUVE D'ATTEINTE 3 — le motif NON ancré, celui d'avant la correction,
        # lisait bien 41. Si cette lecture cesse d'être fautive, la scène ne
        # reproduit plus le défaut et ce test perd son sujet.
        non_ancre = re.compile(r"Prochain num[ée]ro libre\s*:\s*(\d+)")
        premiere = non_ancre.search(mute[debut : fin if fin > 0 else len(mute)])
        assert premiere is not None and premiere.group(1) == "41", (
            "le motif non ancré ne lit plus 41 sur cette scène : elle ne reproduit "
            f"plus le défaut mesuré le 9 septembre 2026 ({premiere})"
        )

        # ET LE VERDICT — la forme discrimine, l'ordre n'y est pour rien.
        assert prochain_numero_annonce(mute) == etat, (
            f"le garde lit {prochain_numero_annonce(mute)} au lieu de {etat} dès que "
            "le récit du §12 remonte au-dessus du §6.1. Ce qui le protège est donc "
            "encore l'ORDRE DU FICHIER, et non la forme de la ligne d'autorité : "
            "une réorganisation de document le casserait en silence"
        )

    def test_deux_lignes_d_autorite_ne_sont_pas_tranchees_en_silence(
        self, journal: str
    ) -> None:
        """L'AMBIGUÏTÉ EST UNE ERREUR, PAS UN PREMIER-ARRIVÉ.

        Si deux lignes d'autorité apparaissaient dans le scope, la forme ne
        discriminerait plus. Choisir la première est exactement le geste qui a
        produit la faute du 8 septembre 2026 : `prochain_numero_annonce` rend
        donc `None`, et le rouge remonte jusqu'au test qui nomme la cause.

        Sans ce test, l'ancrage sur la forme aurait remplacé une dépendance à
        l'ordre par une autre, silencieuse elle aussi.
        """
        ligne = f"**Prochain numéro libre : {prochain_numero_annonce(journal)}.**"
        assert journal.count(ligne) == 1, (
            f"la ligne d'autorité n'a plus sa forme attendue : {ligne!r} apparaît "
            f"{journal.count(ligne)} fois. C'est cette forme que `_LIGNE_DU_PROCHAIN` "
            "reconnaît, et son commentaire écrit pourquoi"
        )

        double = journal.replace(ligne, ligne + "\n\n**Prochain numéro libre : 99.**", 1)
        # PREUVE D'ATTEINTE : la seconde ligne est bien dans le scope.
        debut = double.find(_DEBUT_DU_JOURNAL)
        fin = double.find("\n## ", debut)
        fenetre = double[debut : fin if fin > 0 else len(double)]
        assert len(_LIGNE_DU_PROCHAIN.findall(fenetre)) == 2, (
            "la seconde ligne d'autorité n'est pas dans le scope : la scène "
            "n'atteint pas son cas"
        )

        assert prochain_numero_annonce(double) is None, (
            f"le garde tranche en silence entre deux lignes d'autorité et rend "
            f"{prochain_numero_annonce(double)}. Un extracteur qui choisit entre "
            "deux vérités possibles sans le dire est précisément ce qui a produit "
            "la faute du 8 septembre 2026"
        )

    def test_le_scope_reste_porteur_pour_la_ligne_d_autorite(self, journal: str) -> None:
        """LE TROU QUE MA PROPRE MUTATION A TROUVÉ, ET IL ÉTAIT DANS CE FICHIER.

        `mesuré` le 9 septembre 2026, mutation **M-8** : retirer le scope de
        `prochain_numero_annonce` laissait les **17** tests de ce fichier
        ENTIÈREMENT VERTS. L'ancrage sur la forme suffisait à discriminer les
        deux lignes du document courant, donc le scope était devenu — pour cette
        fonction-là, et pour elle seule — **une borne inerte**. C'est la famille
        de défaut dominante de ce chantier, retrouvée contre la correction qui
        venait de la fermer ailleurs.

        **CE QUE LA SCÈNE MANQUANTE DEVAIT ÊTRE.** Une seconde ligne d'autorité
        **en gras et en tête de ligne**, mais **HORS** du §6.1 — c'est-à-dire ce
        que devient le récit du §12 le jour où quelqu'un le réécrit sans ses
        guillemets. Alors la forme ne discrimine plus, et seul le scope tranche :

            avec le scope   → 44, l'état, correctement lu
            sans le scope   → deux lignes d'autorité, donc `None`, donc rouge

        Le scope et la forme ne sont donc pas redondants : la forme protège de
        ce qui est DANS la fenêtre, le scope de ce qui est DEHORS. Chacun a
        désormais sa mutation.
        """
        ancre = "- **Un numéro est une mesure comme une autre.**"
        assert journal.count(ancre) == 1, (
            f"l'ancre du récit du §12 apparaît {journal.count(ancre)} fois : la "
            "scène ne peut plus être plantée à un endroit connu"
        )
        seconde = "**Prochain numéro libre : 99.**"
        mute = journal.replace(ancre, f"{seconde}\n\n{ancre}", 1)

        debut = mute.find(_DEBUT_DU_JOURNAL)
        fin = mute.find("\n## ", debut)
        fenetre = mute[debut : fin if fin > 0 else len(mute)]

        # PREUVE D'ATTEINTE — la seconde ligne est DEHORS, et elle est bien de la
        # forme que le motif reconnaît. Sans ces deux faits, la scène ne
        # distinguerait pas le scope de la forme.
        assert len(_LIGNE_DU_PROCHAIN.findall(fenetre)) == 1, (
            "la seconde ligne d'autorité est tombée DANS le scope : cette scène "
            "mesure alors la forme, et non le scope — c'est le test voisin"
        )
        assert len(_LIGNE_DU_PROCHAIN.findall(mute)) == 2, (
            "la seconde ligne d'autorité n'est pas reconnue par le motif : la "
            "scène n'atteint pas son cas"
        )

        assert prochain_numero_annonce(mute) == prochain_numero_annonce(journal), (
            "une seconde ligne d'autorité posée HORS du §6.1 change ce que le "
            f"garde lit ({prochain_numero_annonce(mute)}). Le scope ne borne donc "
            "plus la lecture de la ligne d'autorité, et la forme seule ne peut pas "
            "s'en charger : elle ne distingue pas le dedans du dehors"
        )
