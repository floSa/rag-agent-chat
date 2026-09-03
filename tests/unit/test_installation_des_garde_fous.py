"""Le controle d'identite ne doit dependre d'AUCUN arbre de travail.

Ce fichier garde une propriete dont la perte est silencieuse : apres
l'installation documentee, un commit portant une adresse hors liste blanche doit
etre refuse **meme dans un arbre de travail dont `.pre-commit-config.yaml` ne
declare pas le controle d'identite**. Sur les 167 commits de `main`, aucun ne le
declare (``mesure`` le 3 septembre 2026 :
``git rev-list main -- .pre-commit-config.yaml | wc -l`` rend 0, pour
``git rev-list --count main`` = 167) : tout `git checkout` d'un commit ancien,
tout `git bisect`, tout HEAD detache tombe dans ce cas.

Le hook genere par `pre-commit` ouvre sa configuration en chemin RELATIF
(``--config=.pre-commit-config.yaml``). Un controle declare la-dedans est donc
conditionnel a la branche, jamais inconditionnel.

La seule couche independante de l'arbre de travail est ``<type>.legacy``, que
`pre-commit install` cree quand un hook ecrit a la main est deja en place. C'est
ce que ``scripts/installer-les-garde-fous.sh`` monte, et c'est ce que ce fichier
verifie.

CE QUE CE DEPOT A PAYE POUR CE GARDE. Sept commits sont partis avec une adresse
professionnelle sur ce depot personnel : l'historique a ete reecrit, puis le
depot GitHub detruit et recree. ``mesure`` le 3 septembre 2026 :
``api.github.com/repos/floSa/rag-agent-chat`` donne
``created_at = 2026-08-28T07:47:48Z``, quand le plus ancien commit du clone est
date du 2026-04-30 (``git log --reverse --format='%ad' --date=short | head -1``).
Un depot cree quatre mois apres son premier commit est un depot recree.

POURQUOI DES SOUS-PROCESSUS. Le sujet est le comportement de `git commit`, pas
celui d'une fonction Python : rien de ce qui est teste ici n'est importable. On
monte donc un depot git jetable, on y execute le script LIVRE, et on lit le code
de retour et l'etat de HEAD separement — un refus se prouve par les deux, jamais
par la sortie texte.

CE QUI REND CES TESTS NON CREUX. La configuration du depot d'essai est
``repos: []`` : elle ne porte pas le controle d'identite, exactement comme les
167 commits de `main`. Un refus observe ici ne peut donc pas venir d'elle. Et
``test_le_framework_tourne_aussi`` interdit la mutation qui rendrait les autres
verts pour la mauvaise raison — inverser l'ordre des deux gestes laisse le
controle d'identite en place et perd le framework.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
INSTALLEUR = RACINE / "scripts" / "installer-les-garde-fous.sh"
HOOK_IDENTITE = RACINE / "scripts" / "git-hooks" / "pre-commit"
MAKEFILE = RACINE / "Makefile"

# Le chemin tel que la recette du Makefile le nomme, et tel qu'un renommage le
# casserait.
INSTALLEUR_RELATIF = INSTALLEUR.relative_to(RACINE).as_posix()

ADRESSE_INTERDITE = "florian.horellou@aosis.net"
ADRESSE_AUTORISEE = "florian.horellou@gmail.com"

# La configuration d'un arbre de travail qui NE PORTE PAS le controle
# d'identite. `repos: []` evite toute installation d'environnement : le test ne
# touche pas au reseau.
CONFIG_SANS_CONTROLE = "repos: []\n"


def _git(depot: Path, *arguments: str, env: dict[str, str] | None = None):
    """Execute git dans `depot` et rend le CompletedProcess, sans lever."""
    environnement = dict(os.environ)
    environnement.pop("GIT_DIR", None)
    environnement.pop("GIT_WORK_TREE", None)
    if env:
        environnement.update(env)
    return subprocess.run(
        ["git", *arguments],
        cwd=depot,
        env=environnement,
        capture_output=True,
        text=True,
    )


def _identite(adresse_auteur: str, adresse_committer: str) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "floSa",
        "GIT_AUTHOR_EMAIL": adresse_auteur,
        "GIT_COMMITTER_NAME": "floSa",
        "GIT_COMMITTER_EMAIL": adresse_committer,
    }


def _monte_un_depot_jetable(
    depot: Path, contenu_installeur: str
) -> subprocess.CompletedProcess[str]:
    """Monte un depot git jetable et y execute `contenu_installeur`.

    Le depot recoit le hook d'identite LIVRE et une `.pre-commit-config.yaml`
    qui ne declare AUCUN controle d'identite : c'est l'etat des 167 commits de
    `main`. `repos: []` evite toute installation d'environnement de hook, donc
    ce test ne touche pas au reseau.
    """
    scripts = depot / "scripts"
    (scripts / "git-hooks").mkdir(parents=True)
    shutil.copy2(HOOK_IDENTITE, scripts / "git-hooks" / "pre-commit")
    installeur = scripts / INSTALLEUR.name
    installeur.write_text(contenu_installeur)

    (depot / ".pre-commit-config.yaml").write_text(CONFIG_SANS_CONTROLE)

    assert _git(depot, "init", "-b", "principale").returncode == 0
    assert _git(depot, "config", "user.name", "floSa").returncode == 0
    assert _git(depot, "config", "user.email", ADRESSE_AUTORISEE).returncode == 0
    assert _git(depot, "add", "-A").returncode == 0
    assert _git(depot, "commit", "-m", "initial").returncode == 0

    # `PRE_COMMIT` : le depot d'essai n'est pas un projet `uv`, donc le defaut
    # `uv run --no-sync pre-commit` du script n'y trouverait aucun `.venv`. On
    # nomme l'interpreteur qui fait tourner ce test — celui-la meme qui porte le
    # framework, puisque c'est lui qui a lance pytest.
    environnement = dict(os.environ)
    # Comme `_git()`, et pour la meme raison — mais ici elle mord plus fort :
    # c'est le SEUL sous-processus de ce fichier qui ECRIT des hooks. Un
    # `GIT_DIR` herite deporterait l'armement vers le depot qu'il designe, et ce
    # depot est peut-etre celui que ce lot protege.
    environnement.pop("GIT_DIR", None)
    environnement.pop("GIT_WORK_TREE", None)
    environnement["PRE_COMMIT"] = f"{sys.executable} -m pre_commit"
    return subprocess.run(
        ["sh", str(installeur)],
        cwd=depot,
        env=environnement,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def depot_arme(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Un depot jetable, arme par le script LIVRE, sans le hook dans sa config.

    Portee module : le montage coute quelques secondes et aucun test ne le laisse
    modifie — chacun revoque ce qu'il a fait.
    """
    depot = tmp_path_factory.mktemp("depot-arme")
    execution = _monte_un_depot_jetable(depot, INSTALLEUR.read_text())
    assert execution.returncode == 0, (
        f"le script d'installation a echoue :\n{execution.stdout}\n{execution.stderr}"
    )

    # Le depot d'essai ne declare PAS le controle d'identite : tout refus
    # observe ensuite vient donc de la couche `.legacy`, pas de la config.
    assert "identite" not in (depot / ".pre-commit-config.yaml").read_text()

    return depot


class TestLaProtectionNeDependPasDeLArbreDeTravail:
    def test_une_adresse_hors_liste_blanche_est_refusee(self, depot_arme: Path):
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "commit",
            "--allow-empty",
            "-m",
            "essai auteur et committer interdits",
            env=_identite(ADRESSE_INTERDITE, ADRESSE_INTERDITE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        assert resultat.returncode != 0, "le commit a ete accepte"
        assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"

    def test_l_adresse_de_committer_seule_est_refusee(self, depot_arme: Path):
        # L'auteur est valide : c'est le cas que seul un controle portant sur les
        # DEUX identites voit. `git commit --author` le produit sans effort.
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "commit",
            "--allow-empty",
            "-m",
            "essai committer interdit",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_INTERDITE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        assert resultat.returncode != 0, "le commit a ete accepte"
        assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"

    def test_l_adresse_d_auteur_seule_est_refusee(self, depot_arme: Path):
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "commit",
            "--allow-empty",
            "-m",
            "essai auteur interdit",
            env=_identite(ADRESSE_INTERDITE, ADRESSE_AUTORISEE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        assert resultat.returncode != 0, "le commit a ete accepte"
        assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"

    def test_une_adresse_de_la_liste_blanche_passe(self, depot_arme: Path):
        # Sans ce test, tout ce qui precede serait vrai d'un hook qui refuse
        # TOUT — y compris le montage casse, qui echoue faute de trouver son
        # interpreteur.
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "commit",
            "--allow-empty",
            "-m",
            "essai adresse autorisee",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        assert resultat.returncode == 0, (
            f"le commit a ete refuse :\n{resultat.stdout}\n{resultat.stderr}"
        )
        assert apres != avant, "aucun commit n'a ete cree"
        _git(depot_arme, "reset", "--hard", avant)

    def test_le_framework_tourne_aussi(self, depot_arme: Path):
        """Interdit l'inversion des deux gestes du script d'installation.

        Copier le controle d'identite APRES `pre-commit install` laisse tous les
        tests ci-dessus VERTS — le script est bien en place — et perd
        silencieusement les hooks du framework. Ce test asserte donc depuis
        l'autre cote : une configuration dont un hook refuse tout doit refuser
        un commit portant une adresse autorisee.
        """
        config = depot_arme / ".pre-commit-config.yaml"
        original = config.read_text()
        config.write_text(
            "repos:\n"
            "  - repo: local\n"
            "    hooks:\n"
            "      - id: refuse-tout\n"
            "        name: refuse tout\n"
            "        entry: false\n"
            "        language: system\n"
            "        always_run: true\n"
            "        pass_filenames: false\n"
        )
        try:
            avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
            resultat = _git(
                depot_arme,
                "commit",
                "--allow-empty",
                "-m",
                "essai framework",
                env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
            )
            apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

            assert resultat.returncode != 0, (
                "le framework ne tourne pas : son hook « refuse tout » n'a pas arrete le commit"
            )
            assert apres == avant
        finally:
            config.write_text(original)


class TestLAmendEstCouvert:
    """`git commit --amend` reecrit un commit : c'est un geste d'ecriture a part.

    Le montage porte du depot jumeau ne l'assertait NULLE PART. Sa documentation
    l'annoncait couvert — et il l'est — mais aucun test ne le tenait : la
    propriete y vivait sur la seule lecture du code. C'est exactement la forme
    « un garde ne se juge qu'a la mutation qui le fait rougir » appliquee a un
    garde absent.

    Le second test porte le cas subtil, et il est plus fort que ce qu'on attend
    d'un controle d'identite : sur un `--amend`, git EXPORTE dans
    l'environnement du hook l'auteur du commit amende, et non l'identite locale.
    ``mesure`` le 3 septembre 2026, mouchard pose sur `pre-commit.legacy` d'un
    depot jetable :

        MOUCHARD AUTHOR=floSa <florian.horellou@aosis.net> ...
        MOUCHARD COMMITTER=floSa <florian.horellou@gmail.com> ...
        MOUCHARD env GIT_AUTHOR_EMAIL=florian.horellou@aosis.net

    Le hook voit donc l'auteur que l'amend PRODUIRAIT, pas celui que
    `git config` porte. Un amend qui recycle un auteur interdit est refuse alors
    meme que l'identite locale est autorisee. Sans ce test, remplacer
    `git var GIT_AUTHOR_IDENT` par une lecture de `git config user.email`
    laisserait tous les autres tests verts et ouvrirait ce cas.
    """

    def test_un_amend_portant_un_committer_interdit_est_refuse(self, depot_arme: Path):
        depart = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        assert (
            _git(
                depot_arme,
                "commit",
                "--allow-empty",
                "-m",
                "base a amender",
                env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
            ).returncode
            == 0
        )
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        resultat = _git(
            depot_arme,
            "commit",
            "--amend",
            "--allow-empty",
            "--no-edit",
            env=_identite(ADRESSE_INTERDITE, ADRESSE_INTERDITE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        _git(depot_arme, "reset", "--hard", depart)

        assert resultat.returncode != 0, "l'amend a ete accepte"
        assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"

    def test_un_amend_qui_recycle_un_auteur_interdit_est_refuse(self, depot_arme: Path):
        depart = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        arbre = _git(depot_arme, "rev-parse", "HEAD^{tree}").stdout.strip()

        # L'antecedent est fabrique par `git commit-tree`, qui ne declenche
        # AUCUN hook — et non par `git commit --no-verify`, que le mandat
        # interdit et qu'un test n'a aucune raison d'apprendre a quiconque.
        fabrique = _git(
            depot_arme,
            "commit-tree",
            arbre,
            "-p",
            depart,
            "-m",
            "auteur interdit, pose hors des hooks",
            env=_identite(ADRESSE_INTERDITE, ADRESSE_AUTORISEE),
        )
        assert fabrique.returncode == 0, f"{fabrique.stdout}\n{fabrique.stderr}"
        interdit = fabrique.stdout.strip()
        assert _git(depot_arme, "reset", "--hard", interdit).returncode == 0
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint.
        assert (
            _git(depot_arme, "log", "-1", "--format=%ae").stdout.strip() == ADRESSE_INTERDITE
        ), "l'antecedent n'a pas l'auteur interdit : ce test ne mesure plus son cas"

        # L'identite locale est AUTORISEE des deux cotes. Seul l'auteur herite
        # du commit amende est interdit.
        resultat = _git(
            depot_arme,
            "commit",
            "--amend",
            "--allow-empty",
            "--no-edit",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        _git(depot_arme, "reset", "--hard", depart)

        assert resultat.returncode != 0, (
            "l'amend a ete accepte : le controle lit l'identite locale et non "
            "celle du commit produit"
        )
        assert apres == interdit, f"HEAD a bouge : {interdit} -> {apres}"

    def test_un_amend_portant_une_adresse_autorisee_passe(self, depot_arme: Path):
        # Le temoin des deux tests ci-dessus : sans lui, ils seraient vrais d'un
        # montage qui refuse TOUT amend.
        depart = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        assert (
            _git(
                depot_arme,
                "commit",
                "--allow-empty",
                "-m",
                "base a amender",
                env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
            ).returncode
            == 0
        )
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        resultat = _git(
            depot_arme,
            "commit",
            "--amend",
            "--allow-empty",
            "-m",
            "base amendee",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        _git(depot_arme, "reset", "--hard", depart)

        assert resultat.returncode == 0, f"{resultat.stdout}\n{resultat.stderr}"
        assert apres != avant, "l'amend n'a rien reecrit"


class TestUnArbreSansConfigurationResteGarde:
    """Un arbre de travail SANS `.pre-commit-config.yaml` doit rester garde.

    C'est l'etat de **167 des 167 commits de `main`** de ce depot (`mesure` le
    3 septembre 2026, `git cat-file -e <commit>:.pre-commit-config.yaml` sur
    chaque commit de `git rev-list main`). Sur le depot jumeau, dont ce montage
    est porte, le meme comptage donne **1 sur 235** : le fichier y est arrive au
    deuxieme commit du depot. La propriete que son §2.1 range en « fait a
    connaitre » — un arbre sorti a un commit ancien execute les hooks de ce
    commit-la — n'a donc pas la meme portee des deux cotes, et c'est la lecon
    « un raisonnement juste sur un antecedent faux » : l'antecedent est
    234/235 la-bas, 0/167 ici.

    Deux exigences, et il faut les DEUX :

    1. le controle d'identite tient quand meme — c'est `<type>.legacy`, hors de
       l'arbre de travail, qui le porte ;
    2. un commit d'adresse autorisee n'est PAS refuse. Sans
       `--allow-missing-config`, le hook genere par le framework refuse tout sur
       « No .pre-commit-config.yaml file was found » (`mesure`, `rc=1`, HEAD
       immobile), un message qui ne nomme ni la cause ni `make install`. Armer
       les garde-fous briquerait alors `git bisect` et tout `git checkout` d'un
       commit anterieur sur l'historique entier.

    Le second test est celui qui rougit si le drapeau disparait. Le premier est
    celui qui rougit si on croit le remplacer par `-f`, qui supprime la couche
    `.legacy` : les deux ensemble bornent le geste.
    """

    @staticmethod
    def _sans_configuration(depot: Path) -> Path:
        config = depot / ".pre-commit-config.yaml"
        assert config.exists(), "le depot arme devrait porter une configuration"
        config.unlink()
        return config

    def test_une_adresse_interdite_reste_refusee_sans_configuration(self, depot_arme: Path):
        config = self._sans_configuration(depot_arme)
        original = CONFIG_SANS_CONTROLE
        try:
            avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
            resultat = _git(
                depot_arme,
                "commit",
                "--allow-empty",
                "-m",
                "interdit, sans configuration",
                env=_identite(ADRESSE_INTERDITE, ADRESSE_INTERDITE),
            )
            apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

            assert resultat.returncode != 0, "le commit a ete accepte sans configuration"
            assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"
            # Le refus doit venir du controle d'identite, pas de l'absence de
            # configuration : sans cette assertion, ce test serait vert sur le
            # montage qui refuse TOUT, celui-la meme que le test suivant
            # interdit.
            assert "COMMIT REFUSÉ" in resultat.stderr, (
                f"le refus ne vient pas du controle d'identite :\n{resultat.stderr}"
            )
        finally:
            config.write_text(original)

    def test_une_adresse_autorisee_passe_sans_configuration(self, depot_arme: Path):
        config = self._sans_configuration(depot_arme)
        original = CONFIG_SANS_CONTROLE
        try:
            avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
            resultat = _git(
                depot_arme,
                "commit",
                "--allow-empty",
                "-m",
                "autorise, sans configuration",
                env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
            )
            apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

            assert resultat.returncode == 0, (
                "un commit d'adresse autorisee est refuse dans un arbre sans "
                "configuration : les 167 commits de `main` sont briques.\n"
                f"{resultat.stdout}\n{resultat.stderr}"
            )
            assert apres != avant, "aucun commit n'a ete cree"
            _git(depot_arme, "reset", "--hard", avant)
        finally:
            config.write_text(original)


class TestLesCommitsDeFusionSontCouverts:
    """`git commit` n'est pas le seul chemin qui cree un commit.

    `pre-commit install` n'installe que le type `pre-commit`. Une fusion sans
    avance rapide declenche `pre-merge-commit`, et rien d'autre. Un commit de
    fusion portant une adresse interdite partirait donc sans rien rencontrer, et
    le mandat de ce chantier prescrit `--no-ff` pour chaque fusion de lot : ce
    commit-la part sur GitHub, ou la liste des contributeurs ne se defait pas.

    Le trou se ferme des DEUX cotes : le type est installe pour le framework, et
    la copie manuelle est posee sur `pre-merge-commit` comme sur `pre-commit`,
    pour que `pre-merge-commit.legacy` couvre les arbres dont la configuration ne
    porte pas le hook. Sans cette seconde moitie, la fusion serait gardee sur la
    branche du lot et nulle part ailleurs.
    """

    @staticmethod
    def _une_branche_a_fusionner(depot: Path, nom: str) -> None:
        """Cree une branche `nom` portant un fichier a elle, et revient.

        Le nom du fichier derive de celui de la branche : deux appels ne se
        marchent pas dessus. Un harnais non idempotent rendrait ces deux tests
        rouges pour la mauvaise raison — sur « nothing to commit », pas sur leur
        sujet.
        """
        depuis = _git(depot, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert _git(depot, "checkout", "-B", nom, depuis).returncode == 0
        (depot / f"{nom}.txt").write_text(f"apport de {nom}\n")
        assert _git(depot, "add", f"{nom}.txt").returncode == 0
        assert _git(depot, "commit", "-m", f"apport de {nom}").returncode == 0
        assert _git(depot, "checkout", depuis).returncode == 0

    def test_une_fusion_portant_une_adresse_interdite_est_refusee(self, depot_arme: Path):
        self._une_branche_a_fusionner(depot_arme, "fusion-interdite")
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "merge",
            "--no-ff",
            "fusion-interdite",
            "-m",
            "merge interdit",
            env=_identite(ADRESSE_INTERDITE, ADRESSE_INTERDITE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        _git(depot_arme, "merge", "--abort")

        assert resultat.returncode != 0, "la fusion a ete acceptee"
        assert apres == avant, f"HEAD a bouge : {avant} -> {apres}"

    def test_une_fusion_portant_une_adresse_autorisee_passe(self, depot_arme: Path):
        # Le temoin. Sans lui, le test precedent serait vrai d'un montage qui
        # refuse TOUTE fusion — un `pre-merge-commit` casse, par exemple.
        self._une_branche_a_fusionner(depot_arme, "fusion-autorisee")
        avant = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()
        resultat = _git(
            depot_arme,
            "merge",
            "--no-ff",
            "fusion-autorisee",
            "-m",
            "merge autorise",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
        )
        apres = _git(depot_arme, "rev-parse", "HEAD").stdout.strip()

        assert resultat.returncode == 0, f"{resultat.stdout}\n{resultat.stderr}"
        assert apres != avant, "aucun commit de fusion n'a ete cree"
        _git(depot_arme, "reset", "--hard", avant)


class TestLeHarnaisResteDansSonBacASable:
    """Ce fichier ecrit des hooks. Il ne doit les ecrire QUE dans son bac a sable.

    `_git()` purge explicitement `GIT_DIR` et `GIT_WORK_TREE` de
    l'environnement, pour que les commits d'essai aillent bien au depot jetable.
    Le seul sous-processus qui ECRIT des hooks — celui qui execute l'installeur —
    doit les purger aussi : sinon il resout `--git-common-dir` sur le depot
    DESIGNE, et quatre fichiers y partent — `pre-commit`, `pre-commit.legacy`,
    `pre-merge-commit`, `pre-merge-commit.legacy`.

    Ce test asserte depuis le cote qui produit le degat : on DESIGNE un depot par
    `GIT_DIR`, on lance le harnais, et on exige que ce depot ressorte intact.
    """

    def test_git_dir_dans_l_environnement_ne_deporte_pas_les_hooks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        designe = tmp_path / "depot-designe"
        designe.mkdir()
        assert _git(designe, "init", "-q", "-b", "principale", ".").returncode == 0
        hooks_designes = designe / ".git" / "hooks"
        monkeypatch.setenv("GIT_DIR", str(designe / ".git"))

        depot = tmp_path / "depot-sous-git-dir"
        execution = _monte_un_depot_jetable(depot, INSTALLEUR.read_text())

        poses = sorted(
            fichier.name
            for fichier in hooks_designes.iterdir()
            if not fichier.name.endswith(".sample")
        )
        assert not poses, (
            f"le harnais a arme le depot designe par GIT_DIR au lieu du sien : {poses}"
        )
        # Le temoin. Sans lui, l'assertion ci-dessus serait vraie d'un harnais
        # qui n'installe RIEN nulle part — un chemin faux, un interpreteur
        # absent — et ce test serait vert sur le defaut.
        assert execution.returncode == 0, f"{execution.stdout}\n{execution.stderr}"
        assert (depot / ".git" / "hooks" / "pre-commit.legacy").exists(), (
            "le harnais n'a arme aucun hook dans son propre bac a sable"
        )


class TestLeScriptConstateSonPropreResultat:
    """Le script doit ROUGIR quand le montage n'est pas celui qu'il annonce.

    C'est ce qui le distingue d'une consigne ecrite : une consigne suppose que
    le geste a ete fait dans le bon ordre, le script le CONSTATE. Sans ce test,
    le bloc de verification du script serait decoratif — on pourrait le vider
    sans qu'aucun test ne bronche, et l'installation redeviendrait une promesse.

    Le montage casse qu'on lui donne ici est celui que `pre-commit install`
    suggere lui-meme dans sa sortie — « Use -f to use only pre-commit. » — et
    qui supprime la seule couche independante de l'arbre de travail.
    """

    def test_un_installeur_qui_passe_moins_f_est_refuse(self, tmp_path: Path):
        source = INSTALLEUR.read_text()
        mutee = source.replace(
            "$pre_commit install --allow-missing-config $arguments",
            "$pre_commit install -f --allow-missing-config $arguments",
        )
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint.
        # Cette assertion a deja paye : l'ajout de `--allow-missing-config` a
        # l'installeur a tue la mutation precedente, qui visait
        # « $pre_commit install $arguments ». Sans elle, ce test aurait
        # silencieusement cesse de muter quoi que ce soit et serait reste vert.
        assert mutee != source, "la ligne d'installation a change de forme : la mutation est morte"

        depot = tmp_path / "depot-installeur-mute"
        mute = _monte_un_depot_jetable(depot, mutee)

        assert mute.returncode != 0, (
            "un installeur passant -f a rendu 0 : la verification du script "
            f"est morte.\n{mute.stdout}\n{mute.stderr}"
        )
        assert "identite" in mute.stderr, f"le message ne nomme pas ce qui manque :\n{mute.stderr}"
        assert not (depot / ".git" / "hooks" / "pre-commit.legacy").exists()

    def test_un_installeur_qui_ecrase_le_hook_du_framework_est_refuse(self, tmp_path: Path):
        """La MOITIE « le hook genere est-il celui du framework » etait decorative.

        Trouvee par mutation le 3 septembre 2026, dans le montage porte depuis
        `rag-ingestion-pipeline` et dans ce fichier a l'etat ou il venait d'etre
        ecrit — 14 tests : remplacer

            if ! grep -q 'generated by pre-commit' "$genere" 2>/dev/null; then

        par `if false; then` rendait `rc=0` et **0 rouge**. Remesure le meme
        jour, ce test-ci en place : la meme mutation rend **1 rouge**, celui-ci,
        et lui seul. C'est exactement ce qu'on lui demande.

        Le defaut que cette moitie surveille — la copie manuelle passee APRES
        `pre-commit install`, qui ecrase le hook genere — est bien vu par
        d'autres tests, jamais par elle : sur l'inversion complete des deux
        gestes, `<type>.legacy` n'existe pas non plus, donc la seconde moitie du
        bloc rougit et masque la premiere. C'est « deux erreurs qui se
        compensent se cachent mutuellement », vue depuis les gardes.

        COMBIEN D'AUTRES, ET CE QUE CE CHIFFRE VAUT. `mesure` le 3 septembre
        2026, sur cette revision : l'inversion complete rend **15 rouges** dans
        ce fichier, dont **14 autres que ce test-ci** — 12 erreurs au montage de
        la fixture `depot_arme`, et 2 echecs. Une redaction anterieure annoncait
        DOUZE, compte sur un etat anterieur du fichier, et un audit en a mesure
        quinze en comptant ce test-ci : les deux chiffres etaient justes sur leur
        etat, et aucun ne rougit quand le fichier grossit. D'ou la forme
        ci-dessus : le chiffre est borne a sa revision, et ce qu'il compte est
        dit. La propriete qui ne bouge pas, elle, est « au moins un autre test
        voit l'inversion complete » — et c'est elle qui rend ce test-ci
        necessaire, puisque aucun d'eux ne voit la moitie isolee.

        La mutation ci-dessous ISOLE cette moitie-la : on laisse l'ordre livre
        intact — donc `<type>.legacy` est pose et conforme — et on RECOPIE le
        controle d'identite par-dessus le hook genere, juste avant la
        verification. Seule la premiere moitie peut alors rougir. `mesure` le
        3 septembre 2026 : `rc=1`, `legacy conforme=True`,
        `genere est le hook du framework=False`.

        Ce que l'etat mute coute, et c'est pourquoi il doit rougir : le controle
        d'identite y est toujours actif, mais les hooks du framework ont
        disparu — le montage a l'air du bon, et il a perdu une couche.
        """
        source = INSTALLEUR.read_text()
        ancre = "# La verification. C'est elle qui distingue ce script d'une consigne ecrite :"
        assert source.count(ancre) == 1, (
            "l'ancre du bloc de verification a change de forme : la mutation ne mute plus rien"
        )
        recopie = 'for type in $TYPES; do\n    cp "$identite" "$commun/hooks/$type"\ndone\n\n'
        mutee = source.replace(ancre, recopie + ancre, 1)

        depot = tmp_path / "depot-framework-ecrase"
        mute = _monte_un_depot_jetable(depot, mutee)

        assert mute.returncode != 0, (
            "un installeur qui ecrase le hook du framework a rendu 0 : la "
            "premiere moitie de la verification est morte.\n"
            f"{mute.stdout}\n{mute.stderr}"
        )
        assert "framework" in mute.stderr, (
            f"le message ne nomme pas ce qui manque :\n{mute.stderr}"
        )
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint :
        # si `<type>.legacy` avait aussi disparu, ce rouge viendrait de la
        # SECONDE moitie du bloc et ce test ne garderait pas la premiere.
        legacy = depot / ".git" / "hooks" / "pre-commit.legacy"
        assert legacy.exists() and legacy.read_text() == HOOK_IDENTITE.read_text(), (
            "la couche .legacy a disparu : ce test ne mesure plus la moitie "
            "« le hook genere est-il celui du framework »"
        )

    def test_un_installeur_dont_la_liste_de_types_est_vide_est_refuse(self, tmp_path: Path):
        """Une boucle sur une liste VIDE verifie zero chose, et elle est vraie.

        C'est la forme exacte du defaut que ce lot traque, dans le garde-fou de
        ce lot. La boucle de VERIFICATION du script itere la meme variable
        `TYPES` que la boucle d'ARMEMENT : videe, la premiere ne pose aucun
        `<type>.legacy`, la seconde n'a rien a verifier, et le script sortirait
        en 0 en annoncant « Garde-fous armes dans ... » suivi d'une liste vide.
        Le framework, lui, resterait installe : sans `--hook-type`,
        `pre-commit install` retombe sur `default_install_hook_types` de la
        configuration. Le montage a donc exactement l'air du bon, et c'est le
        pire des etats.

        Ce test asserte depuis le cote qui PRODUIT le defaut : on vide la liste
        dans le script LIVRE, et on exige que le script s'en apercoive.
        """
        source = INSTALLEUR.read_text()
        mutee = source.replace('TYPES="pre-commit pre-merge-commit"', 'TYPES=""')
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint :
        # si la ligne `TYPES` change de forme, cette mutation ne mute plus rien
        # et le test resterait vert sans rien garder.
        assert mutee != source, "la ligne TYPES a change de forme : la mutation ne mute plus rien"

        depot = tmp_path / "depot-types-vides"
        mute = _monte_un_depot_jetable(depot, mutee)

        assert mute.returncode != 0, (
            "un installeur dont la liste de types est vide a rendu 0 : il "
            "annonce un montage qu'il n'a pas fait.\n"
            f"{mute.stdout}\n{mute.stderr}"
        )
        assert not (depot / ".git" / "hooks" / "pre-commit.legacy").exists()
        assert not (depot / ".git" / "hooks" / "pre-merge-commit.legacy").exists()

    def test_le_script_livre_passe_sur_le_meme_harnais(self, tmp_path: Path):
        # Le temoin des deux tests precedents : sans lui, un `rc != 0` obtenu
        # pour une raison etrangere a la mutation (un chemin faux, un
        # interpreteur absent) les rendrait verts a tort.
        depot = tmp_path / "depot-installeur-livre"
        livre = _monte_un_depot_jetable(depot, INSTALLEUR.read_text())

        assert livre.returncode == 0, f"{livre.stdout}\n{livre.stderr}"
        assert (depot / ".git" / "hooks" / "pre-commit.legacy").exists()
        assert (depot / ".git" / "hooks" / "pre-merge-commit.legacy").exists()


# ---------------------------------------------------------------------------
# LA CIBLE `install` DU MAKEFILE — le seul geste du depot
#
# Tout ce qui precede garde le SCRIPT. Ces deux classes gardent la CIBLE qui
# l'appelle, et c'est une autre surface : le script peut etre irreprochable et
# ne plus etre appele, ou etre appele apres une etape qui a desarme la porte
# qualite. Les deux etats ont ete mesures a `rc=0` et 0 rouge le 3 septembre
# 2026, sur le lot tel qu'il etait ecrit.
#
# POURQUOI `make -n` ET UN SOUS-PROCESSUS. Une cible de Makefile ne s'importe
# pas. `make -n` imprime la recette que `make` executerait, sans l'executer :
# c'est le point d'entree de la cible qui est mesure, resolution des
# prerequis comprise, et non une lecture du fichier a la main. Rien n'y touche
# ni au reseau, ni au `.venv`, ni aux hooks du clone.
# ---------------------------------------------------------------------------


def _recette_install(makefile: Path) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Rend la recette de `make install` de `makefile`, telle que `make` la voit.

    Le decoupage passe par `shlex` : la propriete a garder porte sur les
    DRAPEAUX passes a `uv`, pas sur le texte de la ligne.
    """
    execution = subprocess.run(
        ["make", "-f", str(makefile), "-n", "install"],
        cwd=RACINE,
        capture_output=True,
        text=True,
    )
    commandes = [shlex.split(ligne) for ligne in execution.stdout.splitlines() if ligne.strip()]
    return execution, commandes


def _arme_les_hooks(commandes: list[list[str]]) -> bool:
    """La recette appelle-t-elle l'installeur de garde-fous LIVRE ?"""
    return any(INSTALLEUR_RELATIF in argument for commande in commandes for argument in commande)


def _retire_des_paquets(commande: list[str]) -> bool:
    """`commande` retire-t-elle des paquets de l'environnement ?

    Ce qui peuple un environnement avec `uv` se range en deux familles, et la
    difference n'est pas cosmetique :

      - `uv pip install` AJOUTE, et ne retire rien — sauf sous `--exact`, qui
        lui donne la semantique de `uv sync` ;
      - `uv sync` et `uv pip sync` RECONCILIENT l'environnement avec ce qui est
        demande, donc retirent tout le reste — `uv sync` sauf sous `--inexact`,
        `uv pip sync` sans echappatoire.

    Ce qui n'est pas `uv` ne peuple pas l'environnement, et rend `False`.
    """
    if not commande or Path(commande[0]).name != "uv":
        return False

    # Les operandes, drapeaux retires : c'est ce qui nomme la sous-commande.
    operandes = [argument for argument in commande[1:] if not argument.startswith("-")]

    if operandes[:2] == ["pip", "install"]:
        return "--exact" in commande
    if operandes[:2] == ["pip", "sync"]:
        return True
    if operandes[:1] == ["sync"]:
        return "--inexact" not in commande
    return False


def _etapes_qui_retirent(commandes: list[list[str]]) -> list[str]:
    """Rend les etapes de la recette qui RETIRENT des paquets de l'environnement.

    La cible `install` n'a le droit qu'a des etapes additives : le `.venv` porte
    les outils que le protocole du §2.2 y a mis, et armer les hooks ne doit pas
    les emporter.
    """
    return [shlex.join(commande) for commande in commandes if _retire_des_paquets(commande)]


class TestLaCibleInstallArmeVraiment:
    """La cible peut cesser d'armer sans qu'un seul test rougisse.

    `mesure` le 3 septembre 2026, sur le lot tel qu'il etait ecrit : retirer la
    ligne `sh scripts/installer-les-garde-fous.sh` de la cible `install` laisse
    `make install` sortir en `rc=0`, rend **0 rouge** sur la batterie, et la
    cible ne pose plus AUCUN hook. C'est mot pour mot le defaut que ce lot
    traque — « un hook declare et non installe est pire qu'absent : on croit
    l'avoir » — dans le seul geste du depot.

    Ce que ces deux tests couvrent ensemble, et ce qu'ils ne couvrent pas : que
    la cible APPELLE l'installeur livre. Que l'installeur, appele, arme et
    constate son propre resultat, est garde par
    `TestLeScriptConstateSonPropreResultat` — quatre tests qui l'executent pour
    de vrai sur un depot jetable. Le maillon qui manquait est celui-ci.
    """

    def test_la_cible_install_appelle_l_installeur_livre(self):
        execution, commandes = _recette_install(MAKEFILE)

        assert execution.returncode == 0, (
            f"`make -n install` a rendu {execution.returncode} :\n"
            f"{execution.stdout}\n{execution.stderr}"
        )
        # Une recette VIDE passerait toute assertion portant sur « aucune etape
        # ne fait X ». Elle n'arme rien non plus.
        assert commandes, "la cible `install` n'a plus aucune etape"

        assert _arme_les_hooks(commandes), (
            f"la cible `install` n'appelle plus {INSTALLEUR_RELATIF} : elle sort "
            f"en 0 sans rien armer.\nrecette :\n{execution.stdout}"
        )
        # Le chemin nomme par la recette doit exister : un renommage de
        # l'installeur sans reprise du Makefile rendrait l'appel inerte.
        assert INSTALLEUR.is_file(), f"{INSTALLEUR_RELATIF} est nomme par la recette et absent"

    def test_une_cible_qui_n_arme_plus_est_vue(self, tmp_path: Path):
        """La mutation qui doit faire rougir le test ci-dessus.

        Sans ce test, `_arme_les_hooks` pourrait rendre `True` sur n'importe
        quoi — une assertion qui ne sait pas dire non ne garde rien.
        """
        source = MAKEFILE.read_text()
        ligne = f"\tsh {INSTALLEUR_RELATIF}\n"
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint.
        assert source.count(ligne) == 1, (
            "la ligne d'armement de la cible `install` a change de forme : la "
            "mutation ne mute plus rien"
        )
        mutee = source.replace(ligne, "")
        assert mutee != source, "la mutation n'a rien change"

        chemin = tmp_path / "Makefile"
        chemin.write_text(mutee)
        execution, commandes = _recette_install(chemin)

        # C'est tout le probleme : la cible mutee reste verte pour `make`.
        assert execution.returncode == 0, (
            "la cible mutee echoue deja : ce test ne mesure plus le defaut "
            "silencieux qu'il decrit"
        )
        assert commandes, "la cible mutee n'a plus aucune etape : mauvaise mutation"
        assert not _arme_les_hooks(commandes), (
            "la cible privee de sa ligne d'armement appelle encore l'installeur :"
            f" le garde ne verrait pas sa disparition.\nrecette :\n{execution.stdout}"
        )


class TestLaCibleInstallNeDesarmeRien:
    """La cible peut desarmer la porte qualite sans qu'un seul test rougisse.

    `mesure` le 3 septembre 2026, dans le `.venv` monte par le protocole du
    §2.2 puis complete par `make install` : la cible passait alors par
    `uv sync --inexact --only-group hooks`, et lui retirer `--inexact` rend
    `rc=0` et **0 rouge** — en ramenant le `.venv` de **183 paquets a 10**.
    `ruff`, `mypy`, `pytest`, `pytest-asyncio` et `pip-audit` en sortent, et le
    `make lint` suivant echoue en `rc=2` sur « mypy: No such file or
    directory ». La cible armait les hooks en desarmant la porte.

    LA PROPRIETE GARDEE EST « ADDITIF », PAS « PAS `uv sync` ». Le troisieme
    test l'exige : la forme bornee d'origine, `--inexact` compris, doit rester
    acceptee. Sans lui, ce garde serait une liste noire de commandes, qui
    vieillirait mal et interdirait une forme correcte.
    """

    def test_la_cible_install_livree_ne_retire_rien(self):
        execution, commandes = _recette_install(MAKEFILE)

        assert execution.returncode == 0, (
            f"`make -n install` a rendu {execution.returncode} :\n{execution.stderr}"
        )
        assert commandes, "la cible `install` n'a plus aucune etape"
        assert _etapes_qui_retirent(commandes) == [], (
            "une etape de `make install` retire des paquets de l'environnement :\n"
            + "\n".join(_etapes_qui_retirent(commandes))
        )

    @pytest.mark.parametrize(
        "remplacement",
        [
            # La mutation du mandat : la forme bornee d'origine, privee de son
            # seul drapeau protecteur.
            "uv sync --only-group hooks",
            # La meme faute dans la forme livree : `--exact` donne a
            # `uv pip install` la semantique de `uv sync`.
            "uv pip install --exact -r requirements-dev.txt",
            "uv pip sync requirements-dev.txt",
        ],
    )
    def test_une_etape_qui_retire_est_vue(self, tmp_path: Path, remplacement: str):
        source = MAKEFILE.read_text()
        ligne = "\tuv pip install -r requirements-dev.txt\n"
        assert source.count(ligne) == 1, (
            "l'etape d'installation de la cible `install` a change de forme : la "
            "mutation ne mute plus rien"
        )
        mutee = source.replace(ligne, f"\t{remplacement}\n")
        assert mutee != source, "la mutation n'a rien change"

        chemin = tmp_path / "Makefile"
        chemin.write_text(mutee)
        execution, commandes = _recette_install(chemin)

        assert execution.returncode == 0, (
            "la cible mutee echoue deja : ce test ne mesure plus le defaut "
            "silencieux qu'il decrit"
        )
        assert _etapes_qui_retirent(commandes) != [], (
            f"« {remplacement} » retire des paquets et le garde ne le voit pas."
            f"\nrecette :\n{execution.stdout}"
        )

    def test_la_forme_bornee_avec_inexact_reste_acceptee(self, tmp_path: Path):
        """Le garde encode « additif », pas une liste noire de sous-commandes.

        `uv sync --inexact` ne retire rien : c'est la forme que ce depot a
        portee jusqu'au 3 septembre 2026, et elle tenait sur CET axe — ce qui
        l'a fait remplacer est un autre axe, le second site qu'elle donnait a la
        version du framework. Un garde qui la refuserait mentirait sur la raison.
        """
        source = MAKEFILE.read_text()
        ligne = "\tuv pip install -r requirements-dev.txt\n"
        assert source.count(ligne) == 1, "l'etape d'installation a change de forme"
        mutee = source.replace(ligne, "\tuv sync --inexact --only-group hooks\n")
        assert mutee != source, "la mutation n'a rien change"

        chemin = tmp_path / "Makefile"
        chemin.write_text(mutee)
        execution, commandes = _recette_install(chemin)

        assert execution.returncode == 0, execution.stderr
        assert _etapes_qui_retirent(commandes) == [], (
            "`uv sync --inexact` est refuse alors qu'il ne retire rien : le garde "
            "est devenu une liste noire.\n" + "\n".join(_etapes_qui_retirent(commandes))
        )
