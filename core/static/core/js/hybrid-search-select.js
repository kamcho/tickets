/**
 * Hybrid search select: text input + dropdown, backed by a hidden field and optional API.
 */
(function (global) {
    'use strict';

    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    function initHybridSearchSelect(config) {
        const hiddenEl = config.hiddenEl;
        if (!hiddenEl) return null;

        const container = document.createElement('div');
        container.className = 'search-select-container';

        const wrapper = document.createElement('div');
        wrapper.className = 'search-select-input-wrapper';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-input search-select-input';
        input.placeholder = config.placeholder || 'Search...';
        input.autocomplete = 'off';
        if (config.disabled) input.disabled = true;

        const icon = document.createElement('i');
        icon.setAttribute('data-feather', 'chevron-down');
        icon.className = 'search-select-chevron';
        icon.style.width = '16px';
        icon.style.height = '16px';

        wrapper.appendChild(input);
        wrapper.appendChild(icon);
        container.appendChild(wrapper);

        const dropdown = document.createElement('div');
        dropdown.className = 'search-select-dropdown';
        container.appendChild(dropdown);

        hiddenEl.parentNode.insertBefore(container, hiddenEl);
        hiddenEl.type = 'hidden';
        hiddenEl.style.display = 'none';

        let selected = config.initial || null;
        let localOptions = config.localOptions || [];
        let fetchAbort = null;

        function setHiddenValue(value) {
            hiddenEl.value = value || '';
            hiddenEl.dispatchEvent(new Event('change', { bubbles: true }));
        }

        function applySelection(item) {
            if (!item) {
                selected = null;
                input.value = '';
                setHiddenValue('');
                return;
            }
            selected = item;
            input.value = config.displayLabel(item);
            setHiddenValue(String(item.value));
        }

        function renderMessage(text, className) {
            dropdown.innerHTML = '';
            const el = document.createElement('div');
            el.className = className || 'search-select-no-results';
            el.textContent = text;
            dropdown.appendChild(el);
        }

        function renderOptions(items, hasMore) {
            dropdown.innerHTML = '';
            if (!items.length) {
                renderMessage(config.emptyMessage || 'No matches found');
                return;
            }
            items.forEach(item => {
                const btn = document.createElement('div');
                btn.className = 'search-select-option';
                btn.setAttribute('role', 'option');
                config.renderOption(item, btn);
                btn.addEventListener('click', () => {
                    applySelection(item);
                    closeDropdown();
                });
                dropdown.appendChild(btn);
            });
            if (hasMore) {
                const hint = document.createElement('div');
                hint.className = 'search-select-more-hint';
                hint.textContent = config.moreMessage || 'Keep typing to narrow results…';
                dropdown.appendChild(hint);
            }
        }

        function filterLocal(term) {
            const t = term.toLowerCase().trim();
            const filtered = localOptions.filter(opt => {
                if (opt.isPlaceholder) return false;
                if (!t) return true;
                return (opt.searchText || '').toLowerCase().includes(t);
            });
            const limit = config.limit || 20;
            const hasMore = filtered.length > limit;
            return { items: filtered.slice(0, limit), hasMore };
        }

        async function fetchRemote(term) {
            if (!config.searchUrl) return { items: [], hasMore: false };
            if (fetchAbort) fetchAbort.abort();
            fetchAbort = new AbortController();
            const url = new URL(config.searchUrl, window.location.origin);
            url.searchParams.set('q', term);
            const response = await fetch(url.toString(), {
                signal: fetchAbort.signal,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) throw new Error('Search failed');
            const data = await response.json();
            return {
                items: (data.results || []).map(r => ({
                    value: String(r.id),
                    name: r.name,
                    sublabel: r.sublabel || '',
                })),
                hasMore: !!data.has_more,
            };
        }

        const loadResults = debounce(async function () {
            const term = input.value.trim();
            if (config.searchUrl) {
                if (term.length < (config.minChars || 0)) {
                    renderMessage(config.startMessage || 'Type to search…');
                    return;
                }
                renderMessage('Searching…', 'search-select-loading');
                try {
                    const { items, hasMore } = await fetchRemote(term);
                    renderOptions(items, hasMore);
                } catch (err) {
                    if (err.name !== 'AbortError') {
                        renderMessage('Could not load results');
                    }
                }
                return;
            }
            const { items, hasMore } = filterLocal(term);
            renderOptions(items, hasMore);
        }, config.debounceMs || 250);

        function openDropdown() {
            if (input.disabled) return;
            container.classList.add('open');
            loadResults();
        }

        function closeDropdown() {
            container.classList.remove('open');
        }

        input.addEventListener('focus', openDropdown);
        input.addEventListener('input', () => {
            if (selected && input.value !== config.displayLabel(selected)) {
                selected = null;
                setHiddenValue('');
            }
            openDropdown();
        });

        document.addEventListener('click', e => {
            if (!container.contains(e.target)) {
                closeDropdown();
                if (selected) {
                    input.value = config.displayLabel(selected);
                } else if (!input.value.trim()) {
                    setHiddenValue('');
                }
            }
        });

        if (config.initial) {
            applySelection(config.initial);
        }

        return {
            container,
            input,
            setDisabled(disabled) {
                input.disabled = disabled;
                if (disabled) {
                    applySelection(null);
                    closeDropdown();
                }
            },
            clear() {
                applySelection(null);
            },
            refreshIcons() {
                if (global.feather) global.feather.replace();
            },
        };
    }

    function renderNamePhoneOption(item, el) {
        const nameSpan = document.createElement('span');
        nameSpan.className = 'search-select-option-name';
        nameSpan.textContent = item.name;
        el.appendChild(nameSpan);
        if (item.sublabel) {
            const sub = document.createElement('span');
            sub.className = 'search-select-option-phone';
            sub.textContent = item.sublabel;
            el.appendChild(sub);
        }
    }

    global.initHybridSearchSelect = initHybridSearchSelect;
    global.renderNamePhoneOption = renderNamePhoneOption;
})(window);
