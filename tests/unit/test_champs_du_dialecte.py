"""L'INVENTAIRE DES CHAMPS QUI DÉPENDENT DU MOTEUR, ET LA TABLE QUI LES TIENT.

LA CAUSE QUE CE FICHIER TRAITE, ET ELLE EST ÉCRITE PAR LE LOT 25 LUI-MÊME
-------------------------------------------------------------------------

> « UNE CAMPAGNE MENÉE SOUS LE DÉFAUT NE PEUT PAS MESURER CE QUI NE VARIE QU'À
> LA BASCULE. »

Le lot 25 l'a écrite après que trois de ses mutations eurent survécu. Son audit
indépendant l'a retournée contre lui et a trouvé **trois champs de plus** :
`_sonder_moteur_llm` prend l'hôte, le modèle demandé et le modèle confronté du
dialecte, et **aucune scène ne le vérifiait ailleurs que sous le défaut**. Trois
mutations qui inversent la décision du lot passaient les 1035 tests sans un
rouge — NB-2 de `documentation/audits/2026-09-16-audit-lot-25.md`.

CE QUE LE LOT 28 CHANGE ICI, ET CE QU'IL NE CHANGE PAS
-------------------------------------------------------

Ce fichier tenait une table à DEUX COLONNES — un champ, deux dialectes — et son
garde central exigeait que les deux colonnes DIFFÈRENT : une scène dont les deux
côtés portent la même valeur ne distingue pas le code servi d'un mutant qui
ignore le dialecte, et elle a l'air verte.

Le lot 28 retire le second moteur. La colonne disparaît ; **la cause, non**. Elle
est exactement celle qu'elle a toujours été — « une scène qui hérite du défaut ne
mesure pas le site, elle mesure le défaut » — et le garde est TRANSPOSÉ, pas
retiré : chaque valeur de la table doit différer du DÉFAUT DU CODE, et chaque
adresse et chaque nom de modèle que les doubles servent sont POSÉS par ce
fichier, jamais hérités. Un mutant qui remplacerait `dialecte.hote` par une
constante, ou `dialecte.modele` par le défaut du champ, rougit ici.

LA TABLE ET SES GARDES
-----------------------

1. **elle est EXHAUSTIVE** — `test_la_table_couvre_tous_les_champs_du_releve`
   confronte ses clés à `MoteurLlmHealth.model_fields`. Un champ neuf au schéma
   qui n'est pas classé fait rougir, et le message dit quoi faire ;
2. **elle ÉCARTE LES DÉFAUTS** — `test_aucune_valeur_attendue_n_est_un_defaut`
   refuse qu'une valeur attendue coïncide avec un défaut de `Settings`. C'est le
   garde anti-« mesuré sous le défaut », transposé du garde de parité ;
3. **elle est JOUÉE** — une seule scène, paramétrée sur le champ, lit la table.
   Ajouter une ligne suffit à ajouter une scène.

LE DOUBLE ROUTE PAR (HÔTE, CHEMIN), ET C'EST CE QUI LE REND MORDANT
--------------------------------------------------------------------

Un double qui route sur le seul CHEMIN répond identiquement à toute adresse, et
une sonde qui interroge le mauvais hôte y reste invisible. Celui d'ici tient ses
serveurs **à leurs adresses** : se tromper d'hôte fait recevoir la réponse d'un
autre serveur, ou lever comme lèverait une connexion refusée.

CE FICHIER NE MESURE AUCUN INSTANTANÉ. Les versions, les noms et la fenêtre sont
ceux des doubles, jamais ceux des serveurs du poste : ce qui est asserté est la
RELATION « ce champ vient du serveur qu'on interroge », pas la valeur du jour.
"""

import asyncio
from typing import Any
from urllib.parse import urlsplit

import pytest

from src.agent.settings import Settings, settings
from src.api.schemas import MoteurLlmHealth

# ─── CE QUE CE FICHIER POSE, ET QUI N'EST AUCUN DÉFAUT ───────────────────────
#
# L'hôte, le modèle et la version sont ceux des doubles. Aucun n'est le défaut du
# code : c'est la condition pour qu'une mutation qui remplace `dialecte.hote` ou
# `dialecte.modele` par une constante SE VOIE. Sous un hôte égal au défaut, le
# mutant serait strictement équivalent au code servi, et la scène serait verte
# sur un code faux. `test_aucune_valeur_attendue_n_est_un_defaut` le tient.
_HOTE = "http://serveur-d-essai:8000"
_AUTRE_HOTE = "http://serveur-etranger:8000"
_MODELE = "org/moteur-d-essai-e4b-w4a16"

# Le modèle qu'un AUTRE serveur sert — celui de l'équipe voisine sur une instance
# partagée. Choisi pour ne PAS s'apparier au nôtre : `le_serveur_sert_ce_que_nous
# _demandons` apparie par INFIXE après réduction, et
# `test_les_deux_noms_de_modele_ne_s_apparient_pas_l_un_a_l_autre` le vérifie
# plutôt que de le croire sur parole.
_MODELE_ETRANGER = "autre-equipe/modele-tiers-q8"

_VERSION = "0.28.0-essai"
_FENETRE = 32768


# ─── LA TABLE, ET C'EST ELLE QUE CE FICHIER EXISTE POUR TENIR ────────────────
#
# Chaque champ du relevé, et la valeur que le relevé doit porter quand le serveur
# d'en face est celui que le réglage désigne. C'est le seul endroit à modifier
# quand un champ s'ajoute.
_ATTENDU: dict[str, Any] = {
    "serveur": "vllm",
    "endpoint": _HOTE,
    "version": _VERSION,
    "modele_demande": _MODELE,
    "modele_servi": _MODELE,
    "fenetre_servie": _FENETRE,
}

# CE QUI NE VIENT PAS DU SERVEUR, ET POURQUOI — la seconde moitié de la
# partition. Un champ est dans l'une ou dans l'autre, jamais dans les deux ni
# dans aucune, et le garde d'exhaustivité l'exige.
_INVARIANTS: dict[str, str] = {
    # NOS drapeaux d'appel : ils viennent de `settings`, pas du serveur. Leur
    # propre lacune — n'être mesurés qu'à leur valeur PAR DÉFAUT — est traitée
    # plus bas, par `_REGLAGES_EPROUVES` et son garde.
    "options": "du réglage, pas du serveur",
    # L'instant du relevé : il ne dépend pas du serveur joint.
    "releve_le": "l'instant de la mesure",
}


# ─── Le double : des serveurs, À LEURS ADRESSES ──────────────────────────────


class _Reponse:
    def __init__(self, code: int, charge: Any) -> None:
        self.status_code, self._charge = code, charge

    def json(self) -> Any:
        return self._charge


def _routes(modele: str, *, version: str = _VERSION) -> dict[str, _Reponse]:
    """Les deux routes que la sonde interroge, sur un serveur qui sert `modele`."""
    return {
        "/version": _Reponse(200, {"version": version}),
        "/v1/models": _Reponse(200, {"data": [{"id": modele, "max_model_len": _FENETRE}]}),
    }


_SERVEURS: dict[str, dict[str, _Reponse]] = {
    _HOTE: _routes(_MODELE),
    # UN SECOND SERVEUR, QUI RÉPOND PARFAITEMENT ET NE SERT PAS NOTRE MODÈLE.
    # C'est le cas de ce poste : `vllm-central` est partagé avec deux autres
    # équipes. Une sonde qui part sur le mauvais hôte y reçoit 200 sur tout, et
    # c'est précisément pour cela qu'un double qui LÈVE partout ne mesurerait
    # rien — il transformerait une mutation en panne au lieu d'un relevé faux.
    _AUTRE_HOTE: _routes(_MODELE_ETRANGER),
}


class _Poste:
    """Le poste, avec ses serveurs d'inférence à leurs adresses.

    Router sur le seul chemin rendrait une constante d'hôte invisible : toutes
    les adresses répondraient pareil. Ici, se tromper d'hôte fait recevoir la
    réponse de l'autre serveur — ce qui est le comportement réel.
    """

    def __init__(self, serveurs: dict[str, dict[str, _Reponse]]) -> None:
        self.serveurs = serveurs
        self.demandes: list[str] = []

    async def __aenter__(self) -> "_Poste":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    async def get(self, url: str) -> _Reponse:
        self.demandes.append(url)
        decoupe = urlsplit(url)
        base = f"{decoupe.scheme}://{decoupe.netloc}"
        routes = self.serveurs.get(base)
        if routes is None:
            # Un hôte qu'aucun serveur ne sert : la connexion échoue, comme elle
            # échouerait pour de vrai. `_lire_json` l'absorbe et rend `None`.
            raise ConnectionError(f"aucun serveur à {base}")
        reponse = routes.get(decoupe.path)
        return reponse if reponse is not None else _Reponse(404, {"detail": "Not Found"})


def _releve(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reglages: dict[str, Any] | None = None,
    serveurs: dict[str, dict[str, _Reponse]] | None = None,
) -> tuple[Any, _Poste]:
    """Joue la sonde de `/health` contre le poste, sur des réglages POSÉS.

    LES DEUX RÉGLAGES DU MOTEUR SONT POSÉS HORS DE LEUR DÉFAUT, et c'est ce qui
    fait mesurer : une mutation qui les remplacerait par une constante désigne
    alors une valeur DIFFÉRENTE, donc produit un relevé faux plutôt qu'une
    panne. Un mutant qui lève n'apprend rien sur le garde.
    """
    from src.api import main

    monkeypatch.setattr(settings, "llm_host", _HOTE)
    monkeypatch.setattr(settings, "llm_model", _MODELE)
    for champ, valeur in (reglages or {}).items():
        monkeypatch.setattr(settings, champ, valeur)
    monkeypatch.setattr(main, "_moteur_releve", None)
    client = _Poste(serveurs if serveurs is not None else _SERVEURS)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_k: client)
    return asyncio.run(main._sonder_moteur_llm()), client


# ─── LES DÉFAUTS DÉCLARÉS, ET RIEN D'AUTRE ───────────────────────────────────


def _defauts_du_code(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """`Settings` tel que le CODE le déclare, sans le poste qui l'exécute.

    CE QUE `Settings(_env_file=None)` NE FAISAIT PAS, ET C'EST LE LOT 30 QUI L'A
    MESURÉ. Deux gardes de ce fichier lisaient les défauts ainsi, en écrivant
    qu'ils les prenaient « sur le CHAMP, jamais sur le `.env` du poste ».
    `_env_file=None` neutralise le FICHIER ; il ne neutralise pas
    l'ENVIRONNEMENT, dont `pydantic-settings` fait une source de priorité
    SUPÉRIEURE au fichier — `mesuré` le 22 septembre 2026 : un `.env` portant
    `LLM_NUM_CTX=32768` face à une variable d'environnement à `8192` rend 8192.

    Les deux gardes héritaient donc du lancement. `test_aucune_valeur_attendue_
    n_est_un_defaut` est devenu rouge sous `LLM_NUM_CTX=32768`, qui est la valeur
    que `_FENETRE` pose ; `test_aucune_valeur_d_epreuve_n_est_la_valeur_par_
    defaut` ne l'était pas encore, mais il rougirait sous `LLM_NUM_CTX=16384` —
    une scène verte par coïncidence de chiffres, pas par construction.

    Le geste : retirer de l'environnement l'alias de chaque champ avant de
    construire. Les validateurs de `Settings` tournent donc tous, ce qu'une
    lecture de `model_fields[...].default` n'aurait pas fait.
    """
    for champ in Settings.model_fields.values():
        if champ.alias:
            monkeypatch.delenv(champ.alias, raising=False)
    return Settings(_env_file=None)


# ─── LES GARDES DE LA TABLE ──────────────────────────────────────────────────


def test_la_table_couvre_tous_les_champs_du_releve() -> None:
    """LE GARDE QUI REND L'OUBLI IMPOSSIBLE, et c'est le cœur de ce fichier.

    Un champ ajouté à `MoteurLlmHealth` sans être classé fait rougir ici. Le
    geste attendu au rouge n'est pas d'élargir ce test : c'est de dire, dans
    `_ATTENDU` ou dans `_INVARIANTS`, ce que ce champ vaut et d'où il vient.
    C'est précisément la question que personne n'avait posée aux trois champs de
    NB-2.
    """
    du_schema = set(MoteurLlmHealth.model_fields)
    classes = set(_ATTENDU) | set(_INVARIANTS)
    assert classes == du_schema, (
        f"champ(s) de `MoteurLlmHealth` non classé(s) : {sorted(du_schema - classes)} ; "
        f"champ(s) classé(s) qui n'existe(nt) plus : {sorted(classes - du_schema)}. "
        "Tout champ du relevé doit dire ce qu'il vaut quand le serveur répond "
        "(`_ATTENDU`) ou pourquoi il n'en vient pas (`_INVARIANTS`). Trois "
        "champs ont vécu non gardés parce que personne ne leur avait posé la "
        "question — NB-2 de l'audit du 16 septembre 2026."
    )
    assert not (set(_ATTENDU) & set(_INVARIANTS)), (
        "un champ est à la fois déclaré venu du serveur et invariant : la "
        "partition n'en est plus une, et l'exhaustivité ne prouve plus rien"
    )


def test_aucune_valeur_attendue_n_est_un_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE GARDE ANTI-« MESURÉ SOUS LE DÉFAUT », TRANSPOSÉ AU LOT 28.

    Il exigeait que les deux colonnes de la table diffèrent l'une de l'autre.
    Il n'y a plus qu'une colonne ; la cause est la même et elle s'énonce contre
    le CODE : une valeur attendue qui coïncide avec un défaut de `Settings` ne
    peut pas distinguer le code servi d'un mutant qui écrit ce défaut en dur.

    Les défauts sont lus par `_defauts_du_code` — sur le CHAMP, ni sur le `.env`
    du poste ni sur l'environnement du lancement.
    """
    defauts = _defauts_du_code(monkeypatch)
    tous = {getattr(defauts, champ) for champ in Settings.model_fields}
    confondus = {
        champ: valeur for champ, valeur in _ATTENDU.items() if valeur in tous
    }
    assert not confondus, (
        f"valeur(s) attendue(s) égale(s) à un défaut du code : {confondus}. Une "
        "scène qui attend ce que le code écrirait de toute façon ne peut pas "
        "distinguer la variable de la constante."
    )
    assert defauts.llm_host != _HOTE and defauts.llm_model != _MODELE, (
        "l'hôte ou le modèle POSÉ par ce fichier est le défaut du code : la "
        "sonde serait alors mesurée exactement là où elle ne prouve rien"
    )


def test_les_deux_noms_de_modele_ne_s_apparient_pas_l_un_a_l_autre() -> None:
    """PREUVE D'ATTEINTE DES DOUBLES, et elle n'est pas décorative.

    L'appariement est un INFIXE après réduction, pas une égalité. Si le nom du
    modèle étranger était par accident infixe du nôtre, le double du serveur
    partagé cesserait de séparer quoi que ce soit et les scènes de
    mésconfiguration seraient vertes sur un code faux.
    """
    from src.api.main import _le_serveur_sert_ce_que_nous_demandons as apparie

    assert apparie(_MODELE, _MODELE), (
        "le double ne sert même pas ce que la scène demande : elle ne "
        "mesurerait alors qu'un relevé partiel"
    )
    assert not apparie(_MODELE_ETRANGER, _MODELE), (
        "le modèle d'une autre équipe s'apparie à ce que nous demandons : la "
        "scène ne sépare plus les deux serveurs"
    )


# ─── LA SCÈNE UNIQUE, JOUÉE SUR CHAQUE CHAMP ─────────────────────────────────


@pytest.mark.parametrize("champ", sorted(_ATTENDU))
def test_chaque_champ_du_releve_vient_du_serveur_interroge(
    monkeypatch: pytest.MonkeyPatch, champ: str
) -> None:
    """CHAQUE champ de la table. Une seule scène.

    C'est ici que meurent les trois survivantes de NB-2 : l'hôte interrogé, le
    modèle demandé et le modèle confronté. Et c'est ici que mourra la quatrième,
    sans qu'on ait à y penser — elle est dans la table, ou elle fait rougir le
    garde d'exhaustivité.
    """
    releve, _ = _releve(monkeypatch)
    assert releve is not None, (
        "la sonde n'a rien rendu : le double ne ressemble à aucun serveur réel, "
        "ou la sonde interroge le mauvais hôte"
    )
    assert getattr(releve, champ) == _ATTENDU[champ], (
        f"`/health` publie `moteur_llm.{champ} = {getattr(releve, champ)!r}` "
        f"quand le serveur interrogé dit {_ATTENDU[champ]!r}. Ce champ ne vient "
        "plus de ce qu'on a joint."
    )


def test_la_sonde_n_interroge_que_l_hote_du_dialecte(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'HÔTE INTERROGÉ, ASSERTÉ DIRECTEMENT ET NON PAR SES CONSÉQUENCES.

    `endpoint` dit quel hôte le relevé PUBLIE ; ceci dit quel hôte il a
    réellement JOINT. Les deux peuvent diverger — un relevé qui publie un hôte
    et en interroge un autre est exactement la panne de REPAR-18, où la sonde
    affirmait un fait sur un serveur qu'elle n'avait pas consulté.

    ET LE COÛT EST RÉEL : `vllm-central` appartient à l'équipe voisine. Une
    sonde qui part sur le mauvais hôte y tape à chaque battement de `/health`.
    """
    _, client = _releve(monkeypatch)
    assert client.demandes, "la sonde n'a interrogé aucun hôte : elle ne mesure rien"
    egares = [u for u in client.demandes if not u.startswith(_HOTE)]
    assert not egares, (
        f"la sonde a interrogé {egares} — l'hôte du dialecte est {_HOTE}. Un "
        "relevé pris sur un serveur auquel l'agent ne parle pas est une "
        "affirmation fausse, pas une absence."
    )


def test_le_releve_ne_coute_que_deux_requetes(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEUX, ET C'ÉTAIT TROIS AVANT LE LOT 28 — la version, puis le catalogue.

    La troisième était la route de version de l'autre moteur, essayée d'abord.
    Elle part avec lui. Ce compte a un site canonique, `_MOTEUR_REQUETES_MAX`, et
    cette scène le relit plutôt que de le recopier : deux chiffres qui doivent
    s'accorder finissent par diverger.

    Le coût n'est pas théorique : `/health` est battu toutes les 20 s contre un
    serveur PARTAGÉ avec deux autres équipes.
    """
    from src.api import main

    _, client = _releve(monkeypatch)
    assert len(client.demandes) == main._MOTEUR_REQUETES_MAX == 2, (
        f"le relevé a coûté {len(client.demandes)} requêtes "
        f"({client.demandes}) quand le site canonique en annonce "
        f"{main._MOTEUR_REQUETES_MAX}"
    )


def test_un_serveur_qui_sert_une_autre_equipe_ne_signe_pas_pour_nous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE RÉGLAGE POINTÉ VERS UN SERVEUR QUI RÉPOND ET NE NOUS SERT PAS.

    C'est le cas de ce poste, et il n'est pas théorique : `vllm-central` est
    partagé. Le serveur se déclare, sa version est lue — ce sont des faits, et ils
    sont relevés de lui — mais il ne sert pas le modèle que NOUS demandons.
    `modele_servi` doit donc être nul.

    Publier `entrees[0]["id"]` ferait signer une campagne sous le nom du modèle
    d'une autre équipe, mémorisé à vie : non bloquante §2 de l'audit du
    15 septembre 2026.
    """
    releve, _ = _releve(monkeypatch, reglages={"llm_host": _AUTRE_HOTE})
    assert releve is not None
    assert releve.serveur == "vllm", (
        "le discriminant doit rester relevé DU SERVEUR : ce serveur-là répond, "
        "et c'est un fait qu'un exploitant doit voir"
    )
    assert releve.modele_demande == _MODELE
    assert releve.modele_servi is None, (
        f"`modele_servi = {releve.modele_servi!r}` : ce serveur ne sert PAS ce "
        "que nous demandons, et le relevé l'affirme pourtant."
    )


def test_un_serveur_qui_ne_dit_pas_son_nom_laisse_le_releve_muet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE RELEVÉ NE DEVINE PAS, ET IL NE NOMME PLUS L'AUTRE MOTEUR.

    Avant le lot 28, un serveur qui ne répondait pas à la route de version de ce
    moteur-ci était interrogé sur celle de l'autre, et pouvait être NOMMÉ. Ce
    n'est plus possible : le dépôt ne supporte plus qu'un moteur, donc il ne sait
    plus reconnaître les autres — seulement dire que ce n'est pas celui-là.

    Ce que cette scène tient : le champ ENTIER est muet, et rien n'est inventé.
    Un relevé qui rangerait un serveur muet dans « vllm » serait une affirmation
    positive fausse, et elle serait mémorisée à vie.
    """
    muet = {_HOTE: {"/v1/models": _Reponse(200, {"data": [{"id": _MODELE}]})}}
    releve, client = _releve(monkeypatch, serveurs=muet)
    assert releve is None, (
        f"un serveur sans route de version a été rangé sous {releve!r} : le "
        "relevé devine au lieu de se taire"
    )
    assert client.demandes, "la sonde n'a rien interrogé : la scène ne mesure rien"


def test_le_releve_partiel_n_est_toujours_pas_memorise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'ACQUIS DE REPAR-18, PROUVÉ APRÈS CE LOT ET NON SUPPOSÉ.

    `_releve_est_complet` refuse de figer un relevé sans `modele_servi`. C'est ce
    qui empêche qu'un nom faux soit publié pour la vie du processus — et le prix
    est connu, écrit et journalisé : la sonde repart à chaque battement.
    """
    from src.api import main

    releve, _ = _releve(monkeypatch, reglages={"llm_host": _AUTRE_HOTE})
    assert releve is not None and releve.modele_servi is None
    assert main._moteur_releve is None, (
        "un relevé INCOMPLET a été mémorisé : il serait republié à l'identique "
        "pour toute la vie du processus, et `--compare` le lirait comme un fait"
    )


def test_l_endpoint_publie_reste_expurge_a_travers_le_releve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-7 : L'EXPURGATION N'ÉTAIT GARDÉE QUE SUR LA FONCTION, PAS SUR LE RELEVÉ.

    `_endpoint_expurge` a ses propres scènes ; ce qui n'en avait aucune est le
    fait que `/health` publie bien son RÉSULTAT et non l'hôte brut. **Ce dépôt
    est public et `runs/*.json` y est versionné** : un déploiement qui met des
    identifiants dans `LLM_HOST` les verrait recopiés dans une campagne commitée.
    Le sujet n'est pas neutre, et il ne se garde pas par lecture.

    Le mot de passe de cette scène est FABRIQUÉ pour elle et ne désigne aucun
    secret de ce poste.
    """
    hote_avec_secret = "http://exploitant:mot-de-passe-fabrique@serveur-d-essai:8000"
    releve, _ = _releve(
        monkeypatch,
        reglages={"llm_host": hote_avec_secret},
        serveurs={**_SERVEURS, hote_avec_secret: _routes(_MODELE)},
    )
    assert releve is not None, "le double n'a pas répondu : la scène ne mesure rien"
    assert releve.endpoint == _HOTE
    assert "mot-de-passe-fabrique" not in (releve.endpoint or ""), (
        "l'endpoint publié par `/health` porte le secret de l'URL du serveur, "
        "et `runs/*.json` est versionné dans un dépôt public"
    )


# ─── LES TROIS SITES QUI PUBLIENT LE MODÈLE DEMANDÉ ──────────────────────────
#
# NB-3 : `/health` le publie DEUX fois, et `usage.configuration()` une
# troisième. Un seul des trois était gardé.
#
# POURQUOI GARDER L'ACCORD PLUTÔT QUE SUPPRIMER LA DUPLICATION, et le choix est
# mesuré, pas confortable. Les trois clés ont des LECTEURS :
#
#   - `/health` racine `llm_model` est listé comme clé publique du contrat dans
#     `documentation/moteur_llm.md` (§ « clés de /health ») ;
#   - `moteur_llm.modele_demande` est lu par `scripts/evaluate.py`, qui en fait
#     une ligne de `--compare` (`_CHAMPS_DU_MOTEUR`) ;
#   - `usage.configuration()["llm_model"]` est lu par une requête SQL PUBLIÉE
#     dans `documentation/capture_usage.md`, et il entre dans `config_hash`.
#
# Supprimer l'une des trois est donc un changement de contrat envers des
# lecteurs hors de ce dépôt, pour un gain qu'un garde d'accord donne sans le
# coût. Ce qui ne se défendait pas était de laisser la promesse dépasser le
# garde : c'est cela qui est fermé ici.


def test_les_trois_sites_du_modele_demande_s_accordent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trois publications du même fait, confrontées DANS LE MÊME ÉTAT.

    Une régression sur l'un des trois les ferait diverger — deux modèles demandés
    différents dans la même réponse `/health`, et une campagne enregistrée sous
    une empreinte qui n'est pas la sienne.

    Le modèle est POSÉ hors du défaut : un site qui lirait le défaut du champ au
    lieu du dialecte rougit ici.
    """
    from src.agent import usage
    from src.api import main

    monkeypatch.setattr(settings, "llm_host", _HOTE)
    monkeypatch.setattr(settings, "llm_model", _MODELE)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_moteur_releve", None)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_k: _Poste(_SERVEURS))

    reponse = asyncio.run(main.health())

    assert reponse.llm_model == _MODELE, (
        f"`/health` publie `llm_model = {reponse.llm_model!r}` : il annonce un "
        "modèle que personne n'a demandé"
    )
    assert reponse.moteur_llm is not None, (
        "le relevé du moteur est muet dans cette scène : la confrontation des "
        "trois sites ne mesure alors que deux d'entre eux"
    )
    assert reponse.moteur_llm.modele_demande == reponse.llm_model, (
        f"LA MÊME RÉPONSE `/health` annonce DEUX modèles demandés : "
        f"`llm_model = {reponse.llm_model!r}` et "
        f"`moteur_llm.modele_demande = {reponse.moteur_llm.modele_demande!r}`. "
        "Deux endroits qui doivent s'accorder finissent par diverger — c'est la "
        "leçon du lot 19, et ici la divergence se lit par un exploitant."
    )
    # `configuration()` rend (empreinte, detail) : c'est le DÉTAIL qui porte la
    # clé, et l'empreinte n'en est que le condensat.
    _, detail = usage.configuration()
    assert detail["llm_model"] == _MODELE, (
        "l'empreinte qui REGROUPE les campagnes ne suit pas le modèle demandé : "
        "une campagne s'enregistrerait sous l'empreinte d'un autre moteur, et la "
        "comparaison appariée s'en servirait sans le savoir"
    )


# ─── UN RÉGLAGE N'EST JAMAIS ÉPROUVÉ À SA VALEUR PAR DÉFAUT ──────────────────
#
# NB-4, ET C'EST UNE FAMILLE, PAS UN CAS. `"num_ctx": settings.llm_num_ctx`
# remplacé par `"num_ctx": 8192` survivait aux 1035 tests : `llm_num_ctx` VAUT
# 8192, et les trois témoins comparaient à 8192 — l'un d'eux en monkeypatchant
# le réglage à SA PROPRE VALEUR PAR DÉFAUT. Aucune scène ne pouvait distinguer
# la variable de la constante, et toutes étaient vertes.
#
# La table ci-dessous donne à chaque réglage transmis une valeur d'épreuve, et
# `test_aucune_valeur_d_epreuve_n_est_la_valeur_par_defaut` refuse qu'elle soit
# le défaut. Un réglage neuf publié dans `options` sans valeur d'épreuve fait
# rougir le garde d'exhaustivité : là encore, il n'y a rien à penser à écrire
# deux fois.

_REGLAGES_EPROUVES: dict[str, Any] = {
    "llm_thinking": True,  # défaut : False
    "native_tool_calling": False,  # défaut : True
    "llm_temperature": 0.37,  # défaut : 0.1
    "llm_num_ctx": 16384,  # défaut : 8192
    "llm_max_tokens": 1234,  # défaut : 4096
}

# Le nom publié dans `moteur_llm.options` pour chaque réglage. C'est cette
# correspondance que le garde d'exhaustivité confronte au relevé réel.
_NOM_PUBLIE: dict[str, str] = {
    "llm_thinking": "thinking",
    "native_tool_calling": "outils_natifs",
    "llm_temperature": "temperature",
    "llm_num_ctx": "num_ctx",
    "llm_max_tokens": "max_tokens",
}


def test_aucune_valeur_d_epreuve_n_est_la_valeur_par_defaut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE GARDE DE LA FAMILLE, et il vaut pour tout réglage à venir.

    Un test qui monkeypatche un réglage à sa propre valeur par défaut ne mesure
    rien, et il a l'air vert. Les défauts sont lus par `_defauts_du_code` — sur
    le CHAMP, ni sur le `.env` du poste ni sur l'environnement du lancement, ce
    qui rendrait ce garde dépendant de la machine qui l'exécute.
    """
    defauts = _defauts_du_code(monkeypatch)
    confondus = {
        champ: valeur
        for champ, valeur in _REGLAGES_EPROUVES.items()
        if valeur == getattr(defauts, champ)
    }
    assert not confondus, (
        f"valeur(s) d'épreuve égale(s) au défaut du champ : {confondus}. Une "
        "scène qui pose un réglage à sa propre valeur par défaut ne peut pas "
        "distinguer la variable de la constante : c'est NB-4, et la mutation "
        "`settings.llm_num_ctx` → `8192` survivait à 1035 tests pour cela."
    )


def test_la_table_des_reglages_couvre_tout_ce_que_health_publie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un réglage publié sans valeur d'épreuve serait indiscernable d'une constante."""
    releve, _ = _releve(monkeypatch)
    assert releve is not None
    publies = set(releve.options)
    couverts = set(_NOM_PUBLIE.values())
    assert publies == couverts, (
        f"réglage(s) publié(s) par `moteur_llm.options` sans valeur d'épreuve : "
        f"{sorted(publies - couverts)} ; valeur(s) d'épreuve pour un réglage qui "
        f"n'est plus publié : {sorted(couverts - publies)}. Donne-lui une valeur "
        "DIFFÉRENTE de son défaut dans `_REGLAGES_EPROUVES`."
    )
    assert set(_REGLAGES_EPROUVES) == set(_NOM_PUBLIE)


@pytest.mark.parametrize("champ", sorted(_REGLAGES_EPROUVES))
def test_chaque_reglage_publie_est_celui_du_reglage_et_non_sa_constante(
    monkeypatch: pytest.MonkeyPatch, champ: str
) -> None:
    """`/health` publie la VALEUR DU RÉGLAGE, éprouvée hors de son défaut."""
    releve, _ = _releve(monkeypatch, reglages=_REGLAGES_EPROUVES)
    assert releve is not None
    publie = releve.options[_NOM_PUBLIE[champ]]
    assert publie == _REGLAGES_EPROUVES[champ], (
        f"`moteur_llm.options.{_NOM_PUBLIE[champ]}` vaut {publie!r} quand "
        f"`settings.{champ}` vaut {_REGLAGES_EPROUVES[champ]!r} : le champ est "
        "codé en dur, ou lu ailleurs que dans le réglage"
    )


def test_la_fenetre_publiee_est_le_reglage_et_non_huit_mille_cent_quatre_vingt_douze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LA SCÈNE QUI SÉPARE `settings.llm_num_ctx` DE LA CONSTANTE 8192.

    Le séparateur que l'audit a construit : `LLM_NUM_CTX=16384`.

    ELLE A CHANGÉ DE SITE AU LOT 28, ET PAS DE SUJET. Elle mesurait ce réglage
    dans la CHARGE envoyée au serveur ; le dialecte servi n'a pas de champ de
    fenêtre — l'y mettre le ferait ignorer en silence — et `LLM_NUM_CTX` est
    désormais un budget CLIENT. Ce qu'il commande encore et qui se voit de
    l'extérieur est ce que `/health` PUBLIE sous `options.num_ctx`, en regard de
    la fenêtre RÉELLEMENT servie. Un mutant qui y écrirait 8192 en dur ferait
    croire à un écart nul entre les deux, ou à un écart qui n'existe pas.
    """
    releve, _ = _releve(monkeypatch, reglages={"llm_num_ctx": _REGLAGES_EPROUVES["llm_num_ctx"]})
    assert releve is not None
    assert releve.options["num_ctx"] == _REGLAGES_EPROUVES["llm_num_ctx"], (
        f"`/health` publie `options.num_ctx = {releve.options['num_ctx']!r}` "
        f"quand `LLM_NUM_CTX` vaut {_REGLAGES_EPROUVES['llm_num_ctx']!r} : la "
        "fenêtre publiée est une CONSTANTE, et le réglage ne se lit plus"
    )
    assert releve.fenetre_servie == _FENETRE, (
        "la fenêtre SERVIE n'est plus celle du serveur : l'écart entre ce qu'on "
        "demande et ce qu'on sert cesse alors d'être visible"
    )


# ─── LE DÉLAI DE LECTURE DU FLUX, QUI N'ÉTAIT GARDÉ PAR RIEN ─────────────────


def test_le_delai_de_lecture_du_flux_n_est_pas_borne(monkeypatch: pytest.MonkeyPatch) -> None:
    """NB-7 : `read=None` EST CE QUI AUTORISE UN PREMIER TOKEN TARDIF.

    `httpx.Timeout(30.0, read=None)` borne la connexion, l'écriture et le pool à
    30 s et laisse la LECTURE sans borne : c'est ce qui permet à une génération
    dont le préfill s'exécute sur processeur de rendre son premier token après
    la trentième seconde. Le borner couperait ces générations-là, **et rien ne
    le dirait** — la ligne était présente à l'identique dans `main` avant le lot
    25, et sa mutation en `read=30.0` survivait aux 1035 tests.

    CE QUE CE GARDE MESURE, ET CE QU'IL NE MESURE PAS. Il assert la PROPRIÉTÉ
    « la lecture n'est pas bornée » sur l'objet que le poste de flux construit
    réellement, en l'interceptant à la frontière `httpx`. Il n'assert **aucun**
    des trois autres délais : les borner est une décision d'exploitation, et un
    garde qui épinglerait 30.0 rougirait sur un réglage légitime. Il ne mesure
    pas non plus une génération de plus de trente secondes — il faudrait un vrai
    préfill lent, et ce n'est pas un test unitaire.
    """
    import json as _json

    from src.agent import llm

    vus: list[Any] = []

    class _Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield _json.dumps({"message": {"content": "Réponse."}, "done": True})

    class _Stream:
        async def __aenter__(self) -> "_Resp":
            return _Resp()

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            vus.append(kwargs.get("timeout"))

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

        def stream(self, *_a: Any, **_k: Any) -> "_Stream":
            return _Stream()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)

    async def _consomme() -> None:
        async for _ in llm.generate_stream("Quelle est la cadence de purge ?", []):
            pass

    asyncio.run(_consomme())

    assert vus, (
        "le poste de flux n'a construit aucun client : ce garde ne mesure rien, "
        "et il serait vert quel que soit le délai"
    )
    delai = vus[0]
    assert delai is not None, "le client de flux est construit sans délai du tout"
    assert delai.read is None, (
        f"le délai de LECTURE du flux vaut {delai.read!r} au lieu d'être sans "
        "borne. Une génération dont le premier token tarde plus que cela est "
        "coupée, et rien dans le dépôt ne le disait : c'est NB-7 de l'audit du "
        "16 septembre 2026."
    )


# ─── LE SECOND POSTE D'OUTILLAGE, LUI AUSSI HORS DU SITE UNIQUE ─────────────


def test_la_traduction_du_balayage_poste_et_lit_dans_le_dialecte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-5, SECOND POSTE : `scripts/sweep_retrieval.py`.

    Il postait sa route en dur et lisait le corps dans le dialecte de l'ancien
    moteur. Pointé vers le serveur qui sert, il rendait `None` pour CHAQUE
    question — en silence, par `except Exception: return None` — et le balayage
    comparait ensuite ses configurations sur un jeu **sans aucune traduction**,
    en concluant. Une traduction manquante ne fait pas lever ce script : elle
    DÉPLACE le rappel translinguistique mesuré.

    Les DEUX moitiés sont éprouvées ici, parce qu'une seule ne suffit pas : le
    chemin POSTÉ (la charge part au bon endroit dans la bonne forme) et la
    réponse LUE (le corps du dialecte est compris). Un poste qui basculerait
    l'un sans l'autre serait muet de la même façon.
    """
    import importlib.util
    import pathlib

    chemin = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "sweep_retrieval.py"
    spec = importlib.util.spec_from_file_location("sweep_retrieval", chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    corps = {"choices": [{"message": {"content": "What is the purge rate of the collector?"}}]}
    postes: list[str] = []

    class _ReponsePost:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return corps

    # `json` OMBRE LE MODULE, et le nom est imposé : c'est celui du paramètre
    # de `httpx.post`, que ce double remplace. Le renommer ferait passer la
    # charge en positionnel et le double cesserait de ressembler à `httpx`.
    def _post(url: str, json: Any = None, **_k: Any) -> "_ReponsePost":  # noqa: A002
        postes.append(url)
        return _ReponsePost()

    monkeypatch.setattr(module.httpx, "post", _post)
    rendue = module.traduire(
        "Quelle est la cadence de purge du collecteur ?",
        "http://serveur-d-essai:8000",
        "modele-d-essai",
    )

    assert postes == ["http://serveur-d-essai:8000/v1/chat/completions"], (
        f"le balayage a posté sur {postes} : le chemin ne vient pas du site unique"
    )
    assert rendue == "What is the purge rate of the collector?", (
        "la réponse du serveur n'a pas été LUE et la traduction a été écartée "
        f"en silence. Pannes absorbées : {module._PANNES_DE_TRADUCTION}"
    )
