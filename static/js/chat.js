const socket = io();

const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const messagesContainer = document.getElementById('messages');

// ── Scroll to bottom on load ──
scrollToBottom();

// ── Mark existing messages as seen ──
document.querySelectorAll('.message.theirs[data-msg-id]').forEach(el => {
    socket.emit('message_seen', { msg_id: parseInt(el.dataset.msgId) });
});

// ── Send Message ──
function sendMessage() {
    const message = messageInput.value.trim();
    if (message === '') return;
    socket.emit('send_message', {
        message: message,
        receiver_id: FRIEND_ID
    });
    messageInput.value = '';
    messageInput.focus();
}

sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
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
    }

    const msgEl = document.createElement('div');
    msgEl.classList.add('message', isMine ? 'mine' : 'theirs');
    if (data.msg_id) msgEl.dataset.msgId = data.msg_id;
    msgEl.innerHTML = `
        ${!isMine ? `<span class="message-sender">${data.sender}</span>` : ''}
        <div class="message-bubble">${escapeHtml(data.message)}</div>
        <div class="message-meta">
            <span class="message-time">${data.timestamp}</span>
            ${isMine ? `<span class="tick" id="tick-${data.msg_id}">✓</span>` : ''}
        </div>
    `;
    messagesContainer.appendChild(msgEl);
    scrollToBottom();
});

// ── Message Read (ticks turn blue) ──
socket.on('message_read', (data) => {
    const tick = document.getElementById(`tick-${data.msg_id}`);
    if (tick) {
        tick.textContent = '✓✓';
        tick.classList.add('seen');
    }
});

// ── Helpers ──
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}