/* Accessibilité clavier commune.
 *
 * 1. Les éléments non natifs marqués role="button" s'activent avec Entrée / Espace.
 * 2. Les fenêtres superposées existantes (overlays, agrandisseurs de jaquette)
 *    reçoivent la sémantique de dialogue ; le focus y entre à l'ouverture, y reste
 *    (Tab / Maj+Tab bouclent), revient à l'élément d'origine à la fermeture, et
 *    Échap ferme comme un clic sur le fond. Les fonctions d'ouverture/fermeture
 *    de chaque page restent inchangées : on observe seulement leur visibilité.
 */
(function () {
    "use strict";

    var OVERLAY_SELECTOR = [
        ".reject-overlay", ".confirm-overlay", ".delete-overlay", ".dup-delete-overlay",
        ".edit-overlay", ".merge-overlay", ".conflict-overlay", ".poster-lightbox",
        ".reassociate-overlay", ".reassociate-confirm-overlay", ".trash-empty-overlay"
    ].join(", ");
    var FOCUSABLE_SELECTOR = "button:not([disabled]), [href], input:not([disabled]):not([type=\"hidden\"]), " +
        "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])";

    var current = null;
    var returnFocus = null;
    var scheduled = false;

    function _isShown(el) {
        return el.getClientRects().length > 0;
    }

    function _topOpenOverlay() {
        var open = Array.prototype.filter.call(document.querySelectorAll(OVERLAY_SELECTOR), _isShown);
        return open.length ? open[open.length - 1] : null;
    }

    function _focusables(el) {
        return Array.prototype.filter.call(el.querySelectorAll(FOCUSABLE_SELECTOR), _isShown);
    }

    function _sync() {
        scheduled = false;
        document.querySelectorAll(OVERLAY_SELECTOR).forEach(function (el) {
            if (!el.hasAttribute("role")) {
                el.setAttribute("role", "dialog");
                el.setAttribute("aria-modal", "true");
                el.setAttribute("tabindex", "-1");
            }
        });
        var top = _topOpenOverlay();
        if (top === current) return;
        if (top && !current) returnFocus = document.activeElement;
        current = top;
        if (top) {
            // Focus sur le dialogue lui-même : jamais d'activation accidentelle
            // d'un bouton destructif par Entrée ; un champ déjà focalisé est respecté.
            if (!top.contains(document.activeElement)) top.focus();
        } else if (returnFocus && document.contains(returnFocus)) {
            returnFocus.focus();
            returnFocus = null;
        }
    }

    function _schedule() {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(_sync);
    }

    document.addEventListener("keydown", function (e) {
        var t = e.target;
        if ((e.key === "Enter" || e.key === " ") && t.getAttribute &&
                t.getAttribute("role") === "button" && t.tagName !== "BUTTON") {
            e.preventDefault();
            t.click();
            return;
        }
        if (!current) return;
        if (e.key === "Escape") {
            // Les overlays se ferment sur un clic dont la cible est le fond lui-même
            current.click();
            return;
        }
        if (e.key === "Tab") {
            var items = _focusables(current);
            if (!items.length) {
                e.preventDefault();
                return;
            }
            var first = items[0];
            var last = items[items.length - 1];
            var active = document.activeElement;
            if (!current.contains(active)) {
                e.preventDefault();
                first.focus();
            } else if (e.shiftKey && (active === first || active === current)) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && active === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });

    function _init() {
        new MutationObserver(_schedule).observe(document.body, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["class", "style"]
        });
        _sync();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _init);
    } else {
        _init();
    }
})();
