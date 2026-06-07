/**
 * Multi-select categories: modern cards, selection count, description suggestions.
 * Django CheckboxSelectMultiple renders #id_categories > div (not ul/li).
 */
(function () {
    'use strict';

    function getLabelText(labelEl, inputEl) {
        const clone = labelEl.cloneNode(true);
        const inp = clone.querySelector('input');
        if (inp) inp.remove();
        return (clone.textContent || '').replace(/\s+/g, ' ').trim();
    }

    function initSection(section) {
        const categoriesRoot = section.querySelector('[id$="_categories"]');
        if (!categoriesRoot) return;

        const countEl = section.querySelector('[data-category-count]');
        const descEl = document.getElementById('complaint-description') ||
            document.getElementById('ticket-description');
        const suggestUrl = window.CATEGORY_SUGGEST_URL;
        let debounceTimer = null;

        const optionDivs = Array.from(categoriesRoot.querySelectorAll(':scope > div'));
        if (!optionDivs.length) return;

        categoriesRoot.classList.add('category-picker-grid');
        const inputs = [];

        optionDivs.forEach(function (row) {
            const input = row.querySelector('input[type="checkbox"]');
            const label = row.querySelector('label');
            if (!input || !label) return;

            const text = getLabelText(label, input);
            row.className = 'category-card';
            row.dataset.categoryId = input.value;

            const check = document.createElement('span');
            check.className = 'category-card__check';
            check.setAttribute('aria-hidden', 'true');

            const textSpan = document.createElement('span');
            textSpan.className = 'category-card__text';
            textSpan.textContent = text;

            label.className = 'category-card__label';
            label.innerHTML = '';
            label.appendChild(input);
            label.appendChild(check);
            label.appendChild(textSpan);

            input.className = 'category-card__input';
            inputs.push(input);
        });

        function updateSelectedCount() {
            const checked = inputs.filter(function (cb) { return cb.checked; }).length;
            if (!countEl) return;
            countEl.textContent = checked === 1 ? '1 selected' : checked + ' selected';
            countEl.classList.toggle('ticket-categories-count--active', checked > 0);
        }

        function syncCardState(input) {
            const card = input.closest('.category-card');
            if (card) {
                card.classList.toggle('category-card--checked', input.checked);
            }
        }

        function applySuggestions(suggestedIds) {
            const set = new Set((suggestedIds || []).map(Number));
            inputs.forEach(function (cb) {
                const card = cb.closest('.category-card');
                const id = parseInt(cb.value, 10);
                if (set.has(id)) {
                    cb.checked = true;
                    if (card) card.classList.add('category-card--suggested');
                } else if (card) {
                    card.classList.remove('category-card--suggested');
                }
                syncCardState(cb);
            });
            updateSelectedCount();
        }

        function fetchSuggestions() {
            if (!suggestUrl || !descEl) return;
            const text = (descEl.value || '').trim();
            if (text.length < 8) return;

            const url = suggestUrl + (suggestUrl.indexOf('?') >= 0 ? '&' : '?') +
                'description=' + encodeURIComponent(text);

            fetch(url)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    const ids = (data.categories || [])
                        .filter(function (c) { return c.suggested; })
                        .map(function (c) { return c.id; });
                    if (ids.length) applySuggestions(ids);
                })
                .catch(function () { /* ignore */ });
        }

        categoriesRoot.addEventListener('change', function (e) {
            if (!e.target.matches('.category-card__input')) return;
            syncCardState(e.target);
            if (!e.target.checked) {
                const card = e.target.closest('.category-card');
                if (card) card.classList.remove('category-card--suggested');
            }
            updateSelectedCount();
        });

        inputs.forEach(function (cb) {
            syncCardState(cb);
        });
        updateSelectedCount();

        if (descEl && suggestUrl) {
            descEl.addEventListener('input', function () {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(fetchSuggestions, 400);
            });
            if ((descEl.value || '').trim().length >= 8) {
                fetchSuggestions();
            }
        }
    }

    function init() {
        document.querySelectorAll('.ticket-categories-section').forEach(initSection);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
