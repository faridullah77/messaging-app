const socket = io();
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const messagesContainer = document.getElementById('messages');

let currentReplyId = null;
let currentDeleteMsgId = null;
let typingTimeout;

// ── Scroll to bottom on load ──
scrollToBottom();

// ── Convert UTC to Local Time ──
function formatLocalTime(utcString) {
    const date = new Date(utcString + 'Z');
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
}

// ── Convert existing messages time on page load ──
document.querySelectorAll('.message-time[data-utc]').forEach(el => {
    el.textContent = formatLocalTime(el.dataset.utc);
});

// ── Convert last seen time ──
document.querySelectorAll('.last-seen-time[data-utc]').forEach(el => {
    el.textContent = formatLocalTime(el.dataset.utc);
});

// ── Mark existing messages as seen ──
document.querySelectorAll('.message.theirs[data-msg-id]').forEach(el => {
    socket.emit('message_seen', { msg_id: parseInt(el.dataset.msgId) });
});

// ── Image Upload ──
document.getElementById('image-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5000000) {
        alert('Image 5MB se badi nahi honi chahiye!');
        return;
    }
    const formData = new FormData();
    formData.append('image', file);
    formData.append('receiver_id', FRIEND_ID);

    const uploadingEl = document.createElement('div');
    uploadingEl.classList.add('message', 'mine');
    uploadingEl.innerHTML = `<div class="message-bubble" style="opacity:0.6">📷 Uploading...</div>`;
    messagesContainer.appendChild(uploadingEl);
    scrollToBottom();

    fetch('/upload_image', { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
        uploadingEl.remove();
        if (!data.success) alert('Upload failed: ' + data.error);
        e.target.value = '';
    })
    .catch(() => {
        uploadingEl.remove();
        alert('Upload failed!');
    });
});
// ── View Once Upload ──
document.getElementById('view-once-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5000000) {
        alert('Image 5MB se badi nahi honi chahiye!');
        return;
    }
    const formData = new FormData();
    formData.append('image', file);
    formData.append('receiver_id', FRIEND_ID);
    formData.append('view_once', 'true');

    const uploadingEl = document.createElement('div');
    uploadingEl.classList.add('message', 'mine');
    uploadingEl.innerHTML = `<div class="message-bubble" style="opacity:0.6">👁️ Uploading view once...</div>`;
    messagesContainer.appendChild(uploadingEl);
    scrollToBottom();

    fetch('/upload_image', { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
        uploadingEl.remove();
        if (!data.success) alert('Upload failed: ' + data.error);
        e.target.value = '';
    })
    .catch(() => {
        uploadingEl.remove();
        alert('Upload failed!');
    });
});

// ── View Once - Tap to view ──
function viewOnceImage(msgId, el) {
    const msgEl = el.closest('.message');
    const url = el.dataset.url;

    // Show image in fullscreen
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:99999;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:16px;';
    overlay.innerHTML = `
        <p style="color:#fff;font-size:13px;opacity:0.7;">👁️ View Once — will disappear after closing</p>
        <img src="${el.dataset.url}" style="max-width:90vw;max-height:80vh;border-radius:12px;object-fit:contain;"/>
        <button onclick="closeViewOnce(${msgId}, this.closest('div[style]'))" 
                style="padding:10px 24px;border-radius:24px;border:none;background:#25d366;color:#fff;font-size:14px;cursor:pointer;">
            Close
        </button>
    `;
    document.body.appendChild(overlay);

    // Mark as viewed
    fetch(`/view_once/${msgId}`, { method: 'POST' });
}

function closeViewOnce(msgId, overlay) {
    overlay.remove();
}

socket.on('view_once_viewed', (data) => {
    const msgEl = document.querySelector(`[data-msg-id="${data.msg_id}"]`);
    if (msgEl) {
        const viewOnce = msgEl.querySelector('.view-once-tap, .view-once-sent');
        if (viewOnce) {
            viewOnce.outerHTML = '<div class="view-once-viewed">👁️ Viewed</div>';
        }
    }
});

// ── Send Message ──
function sendMessage() {
    const message = messageInput.value.trim();
    if (message === '') return;
    socket.emit('send_message', {
        message: message,
        receiver_id: FRIEND_ID,
        reply_to_id: currentReplyId
    });
   messageInput.value = '';
    messageInput.style.height = 'auto';
    messageInput.focus();
    cancelReply();
    socket.emit('stop_typing', { receiver_id: FRIEND_ID });
}

sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ── Auto resize textarea ──
messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
    socket.emit('typing', { receiver_id: FRIEND_ID });
    clearTimeout(typingTimeout);
    typingTimeout = setTimeout(() => {
        socket.emit('stop_typing', { receiver_id: FRIEND_ID });
    }, 2000);
});



socket.on('user_typing', (data) => {
    if (data.sender_id !== CURRENT_USER_ID) {
        document.getElementById('typing-indicator').style.display = 'flex';
    }
});

socket.on('user_stop_typing', (data) => {
    if (data.sender_id !== CURRENT_USER_ID) {
        document.getElementById('typing-indicator').style.display = 'none';
    }
});

// ── Notification Sound ──
function playNotificationSound() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(880, audioCtx.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.1);
        gainNode.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
        oscillator.start(audioCtx.currentTime);
        oscillator.stop(audioCtx.currentTime + 0.3);
    } catch(e) {
        console.log('Sound not supported');
    }
}

// ── Receive Message ──
socket.on('receive_message', (data) => {
    const isMine = data.sender_id === CURRENT_USER_ID;
    if (!isMine) {
        playNotificationSound();
        socket.emit('message_seen', { msg_id: data.msg_id });
        document.getElementById('typing-indicator').style.display = 'none';
    }
    const msgEl = document.createElement('div');
    msgEl.classList.add('message', isMine ? 'mine' : 'theirs');
    if (data.msg_id) msgEl.dataset.msgId = data.msg_id;

    const replyHtml = data.reply_preview ? `
        <div class="reply-quote">
            <span>${escapeHtml(data.reply_preview.content)}</span>
        </div>` : '';

    msgEl.innerHTML = `
        ${!isMine ? `<span class="message-sender">${data.sender}</span>` : ''}
        ${replyHtml}
       ${data.view_once && !isMine ?
            `<div class="view-once-tap" data-url="${data.message.slice(7,-8)}" onclick="viewOnceImage(${data.msg_id}, this)">👁️ Tap to view (view once)</div>` :
            data.view_once && isMine ?
            `<div class="view-once-sent">👁️ View once • Not viewed yet</div>` :
            `<div class="message-bubble" id="bubble-${data.msg_id}">${renderContent(data.message)}</div>`
        }
        <div class="emoji-picker" id="picker-${data.msg_id}">
            <span onclick="sendReaction(${data.msg_id}, '❤️')">❤️</span>
            <span onclick="sendReaction(${data.msg_id}, '😂')">😂</span>
            <span onclick="sendReaction(${data.msg_id}, '😮')">😮</span>
            <span onclick="sendReaction(${data.msg_id}, '😢')">😢</span>
            <span onclick="sendReaction(${data.msg_id}, '👍')">👍</span>
            <span onclick="sendReaction(${data.msg_id}, '🔥')">🔥</span>
        </div>
        <div class="reactions-bar" id="reactions-${data.msg_id}"></div>
        <div class="message-meta">
            <span class="message-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true })}</span>
            ${isMine ? `<span class="tick" id="tick-${data.msg_id}">✓</span>` : ''}
            ${isMine ? `<span class="edit-btn" onclick="startEdit(${data.msg_id}, '${escapeHtml(data.message).replace(/'/g, "\\'")}')">✏️</span>` : ''}
            ${isMine ? `<span class="delete-btn" onclick="showDeleteOptions(${data.msg_id}, this)">🗑️</span>` : ''}
            <span class="reply-btn" onclick="setReply(${data.msg_id}, '${escapeHtml(data.message).substring(0, 50)}')">↩️</span>
        </div>
    `;
    messagesContainer.appendChild(msgEl);
    scrollToBottom();
});

// ── Message Read ──
socket.on('message_read', (data) => {
    const tick = document.getElementById(`tick-${data.msg_id}`);
    if (tick) {
        tick.textContent = '✓✓';
        tick.classList.add('seen');
    }
});

// ── Message Deleted ──
socket.on('message_deleted', (data) => {
    const msgEl = document.querySelector(`[data-msg-id="${data.msg_id}"]`);
    if (msgEl) {
        const bubble = msgEl.querySelector('.message-bubble');
        if (bubble) {
            bubble.textContent = 'This message was deleted';
            bubble.style.opacity = '0.4';
            bubble.style.fontStyle = 'italic';
        }
        const picker = msgEl.querySelector('.emoji-picker');
        if (picker) picker.remove();
        const deleteBtn = msgEl.querySelector('.delete-btn');
        if (deleteBtn) deleteBtn.remove();
    }
});

// ── Delete Message ──
function showDeleteOptions(msgId, btn) {
    currentDeleteMsgId = msgId;
    document.getElementById('delete-modal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('delete-modal').style.display = 'none';
    currentDeleteMsgId = null;
}

function deleteMessage(deleteFor) {
    if (!currentDeleteMsgId) return;
    fetch(`/delete_message/${currentDeleteMsgId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delete_for: deleteFor })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const msgEl = document.querySelector(`[data-msg-id="${currentDeleteMsgId}"]`);
            if (msgEl) {
                if (deleteFor === 'everyone') {
                    const bubble = msgEl.querySelector('.message-bubble');
                    if (bubble) {
                        bubble.textContent = 'This message was deleted';
                        bubble.style.opacity = '0.4';
                        bubble.style.fontStyle = 'italic';
                    }
                } else {
                    msgEl.remove();
                }
            }
        }
        closeDeleteModal();
    });
}

// ── Reply ──
function setReply(msgId, content) {
    currentReplyId = msgId;
    document.getElementById('reply-preview-text').textContent = content;
    document.getElementById('reply-preview').style.display = 'block';
    messageInput.focus();
}

function cancelReply() {
    currentReplyId = null;
    document.getElementById('reply-preview').style.display = 'none';
}

// ── Edit Message ──
function startEdit(msgId, currentContent) {
    const bubble = document.getElementById(`bubble-${msgId}`);
    if (!bubble) return;
    bubble.innerHTML = `
        <input type="text" class="edit-input" id="edit-input-${msgId}" value="${escapeHtml(currentContent)}" />
        <div class="edit-actions">
            <button onclick="saveEdit(${msgId}, '${escapeHtml(currentContent)}')" class="btn-save-edit">✓ Save</button>
            <button onclick="cancelEdit(${msgId}, '${escapeHtml(currentContent)}')" class="btn-cancel-edit">✕ Cancel</button>
        </div>
    `;
    document.getElementById(`edit-input-${msgId}`).focus();
}

function saveEdit(msgId, originalContent) {
    const input = document.getElementById(`edit-input-${msgId}`);
    if (!input) return;
    const newContent = input.value.trim();
    if (!newContent) return;
    fetch(`/edit_message/${msgId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newContent })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const bubble = document.getElementById(`bubble-${msgId}`);
            if (bubble) bubble.innerHTML = `${escapeHtml(newContent)} <span class="edited-tag">(edited)</span>`;
        } else {
            cancelEdit(msgId, originalContent);
        }
    });
}

function cancelEdit(msgId, originalContent) {
    const bubble = document.getElementById(`bubble-${msgId}`);
    if (bubble) bubble.innerHTML = escapeHtml(originalContent);
}

socket.on('message_edited', (data) => {
    const bubble = document.getElementById(`bubble-${data.msg_id}`);
    if (bubble) bubble.innerHTML = `${escapeHtml(data.new_content)} <span class="edited-tag">(edited)</span>`;
});

// ── Emoji Reactions ──
function sendReaction(msgId, emoji) {
    socket.emit('send_reaction', { msg_id: msgId, emoji: emoji });
    document.querySelectorAll('.emoji-picker').forEach(p => p.classList.remove('show'));
}

socket.on('reaction_updated', (data) => {
    const bar = document.getElementById(`reactions-${data.msg_id}`);
    if (!bar) return;
    bar.innerHTML = '';
    for (const [emoji, count] of Object.entries(data.reactions)) {
        const span = document.createElement('span');
        span.classList.add('reaction-pill');
        span.textContent = `${emoji} ${count}`;
        bar.appendChild(span);
    }
});

// ── Show emoji picker on hover (desktop) ──
document.addEventListener('mouseover', (e) => {
    const msg = e.target.closest('.message');
    if (msg && !e.target.closest('.emoji-picker')) {
        const msgId = msg.dataset.msgId;
        const picker = document.getElementById(`picker-${msgId}`);
        if (picker) {
            document.querySelectorAll('.emoji-picker').forEach(p => p.classList.remove('show'));
            picker.classList.add('show');
        }
    }
});

document.addEventListener('mouseout', (e) => {
    const msg = e.target.closest('.message');
    if (msg && !msg.contains(e.relatedTarget)) {
        const msgId = msg.dataset.msgId;
        const picker = document.getElementById(`picker-${msgId}`);
        if (picker) picker.classList.remove('show');
    }
});

// ── Long press mobile ──
let pressTimer;
let touchMoved = false;

document.addEventListener('touchstart', (e) => {
    touchMoved = false;
    const msg = e.target.closest('.message');
    if (msg && !e.target.closest('.emoji-picker')) {
        pressTimer = setTimeout(() => {
            if (!touchMoved) {
                const msgId = msg.dataset.msgId;
                const picker = document.getElementById(`picker-${msgId}`);
                if (picker) {
                    document.querySelectorAll('.emoji-picker').forEach(p => p.classList.remove('show'));
                    picker.classList.add('show');
                }
            }
        }, 500);
    }
}, { passive: true });

document.addEventListener('touchmove', () => {
    touchMoved = true;
    clearTimeout(pressTimer);
}, { passive: true });

document.addEventListener('touchend', () => clearTimeout(pressTimer), { passive: true });

// ── Close picker when clicking outside ──
document.addEventListener('click', (e) => {
    if (!e.target.closest('.message') && !e.target.closest('.emoji-picker')) {
        document.querySelectorAll('.emoji-picker').forEach(p => p.classList.remove('show'));
    }
});

// ── Search Messages ──
function toggleSearch() {
    const bar = document.getElementById('chat-search-bar');
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('chat-search-input').focus();
}

function closeSearch() {
    document.getElementById('chat-search-bar').style.display = 'none';
    document.querySelectorAll('.message').forEach(m => m.style.opacity = '1');
}

document.getElementById('chat-search-input')?.addEventListener('input', (e) => {
    const query = e.target.value.trim().toLowerCase();
    if (!query) {
        document.querySelectorAll('.message').forEach(m => m.style.opacity = '1');
        return;
    }
    document.querySelectorAll('.message').forEach(m => {
        const bubble = m.querySelector('.message-bubble');
        if (bubble && bubble.textContent.toLowerCase().includes(query)) {
            m.style.opacity = '1';
            m.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else {
            m.style.opacity = '0.2';
        }
    });
});

// ── Dark/Light Theme ──
function toggleTheme() {
    document.body.classList.toggle('light-mode');
    const btn = document.querySelector('.theme-toggle-btn');
    btn.textContent = document.body.classList.contains('light-mode') ? '☀️' : '🌙';
    localStorage.setItem('theme', document.body.classList.contains('light-mode') ? 'light' : 'dark');
}

if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light-mode');
    document.querySelector('.theme-toggle-btn').textContent = '☀️';
}

// ── Helpers ──
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    document.getElementById('scroll-bottom-btn').style.display = 'none';
}

// ── Show/hide scroll button ──
messagesContainer.addEventListener('scroll', () => {
    const btn = document.getElementById('scroll-bottom-btn');
    const distanceFromBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight;
    if (distanceFromBottom > 200) {
        btn.style.display = 'flex';
    } else {
        btn.style.display = 'none';
    }
});

function renderContent(content) {
    if (content.startsWith('[IMAGE]') && content.endsWith('[/IMAGE]')) {
        const url = content.slice(7, -8);
        return `<img src="${url}" class="chat-image" onclick="window.open('${url}', '_blank')" />`;
    }
    return escapeHtml(content);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}
// ── Custom Wallpaper ──
const WALLPAPER_KEY = `wallpaper_${FRIEND_ID}`;
const chatArea = document.querySelector('.chat-area');

const wallpapers = {
    'default': { type: 'pattern', value: '#eae6df' },
    'purple': { type: 'gradient', value: 'linear-gradient(135deg,#667eea,#764ba2)' },
    'pink': { type: 'gradient', value: 'linear-gradient(135deg,#f093fb,#f5576c)' },
    'blue': { type: 'gradient', value: 'linear-gradient(135deg,#4facfe,#00f2fe)' },
    'green': { type: 'gradient', value: 'linear-gradient(135deg,#43e97b,#38f9d7)' },
    'sunset': { type: 'gradient', value: 'linear-gradient(135deg,#fa709a,#fee140)' },
    'lavender': { type: 'gradient', value: 'linear-gradient(135deg,#a18cd1,#fbc2eb)' },
    'peach': { type: 'gradient', value: 'linear-gradient(135deg,#ffecd2,#fcb69f)' },
    'dark': { type: 'color', value: '#1a1a2e' },
};

function applyWallpaper(saved) {
    if (!saved) return;
    if (saved.type === 'pattern') {
        chatArea.style.backgroundImage = '';
        chatArea.style.backgroundColor = saved.value;
    } else if (saved.type === 'gradient') {
        chatArea.style.backgroundImage = saved.value;
        chatArea.style.backgroundColor = '';
    } else if (saved.type === 'color') {
        chatArea.style.backgroundImage = 'none';
        chatArea.style.backgroundColor = saved.value;
    } else if (saved.type === 'custom') {
        chatArea.style.backgroundImage = `url(${saved.value})`;
        chatArea.style.backgroundSize = 'cover';
        chatArea.style.backgroundPosition = 'center';
    }
}

// Load saved wallpaper
try {
    const saved = JSON.parse(localStorage.getItem(WALLPAPER_KEY));
    if (saved) applyWallpaper(saved);
} catch(e) {}

function showWallpaperPicker() {
    document.getElementById('wallpaper-modal').style.display = 'flex';
}

function closeWallpaperModal() {
    document.getElementById('wallpaper-modal').style.display = 'none';
}

function setWallpaper(name) {
    const wp = wallpapers[name];
    if (!wp) return;
    localStorage.setItem(WALLPAPER_KEY, JSON.stringify(wp));
    applyWallpaper(wp);
    closeWallpaperModal();
}

// Custom image wallpaper
document.getElementById('custom-wallpaper-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        const wp = { type: 'custom', value: ev.target.result };
        localStorage.setItem(WALLPAPER_KEY, JSON.stringify(wp));
        applyWallpaper(wp);
        closeWallpaperModal();
    };
    reader.readAsDataURL(file);
});
// ── Message Statistics ──
console.log('Stats clicked, FRIEND_ID:', FRIEND_ID);
    fetch(`/stats/${FRIEND_ID}`)
    .then(res => res.json())
    .then(data => {
        document.getElementById('stats-content').innerHTML = `
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">${data.total}</div>
                    <div class="stat-label">Total Messages</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${data.sent}</div>
                    <div class="stat-label">You Sent</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${data.received}</div>
                    <div class="stat-label">You Received</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${data.sent_images + data.received_images}</div>
                    <div class="stat-label">Images Shared</div>
                </div>
                <div class="stat-card" style="grid-column: span 2;">
                    <div class="stat-number">${data.days_chatting}</div>
                    <div class="stat-label">Days Chatting Together 🎉</div>
                </div>
            </div>
        `;
    });
}

function closeStatsModal() {
    document.getElementById('stats-modal').style.display = 'none';
}