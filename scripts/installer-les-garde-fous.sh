#!/bin/sh
# Arme les garde-fous de ce clone, ET VERIFIE QU'ILS SONT ARMES.
#
# Ce script est appele par `make install`. Il n'y a donc qu'un geste a taper, et
# ce geste constate son propre resultat : il sort en erreur si le montage n'est
# pas celui qu'il annonce.
#
# POURQUOI UN SCRIPT ET PAS DEUX LIGNES DE DOCUMENTATION
#
# Git n'execute jamais ce qui arrive avec un clone : il y a forcement UN geste
# local a faire, et aucune ecriture dans le depot ne peut s'en passer. Ce qui
# peut etre supprime, en revanche, c'est la MEMOIRE d'un ordre. Le montage
# ci-dessous ne tient que si deux gestes sont faits dans le bon sens, et
# l'inversion ne se voit pas : elle ne produit aucune erreur, seulement
# l'absence d'une protection. Un garde-fou qui repose sur la memoire du suivant
# n'est pas un garde-fou.
#
# CE QUE CE SCRIPT MONTE, ET POURQUOI DANS CET ORDRE
#
#   1. les controles ecrits a la main sont copies dans le repertoire des hooks ;
#   2. `pre-commit install`, SANS -f, deplace cette copie en `<type>.legacy`,
#      continue de l'executer AVANT ses propres hooks, et s'installe par-dessus.
#
# Inverse, l'ordre coute le framework : la copie manuelle ecrase le hook genere,
# et seul le controle d'identite subsiste.
#
# LA COUCHE `.legacy` N'EST PAS UN DOUBLON — C'EST LA PROTECTION
#
# Le hook genere par le framework ouvre sa configuration en chemin RELATIF
# (`--config=.pre-commit-config.yaml`) : un controle declare dans ce fichier ne
# vaut que pour les arbres de travail dont la configuration le porte. Sur les
# 167 commits de `main` de ce depot, AUCUN ne la porte (`mesure` le 3 septembre
# 2026 : `git rev-list main -- .pre-commit-config.yaml | wc -l` rend 0, pour
# `git rev-list --count main` = 167). Un `git checkout` d'un commit ancien, un
# `git bisect`, un HEAD detache desarment donc le controle d'identite EN
# SILENCE — et c'est la famille de defaut qui a deja coute ce depot-ci : il a
# fallu le detruire et le recreer sur GitHub (`mesure` : l'API GitHub donne
# `created_at = 2026-08-28`, quand le plus ancien commit du clone est date du
# 2026-04-30). `<type>.legacy` vit HORS de l'arbre de travail : c'est la seule
# couche qui vaille pour tout commit, quelle que soit la branche.
#
# NE JAMAIS PASSER -f. `pre-commit install` le suggere lui-meme dans sa sortie
# — « Use -f to use only pre-commit. » — et c'est precisement le geste qui
# supprime cette couche. Ce script ne le passe pas, et la verification finale
# rougit si la couche a disparu.
set -eu

racine=$(git rev-parse --show-toplevel)
cd "$racine"

# `--git-common-dir` et non `--git-dir` : dans un arbre de travail secondaire,
# `--git-dir` rend `.git/worktrees/<nom>`, qui n'heberge aucun hook. Les hooks
# vivent dans le repertoire COMMUN, partage par le depot et tous ses arbres de
# travail — une installation vaut donc pour tous, et il n'y en a qu'une par
# clone.
commun=$(cd "$(git rev-parse --git-common-dir)" && pwd)
identite="$racine/scripts/git-hooks/pre-commit"
poussee="$racine/scripts/git-hooks/pre-push"
attribution="$racine/scripts/git-hooks/commit-msg"

# LE MOTIF D'ATTRIBUTION N'EST PAS UN HOOK : c'est un fragment SOURCE par
# `pre-push` ET par `commit-msg`. Il est copie a cote d'eux — donc HORS de
# l'arbre de travail, comme la couche `.legacy` elle-meme — et chacun le lit
# par `$(dirname "$0")`. Lu depuis l'arbre, il disparaitrait exactement dans
# les scenes que `.legacy` existe pour couvrir : `git bisect`, HEAD detache,
# commit ancien. Voir le commentaire en tete du fragment.
motifs="$racine/scripts/git-hooks/formes-d-attribution.sh"
motifs_poses="$commun/hooks/formes-d-attribution.sh"

# LE CONTROLE DE POUSSEE EST UN AUTRE SCRIPT, ET IL LE FAUT.
#
# `pre-commit` valide LE commit qu'on fabrique : il lit `git var
# GIT_AUTHOR_IDENT`, c'est-a-dire l'identite du commit en cours. `pre-push` doit
# valider TOUS les commits de la plage qui part, et cette plage lui arrive sur
# l'ENTREE STANDARD. Copier le controle d'identite sous le nom `pre-push` aurait
# donne un hook qui verifie l'identite CONFIGUREE au moment du push et aucun des
# commits qui partent — vert sous toute scene ou le defaut n'est pas dans la
# configuration courante, c'est-a-dire vert sur le defaut reel.
#
# Chaque type a donc sa source, et `source_du_type()` est le seul endroit ou
# cette correspondance est ecrite : la boucle d'armement ET la boucle de
# verification l'appellent tous deux, donc elles ne peuvent pas diverger.
source_du_type() {
    case "$1" in
        pre-push) echo "$poussee" ;;
        commit-msg) echo "$attribution" ;;
        *) echo "$identite" ;;
    esac
}

# Les types de hook qu'il faut armer. `pre-commit` NE SUFFIT PAS : c'est le seul
# type que `pre-commit install` installe par defaut, et il ne couvre pas les
# commits de fusion. `git merge --no-ff` declenche `pre-merge-commit`,
# `prepare-commit-msg` et `commit-msg`, jamais `pre-commit` (`mesure` le
# 3 septembre 2026 sur ce poste, mouchards poses sur chaque hook d'un depot
# jetable). Un commit de fusion portant une adresse interdite partirait donc
# sans rien rencontrer — et le mandat de ce chantier prescrit `--no-ff` pour
# chaque fusion de lot, dont le commit part sur GitHub.
#
# La copie manuelle est posee sur TOUS les types, pour que `<type>.legacy`
# couvre aussi les arbres dont la configuration ne porte pas le hook. Sans cette
# moitie, la fusion serait gardee sur la branche qui declare le hook, et nulle
# part ailleurs.
#
# `pre-push` ENTRE DANS CETTE LISTE LE 9 SEPTEMBRE 2026, et le motif est mesure.
# Le garde-fou d'identite couvrait `commit` et `merge`, jamais `push` : les NEUF
# poussees de ce chantier ont chacune ete protegees par une verification que le
# pilote ecrivait a la main. Un garde-fou qui repose sur la memoire du suivant
# n'est pas un garde-fou — c'est le premier paragraphe de ce fichier. Et
# l'asymetrie de gravite est entiere : un commit local se defait, une poussee
# non. Sept commits partis sous une mauvaise adresse ont coute la reecriture de
# 165 commits, PUIS la destruction et la recreation du depot sur GitHub.
#
# `pre-push` a sa propre source — voir `source_du_type()` ci-dessus — parce
# qu'il valide une PLAGE lue sur l'entree standard, et non le commit courant.
# `commit-msg` ENTRE DANS CETTE LISTE LE 11 SEPTEMBRE 2026, et le motif est
# mesure. Le controle d'identite lit `git var GIT_AUTHOR_IDENT` et
# `GIT_COMMITTER_IDENT` : **il ne lit JAMAIS le message**. Aucun des trois
# types armes jusqu'ici ne le lisait, et `commit-msg` est le SEUL type auquel
# git passe le message — en chemin de fichier, sur `$1`. Un trailer
# d'attribution entrait donc dans un commit local sans rien rencontrer, et
# n'etait attrape qu'a la POUSSEE : jamais public, mais au prix d'une
# reecriture de commits.
#
# **IL COUVRE LA FUSION AUTOMATIQUE, ET C'ETAIT LA QUESTION QUI DECIDAIT DE
# SA VALEUR.** `mesure` le 11 septembre 2026, mouchards poses sur chaque type
# d'un depot jetable, git 2.53.0 : sur `git merge --no-ff --no-edit` PROPRE,
# `pre-commit` ne passe pas, `pre-merge-commit` passe mais SANS aucun chemin
# de message, et `commit-msg` recoit `.git/MERGE_MSG` sur `$1`. Sur une fusion
# dont le conflit a ete resolu a la main, il recoit `.git/COMMIT_EDITMSG`. Le
# mandat prescrit `--no-ff` pour chaque fusion de lot : c'est exactement la
# qu'un message genere porterait un trailer.
#
# Ce qu'il ne couvre PAS est declare au site du hook : `git revert`,
# `git cherry-pick` et `git rebase` n'executent que `prepare-commit-msg`.
TYPES="pre-commit pre-merge-commit pre-push commit-msg"

# UNE BOUCLE SUR UNE LISTE VIDE VERIFIE ZERO CHOSE, ET ELLE EST VRAIE.
#
# La boucle de verification, plus bas, itere CETTE MEME variable. Vide, elle
# n'arme rien, ne verifie rien, et ce script sortirait en 0 en annoncant
# « Garde-fous armes dans ... » suivi d'une liste vide. Le framework, lui,
# resterait installe — sans `--hook-type`, `pre-commit install` retombe sur
# `default_install_hook_types` — donc le montage aurait exactement l'air du bon,
# sans la seule couche independante de l'arbre de travail. C'est le pire des
# etats, parce qu'il ressemble au bon.
# Garde : tests/unit/test_installation_des_garde_fous.py.
if [ -z "$TYPES" ]; then
    echo "ECHEC : aucun type de hook a armer (TYPES est vide)." >&2
    exit 1
fi

if [ ! -f "$identite" ]; then
    echo "ECHEC : $identite est introuvable." >&2
    exit 1
fi

mkdir -p "$commun/hooks"
for type in $TYPES; do
    source=$(source_du_type "$type")
    if [ ! -f "$source" ]; then
        echo "ECHEC : $source est introuvable (type $type)." >&2
        exit 1
    fi
    cp "$source" "$commun/hooks/$type"
    chmod +x "$commun/hooks/$type"
done

# Le fragment de motifs, pose AVANT `pre-commit install` comme les hooks :
# le framework ne le connait pas et ne le deplacera pas, mais un hook copie
# sans son fragment refuserait tout commit en fail-closed jusqu'a la ligne
# suivante. L'ordre evite cette fenetre.
if [ ! -f "$motifs" ]; then
    echo "ECHEC : $motifs est introuvable." >&2
    exit 1
fi
cp "$motifs" "$motifs_poses"

# `PRE_COMMIT` existe pour un seul appelant : le test qui verifie ce script
# (`tests/unit/test_installation_des_garde_fous.py`), qui monte un depot
# temporaire hors du projet `uv` et doit donc nommer l'interpreteur lui-meme.
#
# `--no-sync` n'est pas cosmetique. L'invocation nue, sans ce drapeau,
# synchronise le
# projet AVANT d'executer, donc installe les dependances de production : dont
# `sentence-transformers`, donc `torch`, que `uv.lock` epingle depuis PyPI avec
# 43 paquets `nvidia-*`. Armer un hook git telechargerait la pile CUDA. Il n'y a
# de toute facon rien a synchroniser ici : la cible `install` du Makefile vient
# de mettre `pre-commit` dans le `.venv` par
# `uv pip install -r requirements-dev.txt`, ou sa version est epinglee — et
# c'est son seul site, voir le commentaire en tete du groupe absent dans
# pyproject.toml.
pre_commit="${PRE_COMMIT:-uv run --no-sync pre-commit}"

arguments=""
for type in $TYPES; do
    arguments="$arguments --hook-type $type"
done

# Les types sont passes explicitement plutot que laisses a
# `default_install_hook_types` : cette cle vit dans `.pre-commit-config.yaml`,
# donc dans l'arbre de travail, et l'installation ne doit rien devoir a la
# branche sortie au moment ou on l'execute.
#
# `--allow-missing-config` N'EST PAS `-f`, ET C'EST CE DEPOT-CI QUI L'EXIGE.
#
# Le hook genere par le framework ouvre sa configuration en chemin relatif. Sans
# ce drapeau, un arbre de travail SANS `.pre-commit-config.yaml` fait refuser
# TOUT commit, sur le message « No .pre-commit-config.yaml file was found », qui
# ne nomme ni la cause ni le geste. Or ce fichier n'existe sur ce depot que
# depuis le 3 septembre 2026 : `mesure`, en interrogeant
# `git cat-file -e <commit>:.pre-commit-config.yaml` sur chaque commit,
# **167 des 167 commits de `main` ne le portent pas**. Sur le depot jumeau, dont
# ce montage est porte, le meme comptage donne **1 sur 235** : le drapeau y
# etait inutile, et il est ici indispensable. Sans lui, armer les garde-fous
# briquerait tout `git checkout` d'un commit anterieur, tout `git bisect`, tout
# HEAD detache sur l'historique entier — et, avant la fusion de ce lot, `main`
# lui-meme et l'arbre de travail du pilote.
#
# CE QU'IL NE COUTE PAS, et c'est la difference avec `-f` : la couche
# `<type>.legacy` reste posee et conforme, donc le controle d'identite reste
# INCONDITIONNEL. `mesure` le 3 septembre 2026, depot jetable arme par ce
# script, configuration retiree : une adresse interdite est refusee `rc=1`, HEAD
# immobile, sur le message du controle d'identite ; une adresse autorisee passe
# `rc=0`. Le drapeau rend muets les hooks du framework quand leur configuration
# manque, jamais le controle d'identite.
# Garde : tests/unit/test_installation_des_garde_fous.py,
# `TestUnArbreSansConfigurationResteGarde`.
# shellcheck disable=SC2086
if ! $pre_commit install --allow-missing-config $arguments; then
    echo "ECHEC : « $pre_commit install » a rendu une erreur." >&2
    echo "Le controle d'identite est copie et actif ; les hooks du framework" >&2
    echo "ne le sont pas. Corrige la cause, puis relance : make install" >&2
    exit 1
fi

# La verification. C'est elle qui distingue ce script d'une consigne ecrite :
# elle constate le montage au lieu de le supposer.
erreurs=0
for type in $TYPES; do
    genere="$commun/hooks/$type"
    legacy="$commun/hooks/$type.legacy"

    if ! grep -q 'generated by pre-commit' "$genere" 2>/dev/null; then
        echo "ECHEC : $genere n'est pas le hook du framework." >&2
        echo "  Cause probable : la copie manuelle est passee APRES" >&2
        echo "  « pre-commit install » et l'a ecrase." >&2
        erreurs=1
    fi

    if ! cmp -s "$(source_du_type "$type")" "$legacy"; then
        echo "ECHEC : $legacy ne porte pas le controle ecrit a la main." >&2
        echo "  Cause probable : « pre-commit install -f », qui supprime la" >&2
        echo "  seule couche independante de l'arbre de travail." >&2
        erreurs=1
    fi
done

# LE FRAGMENT FAIT PARTIE DU MONTAGE, DONC IL SE CONSTATE. Absent ou perime,
# `pre-push` et `commit-msg` refusent TOUT en fail-closed : la panne est bruyante
# plutot que silencieuse, mais elle briquerait le depot, et c'est exactement ce
# qu'un script qui « constate son propre resultat » doit voir avant l'utilisateur.
if ! cmp -s "$motifs" "$motifs_poses"; then
    echo "ECHEC : $motifs_poses ne porte pas le motif d'attribution livre." >&2
    echo "  Sans lui, « pre-push » et « commit-msg » refusent tout en" >&2
    echo "  fail-closed. Corrige la cause, puis relance : make install" >&2
    erreurs=1
fi

if [ "$erreurs" -ne 0 ]; then
    echo "" >&2
    echo "Les garde-fous ne sont PAS armes. Ne commite pas avant d'avoir" >&2
    echo "corrige : le controle d'identite est celui dont l'oubli a coute ce" >&2
    echo "depot-ci (documentation/pilotage_du_chantier.md, §2.1)." >&2
    exit 1
fi

echo "Garde-fous armes dans $commun/hooks :"
for type in $TYPES; do
    echo "  $type          hooks du framework (.pre-commit-config.yaml)"
    case "$type" in
        pre-push)
            echo "  $type.legacy   controle de la PLAGE poussee, valable pour toute branche"
            ;;
        commit-msg)
            echo "  $type.legacy   controle du MESSAGE, valable pour toute branche"
            ;;
        *)
            echo "  $type.legacy   controle d'identite, valable pour toute branche"
            ;;
    esac
done
echo "  formes-d-attribution.sh   motif partage par pre-push et commit-msg"
