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
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
INSTALLEUR = RACINE / "scripts" / "installer-les-garde-fous.sh"
HOOK_IDENTITE = RACINE / "scripts" / "git-hooks" / "pre-commit"
# LE CONTROLE DE POUSSEE, ajoute au montage le 9 septembre 2026. C'est un AUTRE
# script que le controle d'identite, et il le faut : `pre-commit` valide le
# commit qu'on fabrique, `pre-push` valide TOUS les commits de la plage qui
# part, lue sur son entree standard.
HOOK_POUSSEE = RACINE / "scripts" / "git-hooks" / "pre-push"
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
    shutil.copy2(HOOK_POUSSEE, scripts / "git-hooks" / "pre-push")
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
        # LA LISTE EST VIDEE PAR MOTIF, ET NON PAR SA VALEUR LITTERALE. `mesure`
        # le 9 septembre 2026 : ce test recopiait `TYPES="pre-commit
        # pre-merge-commit"`, et l'ajout de `pre-push` au montage l'a fait
        # rougir sur SA PROPRE preuve d'atteinte — la mutation ne mutait plus
        # rien. C'est le bon sens de l'erreur, et le motif retire la cause : un
        # type ajoute ne casse plus la mutation, et un renommage de la variable
        # la fait toujours rougir.
        mutee, remplacements = re.subn(
            r'^TYPES=".*"$', 'TYPES=""', source, count=1, flags=re.M
        )
        # Un test qui choisit lui-meme son cas doit prouver qu'il l'a atteint :
        # si la ligne `TYPES` change de forme, cette mutation ne mute plus rien
        # et le test resterait vert sans rien garder.
        assert remplacements == 1, (
            "la ligne `TYPES=\"...\"` n'a pas ete trouvee une fois exactement dans "
            f"l'installeur ({remplacements} substitution(s)) : la mutation ne mute "
            "plus rien"
        )
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


# ─────────────────────────────────────────────────────────────────────────────
# LA POUSSEE, ET C'EST LE TROU QUE LE 9 SEPTEMBRE 2026 FERME
# ─────────────────────────────────────────────────────────────────────────────


def _pousse(depot: Path, lignes: str, distant: str = "origin"):
    """Execute le hook `pre-push` ARME du depot, avec `lignes` sur son entree.

    C'est la copie posee par l'installeur qui est executee — `<type>.legacy` —
    et non le script du dossier `scripts/`. Un test qui lancerait la source ne
    dirait rien du montage ; celui-ci prouve les deux ensemble.
    """
    hook = depot / ".git" / "hooks" / "pre-push.legacy"
    assert hook.is_file(), (
        f"{hook} n'existe pas : l'installeur n'a pas arme la couche `.legacy` de "
        "`pre-push`, et tout ce qui suit mesurerait le vide"
    )
    environnement = dict(os.environ)
    environnement.pop("GIT_DIR", None)
    environnement.pop("GIT_WORK_TREE", None)
    return subprocess.run(
        ["sh", str(hook), distant, "https://example.invalid/depot.git"],
        cwd=depot,
        input=lignes,
        env=environnement,
        capture_output=True,
        text=True,
    )


_ZEROS = "0" * 40


def _ligne_de_poussee(depot: Path, avant: str, apres: str = "HEAD") -> str:
    """La ligne exacte que git ecrit sur l'entree standard d'un `pre-push`."""
    sha_apres = _git(depot, "rev-parse", apres).stdout.strip()
    return f"refs/heads/principale {sha_apres} refs/heads/principale {avant}\n"


class TestLaPousseeEstGardeeParUnVraiGitPush:
    """LA FAIBLESSE STRUCTURELLE DU BANC D'ESSAI, ET ELLE EST FERMEE ICI.

    **CE QUI MANQUAIT.** `_pousse` lance `sh .git/hooks/pre-push.legacy`
    directement, avec une entree standard FABRIQUEE A LA MAIN. Cette classe-la
    est indispensable et le reste — elle sonde des plages qu'un vrai push ne
    permet pas de construire — mais elle ne prouve NI que `git push` atteint le
    montage, NI **l'etat du distant**, qui est la seule preuve qui compte pour un
    hook de poussee. Ces deux preuves n'existaient que dans des mesures
    ponctuelles, hors du depot : *rien ne les retenait*, et une affirmation sans
    site rejouable devient fausse en silence — c'est le reproche du §4.6, ici
    transpose au banc d'essai.

    **CE QUE CETTE CLASSE ETABLIT, ET COMMENT.** Un depot jetable est monte par
    l'INSTALLEUR LIVRE — donc la couche `.legacy` sous le framework, pas une
    copie a la main —, un distant `--bare` est cree sur le disque, et on appelle
    `git push`. Le verdict se lit sur DEUX axes : le `rc` du processus `git
    push`, et **ce que le distant porte reellement** apres coup. Un `rc` seul ne
    prouve rien ici : le sinistre de ce depot est precisement un `rc=0` sous
    lequel sept commits fautifs sont arrives.

    **AUCUN RESEAU.** Le distant est un `git init --bare` local, `ls-remote` s'y
    resout par le systeme de fichiers. Le cout mesure de cette classe est donne
    par `test_le_cout_de_cette_classe_reste_tenable`.

    **ET LES SCENES SONT CONSTRUITES EN DESARMANT LES HOOKS**, jamais par
    `--no-verify` : c'est aussi la scene reelle, les sept commits qui ont coute
    ce depot etant partis avant qu'aucun hook n'existe.
    """

    @pytest.fixture
    def couple(self, tmp_path: Path) -> tuple[Path, Path]:
        """Un depot arme et un distant `--bare`, relies par `origin`."""
        distant = tmp_path / "distant.git"
        assert _git(tmp_path, "init", "--bare", "-q", str(distant)).returncode == 0
        local = tmp_path / "local"
        execution = _monte_un_depot_jetable(local, INSTALLEUR.read_text())
        assert execution.returncode == 0, f"{execution.stdout}\n{execution.stderr}"
        assert _git(local, "remote", "add", "origin", str(distant)).returncode == 0
        return local, distant

    @staticmethod
    def _commit_hors_hooks(depot: Path, n: int, adresse: str) -> str:
        """Un commit fabrique LES HOOKS DESARMES — jamais `--no-verify`."""
        vide = depot / ".git" / "hooks-desarmes"
        vide.mkdir(exist_ok=True)
        (depot / f"f-{n}.txt").write_text(f"contenu {n}\n")
        assert _git(depot, "add", "-A").returncode == 0
        acheve = _git(
            depot,
            "-c",
            f"core.hooksPath={vide}",
            "commit",
            "-m",
            f"commit {n}",
            env=_identite(adresse, adresse),
        )
        assert acheve.returncode == 0, f"{acheve.stdout}\n{acheve.stderr}"
        return _git(depot, "rev-parse", "HEAD").stdout.strip()

    @staticmethod
    def _adresses_chez_le_distant(distant: Path, ref: str) -> list[str]:
        """Les adresses d'auteur REELLEMENT arrivees. La preuve du hook.

        Rend une liste vide quand la ref n'existe pas chez le distant : c'est le
        resultat attendu d'un refus, et il se distingue d'un `rc` par la seule
        chose qu'un `rc` ne dit pas.
        """
        if _git(distant, "rev-parse", "--quiet", "--verify", ref).returncode != 0:
            return []
        return _git(distant, "log", "--format=%ae", ref).stdout.split()

    def test_un_vrai_git_push_atteint_le_montage_et_refuse(
        self, couple: tuple[Path, Path]
    ) -> None:
        """LA PREUVE D'ATTEINTE QUE TOUT LE RESTE DE CE FICHIER SUPPOSAIT.

        `git push` — le programme, pas une entree fabriquee — traverse le hook
        genere par `pre-commit`, atteint la couche `.legacy`, et le refus
        empeche la ref d'arriver. Sans ce test, la batterie entiere pourrait
        etre verte avec un montage qui n'est jamais execute.
        """
        local, distant = couple
        propre = self._commit_hors_hooks(local, 1, ADRESSE_AUTORISEE)
        fautif = self._commit_hors_hooks(local, 2, ADRESSE_INTERDITE)
        assert propre != fautif

        acheve = _git(local, "push", "origin", "principale:refs/heads/principale")

        # AXE 1 — le `rc` du processus `git push`, et non celui d'un filtre.
        assert acheve.returncode != 0, (
            "`git push` a reussi : le montage n'est pas atteint par git, ou le "
            f"hook ne refuse pas.\n{acheve.stdout}\n{acheve.stderr}"
        )
        assert "POUSSEE REFUSEE" in acheve.stderr, (
            "le refus ne vient pas de ce hook : un autre garde a peut-etre "
            f"refuse, et ce test mesurerait autre chose.\n{acheve.stderr}"
        )

        # AXE 2 — L'ETAT DU DISTANT, la seule preuve qui compte.
        assert self._adresses_chez_le_distant(distant, "refs/heads/principale") == [], (
            "la ref est arrivee chez le distant MALGRE le refus : sur ce depot, "
            "une poussee ne se defait pas"
        )

    def test_le_sinistre_de_ce_depot_est_desormais_refuse(
        self, couple: tuple[Path, Path]
    ) -> None:
        """LA SEQUENCE EXACTE QUI A COUTE CE DEPOT, ET ELLE PASSAIT EN SILENCE.

        Le distant est **detruit et recree vide** apres une poussee reussie ; la
        ref de suivi locale, elle, SURVIT. C'est ce qui est arrive a ce depot —
        `created_at = 2026-08-28` pour un premier commit du 2026-04-30.

        `mesure` le 9 septembre 2026, hook alors INTACT, avant toute mutation :

            ce que le hook verifiait : **0** commit
            ce qui partait           : **10** commits
            `rc` du `git push`       : **0**
            arrive chez le distant   : **7** sous l'adresse non autorisee

        La cause : `--not --remotes=<distant>` lit `refs/remotes/`, un CACHE
        LOCAL que la recreation du distant rend menteur. La borne est desormais
        `git ls-remote` — l'etat REEL. Voir le motif ecrit au site.
        """
        local, distant = couple
        for n in range(1, 4):
            self._commit_hors_hooks(local, n, ADRESSE_INTERDITE)
        for n in range(4, 6):
            self._commit_hors_hooks(local, n, ADRESSE_AUTORISEE)

        # Premiere poussee : LES HOOKS DESARMES, parce que la scene commence
        # apres une poussee qui a eu lieu quand le garde n'existait pas.
        vide = local / ".git" / "hooks-desarmes"
        assert _git(
            local,
            "-c",
            f"core.hooksPath={vide}",
            "push",
            "origin",
            "principale:refs/heads/principale",
        ).returncode == 0
        suivi = _git(local, "rev-parse", "refs/remotes/origin/principale").stdout.strip()
        assert suivi, "la ref de suivi n'a pas ete ecrite : la scene ne demarre pas"

        # LE SINISTRE — le distant est detruit et recree VIDE.
        shutil.rmtree(distant)
        assert _git(local, "init", "--bare", "-q", str(distant)).returncode == 0

        # PREUVE D'ATTEINTE 1 — le distant est bien vide, et le cache survit.
        assert _git(local, "ls-remote", "origin").stdout.strip() == "", (
            "le distant recree n'est pas vide : la scene du sinistre n'est pas atteinte"
        )
        assert _git(
            local, "rev-parse", "refs/remotes/origin/principale"
        ).stdout.strip() == suivi, (
            "la ref de suivi locale n'a pas survecu a la recreation : c'est "
            "pourtant elle qui rendait l'ancienne borne menteuse"
        )

        # PREUVE D'ATTEINTE 2 — L'ANCIENNE borne verifiait bien ZERO commit.
        ancienne = _git(
            local, "rev-list", "HEAD", "--not", "--remotes=origin"
        ).stdout.split()
        assert ancienne == [], (
            "`--not --remotes=origin` ne replie plus la plage sur le vide : la "
            f"scene ne reproduit plus le trou mesure ({len(ancienne)} commits)"
        )

        acheve = _git(local, "push", "origin", "principale:refs/heads/principale")

        assert acheve.returncode != 0, (
            "LA SEQUENCE EXACTE DU SINISTRE DE CE DEPOT REPASSE EN SILENCE. "
            "Cinq commits partent, trois sous une adresse non autorisee, et le "
            f"hook n'a rien verifie.\n{acheve.stdout}\n{acheve.stderr}"
        )
        arrivees = self._adresses_chez_le_distant(distant, "refs/heads/principale")
        assert arrivees == [], (
            f"des commits sont ARRIVES chez le distant recree : {sorted(set(arrivees))}. "
            "C'est l'incident irreversible que ce hook existe pour empecher — la "
            "liste des contributeurs, une fois constituee, ne se defait pas"
        )

    def test_une_branche_neuve_sur_une_histoire_REELLEMENT_poussee_passe(
        self, couple: tuple[Path, Path]
    ) -> None:
        """LA BORNE LEGITIME, ET SANS ELLE LE GARDE SERAIT ARRACHE.

        Une branche NEUVE dont l'histoire ancienne — non conforme, anterieure au
        garde — est **reellement** chez le distant doit PASSER. C'est le
        compromis que ce hook defend, et il est legitime : refuser la premiere
        poussee d'une branche neuve sur du passe qu'on ne reecrira pas
        enseignerait le seul geste que ce chantier interdit.

        *Si la reparation de la bloquante avait fait refuser ce geste, elle
        aurait remplace un trou par un garde qu'on desarme.* C'est ce test qui
        l'interdit, et il pousse POUR DE VRAI.
        """
        local, distant = couple
        for n in range(1, 4):
            self._commit_hors_hooks(local, n, ADRESSE_INTERDITE)
        ancien = _git(local, "rev-parse", "HEAD").stdout.strip()
        vide = local / ".git" / "hooks-desarmes"
        assert _git(
            local,
            "-c",
            f"core.hooksPath={vide}",
            "push",
            "origin",
            "principale:refs/heads/principale",
        ).returncode == 0

        # PREUVE D'ATTEINTE 1 — le distant porte REELLEMENT cette histoire, et
        # c'est ce qui distingue cette scene de la fiction d'un `update-ref`.
        assert ancien in _git(local, "ls-remote", "origin").stdout, (
            "le distant ne porte pas l'histoire ancienne : la scene retomberait "
            "sur le cas « distant vide », qui est celui du sinistre"
        )

        assert _git(local, "checkout", "-q", "-b", "sujet").returncode == 0
        neufs = [self._commit_hors_hooks(local, n, ADRESSE_AUTORISEE) for n in (10, 11)]

        acheve = _git(local, "push", "origin", "sujet:refs/heads/sujet")

        assert acheve.returncode == 0, (
            "la premiere poussee d'une branche neuve est refusee alors que son "
            "histoire ancienne est REELLEMENT chez le distant. Le garde serait "
            f"desarme le premier jour.\n{acheve.stdout}\n{acheve.stderr}"
        )
        # PREUVE D'ATTEINTE 2 — la branche est bien arrivee, et entiere.
        arrivees = self._adresses_chez_le_distant(distant, "refs/heads/sujet")
        # SIX et non cinq : `_monte_un_depot_jetable` pose un commit « initial »
        # conforme avant tout le reste. Le compte a ete corrige par la mesure —
        # un compte suppose aurait rendu ce test vert pour la mauvaise raison.
        assert len(arrivees) == 6, (
            f"la branche neuve n'est pas arrivee entiere : {len(arrivees)} commits"
        )
        assert arrivees.count(ADRESSE_INTERDITE) == 3, (
            "l'histoire ancienne non conforme n'est plus chez le distant : la "
            "scene ne mesure plus la borne"
        )
        for neuf in neufs:
            assert _git(
                distant, "rev-parse", "--quiet", "--verify", neuf
            ).returncode == 0, f"le commit conforme {neuf[:12]} n'est pas arrive"

    def test_une_ref_EXISTANTE_atteint_bien_sa_branche_de_code(
        self, couple: tuple[Path, Path]
    ) -> None:
        """LE PIEGE QUE L'AUDIT A PAYE : cette scene exige une ref PREEXISTANTE.

        La branche « ref existante » du hook — `$sha_distant..$sha_local` — est
        la seule saine des deux, `sha_distant` venant de la negociation REELLE
        avec le distant. Mais on ne l'atteint qu'avec une ref distante deja en
        place : sans elle, git passe 40 zeros et c'est l'AUTRE branche qui
        tourne. L'auditeur a rendu un bon `rc` pour cette mauvaise raison, et
        *l'ordre des gestes n'etait ecrit nulle part* — il l'est ici.

        La preuve d'atteinte est donc que la ligne d'entree porte un
        `sha_distant` NON NUL, verifie avant de conclure quoi que ce soit.
        """
        local, distant = couple
        propre = self._commit_hors_hooks(local, 1, ADRESSE_AUTORISEE)
        vide = local / ".git" / "hooks-desarmes"
        assert _git(
            local,
            "-c",
            f"core.hooksPath={vide}",
            "push",
            "origin",
            "principale:refs/heads/principale",
        ).returncode == 0

        # PREUVE D'ATTEINTE — la ref distante PREEXISTE, donc git passera son
        # sha et non 40 zeros. C'est ce fait, et lui seul, qui fait tourner la
        # branche « ref existante ».
        annonce = _git(local, "ls-remote", "origin", "refs/heads/principale").stdout
        assert propre in annonce, f"la ref distante n'est pas en place : {annonce!r}"

        fautif = self._commit_hors_hooks(local, 2, ADRESSE_INTERDITE)
        acheve = _git(local, "push", "origin", "principale:refs/heads/principale")

        assert acheve.returncode != 0, (
            f"un commit non conforme passe sur une ref EXISTANTE.\n{acheve.stderr}"
        )
        assert fautif[:12] in acheve.stderr, (
            f"le refus ne nomme pas le commit fautif.\n{acheve.stderr}"
        )
        # L'ETAT DU DISTANT : la ref est restee sur le commit propre.
        # DEUX et non un : le commit « initial » du depot jetable est conforme
        # lui aussi. La ref est donc restee exactement ou elle etait.
        assert self._adresses_chez_le_distant(distant, "refs/heads/principale") == [
            ADRESSE_AUTORISEE,
            ADRESSE_AUTORISEE,
        ], "le commit fautif est arrive, ou la ref propre a disparu"

    def test_le_cout_de_cette_classe_reste_tenable(self) -> None:
        """LA MESURE QUE L'AUDIT DEMANDE, ET ELLE DECIDE DE L'HEBERGEMENT.

        Un vrai `git push` sort du processus, monte un depot par l'installeur et
        cree un distant : c'est plus cher qu'un appel de fonction. La question
        « est-ce que ces tests tiennent dans la batterie UNITAIRE » se tranche
        par une mesure, pas par une impression.

        `mesure` le 9 septembre 2026, recette du site `pytest tests/unit/` :
        cette classe coute **quelques secondes**, aucun acces reseau — le
        distant est un `git init --bare` local et `ls-remote` s'y resout par le
        systeme de fichiers. Elle reste donc ICI, et non dans
        `tests/integration/`, qui exige la pile demarree et ne tourne pas dans
        la porte.

        Ce test tient la propriete qui rendrait la reponse fausse : **aucune URL
        distante de cette classe ne sort de la machine.** Si un distant `http`
        ou `ssh` y entrait un jour, `ls-remote` pourrait pendre 30 s par test —
        le `timeout` du hook — et la porte deviendrait inutilisable.
        """
        source = Path(__file__).read_text(encoding="utf-8")
        debut = source.index("class TestLaPousseeEstGardeeParUnVraiGitPush")
        # BORNE SUR LA CLASSE, ET NON JUSQU'A LA FIN DU FICHIER. La premiere
        # ecriture prenait `source[debut:]`, donc TOUTE la suite du fichier :
        # elle rougissait sur une URL ecrite dans une AUTRE classe. `mesure` le
        # 9 septembre 2026 — un faux rouge, et le second de ce test.
        suite = source.find("\nclass ", debut + 1)
        corps = source[debut : suite if suite > 0 else len(source)]

        # PREUVE D'ATTEINTE : le corps borne ne contient plus AUCUNE definition
        # de classe apres la sienne. Formule sur la STRUCTURE et non sur le nom
        # de la classe suivante : ce nom est cite dans le docstring ci-dessus,
        # et l'assertion se serait reconnue elle-meme — troisieme faux rouge de
        # cette meme famille dans ce seul test, `mesure` le 9 septembre 2026.
        assert corps.count("\nclass ") == 0, (
            "la borne de lecture deborde sur la classe suivante : ce test "
            "balaierait un corps qui n'est pas le sien"
        )

        # PREUVE D'ATTEINTE : on lit bien le corps de CETTE classe, et il porte
        # la creation du distant local.
        assert 'init", "--bare"' in corps, (
            "le corps lu ne porte plus la creation du distant `--bare` : ce test "
            "balaie autre chose que ce qu'il croit"
        )
        # **LES SCHEMAS SONT ASSEMBLES A L'EXECUTION, ET C'EST UNE CORRECTION
        # MESUREE.** Ecrits en litteral, ils se reconnaissaient EUX-MEMES : ce
        # test rougissait sur sa propre ligne de motif, et ses deux seules
        # sorties auraient ete `--no-verify` ou le retrait du garde. C'est mot
        # pour mot le defaut que le lot 7 a corrige dans `e42d3e6` pour le motif
        # de secret du hook, retrouve ici contre ce test-ci. `mesure` le
        # 9 septembre 2026, premiere execution de cette classe.
        separateur = ":" + "//"
        schemas = [protocole + separateur for protocole in ("http", "https", "ssh", "git")]
        schemas.append("git" + "@")

        # PREUVE D'ATTEINTE : le motif reconnait bien ce qu'il cherche.
        assert any(schema in "un distant https" + separateur + "exemple" for schema in schemas), (
            f"les schemas assembles ne reconnaissent plus une URL : {schemas}. "
            "Ce test comparerait alors le corps a un motif inerte"
        )
        for schema in schemas:
            assert schema not in corps, (
                f"un distant {schema!r} est apparu dans cette classe : `ls-remote` "
                "peut alors pendre jusqu'au `timeout` du hook a chaque test, et la "
                "porte de ce depot deviendrait inutilisable. Le distant doit "
                "rester un `git init --bare` local"
            )


class TestLaPousseeEstGardeeSurTouteLaPlage:
    """LE TROU FERME LE 9 SEPTEMBRE 2026, ET SA DIFFICULTE PROPRE.

    Le garde-fou d'identite couvrait `pre-commit` et `pre-merge-commit`, jamais
    `push`. Les NEUF poussees de ce chantier ont chacune ete protegees par une
    verification que le pilote ecrivait A LA MAIN — et l'asymetrie de gravite
    est entiere : un commit local se defait, une poussee non. Sept commits
    partis sous une adresse professionnelle ont coute la reecriture de 165
    commits PUIS la destruction et la recreation du depot sur GitHub.

    **CE QUI REND CE HOOK DIFFERENT DE `pre-commit`, ET C'EST LE PIEGE.**
    `pre-commit` valide LE commit qu'on fabrique. `pre-push` doit valider TOUS
    les commits de la plage qui part, et cette plage lui arrive sur son ENTREE
    STANDARD. Un hook qui ne verifierait que `HEAD` laisserait passer neuf
    commits sur dix, et il serait VERT sous toute scene ou le defaut n'est pas
    en tete — la huitieme occurrence dans ce chantier de « un garde vert sous
    une scene que le defaut ne rencontre jamais ».

    **C'EST POURQUOI LE CAS CENTRAL DE CETTE CLASSE EST UN COMMIT DU MILIEU.**
    `test_un_commit_du_milieu_de_la_plage_est_refuse` construit une plage de
    cinq commits dont le TROISIEME porte une adresse non autorisee, HEAD etant
    conforme. Un hook qui regarde `HEAD` passe ; celui-ci refuse, et il nomme le
    commit.

    **ET LES DEUX SENS**, parce qu'un `pre-push` qui refuse tout est aussi
    inutile qu'un `pre-push` qui accepte tout : une plage propre passe, et la
    plage REELLE de ce depot — 276 commits, 83 129 lignes ajoutees traversees
    par le controle de secret — passe aussi, ce qui est mesure par
    `test_la_plage_reelle_de_ce_depot_passe`.
    """

    @pytest.fixture
    def depot_pousse(self, tmp_path: Path) -> Path:
        """Un depot arme, avec une plage de cinq commits par-dessus l'initial.

        Portee fonction et non module : chaque test de cette classe reecrit ou
        etend l'historique, et un etat partage rendrait leurs plages
        dependantes de l'ordre de collecte.
        """
        depot = tmp_path / "depot-poussee"
        execution = _monte_un_depot_jetable(depot, INSTALLEUR.read_text())
        assert execution.returncode == 0, f"{execution.stdout}\n{execution.stderr}"
        return depot

    def _commit(
        self,
        depot: Path,
        n: int,
        adresse: str,
        message: str = "",
        committer: str | None = None,
    ) -> None:
        """Fabrique un commit dans la plage, LE `pre-commit` MIS DE COTE.

        **JAMAIS PAR `--no-verify`**, que ce chantier interdit absolument : par
        un `core.hooksPath` pointant sur un repertoire vide, le temps de la
        fabrication. La distinction n'est pas cosmetique — `--no-verify` est un
        geste d'auteur qu'on prend l'habitude de taper, `core.hooksPath` est un
        reglage de harnais qui ne quitte pas ce test.

        **ET LA SCENE AINSI CONSTRUITE EST LA SCENE REELLE.** Un commit non
        conforme dans une plage a poussee ne vient jamais d'un `pre-commit`
        contourne : il vient d'un clone qui n'a jamais tape `make install`, d'un
        `git checkout` ancien qui desarmait le controle en silence avant la
        couche `.legacy`, ou d'un commit anterieur a l'armement du garde-fou.
        C'est exactement l'origine des SEPT commits qui ont coute ce depot : ils
        sont partis avant qu'aucun hook n'existe. Le `pre-push` est la derniere
        barriere, et la seule qui voit la plage.
        """
        vide = depot / ".git" / "hooks-desarmes"
        vide.mkdir(exist_ok=True)
        (depot / f"fichier-{n}.txt").write_text(f"contenu {n}\n")
        assert _git(depot, "add", "-A").returncode == 0
        acheve = _git(
            depot,
            "-c",
            f"core.hooksPath={vide}",
            "commit",
            "-m",
            message or f"commit {n}",
            env=_identite(adresse, committer if committer is not None else adresse),
        )
        assert acheve.returncode == 0, f"{acheve.stdout}\n{acheve.stderr}"

    def test_une_plage_propre_passe(self, depot_pousse: Path) -> None:
        """LE SENS QUI REND L'AUTRE CROYABLE."""
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        for n in range(1, 6):
            self._commit(depot_pousse, n, ADRESSE_AUTORISEE)

        acheve = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
        assert acheve.returncode == 0, (
            "une plage de cinq commits tous conformes est refusee : un `pre-push` "
            f"qui refuse tout est aussi inutile qu'un qui accepte tout.\n"
            f"{acheve.stdout}\n{acheve.stderr}"
        )
        assert acheve.stdout == "", (
            f"le hook parle alors que tout est conforme : {acheve.stdout!r}. Un hook "
            "bavard au succes apprend a ne plus le lire"
        )

    def test_un_commit_du_milieu_de_la_plage_est_refuse(self, depot_pousse: Path) -> None:
        """LE CAS QUI DECIDE DE TOUT — ET LA PREUVE D'ATTEINTE EST EXPLICITE.

        Cinq commits, le TROISIEME sous une adresse non autorisee, HEAD
        conforme. Le test prouve d'abord que la scene est bien celle qu'il
        decrit — HEAD est conforme, le troisieme ne l'est pas — avant de lire le
        `rc` du hook. Un `rc` juste n'est pas une preuve d'atteinte.
        """
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        for n in (1, 2):
            self._commit(depot_pousse, n, ADRESSE_AUTORISEE)
        self._commit(depot_pousse, 3, ADRESSE_INTERDITE)
        fautif = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        for n in (4, 5):
            self._commit(depot_pousse, n, ADRESSE_AUTORISEE)

        # PREUVE D'ATTEINTE — la scene est celle que le docstring annonce.
        plage = _git(depot_pousse, "rev-list", f"{base}..HEAD").stdout.split()
        assert len(plage) == 5, f"la plage n'a pas cinq commits : {plage}"
        assert plage[0] != fautif and plage[-1] != fautif, (
            "le commit fautif est en tete ou en queue de plage : ce test ne "
            "mesure plus ce qu'il decrit"
        )
        assert _git(depot_pousse, "show", "-s", "--format=%ae", "HEAD").stdout.strip() == (
            ADRESSE_AUTORISEE
        ), "HEAD n'est pas conforme : un hook qui ne lit que HEAD rougirait aussi"
        assert _git(depot_pousse, "show", "-s", "--format=%ae", fautif).stdout.strip() == (
            ADRESSE_INTERDITE
        ), "le commit du milieu n'est pas celui qu'on croit"

        acheve = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
        assert acheve.returncode != 0, (
            "une plage dont le TROISIEME commit porte une adresse non autorisee "
            "est acceptee : le hook ne regarde que HEAD, et il laisserait passer "
            f"neuf commits sur dix.\n{acheve.stdout}\n{acheve.stderr}"
        )
        assert ADRESSE_INTERDITE in acheve.stderr, (
            f"le refus ne nomme pas l'adresse fautive : {acheve.stderr!r}"
        )
        assert fautif[:12] in acheve.stderr, (
            f"le refus ne nomme pas le commit fautif : {acheve.stderr!r}. Sur une "
            "plage de cinq, un refus qui ne dit pas lequel ne se corrige pas"
        )

    def test_le_committer_seul_suffit_a_refuser(self, depot_pousse: Path) -> None:
        """L'auteur ET le committer, comme au `pre-commit`.

        Une fusion, un `rebase`, un `cherry-pick` reecrivent le committer en
        gardant l'auteur : c'est le chemin par lequel une adresse interdite
        entre sans qu'on l'ait tapee.
        """
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        self._commit(
            depot_pousse,
            500,
            ADRESSE_AUTORISEE,
            "auteur conforme, committer non",
            committer=ADRESSE_INTERDITE,
        )
        assert _git(depot_pousse, "show", "-s", "--format=%ae", "HEAD").stdout.strip() == (
            ADRESSE_AUTORISEE
        )
        assert _git(depot_pousse, "show", "-s", "--format=%ce", "HEAD").stdout.strip() == (
            ADRESSE_INTERDITE
        )

        refus = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
        assert refus.returncode != 0, (
            "un committer non autorise passe : le hook ne lit que l'auteur, et "
            "toute fusion echappe"
        )

    def test_l_attribution_a_un_assistant_est_refusee(self, depot_pousse: Path) -> None:
        """LES DEUX FORMES QUE CES OUTILS PRODUISENT REELLEMENT.

        Un trailer d'attribution et une ligne de signature. Les deux sont
        construites ici a l'execution, morceau par morceau, pour qu'aucune ne
        soit ecrite en clair dans un fichier de ce depot public.
        """
        formes = (
            "Co-Authored" + "-By: un outil <un@exemple.invalid>",
            "\U0001f916 " + "Generated with [un outil](https://exemple.invalid)",
        )
        for i, forme in enumerate(formes, start=1):
            base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
            self._commit(depot_pousse, 100 + i, ADRESSE_AUTORISEE, f"un travail\n\n{forme}\n")
            assert forme.split("\n")[0] in _git(
                depot_pousse, "show", "-s", "--format=%B", "HEAD"
            ).stdout, "la forme n'est pas dans le message : scene non atteinte"

            refus = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
            assert refus.returncode != 0, (
                f"la forme d'attribution {forme!r} passe la poussee : le hook ne la "
                "voit pas, et le depot est public"
            )

    def test_un_message_qui_RACONTE_la_signature_n_est_pas_refuse(
        self, depot_pousse: Path
    ) -> None:
        """LE DEFAUT DU 9 SEPTEMBRE 2026, ET IL ETAIT LATENT.

        La deuxieme alternative du motif d'attribution — la ligne de
        SIGNATURE — n'etait pas ancree en tete de ligne, contrairement aux trois
        autres. Un message de commit qui NOMME la forme au milieu d'une phrase
        etait donc refuse, et les deux seules sorties etaient `--no-verify` — que
        ce chantier interdit absolument — ou le retrait du garde.

        **C'EST MOT POUR MOT LE DEFAUT CORRIGE DANS `e42d3e6`** pour le motif de
        secret, une ligne plus bas dans le meme fichier : *un garde qui provoque
        la panne qu'il surveille.* Le trouver deux fois dans le meme motif dit
        que la propriete « chaque alternative porte sa borne » doit etre gardee,
        pas relue.

        **LATENT, ET C'EST CE QUI LE RENDAIT INVISIBLE.** `mesure` le 9 septembre
        2026 : `git log --format='%B' | grep -icE 'generated (with|by) \\['` rend
        **0** sur toute l'histoire du depot. Le premier rapport a nommer la forme
        aurait ete le premier a ne plus pouvoir etre commite.

        **LES DEUX DIRECTIONS**, parce que l'ancrage ne doit rien ouvrir : le
        recit passe, et la signature en tete de ligne — indentee comprise — reste
        refusee. La chaine n'est ecrite dans aucun fichier : elle est assemblee
        a l'execution, le depot etant public.
        """
        signature = "Generated" + " with" + " ["
        base_avant_tout = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()

        # SENS 1 — LE RECIT PASSE. Ces trois phrases sont celles qu'un rapport
        # de lot ecrit forcement pour nommer cette fermeture, celui-ci compris.
        recits = (
            f"fix(pre-push): la forme « {signature}… » n'etait pas ancree",
            f"on documente que {signature}Nom] est une forme d'attribution",
            f"le motif refusait {signature}Nom] au milieu d'une phrase de prose",
        )
        for i, recit in enumerate(recits, start=1):
            base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
            self._commit(depot_pousse, 300 + i, ADRESSE_AUTORISEE, recit)
            # PREUVE D'ATTEINTE : la forme est bien dans le message pousse.
            assert signature in _git(
                depot_pousse, "show", "-s", "--format=%B", "HEAD"
            ).stdout, "la forme n'est pas dans le message : scene non atteinte"

            acheve = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
            assert acheve.returncode == 0, (
                f"un message qui RACONTE la forme est refuse : {recit!r}. Les deux "
                "seules sorties seraient `--no-verify`, que ce chantier interdit, "
                f"ou le retrait du garde.\n{acheve.stderr}"
            )

        # SENS 2 — LA FORME EN TETE DE LIGNE RESTE REFUSEE, indentee comprise.
        # Sans ce sens, l'ancrage ne serait pas une correction mais un
        # relachement : le garde accepterait la signature qu'il existe pour voir.
        for i, prefixe in enumerate(("", "   "), start=1):
            base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
            self._commit(
                depot_pousse,
                310 + i,
                ADRESSE_AUTORISEE,
                f"un travail\n\n{prefixe}{signature}un outil](https://exemple.invalid)\n",
            )
            refus = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
            assert refus.returncode == 1, (
                f"la signature prefixee par {prefixe!r} passe desormais : "
                "l'ancrage a ete pose sans `[[:space:]]*`, ou le motif a perdu "
                f"son alternative.\n{refus.stdout}"
            )

        assert base_avant_tout, "garde-fou de lecture"

    def test_une_mention_en_prose_n_est_pas_refusee(self, depot_pousse: Path) -> None:
        """LA BORNE ECRITE DU CONTROLE D'ATTRIBUTION, ET ELLE EST DELIBEREE.

        Ce depot documente sa propre regle sur plusieurs pages, et un message de
        commit qui la raconte est legitime — celui de cette fermeture-ci en est
        un. Un hook qui refuserait le mot enseignerait le seul geste que ce
        chantier interdit absolument : `--no-verify`. Un garde qu'on desarme
        pour travailler ne garde plus rien.
        """
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        self._commit(
            depot_pousse,
            200,
            ADRESSE_AUTORISEE,
            "docs: la regle interdit toute attribution a un assistant de "
            "generation de code, ni auteur ni committer ni trailer",
        )
        acheve = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
        assert acheve.returncode == 0, (
            "un message qui RACONTE la regle est refuse : le controle est devenu "
            "un filtre de vocabulaire, et il enseignerait `--no-verify`.\n"
            f"{acheve.stderr}"
        )

    def test_un_secret_ajoute_est_refuse(self, depot_pousse: Path) -> None:
        """La troisieme verification, sur les lignes AJOUTEES de la plage.

        La forme plantee est un en-tete de cle privee — assemble a l'execution,
        donc absent de tout fichier de ce depot — et elle est plantee dans un
        commit du MILIEU, comme l'adresse.
        """
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        self._commit(depot_pousse, 300, ADRESSE_AUTORISEE)

        entete = "-----BEGIN" + " RSA PRIVATE KEY-----"
        (depot_pousse / "cle.pem").write_text(f"{entete}\nAAAA\n")
        vide = depot_pousse / ".git" / "hooks-desarmes"
        vide.mkdir(exist_ok=True)
        assert _git(depot_pousse, "add", "-A").returncode == 0
        assert _git(
            depot_pousse,
            "-c",
            f"core.hooksPath={vide}",
            "commit",
            "-m",
            "un fichier",
            env=_identite(ADRESSE_AUTORISEE, ADRESSE_AUTORISEE),
        ).returncode == 0
        fautif = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        self._commit(depot_pousse, 301, ADRESSE_AUTORISEE)

        # PREUVE D'ATTEINTE : la ligne est bien AJOUTEE par ce commit.
        ajoutees = _git(depot_pousse, "show", "--format=", "--unified=0", fautif).stdout
        assert f"+{entete}" in ajoutees, (
            "l'en-tete n'apparait pas dans les lignes ajoutees du commit : la "
            "scene n'est pas celle que ce test decrit"
        )

        refus = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, base))
        assert refus.returncode != 0, (
            "une cle privee ajoutee au milieu de la plage part sans rien "
            f"rencontrer.\n{refus.stdout}\n{refus.stderr}"
        )
        assert fautif[:12] in refus.stderr, f"le refus ne nomme pas le commit : {refus.stderr!r}"

    def test_le_motif_de_secret_est_bien_passe_a_grep_et_non_lu_comme_une_option(self) -> None:
        """LE FAUX VERT QUE CE LOT A TROUVE CONTRE LUI-MEME, ET IL EST GARDE.

        Le motif de secret COMMENCE PAR UN TIRET (`-----BEGIN ...`). Passe en
        argument nu, `grep` le lit comme une OPTION : il rend `rc=2` sur
        « unrecognized option », le `if` du hook le lit comme faux, et le hook
        sort en **0 sans avoir rien verifie**. `mesure` le 9 septembre 2026 en
        retournant la premiere ecriture de ce hook contre les 276 commits de ce
        depot : `rc=0`, et le controle n'avait pas tourne une seule fois. Un
        `rc` juste pour la mauvaise raison.

        Le hook passe donc tous ses motifs par `-e`. Ce test tient la propriete
        au niveau du TEXTE du hook, parce que c'est la seule facon de la voir :
        au niveau du comportement, la version fautive et la version juste
        rendent le meme `rc=0` sur un depot sain.
        """
        # LES LIGNES DE COMMENTAIRE SONT ECARTEES, et c'est ce test qui l'a
        # trouve contre lui-meme : le bandeau du hook CITE la forme fautive
        # pour expliquer le piege, et un scan du fichier entier la comptait
        # comme un appel. C'est la meme distinction que le garde de surete du
        # depot — un recit se raconte, une instruction s'execute — a un autre
        # endroit du chantier.
        lignes = [
            ligne
            for ligne in HOOK_POUSSEE.read_text().splitlines()
            if not ligne.lstrip().startswith("#")
        ]
        appels = re.findall(r"grep -q[a-zA-Z]*(?: -e)? [\"']?\$FORMES", "\n".join(lignes))
        assert appels, "aucun appel a grep sur une variable `$FORMES...` : le hook a change"
        sans_e = [appel for appel in appels if " -e " not in appel]
        assert not sans_e, (
            f"un motif est passe a grep SANS `-e` : {sans_e}. Si ce motif commence "
            "par un tiret, grep le lit comme une option, rend rc=2, et le hook sort "
            "en 0 sans avoir rien verifie — le faux vert du 9 septembre 2026"
        )

    def test_le_hook_ne_reconnait_aucune_de_ses_propres_lignes_comme_un_secret(self) -> None:
        """LE DEFAUT QUE CE LOT A TROUVE PAR UN VRAI `git push`, ET IL EST GARDE.

        **La premiere ecriture de ce hook portait une cinquieme alternative de
        secret, l'en-tete d'un format de cle precis, ECRITE EN ENTIER.** Cette
        alternative se reconnaissait elle-meme — et etait de surcroit reconnue
        par la premiere, generique, qui la couvre. La ligne qui pose le motif est
        une ligne AJOUTEE : elle portait donc un « secret », et le hook refusait
        le commit meme qui l'introduit. `mesure` le 9 septembre 2026, `git push`
        reel vers un distant jetable : `rc=1` sur le commit du hook, message
        « une ligne ajoutee porte un secret », **et aucune ref chez le distant**.

        **ET LA BATTERIE ETAIT VERTE QUAND LE DEFAUT EST NE.**
        `test_la_plage_reelle_de_ce_depot_passe` ne l'a vu qu'AU COMMIT SUIVANT,
        le commit fautif n'existant pas encore quand elle a tourne. Un garde qui
        ne peut voir un defaut qu'un commit plus tard est un garde a moitie
        ecrit : ce test-ci le voit AU MOMENT OU LE MOTIF EST ECRIT, sans lire
        aucun historique.

        **ET LA PREMIERE CORRECTION VISAIT LA MAUVAISE CAUSE — mesure par la
        mutation qui devait la reproduire.** Elle assemblait le motif de cle en
        deux variables que le shell recompose, sur le motif « ecrit d'une piece,
        il se reconnait ». Remettre le motif generique d'une piece a laisse cette
        batterie **entierement verte** (`rc=0`, 38 tests) : l'assemblage n'y
        etait pour rien. La vraie cause est l'alternative LITTERALE, et sa
        suppression est la correction complete — elle ne retire aucune
        couverture, la generique la couvrant. L'assemblage a ete retire plutot
        que garde sur un motif faux.

        Ce qui protege les quatre alternatives qui restent est mesure : chacune
        porte, apres son prefixe litteral, une CLASSE de caracteres dont le
        texte source n'est pas membre.
        """
        source = HOOK_POUSSEE.read_text()
        motifs = re.search(r"^FORMES_DE_SECRET='(.+)'$", source, re.M)
        assert motifs, (
            "la variable `FORMES_DE_SECRET` n'est plus posee sous la forme attendue :"
            " ce test ne mesure plus rien"
        )
        compose = motifs.group(1)
        # Une variable du shell dans le motif serait resolue ici. Il n'y en a
        # plus — voir le docstring — mais un futur assemblage ne doit pas rendre
        # ce test aveugle en le laissant comparer un `$NOM` litteral.
        for nom, valeur in re.findall(r"^(_[A-Z_]+)='([^']*)'$", source, re.M):
            compose = compose.replace(f"${nom}", valeur)
        assert "$" not in compose, f"une variable du motif n'a pas ete resolue : {compose}"

        # PREUVE D'ATTEINTE : le motif compose est bien celui qui mord.
        entete = "-----BEGIN" + " RSA PRIVATE KEY-----"
        assert re.search(compose, entete), (
            f"le motif compose ne reconnait plus un en-tete de cle privee : {compose!r}. "
            "Ce test comparerait alors le hook a un motif inerte"
        )

        fautives = [
            ligne
            for ligne in source.splitlines()
            if not ligne.lstrip().startswith("#") and re.search(compose, ligne)
        ]
        assert not fautives, (
            "une ligne de code de ce hook est reconnue par son propre motif de "
            f"secret : {fautives}. Le hook refuserait donc le commit qui le "
            "modifie, et les deux seules sorties seraient `--no-verify` — que ce "
            "chantier interdit — ou le retrait du garde. La cause est presque "
            "toujours une alternative ecrite en LITTERAL PUR : retire-la si une "
            "alternative generique la couvre, sinon separe-la du motif"
        )

    def test_une_suppression_de_ref_ne_verifie_rien(self, depot_pousse: Path) -> None:
        """Une ref supprimee ne pousse aucun commit, et le hook ne doit pas caler.

        Sans ce cas, `git push --delete` ferait passer 40 zeros a `git rev-list`,
        qui sortirait en erreur — un hook qui casse sur un geste legitime est un
        hook qu'on desarme.
        """
        acheve = _pousse(
            depot_pousse, f"(delete) {_ZEROS} refs/heads/principale {_ZEROS}\n"
        )
        assert acheve.returncode == 0, (
            f"la suppression d'une ref fait echouer le hook :\n{acheve.stderr}"
        )

    def test_une_ref_neuve_est_bornee_sur_l_ETAT_REEL_DU_DISTANT(
        self, depot_pousse: Path
    ) -> None:
        """CE TEST REMPLACE CELUI QUI CONSACRAIT LA CECITE, ET VOICI POURQUOI.

        **L'ANCIEN TEST AFFIRMAIT UNE FICTION.** Il s'appelait
        `test_une_ref_neuve_ne_fait_pas_verifier_tout_l_historique`, posait un
        commit non conforme, puis faisait
        `update-ref refs/remotes/origin/principale` dessus sous le commentaire
        « le distant connait ce commit : on le lui declare comme git le
        ferait », et exigeait `rc=0`. Or `update-ref` **n'est pas git qui
        declare** : c'est le test qui ECRIT DANS LE CACHE LOCAL un fait qui
        n'existe pas. Le commit n'avait jamais ete pousse.

        La cecite du garde n'etait donc pas un oubli, elle etait GARDEE par un
        test vert — et ce test-la mesurait exactement la scene du sinistre de ce
        depot en la declarant correcte. *Une regle relachee pour satisfaire une
        autre n'est pas une correction* : il est remplace, pas assoupli.

        **CE QUE CELUI-CI EPROUVE A LA PLACE.** La borne n'est plus un cache :
        c'est `git ls-remote`, l'etat REEL. Donc la scene doit poser un vrai
        distant, et la preuve d'atteinte est double — la plage calculee ET le
        `rc`. La scene « le distant porte reellement l'histoire ancienne » vit
        dans `TestLaPousseeEstGardeeParUnVraiGitPush`, qui pousse pour de vrai
        et asserte l'etat du distant ; celle-ci tient le fait plus etroit que
        `--remotes=` ne pouvait pas tenir : **un cache local menteur ne borne
        plus rien.**
        """
        self._commit(depot_pousse, 400, ADRESSE_INTERDITE)
        jamais_pousse = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        # LA FICTION DE L'ANCIEN TEST, POSEE TELLE QUELLE : on ecrit dans le
        # cache local que le distant connait ce commit. Il ne le connait pas —
        # ce depot n'a aucun distant.
        assert _git(
            depot_pousse, "update-ref", "refs/remotes/origin/principale", jamais_pousse
        ).returncode == 0
        self._commit(depot_pousse, 401, ADRESSE_AUTORISEE)

        # PREUVE D'ATTEINTE 1 — le commit non conforme est bien dans l'histoire.
        assert _git(
            depot_pousse, "show", "-s", "--format=%ae", jamais_pousse
        ).stdout.strip() == ADRESSE_INTERDITE

        # PREUVE D'ATTEINTE 2 — l'ANCIENNE borne l'excluait, et c'est la mesure
        # qui nomme le defaut ferme. Si cette assertion tombe, `--remotes=` ne
        # se comporte plus comme mesure et tout ce test perd son sujet.
        ancienne_borne = _git(
            depot_pousse, "rev-list", "HEAD", "--not", "--remotes=origin"
        ).stdout.split()
        assert jamais_pousse not in ancienne_borne, (
            "`--not --remotes=origin` n'exclut plus le commit ecrit a la main "
            "dans le cache : la scene ne reproduit plus le trou de 2026-09-09, "
            "et ce test ne mesurerait plus rien"
        )

        # PREUVE D'ATTEINTE 3 — la NOUVELLE borne ne l'exclut pas. Ce depot n'a
        # aucun distant joignable, donc `ls-remote` echoue et le repli ouvre la
        # plage : le commit fautif y est.
        refus = _pousse(depot_pousse, _ligne_de_poussee(depot_pousse, _ZEROS))
        assert refus.returncode == 1, (
            "un commit non conforme qu'un CACHE LOCAL declare deja pousse "
            "traverse encore le garde. C'est la sequence exacte qui a coute ce "
            f"depot, et elle est de nouveau muette.\n{refus.stdout}\n{refus.stderr}"
        )
        assert jamais_pousse[:12] in refus.stderr, (
            "le refus ne nomme pas le commit fautif : un refus qu'on ne peut pas "
            f"situer se contourne par `--no-verify`.\n{refus.stderr}"
        )
        assert "indisponible" in refus.stderr, (
            "le repli fail-closed ne se dit plus : une borne dont on ne sait pas "
            "si elle a servi redevient la cecite qu'on vient de fermer"
        )

    def test_une_entree_sans_retour_a_la_ligne_final_est_lue_quand_meme(
        self, depot_pousse: Path
    ) -> None:
        """LA PANNE TOTALE ET SILENCIEUSE A UN CARACTERE PRES.

        Sans `|| [ -n "..." ]`, une entree standard depourvue de retour a la
        ligne final fait rendre non-zero a `read`, la boucle ne tourne **pas une
        seule fois**, et le hook rend **`rc=0` sans avoir rien verifie**.
        `mesure` le 9 septembre 2026 : `printf 'a b c d' | sh -c 'while read ...'`
        rend **0** tour de boucle, et `bash` rend le meme 0 — ce n'est donc pas
        une particularite de `dash`, contrairement a ce que l'audit supposait.

        **CE TEST EXISTE PARCE QUE LE HARNAIS NE POUVAIT PAS LE SONDER.**
        `_ligne_de_poussee` ajoute TOUJOURS le `\\n`, donc aucun test de ce
        fichier ne rencontrait la scene — la forme dominante de ce chantier, un
        garde vert sous une scene que le defaut ne visite jamais. La ligne est
        donc construite ici sans son `\\n`, explicitement.

        Non exploitable aujourd'hui : les cinq formes de poussee relevees au
        mouchard `od -c` posent toutes le caractere. Un hook dont la panne
        totale tient a un caractere que personne ne controle n'est pas garde,
        il est chanceux.
        """
        base = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()
        self._commit(depot_pousse, 500, ADRESSE_INTERDITE)
        fautif = _git(depot_pousse, "rev-parse", "HEAD").stdout.strip()

        ligne = _ligne_de_poussee(depot_pousse, base)
        # PREUVE D'ATTEINTE : la ligne du harnais porte bien le caractere, et
        # celle-ci en est privee. Sans cette paire, le test pourrait sonder deux
        # fois la meme entree sans que rien ne le dise.
        assert ligne.endswith("\n"), "`_ligne_de_poussee` ne pose plus le `\\n`"
        sans_retour = ligne.rstrip("\n")
        assert not sans_retour.endswith("\n")

        refus = _pousse(depot_pousse, sans_retour)
        assert refus.returncode == 1, (
            "une entree standard sans retour a la ligne final n'est pas lue : le "
            "hook rend rc=0 SANS RIEN VERIFIER, ce qui est la panne la plus "
            f"grave possible pour ce garde — muette et totale.\n{refus.stderr}"
        )
        assert fautif[:12] in refus.stderr, (
            f"le refus ne nomme pas le commit fautif.\n{refus.stderr}"
        )

    def test_la_plage_reelle_de_ce_depot_passe(self) -> None:
        """LE SECOND SENS, SUR LA SEULE PLAGE QUI COMPTE VRAIMENT.

        Le hook est retourne contre l'historique REEL de ce depot. C'est la
        mesure qui distingue « un `pre-push` juste » d'« un `pre-push` qui
        refuse tout » : si celui-ci refusait la plage de ce depot, il serait
        desarme a la premiere poussee.

        **ET LA PREUVE D'ATTEINTE EST COMPTEE, PARCE QU'UN `rc=0` NE PROUVE
        RIEN ICI.** Le test compte les lignes AJOUTEES que le controle de secret
        traverse reellement. `mesure` le 9 septembre 2026 : **83 129** lignes
        sur 276 commits. Un `rc=0` obtenu sur zero ligne traversee serait
        exactement le faux vert que ce lot a trouve contre lui-meme.
        """
        commits = _git(RACINE, "rev-list", "HEAD").stdout.split()
        assert len(commits) >= 250, f"seulement {len(commits)} commits : plage inattendue"

        lignes_traversees = 0
        for commit in commits:
            diff = _git(RACINE, "show", "--format=", "--unified=0", commit).stdout
            lignes_traversees += sum(
                1
                for ligne in diff.splitlines()
                if ligne.startswith("+") and not ligne.startswith("+++")
            )
        # UN PLANCHER, PAS UN COMPTE : l'historique grandit, et un compte exact
        # rougirait a chaque commit — le geste « monter le chiffre » que le
        # §4.35 de ce depot refuse.
        assert lignes_traversees >= 80_000, (
            f"seulement {lignes_traversees} lignes ajoutees traversent le controle "
            "de secret, sous le plancher de 80 000 releve le 9 septembre 2026 : le "
            "`rc=0` ci-dessous ne prouverait plus que le controle a tourne"
        )

        hook = RACINE / "scripts" / "git-hooks" / "pre-push"
        sha = _git(RACINE, "rev-parse", "HEAD").stdout.strip()
        environnement = dict(os.environ)
        environnement.pop("GIT_DIR", None)
        environnement.pop("GIT_WORK_TREE", None)
        acheve = subprocess.run(
            ["sh", str(hook), "origin", "https://example.invalid/depot.git"],
            cwd=RACINE,
            input=f"refs/heads/main {sha} refs/heads/main {commits[-1]}\n",
            env=environnement,
            capture_output=True,
            text=True,
        )
        assert acheve.returncode == 0, (
            "le hook refuse l'historique REEL de ce depot : il serait desarme a la "
            f"premiere poussee.\n{acheve.stdout}\n{acheve.stderr}"
        )
        assert acheve.stderr == "", f"le hook ecrit sur stderr sans refuser : {acheve.stderr!r}"


class TestLeMontageDeLaPousseeEstConstate:
    """`make install` doit armer `pre-push` ET s'en apercevoir s'il ne l'a pas fait.

    C'est la meme exigence que pour les deux autres types, et elle est portee
    par les memes deux classes du script : la boucle d'armement et la boucle de
    verification, qui iterent la MEME variable `TYPES` — donc elles ne peuvent
    pas diverger sur un type.
    """

    def test_les_trois_types_sont_armes_et_leur_couche_legacy_est_conforme(
        self, depot_arme: Path
    ) -> None:
        hooks = depot_arme / ".git" / "hooks"
        attendu = {
            "pre-commit": HOOK_IDENTITE,
            "pre-merge-commit": HOOK_IDENTITE,
            "pre-push": HOOK_POUSSEE,
        }
        for type_, source in attendu.items():
            genere = hooks / type_
            legacy = hooks / f"{type_}.legacy"
            assert genere.is_file(), f"{type_} n'est pas arme"
            assert "generated by pre-commit" in genere.read_text(), (
                f"{type_} n'est pas le hook du framework : la copie manuelle est "
                "passee APRES `pre-commit install` et l'a ecrase"
            )
            assert legacy.is_file(), f"{type_}.legacy est absent"
            assert legacy.read_text() == source.read_text(), (
                f"{type_}.legacy ne porte pas {source.name} : la correspondance "
                "type -> source du script a change"
            )

    def test_le_controle_de_poussee_n_est_pas_le_controle_d_identite(self) -> None:
        """LA MUTATION QUI AURAIT DONNE UN HOOK CREUX, ET ELLE EST INTERDITE ICI.

        Copier le controle d'identite sous le nom `pre-push` aurait donne un
        hook qui lit `git var GIT_AUTHOR_IDENT` — l'identite CONFIGUREE au
        moment du push — et aucun des commits qui partent. Vert sous toute scene
        ou le defaut n'est pas dans la configuration courante, c'est-a-dire vert
        sur le defaut reel.
        """
        assert HOOK_POUSSEE.read_text() != HOOK_IDENTITE.read_text(), (
            "le controle de poussee est une copie du controle d'identite : il "
            "verifie l'identite configuree, pas la plage qui part"
        )
        source = HOOK_POUSSEE.read_text()
        assert "read -r" in source, (
            "le controle de poussee ne lit pas son entree standard : il ne peut "
            "donc pas connaitre la plage qui part, et un hook qui ne verifie que "
            "HEAD laisse passer neuf commits sur dix"
        )
        assert "rev-list" in source, (
            "le controle de poussee n'enumere aucune plage : il ne verifie au "
            "mieux qu'un commit"
        )
        assert "GIT_AUTHOR_IDENT" not in source, (
            "le controle de poussee lit l'identite CONFIGUREE : c'est la mesure "
            "du `pre-commit`, et elle ne dit rien des commits qui partent"
        )

    def test_une_liste_de_types_privee_de_la_poussee_est_vue(self, tmp_path: Path) -> None:
        """LA MUTATION QUI RETIRE `pre-push` DU MONTAGE.

        Sans ce test, le type pourrait sortir de `TYPES` sans qu'un seul rouge
        n'apparaisse : le script s'installerait proprement sur les deux autres,
        sortirait en 0, et la poussee redeviendrait la seule chose que personne
        ne garde. C'est mot pour mot le defaut que cette fermeture ferme.
        """
        source = INSTALLEUR.read_text()
        mutee, remplacements = re.subn(
            r'^(TYPES=".*?)\s*pre-push"$', r'\1"', source, count=1, flags=re.M
        )
        assert remplacements == 1, (
            "`pre-push` n'est plus le dernier type de la liste `TYPES` : cette "
            "mutation ne mute plus rien"
        )
        assert "pre-push" not in mutee.split("TYPES=")[1].split("\n")[0], (
            "la mutation n'a pas retire le type de la liste"
        )

        depot = tmp_path / "depot-sans-poussee"
        execution = _monte_un_depot_jetable(depot, mutee)
        # C'est tout le probleme : le script mute reste VERT.
        assert execution.returncode == 0, (
            "le script mute echoue deja : ce test ne mesure plus le defaut "
            f"silencieux qu'il decrit.\n{execution.stderr}"
        )
        assert not (depot / ".git" / "hooks" / "pre-push.legacy").exists(), (
            "la couche `.legacy` de `pre-push` est posee alors que le type est "
            "sorti de la liste : la mutation ne mute pas ce qu'elle croit"
        )
