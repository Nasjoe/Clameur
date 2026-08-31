from django.contrib import admin
from solo.admin import SingletonModelAdmin

from bornes.models import Reglages

# `SingletonModelAdmin` remplace la liste et le bouton « ajouter » par un acces
# direct au formulaire : il n'y a qu'un objet, on ne le cherche pas.
# / One object: no list, no add button, straight to the form.
admin.site.register(Reglages, SingletonModelAdmin)
