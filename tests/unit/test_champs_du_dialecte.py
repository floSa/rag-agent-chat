"""L'INVENTAIRE DES CHAMPS QUI DÉPENDENT DU DIALECTE, ET LA TABLE QUI LES TIENT.

LA CAUSE QUE CE FICHIER TRAITE, ET ELLE EST ÉCRITE PAR LE LOT 25 LUI-MÊME
-------------------------------------------------------------------------

> « UNE CAMPAGNE MENÉE SOUS LE DÉFAUT NE PEUT PAS MESURER CE QUI NE VARIE QU'À
> LA BASCULE. »

Le lot 25 l'a écrite après que trois de ses mutations eurent survécu. Son audit
indépendant l'a retournée contre lui et a trouvé **trois champs de plus** :
`_sonder_moteur_llm` prend l'hôte, le modèle demandé et le modèle confronté du
dialecte, et **aucune scène ne le vérifiait ailleurs que sous le défaut**, où
`dialecte.hote` EST `settings.ollama_host`. Trois mutations qui inversent la
décision du lot passaient les 1035 tests sans un rouge — NB-2 de
`documentation/audits/2026-09-16-audit-lot-25.md`, et les trois sont rejouées
mortes par la campagne de REPAR-26 au §4.61 du registre.

CE QUI EST FAIT ICI N'EST PAS TROIS SCÈNES DE PLUS
---------------------------------------------------

Trois scènes de plus refermeraient les trois champs connus et laisseraient le
QUATRIÈME s'ajouter en silence. Ce qui est posé ici est une **table dont
l'exhaustivité est gardée** : `_ATTENDU` donne, pour **chaque** champ de
`MoteurLlmHealth` et pour **chacun des deux dialectes**, la valeur que le relevé
doit porter. Quatre gardes la tiennent, et c'est leur conjonction qui rend
l'oubli impossible :

1. **elle est EXHAUSTIVE** — `test_la_table_couvre_tous_les_champs_du_releve`
   confronte ses clés à `MoteurLlmHealth.model_fields`. Un champ neuf au schéma
   qui n'est pas classé fait rougir, et le message dit quoi faire ;
2. **elle est PARITAIRE** — les deux dialectes portent exactement les mêmes
   clés. On ne peut pas décrire un champ d'un seul côté ;
3. **elle SÉPARE** — `test_la_table_separe_reellement_les_deux_dialectes` exige
   que la valeur attendue diffère entre les deux colonnes. C'est le garde
   anti-« mesuré sous le défaut » : une scène dont les deux côtés portent la
   même valeur ne mesure RIEN, et elle a l'air verte. C'est l'erreur exacte que
   `num_ctx` a payée (NB-4), où les trois témoins comparaient à 8192 quand le
   défaut du réglage vaut 8192 ;
4. **elle est JOUÉE** — une seule scène, paramétrée sur (champ × dialecte), lit
   la table. Ajouter une ligne suffit à ajouter deux scènes.

**LE POINT QUI COMPTE : IL N'Y A RIEN À ÉCRIRE DEUX FOIS.** La scène est unique
et jouée sous les deux dialectes ; ce qui varie est une entrée de table. C'est la
leçon du lot 19 appliquée à la MESURE elle-même — deux gardes qu'il faut penser
à écrire tous les deux finiront par diverger, exactement comme deux sites de
décision.

LE DOUBLE ROUTE PAR (HÔTE, CHEMIN), ET C'EST CE QUI REND M09 MORDANTE
----------------------------------------------------------------------

`_ClientSimule` de `test_moteur_llm.py` route sur le seul CHEMIN : il répond
donc identiquement à `serveur-ollama` et à `serveur-vllm`, et une sonde qui
interroge le mauvais hôte y reste invisible. Le double d'ici tient **deux
serveurs à deux adresses**, comme le poste réel en tient deux. Une sonde qui
part sur l'hôte d'Ollama en croyant parler à vLLM y reçoit les réponses
d'Ollama — et tout le relevé bascule, ce qui est exactement ce qui se passerait
en production. Un hôte qu'aucun serveur ne sert LÈVE, comme lèverait une vraie
connexion refusée.

CE FICHIER NE MESURE AUCUN INSTANTANÉ. Les versions, les noms et la fenêtre sont
ceux des doubles, jamais ceux des serveurs du poste : ce qui est asserté est la
RELATION « ce champ suit le dialecte », pas la valeur du jour.
"""

import asyncio
from typing import Any
from urllib.parse import urlsplit

import pytest

from src.agent.dialecte_llm import dialecte_courant
from src.agent.settings import Settings, settings
from src.api.schemas import MoteurLlmHealth


@pytest.fixture(autouse=True)
def _base_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pose EXPLICITEMENT le dialecte d'Ollama comme base de ce fichier.

    Ces scènes héritaient du défaut de `LLM_ENGINE`, qui valait `ollama`. Le
    défaut décrit désormais ce qui est SERVI — vLLM —, et vingt-quatre scènes
    sont devenues rouges d'un coup : elles ne DEMANDAIENT pas le dialecte
    qu'elles mesuraient, elles le SUPPOSAIENT.

    Une scène qui veut le dialecte d'Ollama le demande, comme les scènes vLLM
    posent déjà le leur. Celles-ci surchargent cette fixture après elle, et rien
    ne change pour elles.
    """
    monkeypatch.setattr(settings, "llm_engine", "ollama")


# ─── Les deux postes de la scène, DISJOINTS SUR TOUT ─────────────────────────
#
# Hôtes, ports et noms de modèle sont distincts des deux côtés. C'est la
# condition pour qu'une mutation qui confond les deux réglages SE VOIE : sous
# `OLLAMA_HOST == VLLM_HOST`, `hote = settings.ollama_host` serait strictement
# équivalent au code servi, et la scène serait verte sur un code faux.
_HOTE = {"ollama": "http://serveur-ollama:11434", "vllm": "http://serveur-vllm:8000"}

# LES DEUX NOMS SONT CHOISIS POUR QUE L'APPARIEMENT LES SÉPARE, et ce n'est pas
# cosmétique : `_le_serveur_sert_ce_que_nous_demandons` apparie par INFIXE après
# réduction (voir son site). Réduits, ils donnent `moteurollamae4b` et
# `orgmoteurvllme4bw4a16` — aucun n'est infixe de l'autre, donc demander l'un au
# serveur de l'autre rend bien `modele_servi: None`.
# `test_les_deux_noms_de_modele_ne_s_apparient_pas_l_un_a_l_autre` le vérifie
# plutôt que de le croire sur parole.
_MODELE = {"ollama": "moteur-ollama:e4b", "vllm": "org/moteur-vllm-e4b-w4a16"}

_VERSION = {"ollama": "0.30.10", "vllm": "0.28.0"}
_EMPREINTE_COMPLETE = "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb"
_FENETRE_VLLM = 32768


# ─── LA TABLE, ET C'EST ELLE QUE CE FICHIER EXISTE POUR TENIR ────────────────
#
# Chaque champ du relevé, sous chaque dialecte, et la valeur que le relevé doit
# porter quand la bascule est faite ET que le serveur d'en face est celui que le
# réglage désigne. C'est le seul endroit à modifier quand un champ s'ajoute.
_ATTENDU: dict[str, dict[str, Any]] = {
    "ollama": {
        "serveur": "ollama",
        "endpoint": _HOTE["ollama"],
        "version": _VERSION["ollama"],
        "modele_demande": _MODELE["ollama"],
        "modele_servi": _MODELE["ollama"],
        "empreinte_du_modele": _EMPREINTE_COMPLETE[:16],
        "quantification": "Q4_K_M",
        "fenetre_servie": None,
    },
    "vllm": {
        "serveur": "vllm",
        "endpoint": _HOTE["vllm"],
        "version": _VERSION["vllm"],
        "modele_demande": _MODELE["vllm"],
        "modele_servi": _MODELE["vllm"],
        # vLLM ne publie NI empreinte de poids NI quantification en champ : c'est
        # une borne mesurée sur les sept routes GET de l'instance de ce poste, et
        # elle est écrite au site de `MoteurLlmHealth.empreinte_du_modele`.
        "empreinte_du_modele": None,
        "quantification": None,
        "fenetre_servie": _FENETRE_VLLM,
    },
}

# CE QUI NE SUIT PAS LE DIALECTE, ET POURQUOI — la seconde moitié de la
# partition. Un champ est dans l'une ou dans l'autre, jamais dans les deux ni
# dans aucune, et le garde d'exhaustivité l'exige.
_INVARIANTS_DU_DIALECTE: dict[str, str] = {
    # NOS drapeaux d'appel : ils viennent de `settings`, pas du dialecte. Leur
    # propre lacune — n'être mesurés qu'à leur valeur PAR DÉFAUT — est traitée
    # plus bas, par `_REGLAGES_EPROUVES` et son garde.
    "options": "du réglage, pas du dialecte",
    # L'instant du relevé : il ne dépend ni du moteur ni du serveur joint.
    "releve_le": "l'instant de la mesure",
}


# ─── Le double : DEUX serveurs, à DEUX adresses ──────────────────────────────


class _Reponse:
    def __init__(self, code: int, charge: Any) -> None:
        self.status_code, self._charge = code, charge

    def json(self) -> Any:
        return self._charge


_ROUTES_OLLAMA: dict[str, _Reponse] = {
    "/api/version": _Reponse(200, {"version": _VERSION["ollama"]}),
    "/api/tags": _Reponse(
        200,
        {
            "models": [
                {
                    "name": _MODELE["ollama"],
                    "model": _MODELE["ollama"],
                    "digest": _EMPREINTE_COMPLETE,
                    "details": {"quantization_level": "Q4_K_M"},
                }
            ]
        },
    ),
}

# `/api/version` est ABSENTE, et c'est le fait qui discrimine : le vrai
# `vllm-central` y rend 404 (`mesuré` le 15 septembre 2026). Un double qui y
# répondrait ferait conclure « ollama » sur un serveur vLLM.
_ROUTES_VLLM: dict[str, _Reponse] = {
    "/version": _Reponse(200, {"version": _VERSION["vllm"]}),
    "/v1/models": _Reponse(
        200, {"data": [{"id": _MODELE["vllm"], "max_model_len": _FENETRE_VLLM}]}
    ),
}

_SERVEURS: dict[str, dict[str, _Reponse]] = {
    _HOTE["ollama"]: _ROUTES_OLLAMA,
    _HOTE["vllm"]: _ROUTES_VLLM,
}


class _DeuxServeurs:
    """Le poste, avec ses DEUX serveurs d'inférence à leurs DEUX adresses.

    Router sur le seul chemin rendrait `hote = settings.ollama_host` invisible :
    les deux hôtes répondraient pareil. Ici, se tromper d'hôte fait recevoir les
    réponses de l'autre serveur — ce qui est le comportement réel.
    """

    def __init__(self, serveurs: dict[str, dict[str, _Reponse]]) -> None:
        self.serveurs = serveurs
        self.demandes: list[str] = []

    async def __aenter__(self) -> "_DeuxServeurs":
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


def _releve_sous(
    monkeypatch: pytest.MonkeyPatch,
    moteur: str,
    *,
    reglages: dict[str, Any] | None = None,
    serveurs: dict[str, dict[str, _Reponse]] | None = None,
) -> tuple[Any, _DeuxServeurs]:
    """Joue la sonde de `/health` sous UN dialecte, contre le poste à deux serveurs.

    LES QUATRE RÉGLAGES DES DEUX MOTEURS SONT POSÉS QUEL QUE SOIT LE MOTEUR
    ÉPROUVÉ, et c'est ce qui fait mesurer : une mutation vers `settings.ollama_*`
    y désigne une valeur EXISTANTE et DIFFÉRENTE, donc elle produit un relevé
    faux plutôt qu'une panne. Un mutant qui lève n'apprend rien sur le garde.

    `reglages` surcharge ensuite, pour les scènes de mésconfiguration.
    """
    from src.api import main

    monkeypatch.setattr(settings, "ollama_host", _HOTE["ollama"])
    monkeypatch.setattr(settings, "ollama_model", _MODELE["ollama"])
    monkeypatch.setattr(settings, "vllm_host", _HOTE["vllm"])
    monkeypatch.setattr(settings, "vllm_model", _MODELE["vllm"])
    monkeypatch.setattr(settings, "llm_engine", moteur)
    for champ, valeur in (reglages or {}).items():
        monkeypatch.setattr(settings, champ, valeur)
    monkeypatch.setattr(main, "_moteur_releve", None)
    client = _DeuxServeurs(serveurs if serveurs is not None else _SERVEURS)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_k: client)
    return asyncio.run(main._sonder_moteur_llm()), client


# ─── LES GARDES DE LA TABLE ──────────────────────────────────────────────────


def test_la_table_couvre_tous_les_champs_du_releve() -> None:
    """LE GARDE QUI REND L'OUBLI IMPOSSIBLE, et c'est le cœur de ce fichier.

    Un champ ajouté à `MoteurLlmHealth` sans être classé fait rougir ici. Le
    geste attendu au rouge n'est pas d'élargir ce test : c'est de dire, dans
    `_ATTENDU` ou dans `_INVARIANTS_DU_DIALECTE`, ce que ce champ vaut de chaque
    côté de la bascule. C'est précisément la question que personne n'avait posée
    aux trois champs de NB-2.
    """
    du_schema = set(MoteurLlmHealth.model_fields)
    classes = set(_ATTENDU["ollama"]) | set(_INVARIANTS_DU_DIALECTE)
    assert classes == du_schema, (
        f"champ(s) de `MoteurLlmHealth` non classé(s) : {sorted(du_schema - classes)} ; "
        f"champ(s) classé(s) qui n'existe(nt) plus : {sorted(classes - du_schema)}. "
        "Tout champ du relevé doit dire ce qu'il vaut SOUS LES DEUX DIALECTES "
        "(`_ATTENDU`) ou pourquoi il n'en dépend pas (`_INVARIANTS_DU_DIALECTE`). "
        "Trois champs ont vécu non gardés parce que personne ne leur avait posé "
        "la question — NB-2 de l'audit du 16 septembre 2026."
    )
    assert not (set(_ATTENDU["ollama"]) & set(_INVARIANTS_DU_DIALECTE)), (
        "un champ est à la fois déclaré dépendant du dialecte et invariant : la "
        "partition n'en est plus une, et l'exhaustivité ne prouve plus rien"
    )


def test_la_table_decrit_les_deux_dialectes_a_parite() -> None:
    """Un champ décrit d'un seul côté ne mesure pas la bascule : il mesure un état."""
    assert set(_ATTENDU) == {"ollama", "vllm"}
    assert set(_ATTENDU["ollama"]) == set(_ATTENDU["vllm"]), (
        "les deux colonnes de `_ATTENDU` ne portent pas les mêmes champs : "
        f"{sorted(set(_ATTENDU['ollama']) ^ set(_ATTENDU['vllm']))}"
    )


def test_la_table_separe_reellement_les_deux_dialectes() -> None:
    """LE GARDE ANTI-« MESURÉ SOUS LE DÉFAUT », posé sur la table elle-même.

    Une scène dont les deux côtés portent la même valeur pour un champ ne peut
    pas distinguer le code servi d'un mutant qui ignore le dialecte : elle est
    verte, et elle ne mesure rien.

    Ce garde l'interdit AU NIVEAU DE LA TABLE, donc avant qu'une scène soit
    écrite : si un champ neuf ne peut honnêtement pas différer entre les deux
    dialectes, sa place est dans `_INVARIANTS_DU_DIALECTE`, avec sa raison.
    """
    confondus = [c for c in _ATTENDU["ollama"] if _ATTENDU["ollama"][c] == _ATTENDU["vllm"][c]]
    assert not confondus, (
        f"champ(s) portant la MÊME valeur attendue sous les deux dialectes : "
        f"{confondus}. Une mutation qui ignore le dialecte y resterait "
        "invisible. Donne-leur deux valeurs distinctes, ou classe-les dans "
        "`_INVARIANTS_DU_DIALECTE` avec la raison."
    )


def test_les_deux_noms_de_modele_ne_s_apparient_pas_l_un_a_l_autre() -> None:
    """PREUVE D'ATTEINTE DES DOUBLES, et elle n'est pas décorative.

    L'appariement de vLLM est un INFIXE après réduction, pas une égalité. Si le
    nom d'Ollama était par accident infixe du nom vLLM, la mutation « apparier
    sur `settings.ollama_model` » rendrait le MÊME `modele_servi` que le code
    servi, et le garde de NB-2 serait vert sur un code faux.
    """
    from src.api.main import _le_serveur_sert_ce_que_nous_demandons as apparie

    assert apparie(_MODELE["vllm"], _MODELE["vllm"]), (
        "le double vLLM ne sert même pas ce que la scène demande : elle ne "
        "mesurerait alors qu'un relevé partiel"
    )
    assert not apparie(_MODELE["vllm"], _MODELE["ollama"]), (
        "le nom d'Ollama s'apparie à l'entrée vLLM : la scène ne sépare plus "
        "les deux réglages"
    )


# ─── LA SCÈNE UNIQUE, JOUÉE SOUS LES DEUX DIALECTES ──────────────────────────


@pytest.mark.parametrize("moteur", ["ollama", "vllm"])
@pytest.mark.parametrize("champ", sorted(_ATTENDU["ollama"]))
def test_chaque_champ_du_releve_suit_le_dialecte(
    monkeypatch: pytest.MonkeyPatch, champ: str, moteur: str
) -> None:
    """CHAQUE champ de la table, sous CHAQUE dialecte. Une seule scène.

    C'est ici que meurent les trois survivantes de NB-2 : l'hôte interrogé, le
    modèle demandé et le modèle confronté. Et c'est ici que mourra la quatrième,
    sans qu'on ait à y penser — elle est dans la table, ou elle fait rougir le
    garde d'exhaustivité.
    """
    releve, _ = _releve_sous(monkeypatch, moteur)
    assert releve is not None, (
        f"la sonde n'a rien rendu sous `LLM_ENGINE={moteur}` : le double ne "
        "ressemble à aucun serveur réel, ou la sonde interroge le mauvais hôte"
    )
    assert getattr(releve, champ) == _ATTENDU[moteur][champ], (
        f"sous `LLM_ENGINE={moteur}`, `/health` publie "
        f"`moteur_llm.{champ} = {getattr(releve, champ)!r}` quand le dialecte "
        f"désigne {_ATTENDU[moteur][champ]!r}. Ce champ ne suit plus la bascule."
    )


@pytest.mark.parametrize("moteur", ["ollama", "vllm"])
def test_la_sonde_n_interroge_que_l_hote_du_dialecte(
    monkeypatch: pytest.MonkeyPatch, moteur: str
) -> None:
    """L'HÔTE INTERROGÉ, ASSERTÉ DIRECTEMENT ET NON PAR SES CONSÉQUENCES.

    `endpoint` dit quel hôte le relevé PUBLIE ; ceci dit quel hôte il a
    réellement JOINT. Les deux peuvent diverger — un relevé qui publie un hôte
    et en interroge un autre est exactement la panne de REPAR-18, où la sonde
    affirmait un fait sur un serveur qu'elle n'avait pas consulté.

    ET LE COÛT EST RÉEL : `vllm-central` appartient à l'équipe voisine. Une
    sonde qui part sur le mauvais hôte y tape à chaque battement de `/health`.
    """
    _, client = _releve_sous(monkeypatch, moteur)
    assert client.demandes, "la sonde n'a interrogé aucun hôte : elle ne mesure rien"
    egares = [u for u in client.demandes if not u.startswith(_HOTE[moteur])]
    assert not egares, (
        f"sous `LLM_ENGINE={moteur}`, la sonde a interrogé {egares} — l'hôte du "
        f"dialecte est {_HOTE[moteur]}. Un relevé pris sur un serveur auquel "
        "l'agent ne parle plus est une affirmation fausse, pas une absence."
    )


def test_une_mesconfiguration_ne_se_rattrape_pas_sur_l_autre_reglage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LLM_ENGINE=vllm` POINTÉ VERS UN OLLAMA : le relevé doit le DIRE.

    Le séparateur que l'audit du 16 septembre 2026 a raisonné sans le jouer
    (sa mutation M15). Le serveur se déclare Ollama — c'est un fait, et il est
    relevé de lui —, mais il ne porte pas le modèle que NOUS demandons, qui est
    `VLLM_MODEL`. `modele_servi` doit donc être nul.

    Apparier sur `settings.ollama_model` ferait publier `modele_servi` = le
    modèle d'Ollama sur un relevé dont `modele_demande` est celui de vLLM : deux
    champs qui se contredisent dans la même réponse, et un relevé mémorisé à vie
    sous un nom que personne n'a demandé. REPAR-18 a payé exactement cette
    phrase-là, dans l'autre sens.
    """
    releve, _ = _releve_sous(monkeypatch, "vllm", reglages={"vllm_host": _HOTE["ollama"]})
    assert releve is not None
    assert releve.serveur == "ollama", (
        "le discriminant doit rester relevé DU SERVEUR : c'est ce qu'un "
        "exploitant a besoin de voir quand son réglage désigne l'autre moteur"
    )
    assert releve.modele_demande == _MODELE["vllm"]
    assert releve.modele_servi is None, (
        f"`modele_servi = {releve.modele_servi!r}` : ce serveur ne sert PAS ce "
        "que nous demandons, et le relevé l'affirme pourtant."
    )


def test_le_releve_partiel_n_est_toujours_pas_memorise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'ACQUIS DE REPAR-18, PROUVÉ APRÈS CE LOT ET NON SUPPOSÉ.

    `_releve_est_complet` refuse de figer un relevé sans `modele_servi`. C'est ce
    qui empêche qu'un nom faux soit publié pour la vie du processus — et le prix
    est connu, écrit et journalisé : la sonde repart à chaque battement.

    REPAR-26 ne touche pas ce prédicat ; ce test le prouve encore debout après
    lui, plutôt que de l'affirmer.
    """
    from src.api import main

    releve, _ = _releve_sous(monkeypatch, "vllm", reglages={"vllm_host": _HOTE["ollama"]})
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
    identifiants dans `OLLAMA_HOST` les verrait recopiés dans une campagne
    commitée. Le sujet n'est pas neutre, et il ne se garde pas par lecture.

    Le mot de passe de cette scène est FABRIQUÉ pour elle et ne désigne aucun
    secret de ce poste.
    """
    hote_avec_secret = "http://exploitant:mot-de-passe-fabrique@serveur-ollama:11434"
    releve, _ = _releve_sous(
        monkeypatch,
        "ollama",
        reglages={"ollama_host": hote_avec_secret},
        serveurs={**_SERVEURS, hote_avec_secret: _ROUTES_OLLAMA},
    )
    assert releve is not None, "le double n'a pas répondu : la scène ne mesure rien"
    assert releve.endpoint == _HOTE["ollama"]
    assert "mot-de-passe-fabrique" not in (releve.endpoint or ""), (
        "l'endpoint publié par `/health` porte le secret de l'URL du serveur, "
        "et `runs/*.json` est versionné dans un dépôt public"
    )


# ─── LES TROIS SITES QUI PUBLIENT LE MODÈLE DEMANDÉ ──────────────────────────
#
# NB-3 : `/health` le publie DEUX fois, et `usage.configuration()` une
# troisième. Un seul des trois était gardé à la bascule.
#
# POURQUOI GARDER L'ACCORD PLUTÔT QUE SUPPRIMER LA DUPLICATION, et le choix est
# mesuré, pas confortable. Les trois clés ont des LECTEURS :
#
#   - `/health` racine `ollama_model` est listé comme clé publique du contrat
#     dans `documentation/moteur_llm.md` (§ « clés de /health ») ;
#   - `moteur_llm.modele_demande` est lu par `scripts/evaluate.py`, qui en fait
#     une ligne de `--compare` (`_CHAMPS_DU_MOTEUR`) ;
#   - `usage.configuration()["ollama_model"]` est lu par une requête SQL
#     PUBLIÉE dans `documentation/capture_usage.md`, et son NOM est délibérément
#     conservé pour ne pas dégrouper les campagnes déjà dans `runs/`.
#
# Supprimer l'une des trois est donc un changement de contrat envers des
# lecteurs hors de ce dépôt, pour un gain qu'un garde d'accord donne sans le
# coût. Ce qui ne se défendait pas était de laisser la promesse dépasser le
# garde : c'est cela qui est fermé ici.


@pytest.mark.parametrize("moteur", ["ollama", "vllm"])
def test_les_trois_sites_du_modele_demande_s_accordent(
    monkeypatch: pytest.MonkeyPatch, moteur: str
) -> None:
    """Trois publications du même fait, confrontées DANS LE MÊME ÉTAT.

    Sous `LLM_ENGINE=vllm`, une régression sur l'un des trois les ferait
    diverger — deux modèles demandés différents dans la même réponse `/health`,
    et une campagne enregistrée sous une empreinte qui n'est pas la sienne.
    """
    from src.agent import usage
    from src.api import main

    monkeypatch.setattr(settings, "ollama_host", _HOTE["ollama"])
    monkeypatch.setattr(settings, "ollama_model", _MODELE["ollama"])
    monkeypatch.setattr(settings, "vllm_host", _HOTE["vllm"])
    monkeypatch.setattr(settings, "vllm_model", _MODELE["vllm"])
    monkeypatch.setattr(settings, "llm_engine", moteur)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_moteur_releve", None)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_k: _DeuxServeurs(_SERVEURS))

    reponse = asyncio.run(main.health())
    attendu = _MODELE[moteur]

    assert reponse.ollama_model == attendu, (
        f"`/health` publie `ollama_model = {reponse.ollama_model!r}` sous "
        f"`LLM_ENGINE={moteur}` : il annonce un modèle que personne n'a demandé"
    )
    assert reponse.moteur_llm is not None, (
        "le relevé du moteur est muet dans cette scène : la confrontation des "
        "trois sites ne mesure alors que deux d'entre eux"
    )
    assert reponse.moteur_llm.modele_demande == reponse.ollama_model, (
        f"LA MÊME RÉPONSE `/health` annonce DEUX modèles demandés : "
        f"`ollama_model = {reponse.ollama_model!r}` et "
        f"`moteur_llm.modele_demande = {reponse.moteur_llm.modele_demande!r}`. "
        "Deux endroits qui doivent s'accorder finissent par diverger — c'est la "
        "leçon du lot 19, et ici la divergence se lit par un exploitant."
    )
    # `configuration()` rend (empreinte, detail) : c'est le DÉTAIL qui porte la
    # clé, et l'empreinte n'en est que le condensat.
    _, detail = usage.configuration()
    assert detail["ollama_model"] == attendu, (
        "l'empreinte qui REGROUPE les campagnes ne suit pas le moteur : une "
        "campagne menée sous vLLM s'enregistrerait sous l'empreinte d'Ollama, "
        "et la comparaison appariée s'en servirait sans le savoir"
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


def test_aucune_valeur_d_epreuve_n_est_la_valeur_par_defaut() -> None:
    """LE GARDE DE LA FAMILLE, et il vaut pour tout réglage à venir.

    Un test qui monkeypatche un réglage à sa propre valeur par défaut ne mesure
    rien, et il a l'air vert. Les défauts sont lus sur `Settings(_env_file=None)`
    — donc sur le CHAMP, jamais sur le `.env` du poste, qui n'est pas versionné
    et rendrait ce garde dépendant de la machine qui l'exécute.
    """
    defauts = Settings(_env_file=None)
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
    releve, _ = _releve_sous(monkeypatch, "ollama")
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
    releve, _ = _releve_sous(monkeypatch, "ollama", reglages=_REGLAGES_EPROUVES)
    assert releve is not None
    publie = releve.options[_NOM_PUBLIE[champ]]
    assert publie == _REGLAGES_EPROUVES[champ], (
        f"`moteur_llm.options.{_NOM_PUBLIE[champ]}` vaut {publie!r} quand "
        f"`settings.{champ}` vaut {_REGLAGES_EPROUVES[champ]!r} : le champ est "
        "codé en dur, ou lu ailleurs que dans le réglage"
    )


def test_la_fenetre_demandee_a_ollama_est_le_reglage_et_non_huit_mille_cent_quatre_vingt_douze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LA SCÈNE QUI SÉPARE `settings.llm_num_ctx` DE LA CONSTANTE 8192.

    Le séparateur que l'audit a construit : `LLM_NUM_CTX=16384`. Le code servi
    envoie alors `options.num_ctx = 16384` à Ollama ; le mutant envoie 8192, et
    `LLM_NUM_CTX` cesse silencieusement d'être transmis au serveur — la fenêtre
    dépend alors de l'`OLLAMA_CONTEXT_LENGTH` du serveur, qui diffère entre
    l'Ollama embarqué et le service central. Le même prompt donnerait deux
    comportements, ce que ce champ existe précisément pour empêcher.
    """
    monkeypatch.setattr(settings, "llm_num_ctx", _REGLAGES_EPROUVES["llm_num_ctx"])
    charge = dialecte_courant().charge(
        [{"role": "user", "content": "Quelle est la cadence de purge du collecteur ?"}],
        stream=True,
        temperature=0.1,
        max_tokens=4096,
        thinking=False,
    )
    assert charge["options"]["num_ctx"] == _REGLAGES_EPROUVES["llm_num_ctx"], (
        f"la charge d'Ollama porte `num_ctx = {charge['options']['num_ctx']!r}` "
        f"quand `LLM_NUM_CTX` vaut {_REGLAGES_EPROUVES['llm_num_ctx']!r} : la "
        "fenêtre demandée est une CONSTANTE, et le réglage ne part plus"
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


@pytest.mark.parametrize("moteur", ["ollama", "vllm"])
def test_la_traduction_du_balayage_poste_et_lit_dans_le_dialecte(
    monkeypatch: pytest.MonkeyPatch, moteur: str
) -> None:
    """NB-5, SECOND POSTE : `scripts/sweep_retrieval.py`.

    Il postait `/api/chat` en dur et lisait `message.content` à la racine.
    Pointé vers un serveur vLLM, il rendait `None` pour CHAQUE question — en
    silence, par `except Exception: return None` — et le balayage comparait
    ensuite ses configurations sur un jeu **sans aucune traduction**, en
    concluant. Une traduction manquante ne fait pas lever ce script : elle
    DÉPLACE le rappel translinguistique mesuré.

    Les DEUX moitiés sont éprouvées ici, parce qu'une seule ne suffit pas : le
    chemin POSTÉ (la charge part au bon endroit dans la bonne forme) et la
    réponse LUE (le corps du dialecte est compris). Un poste qui basculerait
    l'un sans l'autre serait muet de la même façon.
    """
    import importlib.util
    import pathlib

    from src.agent.settings import settings as reglages

    chemin = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "sweep_retrieval.py"
    spec = importlib.util.spec_from_file_location("sweep_retrieval", chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(reglages, "llm_engine", moteur)
    corps = {
        "ollama": {"message": {"content": "What is the purge rate of the collector?"}},
        "vllm": {"choices": [{"message": {"content": "What is the purge rate of the collector?"}}]},
    }[moteur]
    postes: list[str] = []

    class _Reponse:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return corps

    # `json` OMBRE LE MODULE, et le nom est imposé : c'est celui du paramètre
    # de `httpx.post`, que ce double remplace. Le renommer ferait passer la
    # charge en positionnel et le double cesserait de ressembler à `httpx`.
    def _post(url: str, json: Any = None, **_k: Any) -> "_Reponse":  # noqa: A002
        postes.append(url)
        return _Reponse()

    monkeypatch.setattr(module.httpx, "post", _post)
    rendue = module.traduire(
        "Quelle est la cadence de purge du collecteur ?",
        "http://serveur-d-essai:11434",
        "modele-d-essai",
    )

    chemin_attendu = "/api/chat" if moteur == "ollama" else "/v1/chat/completions"
    assert postes == [f"http://serveur-d-essai:11434{chemin_attendu}"], (
        f"sous `LLM_ENGINE={moteur}`, le balayage a posté sur {postes} : le "
        "chemin ne suit pas le dialecte"
    )
    assert rendue == "What is the purge rate of the collector?", (
        f"sous `LLM_ENGINE={moteur}`, la réponse du serveur n'a pas été LUE et "
        f"la traduction a été écartée en silence. Pannes absorbées : "
        f"{module._PANNES_DE_TRADUCTION}"
    )
