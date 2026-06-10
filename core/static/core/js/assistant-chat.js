(function () {
    const form = document.getElementById('assistant-form');
    const input = document.getElementById('assistant-input');
    const messagesEl = document.getElementById('assistant-messages');
    const sendBtn = document.getElementById('assistant-send');
    const streamUrl = window.ASSISTANT_CHAT_STREAM_URL;
    const ticketListEl = document.getElementById('assistant-ticket-list');
    const currentTicketEl = document.getElementById('assistant-current-ticket');
    const progressPanelEl = document.getElementById('assistant-progress-panel');
    const suggestUrl = window.CATEGORY_SUGGEST_URL;
    let allCategories = window.ASSISTANT_CATEGORIES || [];
    let chatCategoryPickerEl = null;
    let pendingComplaintText = '';

    if (!form || !messagesEl || !streamUrl) return;

    let sidebarState = window.ASSISTANT_SIDEBAR || {
        customer: null,
        tickets: [],
        current_ticket: null,
    };
    let selectedTicketId = sidebarState.current_ticket
        ? sidebarState.current_ticket.ticket_id
        : null;

    const STEP_ICONS = {
        pending: '<svg class="assistant-step-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="3 3"><circle cx="12" cy="12" r="9"/></svg>',
        active: '<svg class="assistant-step-icon assistant-step-icon--spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9" stroke-dasharray="14 42" stroke-linecap="round"/></svg>',
        done: '<svg class="assistant-step-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>',
        error: '<svg class="assistant-step-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    };

    const FIELD_ICONS = {
        status: 'activity',
        priority: 'flag',
        category: 'folder',
        issue: 'file-text',
        description: 'file-text',
    };

    function getCsrfToken() {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function portalTicketUrl(ticketId) {
        const base = (window.ASSISTANT_PORTAL_TICKETS_BASE || '/portal/tickets').replace(/\/$/, '');
        return base + '/' + encodeURIComponent(ticketId) + '/';
    }

    function ticketHref(ticket) {
        if (ticket && ticket.detail_url) {
            return ticket.detail_url;
        }
        return portalTicketUrl(ticket && ticket.ticket_id ? ticket.ticket_id : ticket);
    }

    function textWithTicketLinks(plainText) {
        const escaped = escapeHtml(plainText);
        return escaped.replace(/\b(TKT-[A-F0-9]{8})\b/gi, function (id) {
            return (
                '<a class="assistant-ticket-link" href="' +
                portalTicketUrl(id) +
                '">' +
                id +
                '</a>'
            );
        });
    }

    function stripMarkdown(text) {
        return (text || '')
            .replace(/\*\*(.+?)\*\*/g, '$1')
            .replace(/__(.+?)__/g, '$1')
            .replace(/\*(.+?)\*/g, '$1');
    }

    function formatDate(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
        } catch (e) {
            return '';
        }
    }

    const COMPLAINT_PATTERN = /problem|issue|complain|complaint|broken|fault|error|not working|help with|support|trouble|failed|outage|slow|down|fix|repair|wrong|missing|unable/i;

    function isComplaintMessage(text) {
        const t = (text || '').trim();
        if (t.length < 12) return false;
        if (COMPLAINT_PATTERN.test(t)) return true;
        return t.split(/\s+/).length >= 10;
    }

    function removeChatCategoryPicker() {
        if (chatCategoryPickerEl) {
            chatCategoryPickerEl.remove();
            chatCategoryPickerEl = null;
        }
    }

    function getChatCategoryIds() {
        if (!chatCategoryPickerEl) return [];
        return Array.from(
            chatCategoryPickerEl.querySelectorAll('input[type="checkbox"]:checked'),
        ).map(function (cb) { return parseInt(cb.value, 10); }).filter(Boolean);
    }

    function fetchCategoriesForDescription(description) {
        if (!suggestUrl) {
            return Promise.resolve(allCategories);
        }
        const url = suggestUrl + (suggestUrl.indexOf('?') >= 0 ? '&' : '?') +
            'description=' + encodeURIComponent(description || '');
        return fetch(url)
            .then(function (res) { return res.json(); })
            .then(function (data) {
                allCategories = data.categories || allCategories;
                return allCategories;
            })
            .catch(function () { return allCategories; });
    }

    function showChatCategoryPicker(description, promptText) {
        removeChatCategoryPicker();
        pendingComplaintText = description;

        const wrap = document.createElement('div');
        wrap.className = 'assistant-msg assistant-msg--bot assistant-msg--category-pick';
        wrap.id = 'assistant-chat-category-picker';
        wrap.innerHTML =
            '<div class="assistant-msg-bubble assistant-category-chat-card">' +
            '<p class="assistant-category-chat-card__title">' +
            escapeHtml(promptText || 'Which categories best describe your problem?') +
            '</p>' +
            '<p class="assistant-category-chat-card__hint">Select all that apply — we suggested matches based on what you wrote.</p>' +
            '<p class="assistant-category-chat-error" id="assistant-category-error">Please select at least one category.</p>' +
            '<div class="assistant-category-chat-list" role="group" aria-label="Complaint categories">' +
            '<p style="color:var(--text-muted);font-size:0.85rem;margin:0;">Loading categories…</p>' +
            '</div>' +
            '<div class="assistant-category-chat-actions">' +
            '<button type="button" class="btn btn-primary" id="assistant-category-continue">Continue</button>' +
            '<button type="button" class="btn btn-secondary" id="assistant-category-cancel">Cancel</button>' +
            '</div></div>';
        messagesEl.appendChild(wrap);
        chatCategoryPickerEl = wrap;
        scrollToBottom();

        const listEl = wrap.querySelector('.assistant-category-chat-list');
        const errEl = wrap.querySelector('.assistant-category-chat-error');
        const continueBtn = wrap.querySelector('#assistant-category-continue');
        const cancelBtn = wrap.querySelector('#assistant-category-cancel');

        fetchCategoriesForDescription(description).then(function (categories) {
            if (!categories.length) {
                listEl.innerHTML = '<p style="margin:0;color:var(--text-muted);font-size:0.85rem;">No categories available.</p>';
                return;
            }
            listEl.innerHTML = '';
            categories.forEach(function (cat) {
                const label = document.createElement('label');
                label.className = 'assistant-category-chat-option' +
                    (cat.suggested ? ' assistant-category-chat-option--suggested' : '');
                label.innerHTML =
                    '<input type="checkbox" value="' + cat.id + '"' +
                    (cat.suggested ? ' checked' : '') + '>' +
                    '<span>' + escapeHtml(cat.name) + '</span>' +
                    (cat.suggested ? '<span class="assistant-category-chat-option__badge">Suggested</span>' : '');
                listEl.appendChild(label);
            });
            scrollToBottom();
        });

        continueBtn.addEventListener('click', function () {
            const ids = getChatCategoryIds();
            if (!ids.length) {
                errEl.classList.add('assistant-category-chat-error--visible');
                return;
            }
            errEl.classList.remove('assistant-category-chat-error--visible');
            const msg = pendingComplaintText;
            removeChatCategoryPicker();
            pendingComplaintText = '';
            runAssistantStream(msg, ids);
        });

        cancelBtn.addEventListener('click', function () {
            pendingComplaintText = '';
            removeChatCategoryPicker();
            setLoading(false);
            input.focus();
        });
    }

    function applySidebarData(data) {
        if (!data) return;
        sidebarState = {
            customer: data.customer !== undefined ? data.customer : sidebarState.customer,
            tickets: data.tickets || sidebarState.tickets || [],
            current_ticket: data.current_ticket !== undefined ? data.current_ticket : sidebarState.current_ticket,
        };
        if (data.current_ticket && data.current_ticket.ticket_id) {
            selectedTicketId = data.current_ticket.ticket_id;
        }
        renderSidebar();
    }

    function findTicketById(ticketId) {
        if (!ticketId) return null;
        const list = sidebarState.tickets || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].ticket_id === ticketId) return list[i];
        }
        return sidebarState.current_ticket &&
            sidebarState.current_ticket.ticket_id === ticketId
            ? sidebarState.current_ticket
            : null;
    }

    function renderTicketCard(container, ticket) {
        if (!ticket) {
            container.innerHTML =
                '<p class="assistant-sidebar__empty">Select a ticket or create one in the chat.</p>';
            return;
        }
        const viewUrl = ticketHref(ticket);
        container.innerHTML =
            '<div class="assistant-sidebar-ticket-card">' +
            '<div class="assistant-sidebar-ticket-card__head">' +
            '<a class="assistant-ticket-link" href="' + escapeHtml(viewUrl) + '">' +
            escapeHtml(ticket.ticket_id) + '</a></div>' +
            '<div class="assistant-sidebar-ticket-card__body">' +
            '<div class="assistant-sidebar-ticket-card__row"><span class="assistant-sidebar-ticket-card__label">Status</span>' +
            '<span class="assistant-sidebar-ticket-card__value">' + escapeHtml(ticket.status || '—') + '</span></div>' +
            '<div class="assistant-sidebar-ticket-card__row"><span class="assistant-sidebar-ticket-card__label">Priority</span>' +
            '<span class="assistant-sidebar-ticket-card__value">' + escapeHtml(ticket.priority || '—') + '</span></div>' +
            '<div class="assistant-sidebar-ticket-card__row"><span class="assistant-sidebar-ticket-card__label">Categories</span>' +
            '<span class="assistant-sidebar-ticket-card__value">' +
            escapeHtml(ticket.categories || ticket.category || '—') + '</span></div>' +
            (ticket.description
                ? '<p class="assistant-sidebar-ticket-card__desc">' + escapeHtml(ticket.description) + '</p>'
                : '') +
            '<a class="assistant-ticket-link assistant-sidebar-ticket-card__view" href="' +
            escapeHtml(viewUrl) + '">View ticket details</a>' +
            '</div></div>';
    }

    function renderTicketList() {
        if (!ticketListEl) return;
        const tickets = sidebarState.tickets || [];
        if (!tickets.length) {
            ticketListEl.innerHTML =
                '<p class="assistant-sidebar__empty">No tickets yet. Ask me to open a support request.</p>';
            return;
        }

        const frag = document.createDocumentFragment();
        tickets.forEach(function (t) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'assistant-ticket-list-item' +
                (t.ticket_id === selectedTicketId ? ' assistant-ticket-list-item--active' : '');
            btn.dataset.ticketId = t.ticket_id;
            const itemUrl = ticketHref(t);
            btn.innerHTML =
                '<span class="assistant-ticket-list-item__id">' +
                '<a class="assistant-ticket-link" href="' + escapeHtml(itemUrl) + '" onclick="event.stopPropagation()">' +
                escapeHtml(t.ticket_id) + '</a></span>' +
                '<span class="assistant-ticket-list-item__meta">' +
                escapeHtml(t.status) + ' · ' + escapeHtml(t.priority) +
                (formatDate(t.created_at) ? ' · ' + formatDate(t.created_at) : '') +
                '</span>';
            btn.addEventListener('click', function () {
                selectedTicketId = t.ticket_id;
                renderSidebar();
            });
            frag.appendChild(btn);
        });
        ticketListEl.innerHTML = '';
        ticketListEl.appendChild(frag);
    }

    function renderCurrentTicket() {
        if (!currentTicketEl) return;
        let ticket = findTicketById(selectedTicketId);
        if (!ticket && sidebarState.current_ticket) {
            ticket = sidebarState.current_ticket;
            selectedTicketId = ticket.ticket_id;
        }
        renderTicketCard(currentTicketEl, ticket);
    }

    function renderSidebar() {
        renderTicketList();
        renderCurrentTicket();
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }

    function isTicketDetailLine(line) {
        return /^\s*(Status|Priority|Categories?|Issue|Description|Link)\s*:/i.test(line);
    }

    function isTicketHeader(line) {
        const t = line.trim();
        return t.startsWith('🎫') || /^Ticket\s*[—\-:]/i.test(t) || /\bTKT-[A-F0-9]+\b/i.test(t) && /ticket/i.test(t);
    }

    function renderBotReply(container, rawText) {
        const text = stripMarkdown(rawText);
        const lines = text.split('\n');
        const frag = document.createDocumentFragment();
        let cardBody = null;

        function closeCard() {
            cardBody = null;
        }

        function openCard(titleLine) {
            closeCard();
            const card = document.createElement('div');
            card.className = 'assistant-ticket-card';
            const title = document.createElement('div');
            title.className = 'assistant-ticket-card__title';
            title.innerHTML =
                '<i data-feather="tag"></i><span>' + textWithTicketLinks(titleLine.trim()) + '</span>';
            card.appendChild(title);
            cardBody = document.createElement('div');
            cardBody.className = 'assistant-ticket-card__body';
            card.appendChild(cardBody);
            frag.appendChild(card);
        }

        function addDetailLine(line) {
            const match = line.trim().match(/^(Status|Priority|Categories?|Issue|Description|Link)\s*:\s*(.*)$/i);
            if (!match) return;
            const key = match[1].toLowerCase();
            const row = document.createElement('div');
            row.className = 'assistant-ticket-card__row';
            const icon = FIELD_ICONS[key] || (key === 'link' ? 'external-link' : 'info');
            let valueHtml = escapeHtml(match[2].trim());
            if (key === 'link') {
                const href = match[2].trim();
                valueHtml =
                    '<a class="assistant-ticket-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener">Open ticket</a>';
            } else {
                valueHtml = textWithTicketLinks(match[2].trim());
            }
            row.innerHTML =
                '<i data-feather="' + icon + '"></i>' +
                '<span class="assistant-ticket-card__label">' + escapeHtml(match[1]) + '</span>' +
                '<span class="assistant-ticket-card__value">' + valueHtml + '</span>';
            cardBody.appendChild(row);
        }

        function addParagraph(line) {
            const p = document.createElement('p');
            p.className = 'assistant-reply-line';
            p.innerHTML = textWithTicketLinks(line.trim());
            frag.appendChild(p);
        }

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const trimmed = line.trim();

            if (!trimmed) {
                closeCard();
                continue;
            }

            if (isTicketHeader(trimmed)) {
                openCard(trimmed);
                continue;
            }

            if (cardBody && isTicketDetailLine(line)) {
                addDetailLine(line);
                continue;
            }

            closeCard();
            addParagraph(line);
        }

        closeCard();

        if (!frag.childNodes.length) {
            const p = document.createElement('p');
            p.className = 'assistant-reply-line';
            p.innerHTML = textWithTicketLinks(text);
            frag.appendChild(p);
        }

        container.innerHTML = '';
        container.appendChild(frag);
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }

    const LOGIN_TRIGGER = /sign[\s\-]?in|portal login|log[\s\-]?in.*portal|please sign|must be signed/i;

    function maybeAppendSignInButton(wrap, text) {
        const loginUrl = window.ASSISTANT_PORTAL_LOGIN_URL;
        if (!loginUrl) return;
        if (!LOGIN_TRIGGER.test(text)) return;
        const btn = document.createElement('a');
        btn.href = loginUrl;
        btn.className = 'btn btn-primary assistant-signin-btn';
        btn.innerHTML = '<i data-feather="log-in"></i> Sign In';
        wrap.appendChild(btn);
        if (typeof feather !== 'undefined') feather.replace();
    }

    function setBotBubbleContent(bubble, text) {
        bubble.classList.add('assistant-msg-bubble--formatted');
        renderBotReply(bubble, text);
    }

    function appendMessage(role, text) {
        const wrap = document.createElement('div');
        wrap.className = 'assistant-msg assistant-msg--' + (role === 'user' ? 'user' : 'bot');
        const bubble = document.createElement('div');
        bubble.className = 'assistant-msg-bubble';
        if (role === 'user') {
            bubble.textContent = text;
        } else {
            setBotBubbleContent(bubble, text);
            maybeAppendSignInButton(wrap, text);
        }
        wrap.appendChild(bubble);
        messagesEl.appendChild(wrap);
        scrollToBottom();
        return wrap;
    }

    function setLoading(loading) {
        input.disabled = loading;
        sendBtn.disabled = loading;
    }

    function showTypingIndicator() {
        const wrap = document.createElement('div');
        wrap.className = 'assistant-msg assistant-msg--bot assistant-msg--typing';
        wrap.id = 'assistant-typing';
        wrap.innerHTML = '<div class="assistant-msg-bubble">Thinking…</div>';
        messagesEl.appendChild(wrap);
        scrollToBottom();
        return wrap;
    }

    function removeTypingIndicator() {
        const el = document.getElementById('assistant-typing');
        if (el) el.remove();
    }

    function createSidebarProgress() {
        if (!progressPanelEl) return null;
        progressPanelEl.classList.add('assistant-progress-panel--busy');
        progressPanelEl.innerHTML =
            '<div class="assistant-progress-bubble">' +
            '<div class="assistant-progress-title">Working on your request</div>' +
            '<ul class="assistant-steps" role="list"></ul>' +
            '</div>';
        return {
            list: progressPanelEl.querySelector('.assistant-steps'),
            title: progressPanelEl.querySelector('.assistant-progress-title'),
            steps: new Map(),
        };
    }

    function resetSidebarProgressIdle() {
        if (!progressPanelEl) return;
        progressPanelEl.classList.remove('assistant-progress-panel--busy');
        progressPanelEl.innerHTML =
            '<p class="assistant-sidebar__empty assistant-progress-idle">Waiting for your next message.</p>';
    }

    function finishSidebarProgress(progress) {
        if (!progress || !progress.title) return;
        progress.title.textContent = 'Done';
        const bubble = progressPanelEl.querySelector('.assistant-progress-bubble');
        if (bubble) bubble.classList.add('assistant-progress-bubble--done');
    }

    function upsertStep(progress, stepId, label, status) {
        if (!progress) return;
        let row = progress.steps.get(stepId);
        if (!row) {
            row = document.createElement('li');
            row.className = 'assistant-step';
            row.dataset.stepId = stepId;
            row.innerHTML =
                '<span class="assistant-step-icon-wrap"></span>' +
                '<span class="assistant-step-label"></span>';
            progress.list.appendChild(row);
            progress.steps.set(stepId, row);
        }

        row.className = 'assistant-step assistant-step--' + status;
        row.querySelector('.assistant-step-label').textContent = label;
        row.querySelector('.assistant-step-icon-wrap').innerHTML =
            STEP_ICONS[status] || STEP_ICONS.pending;
    }

    async function readNdjsonStream(response, onEvent) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed) continue;
                try {
                    onEvent(JSON.parse(trimmed));
                } catch (e) {
                    /* skip */
                }
            }
        }

        if (buffer.trim()) {
            try {
                onEvent(JSON.parse(buffer.trim()));
            } catch (e) {
                /* ignore */
            }
        }
    }

    document.querySelectorAll('.assistant-msg--bot .assistant-msg-bubble').forEach(function (bubble) {
        const raw = bubble.textContent.trim();
        if (raw && !bubble.classList.contains('assistant-msg-bubble--formatted')) {
            setBotBubbleContent(bubble, raw);
        }
    });

    renderSidebar();

    async function runAssistantStream(text, categoryIds) {
        setLoading(true);
        const progress = createSidebarProgress();
        const typing = showTypingIndicator();
        let finalReply = '';
        let showedPicker = false;

        try {
            const res = await fetch(streamUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({
                    message: text,
                    category_ids: categoryIds || [],
                }),
            });

            if (!res.ok) {
                let errMsg = 'Something went wrong. Please try again.';
                try {
                    const data = await res.json();
                    if (data.error) errMsg = data.error;
                } catch (err) { /* ignore */ }
                resetSidebarProgressIdle();
                removeTypingIndicator();
                appendMessage('bot', errMsg);
                return;
            }

            await readNdjsonStream(res, function (event) {
                if (event.event === 'category_picker') {
                    showedPicker = true;
                    removeTypingIndicator();
                    resetSidebarProgressIdle();
                    showChatCategoryPicker(
                        event.description || text,
                        event.prompt,
                    );
                } else if (event.event === 'step') {
                    upsertStep(progress, event.id, event.label, event.status);
                } else if (event.event === 'sidebar') {
                    applySidebarData(event);
                } else if (event.event === 'done') {
                    finalReply = event.reply || 'No response.';
                    if (event.sidebar) {
                        applySidebarData(event.sidebar);
                    }
                } else if (event.event === 'error') {
                    upsertStep(progress, 'error', event.message || 'Something failed', 'error');
                }
            });

            if (showedPicker) {
                return;
            }

            finishSidebarProgress(progress);
            removeTypingIndicator();
            appendMessage('bot', finalReply || 'How can I help you further?');
        } catch (err) {
            resetSidebarProgressIdle();
            removeTypingIndicator();
            appendMessage('bot', 'Network error. Please check your connection and try again.');
        } finally {
            if (!chatCategoryPickerEl) {
                setLoading(false);
                input.focus();
            }
        }
    }

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const text = (input.value || '').trim();
        if (!text) return;
        if (chatCategoryPickerEl) return;

        appendMessage('user', text);
        input.value = '';

        await runAssistantStream(text, getChatCategoryIds());
    });

    scrollToBottom();
})();
