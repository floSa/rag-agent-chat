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
import logging
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

    def test_la_fenetre_servie_entre_dans_la_signature(self) -> None:
        """NON BLOQUANTE §4 DE L'AUDIT DU 15 SEPTEMBRE 2026 — 32 768 contre 8 192
        signaient `IDENTIQUE`.

        LE CRITÈRE D'ENTRÉE DANS LA SIGNATURE, ÉCRIT ICI PARCE QUE C'EST ICI
        QU'ON LE LIT : **un champ entre si et seulement s'il est invariant pour
        un moteur donné et varie quand le moteur change.** Les deux moitiés
        comptent, et elles ont chacune leur test dans cette classe.

        CE CRITÈRE EST MESURÉ, PAS SUPPOSÉ. Deux lectures de `/v1/models` contre
        l'instance de ce poste, espacées de 449 s (18:45:28 et 18:52:57 UTC le
        15 septembre 2026, en lecture seule) : `max_model_len` **STABLE** à
        32 768, quand `created` **CHANGE** dans le même intervalle — ce dernier
        étant le contrôle positif qui établit que la comparaison sait voir un
        changement. `fenetre_servie` satisfait donc la première moitié du
        critère ; elle ne bouge qu'au relancement du serveur avec un autre
        `--max-model-len`, c'est-à-dire précisément quand le moteur change.

        POURQUOI CETTE GRANDEUR-LÀ ET PAS UNE AUTRE. Côté vLLM,
        `empreinte_du_modele` est structurellement nulle (§6 de
        `moteur_llm.md`) : `fenetre_servie` est **le seul autre fait relevé du
        serveur**, et c'est exactement la grandeur qui sépare les deux moteurs
        aujourd'hui — vLLM sert 32 768 quand nous demandons 8 192. La comparaison
        appariée est l'instrument avec lequel on jugera la bascule vers vLLM
        (lot 6) ; la laisser hors signature ferait signer `IDENTIQUE` aux deux
        campagnes dont l'écart est le sujet même du jugement.
        """
        evaluate = _evaluate()
        large = evaluate.signature_du_moteur(_moteur(fenetre_servie=32768))
        etroite = evaluate.signature_du_moteur(_moteur(fenetre_servie=8192))
        assert large != etroite, (
            "32 768 et 8 192 signent pareil : c'est l'écart même qui sépare les deux "
            "moteurs, et `--compare` est l'instrument qui doit juger la bascule"
        )
        assert large is not None and "32768" in large, (
            "contrôle positif : la fenêtre doit être LISIBLE dans la ligne, et pas "
            "seulement peser sur une égalité"
        )

    def test_la_fenetre_inconnue_ne_signe_pas_comme_une_fenetre_connue(self) -> None:
        """« MUET » N'EST PAS « DIFFÉRENT », ET CE CHAMP NE FAIT PAS EXCEPTION.

        Côté Ollama `fenetre_servie` est **toujours** nulle — rien dans
        `/api/tags` ne la porte —, et les 19 campagnes de `runs/` au 15 septembre
        2026 sont muettes sur le moteur entier. Une fenêtre inconnue ne doit donc
        pas être imprimée comme une valeur, ni faire signer une campagne Ollama
        comme une campagne vLLM.
        """
        evaluate = _evaluate()
        muette = evaluate.signature_du_moteur(_moteur(fenetre_servie=None))
        connue = evaluate.signature_du_moteur(_moteur(fenetre_servie=32768))
        assert muette is not None, "un serveur connu reste comparable sans sa fenêtre"
        assert muette != connue
        assert "None" not in muette, "une fenêtre inconnue ne s'imprime pas comme une valeur"

    def test_deux_releves_du_meme_moteur_signent_pareil_fenetre_comprise(self) -> None:
        """L'AUTRE MOITIÉ DU CRITÈRE, ET ELLE TIRE EN SENS OPPOSÉ. C'EST LE SUJET.

        `releve_le` est sorti de la signature parce qu'il varie **sans que le
        moteur change** ; `fenetre_servie` y entre parce qu'elle ne varie **que
        si** le moteur change. Ce test tient les deux exigences ENSEMBLE, sur un
        seul couple de relevés : la date bouge, la fenêtre non, et la signature
        ne bouge pas. Sans lui, la fermeture de la §4 aurait pu rouvrir la §3 de
        l'audit précédent sans que rien ne le dise.
        """
        evaluate = _evaluate()
        veille = evaluate.signature_du_moteur(
            _moteur(fenetre_servie=32768, releve_le="2026-09-14T08:00:00+00:00")
        )
        aujourdhui = evaluate.signature_du_moteur(
            _moteur(fenetre_servie=32768, releve_le="2026-09-15T19:00:00+00:00")
        )
        assert veille == aujourdhui, (
            "deux campagnes du même moteur à deux instants signent différemment : "
            "c'est la non bloquante §3 de l'audit précédent, rouverte"
        )
        assert veille is not None and "32768" in veille, (
            "contrôle positif : la fenêtre est bien DANS la signature qu'on vient de "
            "déclarer stable — sans quoi ce test passerait sur une fenêtre ignorée"
        )

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


# L'`id` que l'instance vLLM de ce poste SERT RÉELLEMENT, `mesuré` en lecture
# seule le 15 septembre 2026 à 18:45:28 UTC. Il est ici entier, jamais abrégé.
#
# POURQUOI IL A REMPLACÉ `google/gemma-4` DANS LES DOUBLES. Ce fichier portait un
# `id` inventé et court, et c'est la MÊME faute que celle déjà corrigée sur
# `_ClientSimule` : un double qui ne ressemble à aucun serveur réel. Elle est
# devenue visible quand la sonde s'est mise à confronter l'`id` servi au modèle
# demandé — non bloquante §2 de l'audit du 15 septembre 2026 : `google/gemma-4`
# ne contient pas la taille `e4b`, donc aucun serveur ne l'aurait reconnu comme
# le nôtre, et deux tests ont rougi. **Ils décrivaient une scène qui n'existe
# pas**, et les assertions n'ont pas bougé d'un iota en changeant de scène.
_ID_VLLM_REEL = "google/gemma-4-E4B-it-qat-w4a16-ct"


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
                    200, {"data": [{"id": _ID_VLLM_REEL, "max_model_len": 32768}]}
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


class TestLeServeurVllmDoitServirCeQueNousDEMANDONS:
    """NON BLOQUANTE §2 DE L'AUDIT DU 15 SEPTEMBRE 2026 — et c'est le symétrique
    exact de la bloquante que ce lot venait de fermer.

    LA SCÈNE. Côté Ollama, `modele_servi` n'est rempli que si le tag demandé est
    **trouvé** dans le catalogue : le prédicat de mémorisation peut donc être
    faux, et c'est ce qui a fermé la bloquante. Côté vLLM, il valait
    `entrees[0]["id"]` — **quel que soit cet `id`**, jamais confronté à quoi que
    ce soit. Un serveur qui sert le modèle d'une autre équipe était donc
    mémorisé **à vie sous un nom faux** : `signature_du_moteur` en tirait
    « vllm 0.28.0 — un/modele-sans-rapport », une ligne **ni muette ni vraie**,
    que `confronter_les_moteurs` traitait comme un fait. C'est le contournement
    « par le bas » de la doctrine *« muet n'est pas différent »*, déplacé d'un
    serveur à l'autre : là où le défaut d'origine figeait un SILENCE sur un
    serveur sain, celui-ci figeait une AFFIRMATION POSITIVE fausse.

    POURQUOI LA CONFRONTATION EST POSSIBLE, ALORS QUE LA RÉSERVE R2 LA DÉCLARAIT
    « NON FERMABLE ». R2 posait que les deux noms ne vivent pas dans le même
    espace de nommage et ne se confrontent donc pas. **Mesuré le 15 septembre
    2026 à 18:45 UTC contre l'instance de ce poste, en lecture seule**, cette
    hypothèse est fausse : `GET /v1/models` sert **une** entrée, d'`id`
    `google/gemma-4-E4B-it-qat-w4a16-ct`, quand le réglage versionné de
    `settings.py` demande `gemma4:e4b`. Les deux noms ne sont pas ÉGAUX — R2
    avait raison sur ce point — mais réduits à leurs seuls caractères
    alphanumériques minuscules, le demandé est un **infixe exact** du servi
    (`gemma4e4b` dans `googlegemma4e4bitqatw4a16ct`). Ce n'est donc pas une
    égalité de noms qu'on exige ici, c'est cette relation-là, et elle est
    mesurée sur ce serveur et non supposée.

    CE QUE LA RELATION NE SAIT PAS, ÉCRIT COMME BORNE. Elle ne sépare pas deux
    QUANTIFICATIONS du même modèle — `…-qat-w4a16-ct` et un hypothétique
    `…-fp8` la satisfont tous deux —, et c'est exactement la borne déjà écrite
    au §6 de `moteur_llm.md` : côté vLLM, rien de ce que les sept routes GET de
    l'instance exposent ne distingue deux poids. La relation ferme la question du
    MODÈLE, pas celle du POIDS, et la seconde reste ouverte.
    """

    _VERSION_VLLM = {"/version": _ReponseHttp(200, {"version": "0.28.0"})}

    # L'`id` réellement servi vient du site canonique du module : c'est sa
    # longueur et ses séparateurs qui font tout l'intérêt de la scène.
    _ID_REEL = _ID_VLLM_REEL

    def _catalogue(self, *identifiants: str) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": i, "object": "model", "max_model_len": 32768} for i in identifiants
            ],
        }

    def test_un_serveur_qui_sert_le_modele_d_une_autre_equipe_n_est_pas_memorise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA SCÈNE DE LA NON BLOQUANTE, tenue dans les DEUX conséquences.

        Elle en a deux, et il faut les deux : le nom faux n'est pas PUBLIÉ, et il
        n'est pas MÉMORISÉ. La seconde est la plus chère — figée, elle survit au
        redémarrage du serveur d'en face et ne se répare qu'en redémarrant
        l'agent.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        releve, client = _sonder(
            monkeypatch,
            {
                **self._VERSION_VLLM,
                "/v1/models": _ReponseHttp(200, self._catalogue("un/modele-sans-rapport")),
            },
        )
        assert releve is not None, "un serveur qui a dit son nom n'est pas muet"
        assert releve.serveur == "vllm"
        assert releve.modele_servi is None, (
            "le serveur sert le modèle de quelqu'un d'autre : le publier sous notre nom "
            "est une affirmation POSITIVE fausse, pas un silence"
        )
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, (
            "un nom qui n'est pas le nôtre a été figé pour la vie du processus"
        )

    def test_le_controle_positif_l_id_reellement_servi_par_ce_poste_est_retenu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SANS LUI, LE TEST CI-DESSUS PASSERAIT SUR UNE CONFRONTATION QUI REFUSE TOUT.

        C'est le contrôle qui coûte le plus cher à ce chantier quand il manque :
        une relation de noms trop stricte rendrait `modele_servi` toujours nul
        côté vLLM, donc le re-sondage permanent — deux GET toutes les 20 s vers
        un serveur partagé — sur une instance parfaitement saine. La scène est
        donc jouée avec l'`id` MESURÉ, et le réglage VERSIONNÉ face à lui.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        releve, client = _sonder(
            monkeypatch,
            {**self._VERSION_VLLM, "/v1/models": _ReponseHttp(200, self._catalogue(self._ID_REEL))},
        )
        assert releve is not None
        assert releve.modele_servi == self._ID_REEL
        assert releve.fenetre_servie == 32768
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) == premier, "le relevé complet n'a pas été mémorisé"

    def test_l_entree_retenue_est_la_notre_et_non_la_premiere_du_catalogue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`entrees[0]` N'EST PAS « NOTRE » ENTRÉE, et rien ne le garantissait.

        vLLM peut servir plusieurs modèles, et l'ordre de `data` n'est pas un
        contrat. La sonde parcourt donc le catalogue comme elle le fait côté
        Ollama depuis toujours, au lieu de prendre la première venue — et la
        fenêtre relevée est celle de NOTRE entrée, pas celle d'une autre.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        catalogue = {
            "object": "list",
            "data": [
                {"id": "mistralai/Mistral-Large-3", "max_model_len": 131072},
                {"id": self._ID_REEL, "max_model_len": 32768},
            ],
        }
        releve, _ = _sonder(
            monkeypatch,
            {**self._VERSION_VLLM, "/v1/models": _ReponseHttp(200, catalogue)},
        )
        assert releve is not None
        assert releve.modele_servi == self._ID_REEL, "la PREMIÈRE entrée a été prise sans question"
        assert releve.fenetre_servie == 32768, "la fenêtre relevée est celle d'une AUTRE entrée"

    def test_la_generation_voisine_et_l_autre_taille_sont_bien_refusees(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La relation DISCRIMINE, et ce test en est la mesure.

        Une relation d'inclusion pourrait être laxiste : ces deux noms-là sont
        ceux qu'un exploitant confondrait vraiment — la génération d'avant et
        l'autre taille de la même génération. Tous deux doivent être refusés.
        """
        from src.api import main

        for confusion in ("google/gemma-3-E4B-it", "google/gemma-4-E2B-it-qat"):
            monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
            releve, _ = _sonder(
                monkeypatch,
                {**self._VERSION_VLLM, "/v1/models": _ReponseHttp(200, self._catalogue(confusion))},
            )
            assert releve is not None
            assert releve.modele_servi is None, f"{confusion} a été pris pour le nôtre"

    def test_un_modele_demande_vide_ne_reconnait_rien(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA BORNE QUE J'AI TROUVÉE CONTRE MA PROPRE RELATION.

        Réduit à ses alphanumériques, un réglage vide donne la chaîne vide — et
        la chaîne vide est un infixe de **tout**. Sans ce garde, un `OLLAMA_MODEL`
        absent ou fait de seuls séparateurs aurait reconnu le premier modèle
        venu, c'est-à-dire précisément le défaut qu'on ferme ici, en pire :
        silencieusement, et sur n'importe quel serveur.

        CE QUI RESTE OUVERT, DIT COMME TEL : un réglage dégénérément COURT mais
        non vide — `g` — reste satisfait par presque tout nom. Aucun seuil de
        longueur ne se justifierait sans arbitraire, et un réglage d'un caractère
        est une faute de configuration que ce relevé n'a pas mandat de corriger.
        La borne est écrite, pas fermée.
        """
        from src.api import main

        for degenere in ("", "   ", "/-:"):
            monkeypatch.setattr(main.settings, "ollama_model", degenere)
            releve, _ = _sonder(
                monkeypatch,
                {
                    **self._VERSION_VLLM,
                    "/v1/models": _ReponseHttp(200, self._catalogue(self._ID_REEL)),
                },
            )
            assert releve is not None
            assert releve.modele_servi is None, (
                f"un réglage {degenere!r} a reconnu le premier modèle venu"
            )


class TestUnModeleDERIVEDuNotreNEstPasLeNotre:
    """NON BLOQUANTE §2 DE L'AUDIT DU 15 SEPTEMBRE 2026 — et c'est le cas PROBABLE.

    Les deux bornes que la relation portait — « elle ne sépare pas deux
    QUANTIFICATIONS » et « un réglage dégénérément court reste satisfait » —
    étaient **exactes**, l'audit l'a vérifié. Elles n'étaient pas les seules, et
    celle qui manquait est **plus probable** que les deux qu'elles couvrent :
    dans l'espace de nommage que vLLM sert, un modèle se **dérive** bien plus
    souvent qu'il ne se requantifie.

    UN DÉRIVÉ N'EST PAS UN AUTRE POIDS DU MÊME MODÈLE : C'EST UN AUTRE MODÈLE.
    Une variante ablitérée n'a plus les mêmes garde-fous ; une distillation n'a
    ni la même taille ni le même comportement ; un ajustement métier répond
    autrement. La borne écrite couvrait le POIDS et laissait dehors la
    DÉRIVATION, qui n'est pas la même question.

    CE QUE ÇA COÛTAIT, ET C'EST EXACTEMENT CE QUE CETTE CLÉ EXISTE POUR EMPÊCHER.
    Un catalogue servant un dérivé du nôtre le faisait signer comme le nôtre :
    `modele_servi` publiait un nom que nous n'avions pas demandé, **mémorisé pour
    la vie du processus**, et `signature_du_moteur` en tirait une ligne ni muette
    ni vraie qu'une campagne enregistrait comme le moteur mesuré. Le défaut que
    la non bloquante §2 du lot précédent venait de fermer pour le cas improbable
    — « le voisin sert un modèle sans rapport » — revenait par le cas probable :
    « le voisin change de dérivé sur le même modèle de base ».

    ET RIEN NE LE JOUAIT. La mutation M3a de l'audit — refuser les `id` portant
    un marqueur de dérivation — laissait **870 verts** ; sa jumelle M3b, au même
    site et dans la même forme, en rougissait **5**. Aucune des 870 scènes ne
    jouait un modèle dérivé : les noms qu'elles opposaient étaient tous plus
    COURTS ou divergents EN TÊTE, jamais plus longs par la QUEUE, qui est la
    forme que l'inclusion laisse passer par construction. Les quatre scènes
    ci-dessous sont ces scènes manquantes.
    """

    _VERSION_VLLM = {"/version": _ReponseHttp(200, {"version": "0.28.0"})}
    _ID_REEL = _ID_VLLM_REEL

    def _catalogue(self, *identifiants: str) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": i, "object": "model", "max_model_len": 32768} for i in identifiants],
        }

    def _modele_servi_pour(self, monkeypatch: pytest.MonkeyPatch, identifiant: str) -> str | None:
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        releve, _ = _sonder(
            monkeypatch,
            {**self._VERSION_VLLM, "/v1/models": _ReponseHttp(200, self._catalogue(identifiant))},
        )
        assert releve is not None, "un serveur qui a dit son nom n'est pas muet"
        return releve.modele_servi

    def test_le_temoin_l_id_reellement_servi_par_ce_poste_reste_retenu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TÉMOIN QUI TIENT L'AUTRE BORD DE L'ENCADREMENT, et il passe d'abord.

        Sans lui, les quatre refus ci-dessous seraient satisfaits par une
        relation qui refuse TOUT — c'est-à-dire par la régression que la mutation
        M2 de l'audit garde : `modele_servi` toujours nul côté vLLM, donc le
        re-sondage permanent contre un serveur partagé, sur une instance
        parfaitement saine.
        """
        assert self._modele_servi_pour(monkeypatch, self._ID_REEL) == self._ID_REEL

    def test_une_variante_abliteree_n_est_pas_notre_modele(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Les garde-fous ont été retirés : le modèle ne répond plus comme le nôtre.

        C'est le dérivé dont la conséquence est la plus lourde pour une
        campagne — le nom est le nôtre à un suffixe près, et le comportement
        mesuré n'a rien à voir.
        """
        derive = f"{self._ID_REEL}-abliterated"
        assert self._modele_servi_pour(monkeypatch, derive) is None, (
            f"{derive} a signé comme le nôtre"
        )

    def test_une_requantification_tierce_n_est_pas_notre_modele(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Republié par un tiers sous son propre format, ce n'est plus le poids de l'éditeur.

        À NE PAS CONFONDRE AVEC LA BORNE DE LA QUANTIFICATION, et la scène
        suivante le mesure : deux formats publiés par l'ÉDITEUR sous son propre
        `id` restent indiscernables, parce que rien de ce que vLLM expose ne les
        sépare. Ce qui est refusé ici n'est pas un format, c'est un
        **repackaging tiers**, qui se reconnaît à son vocabulaire.
        """
        derive = "unsloth/gemma-4-E4B-it-qat-w4a16-ct-bnb-4bit"
        assert self._modele_servi_pour(monkeypatch, derive) is None, (
            f"{derive} a signé comme le nôtre"
        )

    def test_une_distillation_n_est_pas_notre_modele(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le nôtre est le PROFESSEUR, pas l'élève — et l'élève porte son nom.

        La forme est celle que l'écosystème publie réellement : le nom du modèle
        distillé garde en QUEUE le nom complet du modèle source.
        """
        derive = f"deepseek-ai/DeepSeek-R1-Distill-{self._ID_REEL.split('/', 1)[1]}"
        assert self._modele_servi_pour(monkeypatch, derive) is None, (
            f"{derive} a signé comme le nôtre"
        )

    def test_un_ajustement_metier_n_est_pas_notre_modele(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le cas le plus probable sur une instance PARTAGÉE avec deux autres équipes.

        C'est le geste ordinaire d'une équipe voisine : partir de notre modèle de
        base et le réentraîner pour son domaine. Le nom reste le nôtre, le moteur
        ne l'est plus.
        """
        derive = f"unequipe/{self._ID_REEL.split('/', 1)[1]}-finetune-juridique-v3"
        assert self._modele_servi_pour(monkeypatch, derive) is None, (
            f"{derive} a signé comme le nôtre"
        )

    def test_le_temoin_inerte_un_nom_sans_rapport_reste_refuse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TÉMOIN INERTE DE CETTE CLASSE, et il établit que les quatre refus sont réels.

        Sans lui, les quatre `None` ci-dessus pourraient être ceux d'une sonde
        qui n'atteint pas son cas — un catalogue mal construit, une route mal
        simulée. Ce nom-là était déjà refusé avant cette fermeture et le reste
        après : c'est le même chemin, et il rend le même verdict.
        """
        assert self._modele_servi_pour(monkeypatch, "un/modele-sans-rapport") is None

    def test_la_borne_de_la_quantification_reste_ouverte_et_c_est_mesure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA BORNE ÉCRITE N'A PAS BOUGÉ, ET CE TEST EST SA MESURE, PAS SA PROMESSE.

        Fermer la dérivation en fermant aussi la quantification aurait été un
        resserrement silencieux : `…-fp8` est un autre POIDS du même modèle,
        publié par le même éditeur sous le même `id` de base, et rien de ce que
        les sept routes GET de vLLM exposent ne le distingue du nôtre. La
        relation ferme la question du MODÈLE ; celle du POIDS reste ouverte, et
        elle reste ouverte APRÈS cette fermeture — ce qui est mesuré ici.
        """
        variante = "google/gemma-4-E4B-it-fp8"
        assert self._modele_servi_pour(monkeypatch, variante) == variante, (
            "la borne du POIDS a été refermée par accident : c'est un resserrement "
            "silencieux, et il rendrait `modele_servi` nul sur un serveur sain"
        )

    def test_la_borne_qui_reste_un_derive_au_vocabulaire_inconnu_passe_encore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CE QUE CETTE FERMETURE NE FERME PAS, MESURÉ ET NON SUPPOSÉ.

        La dérivation se reconnaît ici à un VOCABULAIRE, et un vocabulaire est
        une liste : un dérivé publié sans aucun des mots qu'elle porte reste
        accepté. Rien de ce que vLLM expose ne permet de trancher — l'`id` est
        la seule chose qu'on ait, et « `…-ct-juridique-v3` » est indiscernable
        d'une déclinaison de l'éditeur pour qui ne connaît pas les deux noms.

        LA BORNE EST DONC ÉCRITE ET MESURÉE, pas refermée par une promesse. Elle
        est plus étroite que celle d'avant — quatre familles nommées en sortent —
        et elle n'est pas nulle.
        """
        muet = f"{self._ID_REEL}-juridique-v3"
        assert self._modele_servi_pour(monkeypatch, muet) == muet, (
            "cette scène MESURE la borne : si elle rougit, c'est que la borne s'est "
            "déplacée et que la docstring de la relation doit être réécrite"
        )

    def test_la_borne_qui_reste_les_frontieres_jetees_confondent_deux_modeles_reels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA SECONDE BORNE QUI RESTE, ET ELLE EST STRUCTURELLE, PAS NÉGLIGÉE.

        `_forme_comparable` jette les `-`, les `/` et les `:` **parce qu'ils ne
        tombent pas au même endroit** dans les deux écosystèmes : `gemma4:e4b`
        donne `gemma4|e4b` et `google/gemma-4-E4B-it…` donne `gemma|4|e4b`. Exiger
        que l'aiguille tombe sur des frontières de segments refuserait donc l'`id`
        RÉELLEMENT SERVI par ce poste — c'est-à-dire la régression que la mutation
        M2 garde.

        LE PRIX EST ÉCRIT : `qwen2:5b` est reconnu dans `Qwen/Qwen-2.5B-Chat`, et
        ce sont deux modèles réels et distincts. Cette borne-là ne se ferme pas
        sans fermer le cas nominal, et ce test la mesure pour qu'elle cesse d'être
        une supposition.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "qwen2:5b")
        releve, _ = _sonder(
            monkeypatch,
            {
                **self._VERSION_VLLM,
                "/v1/models": _ReponseHttp(200, self._catalogue("Qwen/Qwen-2.5B-Chat")),
            },
        )
        assert releve is not None
        assert releve.modele_servi == "Qwen/Qwen-2.5B-Chat", (
            "si cette scène rougit, la relation a cessé de jeter les frontières — "
            "et l'`id` réel de ce poste est alors refusé : mesurer avant de se réjouir"
        )

    def test_un_derive_n_est_pas_memorise_et_c_est_la_consequence_chere(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE REFUS NE SUFFIT PAS : IL FAUT QUE LE DÉRIVÉ NE SOIT PAS FIGÉ À VIE.

        C'est la conséquence que la non bloquante chiffrait, et elle survit au
        redémarrage du serveur d'en face : un nom mémorisé ne se répare qu'en
        redémarrant l'agent. Le test compte donc les requêtes d'un second
        battement au lieu de relire le champ.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        releve, client = _sonder(
            monkeypatch,
            {
                **self._VERSION_VLLM,
                "/v1/models": _ReponseHttp(
                    200, self._catalogue(f"{self._ID_REEL}-abliterated")
                ),
            },
        )
        assert releve is not None
        assert releve.modele_servi is None
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) > premier, (
            "un dérivé a été figé pour la vie du processus sous notre nom"
        )


class TestLeSensDeLaRelationEstBORNEEtLeCoutEstCOMPTE:
    """NON BLOQUANTE §3 DE L'AUDIT DU 15 SEPTEMBRE 2026 — une phrase « jamais », fausse.

    Le site écrivait : « le nom servi est plus LONG que le nom demandé, **jamais
    l'inverse** », et en tirait la justification du sens de l'inclusion. C'est une
    affirmation POSITIVE, et elle est fausse : un tag Ollama nomme couramment la
    variante d'instruction et la quantification, que ce site croyait propres aux
    `id` vLLM. **Une borne écrite mais fausse est pire qu'une borne absente**,
    parce qu'on cesse de vérifier ce qu'elle prétend couvrir.

    LA PHRASE A ÉTÉ RENDUE EXACTE AU SITE. Ce qui reste ici est ce qui manquait :
    les trois formes **gardées**, et le coût **compté** au lieu d'être décrit.
    Sans ces scènes, la phrase corrigée serait elle aussi laissée seule — et la
    prochaine réécriture du site n'aurait rien à faire rougir.

    LES TROIS FORMES SONT PUBLIÉES, PAS INVENTÉES : `-instruct-q8_0` et
    `-it-q4_K_M` sont des suffixes de tag Ollama courants, et `hf.co/…:Q4_K_M`
    est la forme exacte sous laquelle Ollama tire un modèle de HuggingFace.

    PROSPECTIF SUR CE DÉPÔT, ET IL FAUT LE DIRE : le réglage versionné est
    `gemma4:e4b`, qui ne porte pas de quantification, donc le défaut ne mord pas
    aujourd'hui. Il mord le jour où un exploitant pose un tag complet dans la
    variable d'environnement du modèle — un geste ordinaire, et rien ne l'en
    empêche.
    """

    _VERSION_VLLM = {"/version": _ReponseHttp(200, {"version": "0.28.0"})}

    # Les trois formes de l'audit, chacune avec l'`id` que le serveur sert
    # RÉELLEMENT en face — donc trois serveurs parfaitement sains.
    _FORMES_NON_RECONNUES = (
        ("llama3:8b-instruct-q8_0", "meta-llama/Llama-3-8B-Instruct"),
        ("gemma4:e4b-it-q4_K_M", "google/gemma-4-E4B"),
        (f"hf.co/{_ID_VLLM_REEL}:Q4_K_M", _ID_VLLM_REEL),
    )

    def _catalogue(self, identifiant: str) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": identifiant, "object": "model", "max_model_len": 32768}],
        }

    def test_les_trois_formes_de_tag_ne_sont_pas_reconnues_et_c_est_epingle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA BORNE, MESURÉE DANS LE SENS OÙ ELLE EST FAUSSE POUR L'EXPLOITANT.

        Ces trois serveurs servent EXACTEMENT ce qu'on leur demande, et le relevé
        publie `modele_servi: null`, dont `signature_du_moteur` tire « modèle
        ABSENT DU SERVEUR ». Ce test ne réclame pas que ce soit réparé : il
        épingle que ça ne l'est pas, pour que la phrase du site cesse d'être
        seule.
        """
        from src.api import main

        for tag, identifiant in self._FORMES_NON_RECONNUES:
            monkeypatch.setattr(main.settings, "ollama_model", tag)
            releve, _ = _sonder(
                monkeypatch,
                {
                    **self._VERSION_VLLM,
                    "/v1/models": _ReponseHttp(200, self._catalogue(identifiant)),
                },
            )
            assert releve is not None, "un serveur qui a dit son nom n'est pas muet"
            assert releve.modele_servi is None, (
                f"le tag {tag!r} est désormais reconnu dans {identifiant!r} : la borne "
                "écrite au site a bougé, et la docstring de "
                "`_le_serveur_sert_ce_que_nous_demandons` doit être réécrite AVEC son coût"
            )

    def test_le_temoin_le_tag_versionne_de_ce_depot_est_bien_reconnu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TÉMOIN INERTE DE CETTE CLASSE, et il est indispensable.

        Sans lui, les trois `None` ci-dessus seraient satisfaits par une relation
        qui ne reconnaît plus rien du tout — le cas que la mutation M2 de l'audit
        garde, et dont le coût est le même re-sondage permanent, mais pour TOUS
        les exploitants au lieu de ceux qui posent un tag complet.
        """
        from src.api import main

        monkeypatch.setattr(main.settings, "ollama_model", "gemma4:e4b")
        releve, _ = _sonder(
            monkeypatch,
            {**self._VERSION_VLLM, "/v1/models": _ReponseHttp(200, self._catalogue(_ID_VLLM_REEL))},
        )
        assert releve is not None
        assert releve.modele_servi == _ID_VLLM_REEL

    def test_le_cout_est_compte_en_requetes_et_non_decrit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE CHIFFRE DE L'AUDIT, REJOUÉ ICI COMME GARDE : 9 CONTRE 3 SUR TROIS BATTEMENTS.

        C'est ce qui sépare une borne écrite d'une borne gardée. Un tag non
        reconnu n'est jamais mémorisé, donc la sonde repart **à chaque
        battement** : trois requêtes toutes les 20 s, indéfiniment, vers un
        serveur d'inférence partagé avec deux autres équipes. Le témoin, lui,
        paie ses trois requêtes une fois.

        POURQUOI COMPTER PLUTÔT QUE RELIRE `modele_servi`. Le champ nul dit que
        le nom n'est pas reconnu ; il ne dit pas ce que ça COÛTE. C'est le coût
        qui décide si cette borne est acceptable, et c'est donc lui qu'on garde.
        """
        from src.api import main

        def _trois_battements(tag: str, identifiant: str) -> int:
            monkeypatch.setattr(main.settings, "ollama_model", tag)
            _, client = _sonder(
                monkeypatch,
                {
                    **self._VERSION_VLLM,
                    "/v1/models": _ReponseHttp(200, self._catalogue(identifiant)),
                },
            )
            for _ in range(2):
                asyncio.run(main._sonder_moteur_llm())
            return len(client.demandes)

        memorise = _trois_battements("gemma4:e4b", _ID_VLLM_REEL)
        assert memorise == 3, (
            f"le témoin MÉMORISÉ a coûté {memorise} requêtes sur trois battements au lieu "
            "de 3 : c'est la base du rapport, et sans elle le chiffre d'en face ne dit rien"
        )
        for tag, identifiant in self._FORMES_NON_RECONNUES:
            permanent = _trois_battements(tag, identifiant)
            assert permanent == 3 * memorise, (
                f"le tag {tag!r} a coûté {permanent} requêtes sur trois battements au lieu "
                f"de {3 * memorise} : le régime de re-sondage a changé, et le coût écrit "
                "au site de la relation est devenu faux"
            )


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
                    200, {"data": [{"id": _ID_VLLM_REEL, "max_model_len": 32768}]}
                ),
            },
        )
        assert releve is not None
        assert releve.modele_servi == _ID_VLLM_REEL
        premier = len(client.demandes)
        asyncio.run(main._sonder_moteur_llm())
        assert len(client.demandes) == premier, "le second appel est reparti sur le réseau"


class TestLeRegimeDeReSondageEstSIGNALE:
    """RÉSERVE R-4 DE L'AUDIT DU 15 SEPTEMBRE 2026 — lisible, jamais signalé.

    LA MESURE DE L'AUDIT, REPRODUITE : aucun appel à `logger` dans
    `_sonder_moteur_llm` ni dans `_lire_json`, quand `main.py` en compte 17
    ailleurs — un contrôle positif qui établit que le zéro n'est pas une sonde
    aveugle. `_relever` ne journalise que si la tâche **lève** ou dépasse le
    plafond, or un relevé partiel ne fait ni l'un ni l'autre : c'est un retour
    normal. La docstring du prédicat affirmait que le prix « se voit » — il était
    **lisible** dans `/health` pour qui le lit, il n'était jamais **annoncé**.

    CE QUE ÇA COÛTAIT. À 4 320 battements par jour, un relevé qui n'aboutit
    jamais, c'est **8 640 requêtes quotidiennes** vers un serveur d'inférence
    partagé avec deux autres équipes, que rien dans les journaux n'annonce. La
    configuration la plus probable — un tag renommé ou retiré du catalogue — est
    précisément celle qui reste silencieuse.

    CE QUE CE SIGNALEMENT NE CHANGE PAS, et c'est délibéré : ni la réponse de
    `/health`, ni le nombre de requêtes, ni le prédicat de mémorisation. Il rend
    visible un régime qui existait déjà.
    """

    def _journal(
        self, monkeypatch: pytest.MonkeyPatch, routes: dict[str, Any], niveau: int = logging.WARNING
    ) -> list[str]:
        from src.api import main

        messages: list[str] = []
        monkeypatch.setattr(
            main.logger, "warning", lambda msg, *a: messages.append(str(msg) % a if a else str(msg))
        )
        _sonder(monkeypatch, routes)
        return messages

    def test_un_releve_non_memorise_est_annonce_dans_le_journal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La configuration la PLUS PROBABLE : le serveur répond, le tag n'y est pas."""
        messages = self._journal(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, {"models": [{"name": "un-autre:tag"}]}),
            },
        )
        assert messages, "le régime de re-sondage permanent n'est annoncé nulle part"
        joint = " ".join(messages)
        assert "moteur_llm" in joint, "le message ne nomme pas la clé concernée"
        assert "gemma4:e4b" in joint, (
            "le message ne dit pas CE QUI est demandé : un exploitant ne saurait pas "
            "quoi réparer"
        )

    def test_un_releve_complet_ne_dit_rien_du_tout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE CONTRÔLE QUI EMPÊCHE CE SIGNALEMENT DE DEVENIR DU BRUIT.

        Sans lui, un journal qui parle à chaque battement d'un serveur sain
        noierait le seul cas qu'il existe pour montrer — et ce lot en a déjà
        rencontré la forme : un garde qui parle toujours ne distingue plus rien.
        """
        messages = self._journal(
            monkeypatch,
            {
                "/api/version": _ReponseHttp(200, {"version": "0.30.10"}),
                "/api/tags": _ReponseHttp(200, _OLLAMA_TAGS),
            },
        )
        assert messages == [], f"un serveur SAIN fait parler le journal : {messages}"

    def test_un_serveur_muet_n_est_pas_annonce_deux_fois(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un serveur qui n'a dit aucun nom est déjà porté par `_sonder_ollama`.

        Ce signalement-ci porte le régime de RE-SONDAGE d'un serveur qui répond,
        pas la panne d'un service — et la santé du service a son propre garde.
        Les mêler ferait deux lignes pour un seul fait.
        """
        assert self._journal(monkeypatch, {}) == []


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
