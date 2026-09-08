"""La chauffe de l'index BM25, et le refus qui la garde.

LA TRAPPE QUE CE FICHIER FERME, ET ELLE ÉTAIT RESTÉE OUVERTE APRÈS AVOIR ÉTÉ
IDENTIFIÉE. L'index lexical de l'agent est **paresseux** : `/health` annonce
`index_lexical: false` après un redémarrage, et la PREMIÈRE recherche le
construit synchroniquement. La campagne de référence du 8 septembre 2026 a
été lancée après une requête de mise en chauffe manuelle, et son compte rendu le
raconte — mais il n'y avait de chauffe **nulle part** dans le code : ni dans
`scripts/evaluate.py`, ni dans le `Makefile`, et aucun test. Un `make eval` sur
une pile fraîchement redémarrée faisait donc passer la question 1 par un index
froid, ce qui abîme précisément la comparabilité **appariée** dont ce dépôt fait
son instrument de décision : la question 1 de la campagne et la question 1 de la
référence ne mesurent alors pas le même chemin de recherche.

**LA DÉCISION, ET SON MOTIF — c'est « les deux », pas « l'un ou l'autre ».**

- *Chauffer seulement* n'est pas fail-closed : la chauffe peut échouer en
  silence — `_lexical_search` absorbe largement et sert la recherche dense
  seule — et la campagne partirait sur un index froid sans qu'un mot le dise.
  C'est la famille du §4.3 : un instrument qui ne mesure pas et ne le dit pas.
- *Refuser seulement* est fail-closed et **inutilisable** : sur une pile
  fraîche, `index_lexical` est TOUJOURS faux jusqu'à ce que quelque chose
  cherche. Un refus sec renverrait donc l'exploitant à la requête de chauffe
  manuelle — c'est-à-dire à sa mémoire, qui est exactement ce que ce chantier
  passe son temps à retirer du chemin critique.

Donc : **on chauffe, puis on vérifie, et on refuse (code 2) si la vérification
ne passe pas.** Le refus ne tombe alors que sur un état qui est une vraie panne,
jamais sur la commodité d'une pile fraîche.

**ET DANS LE PROGRAMME, PAS DANS LA RECETTE.** Le `Makefile` porte DEUX cibles
de campagne — `eval` et `eval-controle` — et une chauffe écrite dans les
recettes serait deux sites qui divergent, la divergence même que
`tests/unit/test_coherence_depot.py` existe pour empêcher. De plus la
documentation invoque `scripts/evaluate.py` directement, et un garde qui vit
dans la recette ne protège pas cet appel. Le code de sortie 2 appartient au
programme qui porte le contrat. Le `Makefile` n'est donc pas touché par ce lot.
"""

import importlib.util
import pathlib

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"


def _evaluate():
    """Charge scripts/evaluate.py sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Reponse:
    """Le strict minimum de l'interface `httpx.Response` que le script utilise."""

    def __init__(self, charge, statut: int = 200) -> None:
        self._charge = charge
        self.status_code = statut

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._charge


def _sante(index_lexical) -> _Reponse:
    return _Reponse({"status": "ok", "services": {"index_lexical": index_lexical}})


class _Agent:
    """Un agent bouchonné dont l'index lexical est PARESSEUX, comme le vrai.

    `index_lexical` est faux jusqu'à ce qu'une recherche arrive : c'est ce
    comportement-là qui est la trappe, et le bouchon le reproduit plutôt que de
    le supposer.
    """

    def __init__(self, *, chaud: bool = False, chauffe_marche: bool = True) -> None:
        self.chaud = chaud
        self.chauffe_marche = chauffe_marche
        self.appels: list[str] = []

    def get(self, url, **_kwargs):
        self.appels.append(f"GET {url}")
        return _sante(self.chaud)

    def post(self, url, **_kwargs):
        self.appels.append(f"POST {url}")
        if not self.chauffe_marche:
            return _Reponse({"detail": "non"}, statut=503)
        self.chaud = True
        return _Reponse({"question": "x", "chunks": []})


def _brancher(monkeypatch, evaluate, agent: _Agent) -> None:
    monkeypatch.setattr(evaluate.httpx, "get", agent.get)
    monkeypatch.setattr(evaluate.httpx, "post", agent.post)


# ─── La chauffe elle-même ─────────────────────────────────────────────────────


def test_un_index_froid_est_chauffe_avant_la_campagne(monkeypatch) -> None:
    """LE CAS QUE LA CAMPAGNE DE RÉFÉRENCE A DÛ FAIRE À LA MAIN."""
    evaluate = _evaluate()
    agent = _Agent(chaud=False)
    _brancher(monkeypatch, evaluate, agent)

    etat = evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    assert etat == evaluate.CHAUFFE_FAITE, etat
    assert any(appel.startswith("POST ") for appel in agent.appels), (
        f"aucune requête de chauffe n'a été émise ({agent.appels}) : ce test ne "
        "prouve rien — c'est l'absence de cette requête qui EST le défaut"
    )
    # Et la vérification a bien eu lieu APRÈS la chauffe : sans ce relevé, une
    # chauffe qui échoue en silence passerait pour une chauffe réussie.
    assert agent.appels.index("POST http://agent/search") < len(agent.appels) - 1
    assert agent.appels[-1] == "GET http://agent/health"


def test_un_index_deja_chaud_ne_paie_pas_de_requete_de_chauffe(monkeypatch) -> None:
    """Une campagne relancée dans la minute ne repaie pas le parcours du corpus."""
    evaluate = _evaluate()
    agent = _Agent(chaud=True)
    _brancher(monkeypatch, evaluate, agent)

    etat = evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    assert etat == evaluate.CHAUFFE_DEJA_CHAUD
    assert agent.appels == ["GET http://agent/health"], agent.appels


# ─── Le refus, et c'est lui qui rend la chauffe fail-closed ───────────────────


def test_une_chauffe_qui_ne_prend_pas_fait_refuser_la_campagne(monkeypatch) -> None:
    """L'INDEX RESTE FROID APRÈS LA CHAUFFE : c'est une panne, pas une commodité.

    Sans ce refus, la campagne partirait sur un index froid — trente minutes de
    génération pour une question 1 non comparable à sa référence.
    """
    evaluate = _evaluate()

    class _AgentQuiResteFroid(_Agent):
        def post(self, url, **_kwargs):
            self.appels.append(f"POST {url}")
            return _Reponse({"question": "x", "chunks": []})  # et `chaud` reste faux

    agent = _AgentQuiResteFroid(chaud=False)
    _brancher(monkeypatch, evaluate, agent)

    etat = evaluate.chauffer_l_index_lexical(
        "http://agent", plafond=6.0, pas=2.0, dormir=lambda _s: None
    )

    assert etat.startswith(evaluate.CHAUFFE_REFUS), etat
    assert "index_lexical" in etat
    assert any(appel.startswith("POST ") for appel in agent.appels), (
        "la chauffe n'a pas été tentée : le refus ne prouve alors rien"
    )


def test_une_requete_de_chauffe_en_erreur_fait_refuser(monkeypatch) -> None:
    """Un `/search` qui rend 503 est un refus, pas un silence."""
    evaluate = _evaluate()
    agent = _Agent(chaud=False, chauffe_marche=False)
    _brancher(monkeypatch, evaluate, agent)

    etat = evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    assert etat.startswith(evaluate.CHAUFFE_REFUS), etat
    assert "503" in etat


def test_un_agent_muet_est_signale_et_n_est_pas_un_refus(monkeypatch) -> None:
    """UN AGENT ABSENT N'EST PAS « UN INDEX PAS PRÊT », et c'est une décision.

    Le contrat de `evaluate.py` réserve déjà un code à « aucune question n'a
    abouti » : **1**, distinct du **2** « la comparaison a été refusée » — garde
    `test_comparaison_appariee.test_sans_agent_joignable_le_script_sort_en_un`,
    et son docstring dit pourquoi la distinction compte. Faire rendre 2 à un
    agent muet réécrirait ce contrat ET ferait mentir le message sur la cause :
    il parlerait d'index lexical alors que rien n'écoute.

    Le trou que cela n'ouvre pas : un agent muet ne peut rien mesurer de faux.
    Le cas dangereux est un agent qui RÉPOND et dont l'index reste froid, et
    celui-là reste un refus — voir les deux tests ci-dessus.

    On n'émet non plus AUCUNE chauffe vers un agent muet : elle ne peut
    qu'échouer, et son échec dirait la même chose une seconde fois.
    """
    evaluate = _evaluate()

    def _get_muet(_url, **_kwargs):
        raise RuntimeError("Connection refused")

    def _post_interdit(_url, **_kwargs):
        raise AssertionError("aucune chauffe ne doit partir vers un agent muet")

    monkeypatch.setattr(evaluate.httpx, "get", _get_muet)
    monkeypatch.setattr(evaluate.httpx, "post", _post_interdit)

    etat = evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    assert etat.startswith(evaluate.CHAUFFE_AGENT_MUET), etat
    assert not etat.startswith(evaluate.CHAUFFE_REFUS), (
        "un agent muet est traité comme un refus de chauffe : le code 2 masquerait "
        "le code 1 du contrat, et le message parlerait d'index à tort"
    )
    assert "Connection refused" in etat


def test_main_ne_refuse_pas_sur_un_agent_muet_et_laisse_venir_le_code_1(
    monkeypatch, tmp_path
) -> None:
    """L'autre moitié de la décision, assertée depuis `main()`."""
    evaluate = _evaluate()
    jeu = tmp_path / "jeu.yaml"
    jeu.write_text(
        "questions:\n  - id: G-001\n    question: q\n    gold_element_ids: ['aaaaaaaaaa']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        evaluate,
        "chauffer_l_index_lexical",
        lambda *_a, **_k: f"{evaluate.CHAUFFE_AGENT_MUET}`/health` illisible — refused",
    )
    tentees: list[str] = []

    def _interroger(_api, question, _timeout):
        tentees.append(question["id"])
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(evaluate, "interroger", _interroger)
    monkeypatch.setattr(
        "sys.argv", ["evaluate.py", "--golden", str(jeu), "--api", "http://agent"]
    )

    assert evaluate.main() == 1
    assert tentees == ["G-001"], (
        f"la campagne n'a pas été tentée ({tentees}) : le 1 vient d'ailleurs que de "
        "« aucune question n'a abouti », et ce test ne prouve rien"
    )


def test_un_health_sans_le_champ_ne_passe_pas_pour_chaud(monkeypatch) -> None:
    """Un agent d'une autre version qui ne publie pas le champ : on refuse.

    `bool(None)` vaut faux, ce qui aurait déclenché une chauffe, puis un refus
    au bout du plafond — mais avec un motif faux (« reste froid ») là où le fait
    est « je ne sais pas lire cet agent ».
    """
    evaluate = _evaluate()

    def _get_sans_champ(_url, **_kwargs):
        return _Reponse({"status": "ok", "services": {"chromadb": True}})

    monkeypatch.setattr(evaluate.httpx, "get", _get_sans_champ)
    monkeypatch.setattr(
        evaluate.httpx,
        "post",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("pas de chauffe ici")),
    )

    etat = evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    assert etat.startswith(evaluate.CHAUFFE_REFUS), etat
    assert "ne publie pas" in etat


# ─── Le raccordement à `main()`, qui est là où le code 2 se décide ────────────


def test_main_refuse_avant_de_poser_la_moindre_question(monkeypatch, tmp_path) -> None:
    """LE REFUS ARRIVE AVANT LA DEMI-HEURE DE GÉNÉRATION, ou il ne sert à rien.

    Le témoin est `interroger`, qui lève : s'il est appelé, le refus est arrivé
    trop tard et le test le dit au lieu de passer.
    """
    evaluate = _evaluate()
    jeu = tmp_path / "jeu.yaml"
    jeu.write_text(
        "questions:\n  - id: G-001\n    question: q\n    gold_element_ids: ['aaaaaaaaaa']\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        evaluate,
        "chauffer_l_index_lexical",
        lambda *_a, **_k: f"{evaluate.CHAUFFE_REFUS}index froid",
    )
    monkeypatch.setattr(
        evaluate,
        "interroger",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("une question a été posée malgré le refus de chauffe")
        ),
    )
    monkeypatch.setattr(
        "sys.argv", ["evaluate.py", "--golden", str(jeu), "--api", "http://agent"]
    )

    assert evaluate.main() == 2


def test_main_laisse_passer_une_chauffe_reussie(monkeypatch, tmp_path) -> None:
    """Et le vert existe : sans lui, le refus ne prouverait rien non plus."""
    evaluate = _evaluate()
    jeu = tmp_path / "jeu.yaml"
    jeu.write_text(
        "questions:\n  - id: G-001\n    question: q\n    gold_element_ids: ['aaaaaaaaaa']\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        evaluate, "chauffer_l_index_lexical", lambda *_a, **_k: evaluate.CHAUFFE_FAITE
    )
    poses: list[str] = []

    def _interroger(_api, question, _timeout):
        poses.append(question["id"])
        return {"answer": "", "sources": [], "contexts": [], "timings": {}}

    monkeypatch.setattr(evaluate, "interroger", _interroger)
    monkeypatch.setattr(
        "sys.argv", ["evaluate.py", "--golden", str(jeu), "--api", "http://agent"]
    )

    assert evaluate.main() == 0
    assert poses == ["G-001"], "la campagne n'a pas tourné : le vert ne prouve rien"


# ─── Ce que la chauffe N'EST PAS ──────────────────────────────────────────────


def test_la_chauffe_ne_passe_pas_par_la_generation(monkeypatch) -> None:
    """`/search` et non `/answer` : la chauffe ne doit pas coûter un LLM.

    Elle n'a besoin que de faire construire l'index BM25, ce que la recherche
    fait synchroniquement. Passer par `/answer` paierait une génération complète
    pour un résultat qu'on jette.
    """
    evaluate = _evaluate()
    agent = _Agent(chaud=False)
    _brancher(monkeypatch, evaluate, agent)

    evaluate.chauffer_l_index_lexical("http://agent", dormir=lambda _s: None)

    postes = [appel for appel in agent.appels if appel.startswith("POST ")]
    assert postes == ["POST http://agent/search"], postes


def test_la_chauffe_n_est_pas_ecrite_dans_le_makefile() -> None:
    """LA DÉCISION EST GARDÉE, pas seulement écrite au docstring.

    Deux cibles de campagne, donc deux sites qui divergeraient. Si un suivant
    déplace la chauffe dans la recette, ce test le lui dit — et le renvoie au
    motif ci-dessus plutôt qu'à sa mémoire.
    """
    makefile = (_RACINE / "Makefile").read_text(encoding="utf-8")
    assert "/search" not in makefile, (
        "une requête de chauffe est écrite dans le Makefile : les deux cibles de "
        "campagne en feraient deux sites divergents, et `scripts/evaluate.py` "
        "invoqué directement ne serait pas protégé"
    )


def test_le_script_appelle_la_chauffe_dans_les_deux_recettes_par_construction() -> None:
    """Un seul site, donc les deux cibles en héritent — c'est le motif de la décision.

    Le test lit le `Makefile` : les deux cibles appellent `scripts/evaluate.py`,
    et c'est CE fait qui rend une chauffe unique suffisante.
    """
    makefile = (_RACINE / "Makefile").read_text(encoding="utf-8")
    for cible in ("eval:", "eval-controle:"):
        bloc = makefile.split(cible, 1)[1].split("\n\n", 1)[0]
        assert "scripts/evaluate.py" in bloc, cible
