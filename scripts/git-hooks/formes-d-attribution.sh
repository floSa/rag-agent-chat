# LE MOTIF D'ATTRIBUTION, ET SON SEUL SITE. Fichier SOURCE, jamais execute.
#
# ── POURQUOI CE FICHIER EXISTE ──
#
# Deux hooks refusent la meme chose sur deux gestes differents : `commit-msg`
# refuse le message DU commit qu'on fabrique, `pre-push` refuse le message de
# chaque commit de la plage qui part. La regle est UNE, et recopier le motif en
# ferait DEUX SITES — la famille de derive que ce depot consigne depuis le
# §4.13 de son registre : deux ecritures d'une meme regle divergent, et rien ne
# rougit de leur divergence. Le motif vit donc ici, et les deux hooks le
# `.`-sourcent.
#
# ── OU CE FICHIER DOIT VIVRE AU RUNTIME, ET CE N'EST PAS L'ARBRE DE TRAVAIL ──
#
# Les hooks de ce depot valent par leur couche `<type>.legacy`, qui vit HORS de
# l'arbre de travail : c'est la seule couche qui tienne sous un `git checkout`
# d'un commit ancien, un `git bisect` ou un HEAD detache — voir le commentaire
# en tete de `scripts/installer-les-garde-fous.sh`. Un fragment source depuis
# l'arbre de travail (`$racine/scripts/git-hooks/...`) RUINERAIT cette
# propriete : il disparaitrait exactement dans les scenes que la couche
# `.legacy` existe pour couvrir, et les 167 commits anterieurs au 3 septembre
# 2026 ne le portent pas.
#
# `scripts/installer-les-garde-fous.sh` copie donc ce fichier A COTE des hooks,
# dans le repertoire de hooks du repertoire git COMMUN, et chaque hook le
# source par `$(dirname "$0")` — « le fichier a cote de moi », ce qui vaut sous
# les trois mises en place mesurees le 11 septembre 2026 sur ce poste,
# git 2.53.0 :
#
#   - git execute le hook directement    : `$0` = `.git/hooks/<type>`,
#     RELATIF, et git pose le repertoire courant a la racine de l'arbre ;
#   - le framework execute `<type>.legacy` : `$0` ABSOLU ;
#   - depuis un arbre de travail SECONDAIRE : `$0` ABSOLU, et il designe le
#     repertoire de hooks COMMUN, pas celui de l'arbre.
#
# Les trois donnent un `dirname` qui contient ce fichier. C'est la propriete
# qu'il faut, et elle ne suppose ni `core.hooksPath`, ni `--git-common-dir`, ni
# la racine de l'arbre.
#
# ── LES BORNES DU MOTIF, ECRITES PLUTOT QUE TUES ──
#
# `-i` est applique a l'appel, pas ecrit ici. `^[[:space:]]*` : un trailer vit
# en tete de ligne, un recit ne s'y trouve pas par accident.
#
# **UNE MENTION EN PROSE N'EST PAS REFUSEE, ET C'EST LA BORNE QUI DECIDE DE
# TOUT.** Ce depot documente sa propre regle sur plusieurs pages, et un message
# de commit qui la raconte est legitime. Un hook qui refuserait le MOT
# enseignerait le seul geste que ce chantier interdit absolument —
# `--no-verify` — et un garde qu'on desarme pour travailler ne garde plus rien.
# Seules les FORMES d'attribution sont refusees.
#
# Les trois premieres alternatives portent leur ancre depuis l'origine ; la
# deuxieme — la ligne de signature — ne l'a recue que le 9 septembre 2026, apres
# qu'un rapport de lot se soit trouve refuse pour avoir NOMME la forme au milieu
# d'une phrase. C'est mot pour mot le defaut corrige dans `e42d3e6` pour le
# motif de secret : un garde qui provoque la panne qu'il surveille. Le trouver
# deux fois dit que la propriete « chaque alternative porte sa borne » doit etre
# GARDEE, pas relue — `test_les_quatre_alternatives_portent_leur_borne`.
#
# La quatrieme alternative, l'emoji, n'est deliberement PAS ancree : il ne se
# rencontre dans aucune prose de ce depot, et les outils qui l'apposent le
# posent en fin de ligne de signature.
#
# **CE QUI N'EST PAS REFUSE ICI, ET QUI L'EST AILLEURS** : le NOM d'auteur porte
# son propre controle dans `pre-push`, sur deux marqueurs de robot seulement, et
# l'ADRESSE — le seul axe qui decide vraiment — porte le sien dans
# `scripts/git-hooks/pre-commit` et dans `pre-push`. Ce fichier ne connait que
# le MESSAGE.
FORMES_D_ATTRIBUTION='^[[:space:]]*co-authored-by:|^[[:space:]]*generated (with|by) \[|^[[:space:]]*(co-)?authored-by:.*\[bot\]|🤖'
