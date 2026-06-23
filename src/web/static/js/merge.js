// Fusion de deux fiches séries — greffé sur le mode sélection de delete.js
(function () {
    'use strict';

    // Lit la sélection courante depuis le sessionStorage de delete.js
    function selectedSeries() {
        try {
            var raw = sessionStorage.getItem('cineorg_delete_selection');
            if (!raw) return [];
            var state = JSON.parse(raw);
            var items = state.items || {};
            return Object.keys(items)
                .map(function (k) { return items[k]; })
                .filter(function (it) { return it.type === 'series'; });
        } catch (e) { return []; }
    }

    // Affiche le bouton « Fusionner » seulement si exactement 2 séries cochées
    function refreshButton() {
        var btn = document.getElementById('merge-confirm-btn');
        if (!btn) return;
        btn.style.display = selectedSeries().length === 2 ? '' : 'none';
    }

    // explicit=true → respecte l'ordre demandé (pas de re-tri par date côté serveur)
    function openOverlay(a, b, explicit) {
        var url = '/library/merge/overlay?a=' + a + '&b=' + b + (explicit ? '&explicit=1' : '');
        fetch(url)
            .then(function (r) { return r.text(); })
            .then(function (html) {
                document.getElementById('merge-overlay-container').innerHTML = html;
                bindRadioReload();
            });
    }

    // Inverser le sens (changer le récipiendaire) recharge l'aperçu
    function bindRadioReload() {
        var form = document.getElementById('merge-form');
        if (!form) return;
        form.querySelectorAll('input[name="keep"]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                var keep = parseInt(this.value, 10);
                var a = parseInt(form.dataset.recipient, 10);
                var b = parseInt(form.dataset.absorbed, 10);
                var other = keep === a ? b : a;
                openOverlay(keep, other, true);
            });
        });
    }

    window.CineMerge = {
        close: function () {
            var c = document.getElementById('merge-overlay-container');
            if (c) c.innerHTML = '';
        },
        apply: function () {
            var form = document.getElementById('merge-form');
            var keep = form.querySelector('input[name="keep"]:checked').value;
            var a = parseInt(form.dataset.recipient, 10);
            var b = parseInt(form.dataset.absorbed, 10);
            var absorbed = parseInt(keep, 10) === a ? b : a;
            var body = new URLSearchParams({ absorbed_id: absorbed });
            fetch('/library/series/' + keep + '/merge', { method: 'POST', body: body })
                .then(function (res) {
                    if (!res.ok) {
                        // 403 (machine non maître), 400 (fiche supprimée entre-temps), 500…
                        return res.json().then(function (d) {
                            alert(d.error || 'Échec de la fusion.');
                            throw new Error('merge-failed');
                        });
                    }
                    var redirect = res.headers.get('HX-Redirect');
                    if (redirect) { window.location.href = redirect; }
                    return res.json();
                })
                .catch(function () { /* feedback déjà affiché via alert */ });
        }
    };

    // Clic sur le bouton « Fusionner » (aucun stopPropagation en amont ici).
    document.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('#merge-confirm-btn')) {
            var series = selectedSeries();
            if (series.length === 2) {
                openOverlay(series[0].id, series[1].id);
            }
        }
    });

    // Rafraîchir la visibilité du bouton après chaque clic. En phase CAPTURE :
    // delete.js appelle e.stopPropagation() sur les cases à cocher, ce qui
    // empêcherait un écouteur en phase de bulle de voir l'événement. Le
    // setTimeout lit l'état une fois que delete.js l'a écrit dans sessionStorage.
    document.addEventListener('click', function () {
        setTimeout(refreshButton, 0);
    }, true);

    document.addEventListener('DOMContentLoaded', refreshButton);
    document.body.addEventListener('htmx:afterSwap', function () {
        setTimeout(refreshButton, 0);
    });
})();
