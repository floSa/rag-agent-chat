"""Le moteur LLM consigné dans les artefacts de campagne, et son garde.

POURQUOI CETTE CLÉ EXISTE. Le banc go/no-go de la bascule vers vLLM
(`documentation/audits/2026-09-15-banc-go-no-go-vllm.md`, §7) a conclu NO-GO sur
la seule question de la qualité, et pas parce que vLLM aurait démérité : **rien
dans `runs/` ne consignait le moteur LLM**. Aucune campagne au disque n'était
donc comparable à une campagne d'après la bascule — on n'aurait pas su si un
écart venait du moteur ou d'autre chose. `mesuré` le 15 septembre 2026 à
15:26 UTC : **19 campagnes sur 19** dans `runs/`, **zéro** portant la clé.

LES QUATRE PROPRIÉTÉS TENUES ICI, et elles viennent du précédent de la clé
`peripherique` :

1. **il SIGNALE, il ne REFUSE pas** — refuser interdirait la comparaison entre
   moteurs, qui est exactement le geste pour lequel cette clé a été demandée ;
2. **trois positions, et `muet` n'est PAS `différent`** — `identique` est
   IMPRIMÉ, sans quoi un silence se lirait comme un accord ;
3. **`--compare` voit une discordance de moteur** comme il voit déjà une
   discordance de périphérique ;
4. **un antécédent antérieur à ce lot est `muet`** — et le dit.

CE QUI EST ASSERTÉ EST LA PROPRIÉTÉ, JAMAIS L'INSTANTANÉ. Aucun test ici
n'épingle « ollama 0.30.10 » ni « vLLM 0.28.0 » : ces deux versions seront
fausses au prochain redémarrage du poste. Ce sont les relations qui sont tenues
— fait contre réglage, muet contre différent, signalement contre refus.
"""

import asyncio
import importlib.util
import io
import json
import pathlib
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"


def _evaluate() -> Any:
    """Charge `scripts/evaluate.py` sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _moteur(**ecarts: Any) -> dict[str, Any]:
    """Un relevé de moteur plausible, que chaque test déforme sur UN point.

    Les valeurs sont celles qu'un serveur rend vraiment, mais **aucun test
    n'assied quoi que ce soit sur elles** : elles sont un décor sur lequel on
    fait varier un champ à la fois. C'est la comparaison à un seul facteur.
    """
    base: dict[str, Any] = {
        "serveur": "ollama",
        "endpoint": "http://ollama:11434",
        "version": "0.30.10",
        "modele_demande": "gemma4:e4b",
        "modele_servi": "gemma4:e4b",
        "empreinte_du_modele": "c6eb396dbd5992bb",
        "quantification": "Q4_K_M",
        "fenetre_servie": None,
        "releve_le": "2026-09-15T17:31:00+00:00",
        "options": {
            "thinking": False,
            "outils_natifs": True,
            "temperature": 0.1,
            "num_ctx": 8192,
            "max_tokens": 4096,
        },
    }
    base.update(ecarts)
    return base


# ─── La signature : le FAIT, jamais l'INTENTION ──────────────────────────────


class TestLaSignaturePorteLeFaitEtNonLeReglage:
    """La leçon de `signature_du_peripherique`, appliquée au moteur.

    `requested` est le réglage et `embedding` le fait ; ici `modele_demande` est
    le réglage et `modele_servi` le fait. Un garde qui signerait sur le réglage
    serait **décoratif sur exactement le cas qu'il existe pour attraper** : deux
    serveurs qui portent deux poids différents sous le même tag `gemma4:e4b`.
    """

    def test_deux_poids_sous_le_meme_tag_ne_signent_pas_pareil(self) -> None:
        evaluate = _evaluate()
        un = evaluate.signature_du_moteur(_moteur(empreinte_du_modele="aaaaaaaaaaaaaaaa"))
        deux = evaluate.signature_du_moteur(_moteur(empreinte_du_modele="bbbbbbbbbbbbbbbb"))
        assert un != deux, (
            "deux poids différents servis sous le même tag rendent la même "
            "signature : l'empreinte ne pèse pas, et le garde serait aveugle au "
            "cas le plus silencieux — un tag Ollama est MUTABLE"
        )

    def test_le_reglage_seul_ne_change_pas_la_signature(self) -> None:
        """La contre-épreuve, et sans elle le test ci-dessus ne prouve rien.

        Un garde qui signerait sur TOUT le dictionnaire passerait aussi le test
        précédent, en signalant de surcroît des campagnes parfaitement
        comparables. C'est ce test-ci qui sépare les deux.
        """
        evaluate = _evaluate()
        un = evaluate.signature_du_moteur(_moteur(modele_demande="gemma4:e4b"))
        deux = evaluate.signature_du_moteur(_moteur(modele_demande="un-autre-alias"))
        assert un == deux, (
            "le nom DEMANDÉ déplace la signature : deux campagnes qui ont tourné "
            "sur le même poids seraient déclarées différentes"
        )

    def test_les_options_ne_sont_pas_dans_la_signature_du_moteur(self) -> None:
        """Elles sont signalées à part, et le motif est qu'elles ne sont pas le moteur.

        Les mêler à la signature ferait lire « moteur différent » là où le moteur
        est le même et où c'est NOTRE appel qui a changé. Les deux se réparent
        autrement.
        """
        evaluate = _evaluate()
        avec = _moteur(options={"thinking": True})
        sans = _moteur(options={"thinking": False})
        assert evaluate.signature_du_moteur(avec) == evaluate.signature_du_moteur(sans)

    def test_un_serveur_connu_sans_modele_servi_n_est_pas_muet(self) -> None:
        """Savoir QUI répondait est déjà comparable, même sans savoir quoi.

        `modele_servi` à `null` veut dire que le tag demandé n'est pas dans le
        catalogue du serveur. L'ignorance est alors NOMMÉE dans la ligne au lieu
        d'effacer ce qu'on sait.
        """
        evaluate = _evaluate()
        signature = evaluate.signature_du_moteur(_moteur(modele_servi=None))
        assert signature is not None
        assert "ABSENT DU SERVEUR" in signature

    def test_l_horodatage_n_entre_pas_dans_la_signature(self) -> None:
        """LE MÊME MOTEUR RELEVÉ À DEUX INSTANTS SIGNE PAREIL, et c'est vital.

        `releve_le` est né pour dire au lecteur externe l'ÂGE du relevé (non
        bloquante §3 de l'audit du 15 septembre 2026). Le glisser dans la
        signature ferait conclure « MOTEUR LLM DIFFÉRENT » à deux campagnes
        tournées sur exactement le même serveur — la famille de faux positifs que
        ce lot existe pour ne pas produire, et le symétrique exact de la
        bloquante qu'il ferme.
        """
        evaluate = _evaluate()
        veille = evaluate.signature_du_moteur(_moteur(releve_le="2026-09-14T08:00:00+00:00"))
        aujourdhui = evaluate.signature_du_moteur(_moteur(releve_le="2026-09-15T19:00:00+00:00"))
        assert veille == aujourdhui, "la date du relevé sépare deux campagnes du même moteur"
        assert veille is not None, "contrôle positif : la signature n'est pas muette des deux côtés"

    def test_sans_serveur_la_signature_est_muette_et_ne_devine_rien(self) -> None:
        evaluate = _evaluate()
        assert evaluate.signature_du_moteur(_moteur(serveur=None)) is None
        assert evaluate.signature_du_moteur(None) is None
        assert evaluate.signature_du_moteur({}) is None


# ─── Les trois positions, et elles ne se confondent jamais ───────────────────


def _position(lignes: list[str]) -> str:
    """Laquelle des trois positions ce bloc de lignes exprime."""
    texte = "\n".join(lignes)
    trouvees = [
        nom
        for nom, motif in (
            ("DIFFERENT", "MOTEUR LLM DIFFÉRENT"),
            ("IDENTIQUE", "moteur LLM : IDENTIQUE"),
            ("MUET", "MOTEUR LLM INCONNU"),
        )
        if motif in texte
    ]
    assert len(trouvees) == 1, (
        f"le bloc exprime {len(trouvees)} positions à la fois ({trouvees}) : "
        "elles doivent s'exclure, un lecteur ne peut pas arbitrer entre deux"
    )
    return trouvees[0]


class TestLesTroisPositionsSontDistinctesEtToujoursEcrites:
    """`muet` n'est pas `différent`, et `identique` est IMPRIMÉ.

    C'EST LA FORME EXACTE DU FAUX VERT que ce chantier a trouvée neuf fois : un
    garde qui ne parle que lorsqu'il mord ne distingue pas « les deux campagnes
    ont tourné sur le même moteur » de « ce garde n'existe pas dans la version
    qui a produit cette sortie ».
    """

    def test_identique_est_imprime_et_ne_se_tait_pas(self) -> None:
        evaluate = _evaluate()
        lignes = evaluate.confronter_les_moteurs(_moteur(), _moteur())
        assert lignes, "le garde se TAIT quand les deux moteurs coïncident"
        assert _position(lignes) == "IDENTIQUE"

    def test_un_antecedent_sans_la_cle_est_muet_et_jamais_different(self) -> None:
        """La quatrième contrainte de forme, et le cas le plus fréquent aujourd'hui.

        Les 19 campagnes de `runs/` au 15 septembre 2026 sont dans ce cas.
        """
        evaluate = _evaluate()
        lignes = evaluate.confronter_les_moteurs(_moteur(), None)
        assert _position(lignes) == "MUET"
        assert "MUETTE (pas de clé `moteur_llm`)" in "\n".join(lignes)

    def test_muet_dans_l_autre_sens_aussi(self) -> None:
        evaluate = _evaluate()
        assert _position(evaluate.confronter_les_moteurs(None, _moteur())) == "MUET"

    def test_deux_moteurs_connus_et_distincts_disent_different(self) -> None:
        evaluate = _evaluate()
        lignes = evaluate.confronter_les_moteurs(
            _moteur(serveur="vllm", version="0.28.0", modele_servi="google/gemma-4",
                    empreinte_du_modele=None),
            _moteur(),
        )
        assert _position(lignes) == "DIFFERENT"

    def test_les_deux_signatures_sont_rendues_au_lecteur_quand_elles_different(self) -> None:
        """Un garde qui dirait « ça diffère » sans dire EN QUOI ne se répare pas."""
        evaluate = _evaluate()
        texte = "\n".join(evaluate.confronter_les_moteurs(
            _moteur(serveur="vllm"), _moteur(serveur="ollama")
        ))
        assert "vllm" in texte and "ollama" in texte

    @pytest.mark.parametrize(
        ("actuel", "precedent"),
        [
            (True, True),
            (True, False),
            (False, True),
            (False, False),
        ],
    )
    def test_une_position_est_ecrite_quel_que_soit_le_couple(
        self, actuel: bool, precedent: bool
    ) -> None:
        """LA PROPRIÉTÉ, ET NON QUATRE SCÈNES : le garde n'a pas de trou.

        Les quatre couples possibles — connu/connu, connu/muet, muet/connu,
        muet/muet — rendent tous exactement une position. Un cinquième état
        n'existe pas, et un silence serait un faux vert.
        """
        evaluate = _evaluate()
        lignes = evaluate.confronter_les_moteurs(
            _moteur() if actuel else None, _moteur() if precedent else None
        )
        assert lignes
        assert _position(lignes) in {"DIFFERENT", "IDENTIQUE", "MUET"}


# ─── Les options d'appel, qui changent le SENS de la réponse ─────────────────


class TestLesOptionsDAppelSontConfronteesAussi:
    """Elles sont du réglage, assumé — et rien au monde ne les relève d'un serveur.

    Elles sont ici parce qu'elles changent le **sens** de la réponse et non sa
    vitesse : deux campagnes contre le même serveur, l'une avec le raisonnement
    allumé et l'autre non, ne mesurent pas la même chose.
    """

    def test_des_options_differentes_sont_signalees_moteur_identique(self) -> None:
        evaluate = _evaluate()
        lignes = evaluate.confronter_les_moteurs(
            _moteur(options={"thinking": True}), _moteur(options={"thinking": False})
        )
        texte = "\n".join(lignes)
        assert _position(lignes) == "IDENTIQUE", "le moteur EST le même : le dire autrement"
        assert "OPTIONS D'APPEL DIFFÉRENTES" in texte
        assert "thinking" in texte, "l'option qui bouge doit être NOMMÉE, pas comptée"

    def test_des_options_identiques_sont_imprimees_elles_aussi(self) -> None:
        """Même motif que la position `identique` : le silence se lirait comme un accord."""
        evaluate = _evaluate()
        texte = "\n".join(evaluate.confronter_les_moteurs(_moteur(), _moteur()))
        assert "options d'appel : IDENTIQUES" in texte

    def test_des_options_inconnues_d_un_cote_ne_se_disent_pas_identiques(self) -> None:
        evaluate = _evaluate()
        texte = "\n".join(evaluate.confronter_les_moteurs(_moteur(options={}), _moteur()))
        assert "inconnues d'un côté au moins" in texte
        assert "IDENTIQUES" not in texte


# ─── Il SIGNALE, il ne REFUSE pas ────────────────────────────────────────────


class TestLeGardeSignaleEtNeRefusePas:
    """La première contrainte de forme, et c'est celle qui coûterait le plus cher.

    `empreinte_des_ancrages` REFUSE parce qu'un corpus remplacé rend des chiffres
    plausibles et faux sur chaque question. Le moteur est de l'autre famille, et
    plus nettement encore que le périphérique : **confronter deux moteurs est
    exactement ce que cette clé a été posée pour permettre**. Un garde qui
    refuserait interdirait le seul geste pour lequel il a été demandé.
    """

    @staticmethod
    def _campagne(chemin: pathlib.Path, lignes: list[dict], moteur: Any) -> pathlib.Path:
        chemin.write_text(
            json.dumps({
                "empreinte_des_ancrages": "sha256:ffff",
                "moteur_llm": moteur,
                "questions": lignes,
            }),
            encoding="utf-8",
        )
        return chemin

    @staticmethod
    def _lignes() -> list[dict]:
        return [{"id": "Q-1", "mrr": 1.0, "rappel_5": 1.0}]

    def test_deux_moteurs_differents_laissent_la_comparaison_aboutir(
        self, tmp_path: pathlib.Path
    ) -> None:
        evaluate = _evaluate()
        reference = self._campagne(tmp_path / "ref.json", self._lignes(), _moteur())
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            rendu = evaluate.comparer_apparie(
                self._lignes(), reference, "sha256:ffff", None, _moteur(serveur="vllm")
            )
        assert rendu is True, (
            "la comparaison REFUSE sur un écart de moteur : elle interdirait la "
            "campagne Ollama contre campagne vLLM, qui est le lot 6 du chantier"
        )
        assert "MOTEUR LLM DIFFÉRENT" in tampon.getvalue(), (
            "elle aboutit mais sans rien dire — un refus muet est pire qu'un refus"
        )

    def test_un_ecart_d_ancrages_reste_un_refus_meme_a_moteur_identique(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Le moteur s'AJOUTE à la discipline de l'empreinte, il ne la remplace pas."""
        evaluate = _evaluate()
        reference = self._campagne(tmp_path / "ref.json", self._lignes(), _moteur())
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            rendu = evaluate.comparer_apparie(
                self._lignes(), reference, "sha256:UN-AUTRE-CORPUS", None, _moteur()
            )
        assert rendu is False


# ─── `--compare` voit le moteur comme il voit le périphérique ────────────────


class TestLaComparaisonVoitLeMoteurCommeElleVoitLePeripherique:
    """La troisième contrainte de forme, tenue par COMPARAISON entre les deux clés.

    Tenir « le mot moteur apparaît » n'aurait rien prouvé : le garde pourrait
    l'imprimer au mauvais endroit, après les flèches, quand le lecteur a déjà
    attribué les écarts. Ce qui est asserté est que **les deux clés sont traitées
    au même rang** — dans le même bloc, avant le tableau.
    """

    def test_les_deux_cles_sont_annoncees_avant_le_tableau_des_metriques(
        self, tmp_path: pathlib.Path
    ) -> None:
        evaluate = _evaluate()
        lignes = [{"id": "Q-1", "mrr": 1.0}]
        reference = tmp_path / "ref.json"
        reference.write_text(
            json.dumps({"empreinte_des_ancrages": "sha256:ffff", "questions": lignes}),
            encoding="utf-8",
        )
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            evaluate.comparer_apparie(lignes, reference, "sha256:ffff", None, _moteur())
        sortie = tampon.getvalue()
        rang_peripherique = sortie.find("PÉRIPHÉRIQUE")
        rang_moteur = sortie.find("MOTEUR LLM")
        rang_tableau = sortie.find("métrique")
        assert rang_peripherique != -1, "le contrôle positif ne mord pas : sonde invalide"
        assert rang_moteur != -1, "`--compare` ne dit RIEN du moteur"
        assert rang_moteur < rang_tableau, (
            "le moteur est annoncé APRÈS le tableau : un lecteur qui l'apprend "
            "là a déjà attribué les écarts au réglage"
        )

    def test_le_moteur_est_lu_sous_la_cle_moteur_llm_de_la_reference(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Le garde lit-il vraiment le fichier, ou se contente-t-il d'être muet ?

        Sans ce test, un `document.get("une_faute_de_frappe")` rendrait MUET sur
        toutes les campagnes du monde — un garde parfaitement vert et
        parfaitement aveugle.
        """
        evaluate = _evaluate()
        lignes = [{"id": "Q-1", "mrr": 1.0}]
        reference = tmp_path / "ref.json"
        reference.write_text(
            json.dumps({
                "empreinte_des_ancrages": "sha256:ffff",
                "moteur_llm": _moteur(serveur="vllm", version="9.9.9"),
                "questions": lignes,
            }),
            encoding="utf-8",
        )
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            evaluate.comparer_apparie(lignes, reference, "sha256:ffff", None, _moteur())
        assert "9.9.9" in tampon.getvalue(), (
            "la clé `moteur_llm` de la référence n'est pas lue : le garde serait "
            "MUET sur toutes les campagnes, et vert"
        )


# ─── La lecture à `/health`, et son silence ──────────────────────────────────


class _Reponse:
    """Le contrat que `moteur_de_la_campagne` touche, et rien de plus."""

    def __init__(self, charge: Any, leve: bool = False) -> None:
        self._charge, self._leve = charge, leve

    def raise_for_status(self) -> None:
        if self._leve:
            raise RuntimeError("503")

    def json(self) -> Any:
        return self._charge


class TestLaLectureDuMoteurALaSante:
    """`None` se lit « je n'ai pas pu lire », jamais « Ollama »."""

    @pytest.mark.parametrize(
        ("charge", "pourquoi"),
        [
            ({}, "un agent ANTÉRIEUR au lot ne publie pas la clé"),
            ({"moteur_llm": None}, "le serveur LLM n'a pas dit son nom"),
            ({"moteur_llm": "ollama"}, "une chaîne là où un objet est attendu"),
            ({"moteur_llm": []}, "une liste là où un objet est attendu"),
        ],
    )
    def test_une_sante_sans_moteur_exploitable_rend_muet(
        self, monkeypatch: pytest.MonkeyPatch, charge: Any, pourquoi: str
    ) -> None:
        evaluate = _evaluate()
        monkeypatch.setattr(evaluate.httpx, "get", lambda *a, **k: _Reponse(charge))
        assert evaluate.moteur_de_la_campagne("http://agent") is None, pourquoi

    def test_une_sante_illisible_rend_muet_sans_lever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        evaluate = _evaluate()

        def _tombe(*_a: Any, **_k: Any) -> None:
            raise OSError("le réseau")

        monkeypatch.setattr(evaluate.httpx, "get", _tombe)
        assert evaluate.moteur_de_la_campagne("http://agent") is None

    def test_le_controle_positif_une_sante_complete_rend_le_moteur(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SANS LUI, LES CINQ TESTS CI-DESSUS PASSERAIENT SUR UN `return None` NU.

        C'est la leçon la plus chère de ce chantier : huit fois un `rc` juste est
        venu de la mauvaise raison. Tout zéro se double d'un contrôle positif.
        """
        evaluate = _evaluate()
        monkeypatch.setattr(
            evaluate.httpx, "get", lambda *a, **k: _Reponse({"moteur_llm": _moteur()})
        )
        releve = evaluate.moteur_de_la_campagne("http://agent")
        assert releve is not None
        assert releve["serveur"] == "ollama"

    def test_seuls_les_champs_enumeres_entrent_dans_l_artefact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/health` peut gagner des champs ; une campagne ne doit pas les gagner seule.

        La PROPRIÉTÉ tenue est l'énumération, pas la liste : le test relit
        `_CHAMPS_DU_MOTEUR` plutôt que de recopier neuf noms qui dériveraient.
        """
        evaluate = _evaluate()
        monkeypatch.setattr(
            evaluate.httpx,
            "get",
            lambda *a, **k: _Reponse({"moteur_llm": {**_moteur(), "un_champ_neuf": 1}}),
        )
        releve = evaluate.moteur_de_la_campagne("http://agent")
        assert releve is not None
        assert set(releve) == set(evaluate._CHAMPS_DU_MOTEUR)
        assert "un_champ_neuf" not in releve


# ─── La sonde de l'agent : elle relève le FAIT, et ne devine rien ────────────


class _ReponseHttp:
    def __init__(self, code: int, charge: Any) -> None:
        self.status_code, self._charge = code, charge

    def json(self) -> Any:
        if isinstance(self._charge, Exception):
            raise self._charge
        return self._charge


class _ClientSimule:
    """Un serveur simulé par sa TABLE DE ROUTES, comme un vrai en a une."""

    def __init__(self, routes: dict[str, _ReponseHttp]) -> None:
        self.routes, self.demandes = routes, []

    async def __aenter__(self) -> "_ClientSimule":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    async def get(self, url: str) -> _ReponseHttp:
        # LE CHEMIN EXACT, ET C'EST UNE CORRECTION MESURÉE CONTRE MOI-MÊME.
        # La première écriture faisait `url.endswith(chemin)` : `/api/version`
        # se termine par `/version`, donc un serveur simulé « vLLM » répondait
        # 200 à la route d'Ollama et le relevé concluait `ollama`. Le code était
        # juste ; **le double ne ressemblait à aucun serveur réel** — le vrai
        # vLLM rend 404 sur `/api/version`, `mesuré` le 15 septembre 2026.
        self.demandes.append(url)
        reponse = self.routes.get(urlsplit(url).path)
        return reponse if reponse is not None else _ReponseHttp(404, {"detail": "Not Found"})


def _sonder(monkeypatch: pytest.MonkeyPatch, routes: dict[str, _ReponseHttp]) -> Any:
    """Joue la sonde de l'agent contre un serveur simulé. Rend (relevé, client)."""
    from src.api import main

    monkeypatch.setattr(main, "_moteur_releve", None)
    client = _ClientSimule(routes)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_k: client)
    return asyncio.run(main._sonder_moteur_llm()), client


_OLLAMA_TAGS = {
    "models": [
        {
            "name": "gemma4:e4b",
            "model": "gemma4:e4b",
            "digest": "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb",
            "details": {"quantization_level": "Q4_K_M"},
        }
    ]
}


class TestLaSondeDeLAgentReleveLeServeurEtNeDevineRien:
    """Le discriminant doit porter un FAIT DES DEUX CÔTÉS.

    `mesuré` le 15 septembre 2026 à 15:25 UTC sur les deux serveurs de ce poste :
    `GET /api/version` rend **200 et un `version`** sur Ollama, et **404 sur
    vLLM**. Un discriminant qui saurait seulement dire « ce n'est pas Ollama »
    rangerait n'importe quel serveur muet dans « vLLM » — celui-ci exige une
    réponse POSITIVE pour conclure, et c'est ce que tiennent les tests ci-dessous.
    """

    def test_un_serveur_qui_ne_dit_rien_n_est_range_dans_aucun_des_deux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releve, _ = _sonder(monkeypatch, {})  # 404 partout
        assert releve is None, (
            "un serveur silencieux est étiqueté : le champ affirmerait un moteur "
            "que personne n'a mesuré"
        )

    def test_un_deux_cents_sans_version_ne_suffit_pas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """200 n'est pas une réponse : c'est le `finish_reason` du banc go/no-go.

        Le banc a mesuré un `finish_reason: "tool_calls"` en HTTP 200 **sans
        aucun appel d'outil** (§2.1). Un code de retour n'est pas un fait.
        """
        releve, _ = _sonder(
            monkeypatch,
            {"/api/version": _ReponseHttp(200, {}), "/version": _ReponseHttp(200, {})},
        )
        assert releve is None

    def test_un_corps_qui_n_est_pas_du_json_ne_fait_pas_lever_la_sante(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releve, _ = _sonder(
            monkeypatch, {"/api/version": _ReponseHttp(200, ValueError("pas du json"))}
        )
        assert releve is None

    def test_ollama_est_reconnu_et_son_poids_releve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releve, _ = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, _OLLAMA_TAGS),
            },
        )
        assert releve is not None
        assert releve.serveur == "ollama"
        assert releve.empreinte_du_modele == "c6eb396dbd5992bb", "le digest doit être TRONQUÉ à 16"
        assert releve.quantification == "Q4_K_M"

    def test_vllm_est_reconnu_quand_ollama_a_repondu_quatre_cent_quatre(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releve, client = _sonder(
            monkeypatch,
            {
                "/version": _ReponseHttp(200, {"version": "0.28.0"}),
                "/v1/models": _ReponseHttp(
                    200, {"data": [{"id": "google/gemma-4", "max_model_len": 32768}]}
                ),
            },
        )
        assert releve is not None
        assert releve.serveur == "vllm"
        assert releve.fenetre_servie == 32768
        assert any(url.endswith("/api/version") for url in client.demandes), (
            "vLLM a été conclu sans avoir écarté Ollama"
        )

    def test_un_tag_absent_du_catalogue_est_rendu_nul_et_non_recopie(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le fait, encore : le serveur ne porte pas ce qu'on lui demande."""
        releve, _ = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, {"models": [{"name": "un-autre:tag"}]}),
            },
        )
        assert releve is not None
        assert releve.modele_servi is None, "le nom DEMANDÉ a été recopié comme s'il était SERVI"

    def test_la_sonde_reste_bornee_en_nombre_de_requetes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le serveur vLLM de ce poste appartient à une autre équipe.

        La borne est asserté comme PROPRIÉTÉ — au plus `_MOTEUR_REQUETES_MAX` —
        et non comme le compte d'une scène : un quatrième appel, même utile, se
        paierait à chaque battement du healthcheck sur un serveur partagé.

        LE CHIFFRE EST RELU AU SITE, JAMAIS RECOPIÉ : il porte aussi le budget de
        durée de la sonde (`test_health_parallele.py`), et un chiffre qui a deux
        copies finit par en avoir deux valeurs. La scène jouée ici est celle du
        PIRE cas — version Ollama écartée, version vLLM, puis catalogue — et le
        test vérifie qu'elle l'atteint réellement, sans quoi la borne serait
        tenue par une scène qui ne la touche pas.
        """
        from src.api import main

        _, client = _sonder(
            monkeypatch,
            {
                "/version": _ReponseHttp(200, {"version": "0.28.0"}),
                "/v1/models": _ReponseHttp(200, {"data": []}),
            },
        )
        assert len(client.demandes) == main._MOTEUR_REQUETES_MAX, (
            "cette scène doit ATTEINDRE la borne, sinon elle ne la tient pas"
        )
        assert len(client.demandes) <= main._MOTEUR_REQUETES_MAX, client.demandes

    def test_aucune_requete_de_generation_n_est_emise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EN LECTURE, et c'est une contrainte d'exploitation, pas de style."""
        _, client = _sonder(
            monkeypatch, {"/api/version": _ReponseHttp(200, {"version": "0.30.10"})}
        )
        interdites = ("/api/generate", "/api/chat", "/v1/chat/completions", "/v1/completions")
        assert not [u for u in client.demandes if u.endswith(interdites)], client.demandes


class TestCeQueLaSondeNeReleveraJamaisCoteVllm:
    """LA BORNE DE LA NON BLOQUANTE §2, ET LES DEUX FAUX AMIS QUI LA GARDENT.

    `mesuré` en lecture seule le 15 septembre 2026 à 17:30–17:31 UTC contre
    l'instance vLLM de ce poste, sur les **sept** routes GET qu'elle déclare à
    `/openapi.json` : **rien n'y distingue deux poids servis sous un même `id`**.
    Ce que `/v1/models` porte d'utile est `id`, `root` et `max_model_len` — et
    deux champs qui ressemblent à un discriminant sans en être un :

    - `created` : j'ai cru y tenir l'instant de DÉMARRAGE du serveur, ce qui
      aurait séparé deux poids (vLLM charge son modèle au lancement). Deux
      lectures du même serveur à quatorze secondes d'écart ont rendu
      `1789493451` puis `1789493465`, soit **l'instant de chaque requête** ;
    - `permission[].id` : un identifiant d'allure stable, régénéré lui aussi à
      chaque requête (`modelperm-8e71c04ff2880f31` puis
      `modelperm-9efd789f275ba600`).

    Les relever ferait **différer deux relevés du même moteur** — exactement le
    faux positif que ce lot existe pour ne pas produire. Ce test tient donc la
    borne dans le sens utile : il ne fige pas l'absence d'empreinte, il interdit
    qu'on la comble avec du bruit.
    """

    _CATALOGUE_REEL = {
        "object": "list",
        "data": [
            {
                "id": "google/gemma-4-E4B-it-qat-w4a16-ct",
                "object": "model",
                "created": 1789493451,
                "owned_by": "vllm",
                "root": "google/gemma-4-E4B-it-qat-w4a16-ct",
                "parent": None,
                "max_model_len": 32768,
                "permission": [
                    {"id": "modelperm-8e71c04ff2880f31", "object": "model_permission"}
                ],
            }
        ],
    }

    def _releve(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        releve, _ = _sonder(
            monkeypatch,
            {
                "/version": _ReponseHttp(200, {"version": "0.28.0"}),
                "/v1/models": _ReponseHttp(200, self._CATALOGUE_REEL),
            },
        )
        return releve

    def test_les_champs_regeneres_a_chaque_requete_ne_sont_pas_releves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        releve = self._releve(monkeypatch)
        assert releve is not None
        publie = releve.model_dump()
        for volatile in ("1789493451", "modelperm-8e71c04ff2880f31"):
            assert volatile not in str(publie), (
                f"{volatile} est régénéré à CHAQUE requête : le relever ferait différer "
                "deux relevés du même serveur"
            )

    def test_le_controle_positif_ce_meme_catalogue_rend_bien_ce_qu_il_porte(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SANS LUI, LE TEST CI-DESSUS PASSERAIT SUR UNE SONDE QUI NE LIT RIEN."""
        releve = self._releve(monkeypatch)
        assert releve is not None
        assert releve.modele_servi == "google/gemma-4-E4B-it-qat-w4a16-ct"
        assert releve.fenetre_servie == 32768

    def test_l_empreinte_reste_nulle_cote_vllm_et_c_est_la_borne_ecrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CE TEST N'EST PAS UN GARDE, C'EST UN CONSTAT DATÉ, et il le dit.

        Il épingle que la position `DIFFÉRENT` de `--compare` est inatteignable
        côté vLLM sur deux poids servis sous le même `id` — §6 de
        `documentation/moteur_llm.md`. Le jour où vLLM exposera un discriminant
        de poids, ce test rougira : c'est **voulu**, il faudra alors relever ce
        champ et réécrire la borne du §6, pas relâcher l'assertion.
        """
        releve = self._releve(monkeypatch)
        assert releve is not None
        assert releve.empreinte_du_modele is None
        assert releve.quantification is None, "côté vLLM elle est dans le NOM, pas dans un champ"


class TestLeReleveDitQuandIlAEtePris:
    """NON BLOQUANTE §3 — le seul cache à vie de `/health` était sans date.

    Un lecteur externe ne pouvait pas distinguer « relevé il y a dix secondes »
    de « relevé il y a onze heures », alors que le serveur d'en face redémarre
    quand l'équipe voisine change son réglage de mémoire GPU.
    """

    def test_le_releve_porte_la_date_a_laquelle_il_a_ete_pris(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        avant = datetime.now(UTC)
        releve, _ = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, _OLLAMA_TAGS),
            },
        )
        apres = datetime.now(UTC)
        assert releve is not None
        assert releve.releve_le is not None, "le relevé est publié sans dire quand il a été pris"
        date = datetime.fromisoformat(releve.releve_le)
        assert date.tzinfo is not None, "une date sans fuseau n'est pas lisible de l'extérieur"
        # Bornée des DEUX côtés par l'horloge du test : une constante recopiée
        # passerait ce test sans que la date décrive quoi que ce soit.
        assert avant.replace(microsecond=0) <= date <= apres

    def test_la_date_est_celle_du_releve_et_ne_se_rafraichit_pas_a_la_lecture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C'EST TOUT L'INTÉRÊT DU CHAMP, et le sens dans lequel il peut mentir.

        Un horodatage recalculé à chaque lecture rendrait un relevé de onze
        heures indiscernable d'un relevé neuf — le défaut exact qu'il ferme.

        LA VIEILLESSE EST INJECTÉE, ET C'EST UNE CORRECTION CONTRE MOI-MÊME.
        Ce test comparait d'abord deux lectures consécutives. Mutation M4 —
        redater le relevé à chaque lecture du cache — l'a laissé **VERT** : les
        deux lectures tombent dans la même seconde, et la date est publiée à la
        seconde. Un garde qui dépend de la vitesse de la machine ne garde rien.
        Le relevé mémorisé est donc vieilli d'un jour à la main, ce qui rend la
        scène déterministe et la mutation mordante.
        """
        from src.api import main

        releve, _ = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, _OLLAMA_TAGS),
            },
        )
        assert releve is not None
        veille = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="seconds")
        monkeypatch.setattr(
            main, "_moteur_releve", releve.model_copy(update={"releve_le": veille})
        )
        relu = asyncio.run(main._sonder_moteur_llm())
        assert relu is not None
        assert relu.releve_le == veille, (
            "la date a été refaite à la lecture : un relevé vieux d'un jour "
            "se présenterait comme neuf"
        )


class TestLaMemorisationDuReleve:
    """Le relevé est mémorisé, et le prix est nommé au site.

    `/health` est battu toutes les 20 s par le healthcheck ; deux requêtes de plus
    à chaque battement vers un serveur d'inférence PARTAGÉ seraient un prix
    permanent pour un fait qui ne change qu'au redémarrage de ce serveur.

    CE QUI EST MÉMORISÉ EST UN RELEVÉ **COMPLET**, et c'est la correction de
    l'audit du 15 septembre 2026 (§1, bloquante). Le prédicat était « le serveur
    a dit son nom » ; il est désormais « le serveur a dit son nom ET ce qu'il
    porte ». Entre les deux se trouve exactement la fenêtre de démarrage que la
    justification du cache prétendait couvrir : un serveur dont le port HTTP
    répond avant que son modèle soit tiré.
    """

    def test_un_succes_complet_est_memorise_et_ne_repart_pas_sur_le_reseau(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REQUALIFIÉ le 15 septembre 2026, et le motif est écrit ici.

        CE QUE CE TEST TENAIT. Sous son ancien nom
        (`test_un_succes_est_memorise_et_ne_repart_pas_sur_le_reseau`), il ne
        servait que `/api/version` : le relevé qu'il obtenait avait
        `modele_servi=None`, `empreinte_du_modele=None`, `quantification=None` —
        un relevé **partiel** — et il exigeait qu'il soit mémorisé **pour la vie
        du processus**. Il nommait « un succès » la scène même du défaut, et
        appliquer le correctif le faisait rougir.

        CE QU'IL TIENT DÉSORMAIS, et c'est ce qu'il a toujours voulu tenir : un
        succès **complet** — le serveur a dit son nom ET ce qu'il porte — est
        mémorisé, et le battement suivant ne repart pas sur le réseau. La scène
        change, l'assertion ne s'assouplit pas : c'est toujours l'égalité stricte
        du compte de requêtes.

        Il n'a **pas** été désactivé et son assertion n'a **pas** été relâchée :
        un test qui rougit parce qu'il décrivait le défaut est un test à
        requalifier.
        """
        from src.api import main

        releve, client = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, _OLLAMA_TAGS),
            },
        )
        assert releve is not None
        assert releve.modele_servi is not None, (
            "la scène de ce test doit être un succès COMPLET : c'est tout son objet"
        )
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) == premier, "le second appel est reparti sur le réseau"

    def test_un_echec_n_est_pas_memorise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sinon un serveur qui finit de démarrer resterait muet pour toujours."""
        from src.api import main

        releve, client = _sonder(monkeypatch, {})
        assert releve is None
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, "le silence a été mémorisé"

    def test_un_releve_partiel_n_est_pas_memorise_et_le_battement_suivant_re_sonde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA SCÈNE DE LA BLOQUANTE — audit du 15 septembre 2026, §1.

        Un serveur qui n'a pas fini de démarrer est précisément celui dont le
        port HTTP répond — donc `/api/version` répond — mais dont le catalogue
        n'est pas encore servi. Le relevé y est construit avec
        `modele_servi=None`, et c'est CE relevé-là que le premier battement du
        healthcheck a le plus de chances de prendre (`start_period: 30s`,
        intervalle 20 s).

        Figé, il publierait `modele_servi: null` en permanence sur un serveur
        parfaitement sain, et `signature_du_moteur` en tirerait
        « modèle ABSENT DU SERVEUR » — une phrase **fausse**, pas une phrase
        muette, qui contourne par le bas la doctrine « muet n'est pas différent ».
        """
        from src.api import main

        releve, client = _sonder(
            monkeypatch, {"/api/version": _ReponseHttp(200, {"version": "0.30.10"})}
        )
        assert releve is not None, "un serveur qui a dit son nom n'est pas muet"
        assert releve.serveur == "ollama"
        assert releve.modele_servi is None, "la scène jouée ici est bien un relevé PARTIEL"
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, (
            "le relevé partiel est figé à vie : le serveur a beau finir de démarrer, "
            "l'agent publiera `modele_servi: null` jusqu'à SON propre redémarrage"
        )

    def test_un_tag_encore_absent_du_catalogue_n_est_pas_memorise_non_plus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le catalogue répond, mais pas encore avec ce qu'on lui demande.

        Deuxième moitié de la même fenêtre, et le code la nomme lui-même au
        site : « le tag demandé peut n'y être pas — il sera tiré au premier
        appel ». Un fait transitoire n'est pas un fait à figer.
        """
        from src.api import main

        releve, client = _sonder(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, {"models": [{"name": "un-autre:tag"}]}),
            },
        )
        assert releve is not None
        assert releve.modele_servi is None
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, "un tag pas encore tiré a été figé à vie"

    def test_cote_vllm_un_catalogue_vide_n_est_pas_memorise_non_plus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le prédicat est le MÊME des deux côtés, et c'est délibéré.

        vLLM charge son modèle au lancement ; un catalogue vide y est donc encore
        plus clairement l'état d'un serveur qui n'a pas fini de démarrer.
        """
        from src.api import main

        releve, client = _sonder(
            monkeypatch,
            {
                "/version": _ReponseHttp(200, {"version": "0.28.0"}),
                "/v1/models": _ReponseHttp(200, {"data": []}),
            },
        )
        assert releve is not None
        assert releve.serveur == "vllm"
        assert releve.modele_servi is None
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, "un catalogue vLLM vide a été figé à vie"

    def test_le_controle_positif_le_releve_complet_vllm_est_memorise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SANS LUI, LES QUATRE TESTS CI-DESSUS PASSERAIENT SUR UN CACHE RETIRÉ.

        C'est la leçon la plus chère de ce chantier : tout zéro — ici « aucune
        mémorisation » — se double d'un contrôle positif qui montre qu'il reste
        une scène où la mémorisation a bien lieu.
        """
        from src.api import main

        releve, client = _sonder(
            monkeypatch,
            {
                "/version": _ReponseHttp(200, {"version": "0.28.0"}),
                "/v1/models": _ReponseHttp(
                    200, {"data": [{"id": "google/gemma-4", "max_model_len": 32768}]}
                ),
            },
        )
        assert releve is not None
        assert releve.modele_servi == "google/gemma-4"
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) == premier, "le second appel est reparti sur le réseau"


class TestLEndpointEstExpurge:
    """CE DÉPÔT EST PUBLIC ET `runs/*.json` Y EST VERSIONNÉ.

    `OLLAMA_HOST` est un nom de service docker sur ce poste, mais rien n'empêche
    un déploiement d'y mettre des identifiants — ils finiraient recopiés dans une
    campagne commitée.
    """

    def test_les_identifiants_ne_survivent_pas_a_l_expurgation(self) -> None:
        from src.api.main import _endpoint_expurge

        expurge = _endpoint_expurge("http://bob:s3cr3t@ollama:11434/v1")
        assert "s3cr3t" not in expurge and "bob" not in expurge
        assert expurge == "http://ollama:11434", "l'hôte et le port doivent survivre"

    def test_une_url_indechiffrable_n_est_pas_recopiee(self) -> None:
        """On ne sait pas ce qu'elle contient : on ne la publie pas."""
        from src.api.main import _endpoint_expurge

        assert _endpoint_expurge("pas-une-url") == "(illisible)"

    def test_le_controle_positif_une_url_ordinaire_traverse_entiere(self) -> None:
        from src.api.main import _endpoint_expurge

        assert _endpoint_expurge("http://ollama:11434") == "http://ollama:11434"


# ─── Ce que les campagnes du disque disent aujourd'hui ───────────────────────


def test_les_campagnes_deja_au_disque_sont_muettes_et_le_restent() -> None:
    """LA BORNE, SUR LE DÉPÔT RÉEL : ce lot ne réécrit AUCUNE campagne.

    Une clé ajoutée aux artefacts ne s'applique pas rétroactivement, et personne
    ne doit croire l'inverse. Ce test n'épingle pas un compte — il tiendrait
    encore si une campagne portant la clé était écrite demain : ce qu'il asserte
    est que **toute campagne sans la clé est traitée en MUET**, jamais en
    « Ollama par défaut ».
    """
    evaluate = _evaluate()
    runs = _RACINE / "runs"
    muettes = 0
    for chemin in sorted(runs.glob("*.json")):
        document = json.loads(chemin.read_text(encoding="utf-8"))
        if document.get("moteur_llm") is None:
            muettes += 1
            lignes = evaluate.confronter_les_moteurs(None, document.get("moteur_llm"))
            assert _position(lignes) == "MUET", f"{chemin.name} n'est pas traitée en muet"
    assert muettes > 0, (
        "aucune campagne muette dans `runs/` : la sonde ne mesure plus rien — "
        "ce test doit alors être relu, pas supprimé"
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
