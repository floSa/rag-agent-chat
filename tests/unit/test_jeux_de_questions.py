"""Les deux jeux de questions du dépôt, gardés dans leur FORME.

CE QUE CE FICHIER GARDE, ET CE QU'IL NE PEUT PAS GARDER. Il confronte les deux
jeux à leur spécification sans toucher aux stores : effectifs, strates, schéma,
réserve, provenance. Il ne peut PAS garder la vérité de leurs ancrages — cela
demande ChromaDB et NebulaGraph, et c'est le travail de
`scripts/verifier_les_ancrages.py`, qui sort en 1 au premier désaccord. Les deux
sont nécessaires et aucun ne remplace l'autre : c'est la même répartition que
celle adoptée par le pipeline pour son propre jeu.

POURQUOI CE FICHIER EXISTE. Le 3 septembre 2026, le jeu de 138 questions alors
versionné désignait 129 `gold_element_ids` dont **0** existait dans le graphe, et
rien dans le dépôt ne rougissait : `make eval` aurait tourné et rendu un tableau
faux, à zéro de rappel. Site canonique du constat et de la décision qui en sort :
`documentation/axes_amelioration.md`, §4.3.
"""

import ast
import importlib.util
import pathlib
import re

import pytest
import yaml

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_FIXTURES = _RACINE / "tests" / "fixtures"
_GENERE = _FIXTURES / "golden_qa_generated.yaml"
_PIPELINE = _FIXTURES / "jeu_de_questions_pipeline.yaml"

# Contrat avec le pipeline, exigence 2 : `element_id` déterministe, dix
# hexadécimaux. L'agent le valide déjà dans `graph_context.py` ; le valider ici
# attrape un jeu de questions mal formé AVANT qu'il ne coûte une campagne.
_ELEMENT_ID = re.compile(r"^[a-f0-9]{10}$")

# La spécification du jeu du pipeline — cinq strates, 12 / 8 / 4 / 4 / 2. Site
# canonique : `documentation/axes_amelioration.md` section 1 de son registre,
# nommée dans le champ `specification` du fichier.
_STRATES = {
    "multi_passages": 12,
    "simple": 8,
    "sans_reponse": 4,
    "de_suivi": 4,
    "reformulee": 2,
}


def _charger(chemin: pathlib.Path) -> dict:
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


def _evaluate():
    """Charge `scripts/evaluate.py` sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location(
        "evaluate", _RACINE / "scripts" / "evaluate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── Les deux jeux sont lisibles par l'instrument qui les consomme ───────────


@pytest.mark.parametrize("chemin", [_GENERE, _PIPELINE])
def test_le_jeu_est_lu_par_la_campagne(chemin: pathlib.Path) -> None:
    """Un jeu que `evaluate.py` ne sait pas lire n'est pas un instrument.

    Le test passe par `charger_questions` et non par `yaml.safe_load` : c'est
    la fonction que `make eval` appelle, et elle seule décide du YAML contre le
    JSON. Un jeu valide qu'elle ne lit pas est aussi inutile qu'un jeu périmé.
    """
    questions = _evaluate().charger_questions(chemin)
    assert questions, f"{chemin.name} : aucune question lue"
    assert all(q.get("id") for q in questions)


@pytest.mark.parametrize("chemin", [_GENERE, _PIPELINE])
def test_les_jeux_sont_en_yaml_et_aucun_jeu_json_ne_subsiste(chemin: pathlib.Path) -> None:
    """Le format est une décision mesurée, pas un goût — et elle est gardée.

    `detect-secrets` lit un `element_id` comme une chaîne hexadécimale à forte
    entropie. `mesuré` le 8 septembre 2026, `detect-secrets-hook` v1.5.0 sur
    l'ensemble des fichiers suivis : **36** détections, dont **34** dans le seul
    `tests/fixtures/golden_qa_generated.json`. Le retirer au profit du YAML
    ramène le dépôt à **2** détections, et c'est ce qui rend ce hook armable
    ici — il ne l'est pas (`.pre-commit-config.yaml` le dit et dit pourquoi).

    La CAUSE a son site canonique chez le pipeline, en tête de
    `documentation/campagnes/2026-09-02-jeu-de-questions.yaml` : son
    transformateur YAML rend les valeurs de mapping et pas les éléments de
    séquence, et les `element_id` d'un jeu vivent en éléments de séquence.

    LE GARDE PORTE AUSSI SUR L'ABSENCE, et c'est ce qui lui a fait trouver
    `tests/fixtures/golden_qa.json` — un TROISIÈME jeu, 15 questions écrites à
    la main, que le cadrage du lot ne nommait pas et qui était le `--golden` par
    DÉFAUT de `evaluate.py`. **13** d'entre elles étaient à réponse — les deux
    autres, `Q-010` et `Q-011`, sont des abstentions — et portaient **0**
    `gold_element_ids` : toutes ses métriques de rappel valaient `None`, ce qui
    se lit « sans objet » et non « cassé ». (« quinze questions à réponse » était
    faux de deux, `mesuré` le 8 septembre 2026 : trouvaille N8.) Il désignait en plus le corpus
    disparu. Retiré par ce lot ; son remplaçant est le jeu du pipeline, qui est
    relu comme lui et annoté à l'élément contre le corpus en service.
    """
    assert chemin.suffix == ".yaml"
    orphelins = sorted(p.name for p in _FIXTURES.glob("golden_qa*.json"))
    assert not orphelins, (
        f"jeu(x) de questions en JSON encore présent(s) : {orphelins}. "
        "34 détections `detect-secrets` sont peut-être revenues avec, et un jeu "
        "qui n'est pas passé par `verifier_les_ancrages.py` peut désigner le vide."
    )


# ─── Le jeu régénéré : le volume de réglage ──────────────────────────────────


def test_le_jeu_regenere_porte_138_questions_et_ses_ancrages_sont_bien_formes() -> None:
    data = _charger(_GENERE)
    questions = data["questions"]
    assert len(questions) == 138
    assert data["_statistiques"]["questions"] == 138

    for question in questions:
        for ancrage in question.get("gold_element_ids") or []:
            assert _ELEMENT_ID.match(ancrage), f"{question['id']} : `{ancrage}` mal formé"


def test_le_jeu_regenere_inscrit_l_index_contre_lequel_il_a_ete_ecrit() -> None:
    """Un jeu qui ne dit pas contre quel index il a été écrit ne peut pas être
    déclaré périmé — et c'est exactement ce qui est arrivé au jeu précédent.

    `mesuré` le 8 septembre 2026 contre ChromaDB : 4 367 chunks, 23 documents,
    1 266 passages exploitables, et **4 367 sur 4 367** en `language: en`. Cette
    dernière ligne est celle qui borne l'axe translinguistique : « question
    française → document anglais » reste mesurable, l'inverse a disparu avec le
    corpus français.
    """
    corpus = _charger(_GENERE)["_statistiques"]["corpus"]
    assert corpus["chunks_indexes"] > 0
    assert corpus["passages_exploitables"] > 0
    assert corpus["documents_porteurs"] > 0
    assert corpus["langues_du_corpus"], "les langues du corpus ne sont pas inscrites"


# ─── Le jeu du pipeline : le contrôle indépendant ────────────────────────────


def test_le_jeu_du_pipeline_porte_ses_cinq_strates_a_l_effectif() -> None:
    """Une strate qui a perdu une question rend un rappel comparable à rien."""
    data = _charger(_PIPELINE)
    effectifs: dict[str, int] = {}
    for question in data["questions"]:
        effectifs[question["type"]] = effectifs.get(question["type"], 0) + 1
    assert effectifs == _STRATES
    assert data["_statistiques"]["par_strate"] == _STRATES
    assert len(data["questions"]) == sum(_STRATES.values()) == 30


def test_le_jeu_du_pipeline_designe_44_ancrages_distincts() -> None:
    data = _charger(_PIPELINE)
    ancres = {a for q in data["questions"] for a in (q.get("gold_element_ids") or [])}
    assert len(ancres) == 44
    assert data["_statistiques"]["ancrages_distincts"] == 44
    for ancrage in ancres:
        assert _ELEMENT_ID.match(ancrage), f"`{ancrage}` mal formé"


def test_les_quatre_questions_de_suivi_portent_leur_historique() -> None:
    """Sans `chat_history`, une question de suivi mesure autre chose.

    C'est la borne mesurée du côté pipeline : son script encode la question
    SEULE, et la strate y rend 20 % — 60 % avec l'historique concaténé. De ce
    côté-ci, `evaluate.interroger` TRANSMET `chat_history` à `/answer`, donc la
    strate mesure la résolution de l'antécédent par l'agent. Les deux chiffres
    ne sont pas comparables, et une question de suivi privée de son historique
    ferait taire la différence.

    Site des deux bornes :
    `rag-ingestion-pipeline/documentation/campagnes/2026-09-02-premiere-campagne-de-reference.md`.
    """
    suivi = [q for q in _charger(_PIPELINE)["questions"] if q["type"] == "de_suivi"]
    assert len(suivi) == 4
    for question in suivi:
        historique = question.get("chat_history")
        assert historique, f"{question['id']} : question de suivi sans historique"
        assert {m["role"] for m in historique} == {"user", "assistant"}


def test_la_reserve_du_jeu_de_30_voyage_avec_lui() -> None:
    """Une réserve qu'on peut perdre en éditant un fichier de données n'en est pas une.

    Trente questions prouvent que la chaîne fonctionne et montrent un défaut
    grossier ; elles ne suffisent pas à arbitrer un réglage. La phrase est dans
    le fichier, et ce test refuse qu'elle en sorte.
    """
    reserve = _charger(_PIPELINE)["_reserve"]
    assert "PAS DÉCISION D'ARCHITECTURE" in reserve
    assert "bruit" in reserve


def test_l_empreinte_de_provenance_se_nomme_au_lieu_de_se_cacher() -> None:
    """L'empreinte NOMME son algorithme, et c'est ce qui remplace le pragma.

    L'empreinte de la source est une valeur de mapping YAML : `detect-secrets`
    la relève comme « Hex High Entropy String », son transformateur YAML rendant
    les valeurs de mapping et pas les éléments de séquence — ce qui est aussi
    pourquoi les 44 `gold_element_ids` du fichier, eux, ne sont jamais détectés.

    `mesuré` le 8 septembre 2026, `detect-secrets-hook` v1.5.0, même valeur sous
    trois formes :

        source_sha256: 960e8b…0d03f                             -> rc=1
        source_sha256: 960e8b…0d03f  # pragma: allowlist secret  -> rc=0
        source_sha256: sha256:960e8b…0d03f                       -> rc=0

    LA TROISIÈME FORME EST RETENUE, et la deuxième retirée : elle supprime le
    pragma, le post-traitement `poser_le_pragma()` qui l'émettait — car
    `yaml.safe_dump` n'écrit pas de commentaire — et le garde de ce
    post-traitement. C'était déjà la technique de
    `evaluate.empreinte_des_ancrages`, et ce script ne l'employait pas : deux
    hachages, deux traitements, dans le même lot.

    Un préfixe ne CACHE rien, contrairement à un pragma : il dit quel algorithme
    a produit les 64 caractères. Un pragma dit « ignore cette ligne », ce qui
    est exactement ce qu'on ne veut pas apprendre à un relecteur.
    """
    lignes = _PIPELINE.read_text(encoding="utf-8").splitlines()
    empreintes = [ligne for ligne in lignes if ligne.strip().startswith("source_sha256:")]
    assert len(empreintes) == 1, f"{len(empreintes)} ligne(s) d'empreinte, une attendue"
    ligne = empreintes[0]
    assert "pragma" not in ligne, (
        "l'empreinte porte de nouveau un pragma : le préfixe `sha256:` le rend "
        "inutile, et un pragma apprend à un relecteur à ignorer une ligne"
    )
    valeur = ligne.split(":", 1)[1].strip()
    assert re.match(r"^sha256:[a-f0-9]{64}$", valeur), f"empreinte mal formée : {valeur!r}"


def test_la_graine_est_transmise_au_generateur_de_texte() -> None:
    """LA GRAINE NE SUFFIT PAS SI ELLE S'ARRÊTE AU TIRAGE — trouvaille N7.

    `echantillonner(..., seed)` fixe les candidats ; mais ils sont consommés
    dans l'ordre jusqu'à `count` ACCEPTATIONS, et le motif de rejet dépend du
    LLM. Un rejet qui tombe autrement décale la suite des ancrages ET réaffecte
    les langues, le tirage de langue vivant dans la même boucle. `mesuré` par
    l'audit du lot 5 : deux exécutions à `--seed 42`, mêmes ancrages mais **7
    textes de question sur 16** différents — `temperature: 0.4`, et **aucun**
    `seed` transmis à Ollama.

    Ce test rougit si la graine cesse d'atteindre la charge Ollama. Il ne
    prouve pas le déterminisme du serveur, qui n'est pas un fait sur ce dépôt :
    la mesure qui l'établit est citée au docstring de
    `generate_golden.demander_question`.
    """
    source = (_RACINE / "scripts" / "generate_golden.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    fonction = next(
        noeud
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "demander_question"
    )
    assert "graine" in [a.arg for a in fonction.args.args], (
        "`demander_question` ne reçoit plus la graine : le tirage est reproductible "
        "et la génération ne l'est pas, ce qui décale les ancrages"
    )
    # La graine doit atteindre `options`, pas seulement la signature : c'est la
    # différence entre « le paramètre existe » et « le serveur le reçoit ».
    options = next(
        noeud
        for noeud in ast.walk(fonction)
        if isinstance(noeud, ast.Dict)
        and any(
            isinstance(cle, ast.Constant) and cle.value == "temperature"
            for cle in noeud.keys
        )
    )
    cles = [c.value for c in options.keys if isinstance(c, ast.Constant)]
    assert "seed" in cles, f"`options` ne porte pas `seed` : {cles}"
    valeur = options.values[cles.index("seed")]
    assert isinstance(valeur, ast.Name) and valeur.id == "graine", (
        "`options[\"seed\"]` n'est pas la graine reçue en paramètre : une constante "
        "figée rendrait `--seed` décoratif"
    )


def test_le_jeu_du_pipeline_nomme_son_site_canonique() -> None:
    """Un chiffre n'a qu'un site. Ce fichier est une DÉRIVATION, et il le dit."""
    data = _charger(_PIPELINE)
    provenance = data["_provenance"]
    assert provenance["source"].endswith("2026-09-02-jeu-de-questions.yaml")
    assert provenance["transpose_par"] == "scripts/adopter_le_jeu_du_pipeline.py"
    assert any("DÉRIVATION" in ligne for ligne in data["_lisez_moi"])


# ─── Le défaut que ce lot existe pour réparer, gardé sur les DEUX jeux ───────


@pytest.mark.parametrize("chemin", [_GENERE, _PIPELINE])
def test_aucune_question_a_reponse_ne_designe_le_vide(chemin: pathlib.Path) -> None:
    """Une question à réponse sans ancrage ne mesure RIEN, et se tait.

    Ses métriques valent `None`, elle disparaît des moyennes, et le résumé
    affiche un chiffre calculé sur moins de questions qu'annoncé. C'est la même
    famille que le zéro de rappel du §4.3 : un instrument qui ne dit pas qu'il
    ne mesure pas.

    La réciproque est gardée aussi : une question d'abstention qui porte un
    ancrage serait comptée comme un échec de rappel au lieu d'être mesurée sur
    l'abstention.
    """
    for question in _charger(chemin)["questions"]:
        ancrages = question.get("gold_element_ids") or []
        if question.get("unanswerable"):
            assert not ancrages, (
                f"{chemin.name} / {question['id']} : abstention attendue avec "
                f"{len(ancrages)} ancrage(s)"
            )
        else:
            assert ancrages, (
                f"{chemin.name} / {question['id']} : question à réponse sans ancrage — "
                "elle ne mesure rien et ne le dira pas"
            )


@pytest.mark.parametrize("chemin", [_GENERE, _PIPELINE])
def test_aucune_question_n_est_desactivee(chemin: pathlib.Path) -> None:
    """`charger_questions` saute les questions marquées `_skip`.

    C'est un test désactivé qui ne s'appelle pas un test désactivé : le jeu
    annonce son effectif dans `_statistiques` et la campagne en mesure moins,
    sans que rien ne le dise.
    """
    data = _charger(chemin)
    sautees = [q["id"] for q in data["questions"] if q.get("_skip")]
    assert not sautees, f"{chemin.name} : question(s) désactivée(s) {sautees}"
    assert len(_evaluate().charger_questions(chemin)) == len(data["questions"])
