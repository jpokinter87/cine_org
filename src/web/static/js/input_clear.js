/*
 * input_clear.js — bouton ✕ d'effacement réutilisable (phase 43-02)
 *
 * Usage : ajouter `data-clearable` sur un <input type="text|search|url|email|tel">.
 * Au chargement et après chaque swap HTMX, les inputs ciblés reçoivent
 * automatiquement un bouton ✕ superposé à droite qui :
 *   - n'apparaît que lorsque la valeur est non vide
 *   - au clic : vide l'input, remet le focus, dispatche input+change
 *     (déclenche HTMX si configuré dessus)
 *
 * Le script détecte les parents déjà positionnés (ex: .lib-search-wrap)
 * pour éviter les wraps imbriqués, et injecte directement le bouton.
 */

(function () {
    "use strict";

    var SELECTOR = "input[data-clearable]";
    var ATTACHED_FLAG = "clearAttached";
    var WRAP_CLASS = "input-clearable-wrap";
    var BUTTON_CLASS = "input-clear-btn";
    var HAS_VALUE_CLASS = "has-value";

    function _createButton() {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = BUTTON_CLASS;
        btn.setAttribute("aria-label", "Effacer");
        btn.setAttribute("tabindex", "-1");
        btn.innerHTML =
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2.2" stroke-linecap="round" width="12" height="12">' +
            '<line x1="18" y1="6" x2="6" y2="18"/>' +
            '<line x1="6" y1="6" x2="18" y2="18"/></svg>';
        return btn;
    }

    function _syncVisibility(container, input) {
        if (input.value && input.value.length > 0) {
            container.classList.add(HAS_VALUE_CLASS);
        } else {
            container.classList.remove(HAS_VALUE_CLASS);
        }
    }

    function _wrapIfNeeded(input) {
        // Si le parent est déjà un wrap positionné (.lib-search-wrap par ex.),
        // on réutilise ce parent sans créer de nouveau conteneur.
        var parent = input.parentElement;
        if (parent && parent.classList.contains(WRAP_CLASS)) {
            return parent;
        }
        if (parent) {
            var computed = window.getComputedStyle(parent);
            if (computed.position !== "static") {
                // Parent déjà positionné (relative/absolute/sticky/fixed)
                parent.classList.add("input-clearable-host");
                return parent;
            }
        }
        // Sinon on insère un span wrap autour de l'input
        var wrap = document.createElement("span");
        wrap.className = WRAP_CLASS;
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        return wrap;
    }

    function attachClearButton(input) {
        if (!input) return;

        var container = _wrapIfNeeded(input);

        // Protection anti-doublon : container-level. Si un bouton existe
        // déjà dans ce container, ne pas en créer un second (cas restauration
        // historique ou re-scan après swap HTMX).
        var existing = container.querySelector(":scope > ." + BUTTON_CLASS);
        if (existing) {
            _syncVisibility(container, input);
            input.dataset[ATTACHED_FLAG] = "1";
            return;
        }

        input.dataset[ATTACHED_FLAG] = "1";
        var btn = _createButton();
        container.appendChild(btn);

        _syncVisibility(container, input);

        input.addEventListener("input", function () {
            _syncVisibility(container, input);
        });
        input.addEventListener("change", function () {
            _syncVisibility(container, input);
        });

        btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            input.value = "";
            _syncVisibility(container, input);
            input.focus();
            // Déclencher HTMX si configuré : les deux events suffisent
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });
    }

    function scan(root) {
        root = root || document;
        var inputs = root.querySelectorAll
            ? root.querySelectorAll(SELECTOR)
            : [];
        inputs.forEach(attachClearButton);
    }

    // Init au DOMContentLoaded (ou immédiat si déjà chargé)
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            scan(document);
        });
    } else {
        scan(document);
    }

    // Re-scan après chaque swap HTMX (inclut les overlays, fragments, etc.)
    document.body.addEventListener("htmx:afterSwap", function (event) {
        scan(event.target || document);
    });
    document.body.addEventListener("htmx:load", function (event) {
        scan(event.target || document);
    });
    // Restauration historique (back/forward navigateur) : le cache HTMX
    // restaure le HTML avant l'injection JS → re-scanner.
    document.body.addEventListener("htmx:historyRestore", function () {
        scan(document);
    });
    // Bfcache des navigateurs (pageshow avec event.persisted=true)
    window.addEventListener("pageshow", function (event) {
        if (event.persisted) scan(document);
    });

    // Exposer l'API publique (optionnel, utile pour code custom)
    window.InputClear = { attach: attachClearButton, scan: scan };
})();
