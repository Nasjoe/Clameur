# Table des matieres de la sauvegarde. La logique vit dans les scripts.
# Kit borgwarehouse (CoopCodeCommun/borgwarehouse), adapte a la pile Clameur.
.PHONY: aide init backup check essai coffre list mount umount

# Point de montage volontairement HORS du dossier sauvegarde : monter le depot
# dedans exposerait la prochaine sauvegarde a se parcourir elle-meme.
MOUNTPOINT ?= /tmp/borg-clameur

aide:
	@echo "Sauvegarde de Clameur vers borgwarehouse :"
	@echo ""
	@echo "  make init      configure la sauvegarde (cle SSH, depot BWH, .env, cron)"
	@echo "  make backup    lance une sauvegarde maintenant"
	@echo "  make check     la derniere sauvegarde est-elle restaurable ?"
	@echo "  make essai     la restaurer POUR DE VRAI, dans une base jetable"
	@echo ""
	@echo "  make coffre    reaffiche ce qui doit etre au coffre-fort"
	@echo ""
	@echo "  make list      liste les archives du depot"
	@echo "  make mount     monte les archives en lecture seule pour piocher dedans"
	@echo "  make umount    demonte"
	@echo ""
	@echo "Pour demarrer :  cp env_example .env && chmod 600 .env && make init"

init:
	@bash initialiser.sh

backup:
	@bash sauvegarder.sh

check:
	@bash verifier.sh

essai:
	@bash essai_de_restauration.sh

# Les cibles ci-dessous parlent au depot directement. Elles rejouent le meme
# BORG_RSH que les scripts : la cle SSH DEDIEE a ce depot, et elle seule
# (-oIdentitiesOnly=yes), sans quoi l'agent SSH proposerait une autre cle et
# borgwarehouse refuserait la connexion.
BORG_ENV = set -a; . ./.env; set +a; \
	   cle="$(CURDIR)/.ssh/$$BORG_PREFIX""_ed25519"; \
	   test ! -f "$$cle" || export BORG_RSH="/usr/bin/ssh -oStrictHostKeyChecking=accept-new -oIdentitiesOnly=yes -i $$cle";

# `make init` n'affiche qu'une fois les elements du coffre-fort. Cette cible
# les reaffiche : sans elle, leur seule copie serait un scrollback de terminal.
# / init shows the vault items once; without this their only copy is scrollback.
coffre:
	@$(BORG_ENV) \
	 echo "A METTRE AU COFFRE-FORT — sans ces elements, les archives sont"; \
	 echo "un bloc chiffre definitivement illisible."; \
	 echo; \
	 echo "Depot      : $$BORG_REPO"; \
	 echo "Passphrase : $$BORG_PASSPHRASE"; \
	 echo; \
	 echo "Cle du depot (borg key export) :"; \
	 borg key export "$$BORG_REPO"

list:
	@$(BORG_ENV) borg list "$$BORG_REPO"

# Monte les archives en FUSE, en LECTURE SEULE : on navigue dedans et on copie
# ce qu'on veut — un seul enregistrement efface par accident, par exemple —
# sans tout extraire.
#   make mount ARCHIVE=clameur-histoires-2026-08-31-18-00
mount:
	@command -v borg >/dev/null || { echo "[mount] borg introuvable" >&2; exit 1; }
	@$(BORG_ENV) \
	 mkdir -p "$(MOUNTPOINT)"; \
	 cible="$$BORG_REPO"; \
	 test -z "$(ARCHIVE)" || cible="$$BORG_REPO::$(ARCHIVE)"; \
	 echo "[mount] $$cible -> $(MOUNTPOINT)"; \
	 borg mount -o ro "$$cible" "$(MOUNTPOINT)" \
	   && echo "[mount] monte. Demonter avec :  make umount"

umount:
	@borg umount "$(MOUNTPOINT)" && echo "[umount] $(MOUNTPOINT) demonte"
