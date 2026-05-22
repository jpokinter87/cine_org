/**
 * Mode sélection par lot (« Batch ») : suppression ou ajout à une collection.
 *
 * Gère l'activation du mode sélection, les cases à cocher sur les jaquettes,
 * le compteur flottant, et l'envoi des requêtes (suppression / collection).
 * L'état est persisté dans sessionStorage pour survivre à la navigation
 * vers les fiches détail et au retour.
 *
 * Le bouton d'activation (#delete-mode-toggle) vit dans #library-content,
 * qui est remplacé à chaque swap HTMX (changement de filtre/tri/recherche).
 * On délègue donc son clic au document et on le requête à la volée, sinon le
 * handler serait perdu après le premier swap.
 */

(function () {
    'use strict';

    var STORAGE_KEY = 'cineorg_delete_selection';

    // --- Chargement de l'état depuis sessionStorage ---
    var selected = new Map();
    var selectMode = false;

    function saveState() {
        var data = { mode: selectMode, items: {} };
        selected.forEach(function (val, key) {
            data.items[key] = val;
        });
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    }

    function loadState() {
        try {
            var raw = sessionStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            var data = JSON.parse(raw);
            selectMode = data.mode || false;
            if (data.items) {
                Object.keys(data.items).forEach(function (key) {
                    selected.set(key, data.items[key]);
                });
            }
        } catch (e) {
            // Ignorer les erreurs de parsing
        }
    }

    function clearState() {
        sessionStorage.removeItem(STORAGE_KEY);
    }

    var container = document.getElementById('library-content');
    if (!container) return;

    // --- Bouton d'activation (présent uniquement sur la machine maître) ---
    if (!document.getElementById('delete-mode-toggle')) return;

    var TOGGLE_ICON_DEFAULT =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> Batch';
    var TOGGLE_ICON_ACTIVE =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> Annuler la sélection';

    // Requête le bouton à la volée (il est recréé à chaque swap HTMX) et
    // applique l'apparence correspondant à l'état courant.
    function applyToggleAppearance() {
        var btn = document.getElementById('delete-mode-toggle');
        if (!btn) return;
        btn.classList.toggle('active', selectMode);
        btn.innerHTML = selectMode ? TOGGLE_ICON_ACTIVE : TOGGLE_ICON_DEFAULT;
    }

    // --- Barre flottante ---
    var bar = document.getElementById('delete-bar');
    var countSpan = document.getElementById('delete-count');
    var confirmBtn = document.getElementById('delete-confirm-btn');
    var cancelBtn = document.getElementById('delete-cancel-btn');

    // --- Overlay confirmation ---
    var overlay = document.getElementById('delete-overlay');
    var overlayCount = document.getElementById('delete-overlay-count');
    var overlayConfirmBtn = document.getElementById('delete-overlay-confirm');
    var overlayCancelBtn = document.getElementById('delete-overlay-cancel');

    function updateUI() {
        var n = selected.size;
        if (countSpan) countSpan.textContent = n;
        if (bar) {
            bar.classList.toggle('active', n > 0 && selectMode);
        }
        syncSelectAllCheckbox();
    }

    // Itère les cartes de la page courante (films + séries) et invoque
    // fn(card, key, type, id, title) pour chacune.
    function forEachCard(fn) {
        container.querySelectorAll('.lib-card').forEach(function (card) {
            var match = (card.getAttribute('href') || '').match(
                /\/library\/(movies|series)\/(\d+)/
            );
            if (!match) return;
            var type = match[1] === 'movies' ? 'movie' : 'series';
            var id = parseInt(match[2], 10);
            var key = type + '-' + id;
            var title = (card.querySelector('.lib-card-title') || {}).textContent || '';
            fn(card, key, type, id, title);
        });
    }

    // Sélectionne (ou désélectionne) toutes les jaquettes de la page courante.
    function setAllCardsSelection(check) {
        forEachCard(function (card, key, type, id, title) {
            var input = card.querySelector('.delete-checkbox input');
            if (check) {
                selected.set(key, { type: type, id: id, title: title });
                card.classList.add('delete-selected');
                if (input) input.checked = true;
            } else {
                selected.delete(key);
                card.classList.remove('delete-selected');
                if (input) input.checked = false;
            }
        });
        updateUI();
        saveState();
    }

    // Reflète l'état de sélection de la page sur la case maître (#select-all-checkbox).
    function syncSelectAllCheckbox() {
        var master = document.getElementById('select-all-checkbox');
        if (!master) return;
        var total = 0;
        var sel = 0;
        forEachCard(function (card, key) {
            total += 1;
            if (selected.has(key)) sel += 1;
        });
        master.checked = total > 0 && sel === total;
        master.indeterminate = sel > 0 && sel < total;
    }

    function enterSelectMode() {
        selectMode = true;
        document.body.classList.add('delete-mode');
        applyToggleAppearance();
        attachCheckboxes();
        updateUI();
        saveState();
    }

    function exitSelectMode() {
        selectMode = false;
        selected.clear();
        document.body.classList.remove('delete-mode');
        applyToggleAppearance();
        removeCheckboxes();
        updateUI();
        clearState();
    }

    // Délégation au document : survit aux remplacements de #library-content
    // (le bouton est recréé à chaque swap HTMX).
    document.addEventListener('click', function (e) {
        if (!e.target || !e.target.closest) return;
        if (!e.target.closest('#delete-mode-toggle')) return;
        if (selectMode) {
            exitSelectMode();
        } else {
            enterSelectMode();
        }
    });

    // Case « Tout sélectionner » — recréée à chaque swap HTMX, donc déléguée.
    document.addEventListener('change', function (e) {
        if (!e.target || e.target.id !== 'select-all-checkbox') return;
        setAllCardsSelection(e.target.checked);
    });

    if (cancelBtn) {
        cancelBtn.addEventListener('click', function () {
            exitSelectMode();
        });
    }

    function attachCheckboxes() {
        var cards = container.querySelectorAll('.lib-card');
        cards.forEach(function (card) {
            if (card.querySelector('.delete-checkbox')) return;

            var href = card.getAttribute('href') || '';
            // Parse: /library/movies/42 or /library/series/7
            var match = href.match(/\/library\/(movies|series)\/(\d+)/);
            if (!match) return;

            var type = match[1] === 'movies' ? 'movie' : 'series';
            var id = parseInt(match[2], 10);
            var key = type + '-' + id;
            var title = (card.querySelector('.lib-card-title') || {}).textContent || '';

            // Restaurer l'état de sélection depuis sessionStorage
            var isSelected = selected.has(key);
            if (isSelected) {
                card.classList.add('delete-selected');
            }

            var cb = document.createElement('label');
            cb.className = 'delete-checkbox';
            cb.innerHTML = '<input type="checkbox"' + (isSelected ? ' checked' : '') + ' data-key="' + key + '" data-type="' + type + '" data-id="' + id + '" data-title="' + title.replace(/"/g, '&quot;') + '">' +
                '<span class="delete-checkbox-mark"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></span>';

            cb.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var input = cb.querySelector('input');
                input.checked = !input.checked;

                if (input.checked) {
                    selected.set(key, { type: type, id: id, title: title });
                    card.classList.add('delete-selected');
                } else {
                    selected.delete(key);
                    card.classList.remove('delete-selected');
                }
                updateUI();
                saveState();
            });

            var poster = card.querySelector('.lib-card-poster');
            if (poster) {
                poster.appendChild(cb);
            }
        });
    }

    function removeCheckboxes() {
        var cbs = container.querySelectorAll('.delete-checkbox');
        cbs.forEach(function (cb) { cb.remove(); });
        var selectedCards = container.querySelectorAll('.delete-selected');
        selectedCards.forEach(function (c) { c.classList.remove('delete-selected'); });
    }

    // --- Confirmation dialog ---
    if (confirmBtn) {
        confirmBtn.addEventListener('click', function () {
            if (selected.size === 0) return;
            if (overlayCount) overlayCount.textContent = selected.size;
            if (overlay) overlay.classList.add('active');
        });
    }

    if (overlayCancelBtn) {
        overlayCancelBtn.addEventListener('click', function () {
            if (overlay) overlay.classList.remove('active');
        });
    }

    if (overlay) {
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.classList.remove('active');
        });
    }

    if (overlayConfirmBtn) {
        overlayConfirmBtn.addEventListener('click', function () {
            if (selected.size === 0) return;

            var items = [];
            selected.forEach(function (val) {
                items.push({ type: val.type, id: val.id });
            });

            overlayConfirmBtn.disabled = true;
            overlayConfirmBtn.textContent = 'Suppression...';

            fetch('/library/delete-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items })
            })
                .then(function (res) {
                    if (res.status === 403) {
                        return res.json().then(function (data) {
                            alert(data.error || 'Accès refusé.');
                            throw new Error('forbidden');
                        });
                    }
                    return res.json();
                })
                .then(function (data) {
                    if (data.deleted !== undefined) {
                        // Nettoyer l'état avant la redirection
                        clearState();
                        window.location.href = '/library/';
                    }
                })
                .catch(function (err) {
                    if (err.message !== 'forbidden') {
                        alert('Erreur lors de la suppression.');
                    }
                    overlayConfirmBtn.disabled = false;
                    overlayConfirmBtn.textContent = 'Confirmer la suppression';
                    if (overlay) overlay.classList.remove('active');
                });
        });
    }

    // --- Action : ajouter à une collection ---
    var collectionBtn = document.getElementById('collection-confirm-btn');
    var collectionOverlay = document.getElementById('collection-overlay');
    var collectionCount = document.getElementById('collection-overlay-count');
    var collectionInput = document.getElementById('collection-name-input');
    var collectionOverlayConfirm = document.getElementById('collection-overlay-confirm');
    var collectionOverlayCancel = document.getElementById('collection-overlay-cancel');

    if (collectionBtn) {
        collectionBtn.addEventListener('click', function () {
            if (selected.size === 0) return;
            if (collectionCount) collectionCount.textContent = selected.size;
            if (collectionInput) collectionInput.value = '';
            if (collectionOverlay) collectionOverlay.classList.add('active');
            if (collectionInput) setTimeout(function () { collectionInput.focus(); }, 50);
        });
    }

    if (collectionOverlayCancel) {
        collectionOverlayCancel.addEventListener('click', function () {
            if (collectionOverlay) collectionOverlay.classList.remove('active');
        });
    }

    if (collectionOverlay) {
        collectionOverlay.addEventListener('click', function (e) {
            if (e.target === collectionOverlay) collectionOverlay.classList.remove('active');
        });
    }

    if (collectionOverlayConfirm) {
        collectionOverlayConfirm.addEventListener('click', function () {
            var name = ((collectionInput && collectionInput.value) || '').trim();
            if (selected.size === 0 || !name) return;

            var items = [];
            selected.forEach(function (val) {
                items.push({ type: val.type, id: val.id });
            });

            collectionOverlayConfirm.disabled = true;
            collectionOverlayConfirm.textContent = 'Ajout...';

            fetch('/library/collection-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ collection_name: name, items: items })
            })
                .then(function (res) {
                    if (res.status === 403) {
                        return res.json().then(function (data) {
                            alert(data.error || 'Accès refusé.');
                            throw new Error('forbidden');
                        });
                    }
                    return res.json();
                })
                .then(function (data) {
                    if (data && data.assigned !== undefined) {
                        if (data.errors && data.errors.length > 0) {
                            alert(
                                data.errors.length +
                                    ' déplacement(s) de symlink en échec. ' +
                                    'Les fiches ont quand même été rattachées à la collection.'
                            );
                        }
                        clearState();
                        window.location.href = '/library/';
                    } else {
                        // Réponse inattendue : réactiver le bouton plutôt que le bloquer
                        collectionOverlayConfirm.disabled = false;
                        collectionOverlayConfirm.textContent = 'Ajouter à la collection';
                        alert('Réponse inattendue du serveur.');
                    }
                })
                .catch(function (err) {
                    if (err.message !== 'forbidden') {
                        alert('Erreur lors de l\'ajout à la collection.');
                    }
                    collectionOverlayConfirm.disabled = false;
                    collectionOverlayConfirm.textContent = 'Ajouter à la collection';
                    if (collectionOverlay) collectionOverlay.classList.remove('active');
                });
        });
    }

    // Ré-attacher les checkboxes après un swap HTMX (changement de filtre/page)
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (selectMode && e.detail.target && e.detail.target.id === 'library-content') {
            setTimeout(function () {
                applyToggleAppearance();
                attachCheckboxes();
                updateUI();
            }, 50);
        }
    });

    // Escape pour quitter le mode sélection
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && selectMode) {
            if (overlay && overlay.classList.contains('active')) {
                overlay.classList.remove('active');
            } else if (collectionOverlay && collectionOverlay.classList.contains('active')) {
                collectionOverlay.classList.remove('active');
            } else {
                exitSelectMode();
            }
        }
    });

    // --- Restauration de l'état au chargement de la page ---
    loadState();
    if (selectMode) {
        enterSelectMode();
    }
})();
