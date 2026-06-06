/*
 * Remplace la confirmation native de HTMX (hx-confirm) par une modale
 * à la charte graphique de l'application, en réutilisant les styles
 * .delete-overlay / .delete-dialog. Préserve le flux HTMX (donc le
 * HX-Redirect renvoyé par le endpoint).
 */
(function () {
    var TRASH_SVG =
        '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/>' +
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 ' +
        '2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/>' +
        '<line x1="14" y1="11" x2="14" y2="17"/></svg>';

    var pending = null;

    function ensureOverlay() {
        var ov = document.getElementById('phantom-confirm-overlay');
        if (ov) return ov;
        ov = document.createElement('div');
        ov.id = 'phantom-confirm-overlay';
        ov.className = 'delete-overlay';
        ov.innerHTML =
            '<div class="delete-dialog">' +
            '<div class="delete-dialog-icon">' + TRASH_SVG + '</div>' +
            '<h3 class="delete-dialog-title">Supprimer cette fiche ?</h3>' +
            '<p class="delete-dialog-text" id="phantom-confirm-text"></p>' +
            '<div class="delete-dialog-actions">' +
            '<button class="reject-dialog-cancel" id="phantom-confirm-cancel">Annuler</button>' +
            '<button class="reject-dialog-confirm" id="phantom-confirm-ok">Supprimer la fiche</button>' +
            '</div></div>';
        document.body.appendChild(ov);
        ov.addEventListener('click', function (e) {
            if (e.target === ov) hide();
        });
        return ov;
    }

    function hide() {
        var ov = document.getElementById('phantom-confirm-overlay');
        if (ov) ov.classList.remove('active');
        pending = null;
    }

    document.body.addEventListener('htmx:confirm', function (evt) {
        var question = evt.detail.question;
        if (!question) return; // Pas de hx-confirm : comportement HTMX normal.

        evt.preventDefault(); // Empêche le confirm() natif.
        var ov = ensureOverlay();
        document.getElementById('phantom-confirm-text').textContent = question;
        pending = evt.detail;
        ov.classList.add('active');

        document.getElementById('phantom-confirm-ok').onclick = function () {
            var detail = pending;
            hide();
            if (detail) detail.issueRequest(true); // Relance sans re-confirmation.
        };
        document.getElementById('phantom-confirm-cancel').onclick = hide;
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') hide();
    });
})();
