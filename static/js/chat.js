const socket = io();

const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const messagesContainer = document.getElementById('messages');

// ── Scroll to bottom on load ──
scrollToBottom();

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

// ── Receive Message ──
socket.on('receive_message', (data) => {
    const isMine = data.sender_id === CURRENT_USER_ID;

    // avoid duplicate if sender
    if (isMine && data.sender_id === CURRENT_USER_ID) {
        // only append if it came from server (not optimistic)
    }

    const msgEl = document.createElement('div');
    msgEl.classList.add('message', isMine ? 'mine' : 'theirs');
    msgEl.innerHTML = `
        ${!isMine ? `<span class="message-sender">${data.sender}</span>` : ''}
        <div class="message-bubble">${escapeHtml(data.message)}</div>
        <span class="message-time">${data.timestamp}</span>
    `;
    messagesContainer.appendChild(msgEl);
    scrollToBottom();
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