/**
 * Client-side Controller for PropAgent MCP
 * Multi-Persona Interactive Property Management Workflow
 * Author: Prajwal Rao
 */

// Application State
let activePersona = 'tenant';
let activeTab = 'tenant';
let chatSessionId = 'sess-' + Math.random().toString(36).substring(2, 9);
let lastDossier = null;

// ── Persona & Tab Navigation ──────────────────────────────────────

function switchPersona(persona) {
  activePersona = persona;

  // Update Persona Button Styles
  const personas = ['tenant', 'owner', 'admin', 'security', 'mcp-tools'];
  personas.forEach(p => {
    const btn = document.getElementById(`persona-btn-${p}`);
    if (!btn) return;
    if (p === persona) {
      btn.className = 'persona-btn px-3 py-1.5 rounded-xl flex items-center gap-2 transition bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
    } else {
      btn.className = 'persona-btn px-3 py-1.5 rounded-xl flex items-center gap-2 transition text-slate-400 hover:text-slate-200 border border-transparent';
    }
  });

  // Map Persona to corresponding tab
  const personaTabMap = {
    'tenant': 'tenant',
    'owner': 'owner',
    'admin': 'admin-config',
    'security': 'security',
    'mcp-tools': 'mcp-tools'
  };

  const targetTab = personaTabMap[persona] || 'tenant';
  switchTab(targetTab);
}

function switchTab(tabName) {
  activeTab = tabName;

  // Toggle Tab Contents
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('text-emerald-400', 'bg-emerald-500/10', 'border-emerald-500/20');
    btn.classList.add('text-slate-400');
  });

  const content = document.getElementById(`tab-content-${tabName}`);
  const btn = document.getElementById(`tab-btn-${tabName}`);
  if (content) content.classList.remove('hidden');
  if (btn) {
    btn.classList.remove('text-slate-400');
    btn.classList.add('text-emerald-400', 'bg-emerald-500/10', 'border-emerald-500/20');
  }

  // Load Tab-specific data
  if (tabName === 'owner') {
    loadOwnerPending();
    loadRequests();
  } else if (tabName === 'admin-config') {
    loadAdminPending();
    loadBylawsConfig();
  } else if (tabName === 'directory') {
    loadDirectory();
  } else if (tabName === 'mcp-tools') {
    loadMcpTools();
  }

  pollNotifications();
}

function toggleTenantMode(mode) {
  const chatContainer = document.getElementById('tenant-chat-container');
  const formContainer = document.getElementById('tenant-form-container');
  const btnChat = document.getElementById('btn-mode-chat');
  const btnForm = document.getElementById('btn-mode-form');

  if (mode === 'chat') {
    chatContainer.classList.remove('hidden');
    formContainer.classList.add('hidden');
    btnChat.className = 'px-3 py-1.5 rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-semibold flex items-center gap-1.5 transition';
    btnForm.className = 'px-3 py-1.5 rounded-xl bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition';
  } else {
    chatContainer.classList.add('hidden');
    formContainer.classList.remove('hidden');
    btnForm.className = 'px-3 py-1.5 rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-semibold flex items-center gap-1.5 transition';
    btnChat.className = 'px-3 py-1.5 rounded-xl bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition';
  }
}

// ── 1. Tenant Conversational Chat & Intake ─────────────────────────

function appendChatMessage(role, contentHtml) {
  const msgContainer = document.getElementById('chat-messages');
  if (!msgContainer) return;

  const row = document.createElement('div');
  if (role === 'user') {
    row.className = 'flex items-start justify-end gap-2.5';
    row.innerHTML = `
      <div class="chat-bubble-user p-3 rounded-2xl rounded-tr-none max-w-[85%] text-white leading-relaxed shadow-sm">
        ${contentHtml}
      </div>
      <div class="w-6 h-6 rounded-full bg-emerald-600 text-white flex items-center justify-center text-xs flex-shrink-0 mt-0.5 font-bold">
        P
      </div>
    `;
  } else {
    row.className = 'flex items-start gap-2.5';
    row.innerHTML = `
      <div class="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xs flex-shrink-0 mt-0.5">
        <i class="fa-solid fa-robot"></i>
      </div>
      <div class="chat-bubble-bot p-3 rounded-2xl rounded-tl-none max-w-[85%] text-slate-200 leading-relaxed shadow-sm">
        ${contentHtml}
      </div>
    `;
  }

  msgContainer.appendChild(row);
  msgContainer.scrollTop = msgContainer.scrollHeight;
}

async function handleChatSubmit(e) {
  if (e && e.preventDefault) e.preventDefault();

  const inputEl = document.getElementById('chat-input');
  const message = inputEl.value.trim();
  if (!message) return;

  appendChatMessage('user', escapeHtml(message));
  inputEl.value = '';

  const sendBtn = document.getElementById('btn-send-chat');
  sendBtn.disabled = true;

  // Append temporary typing indicator
  const typingRow = document.createElement('div');
  typingRow.id = 'chat-typing-indicator';
  typingRow.className = 'flex items-start gap-2.5';
  typingRow.innerHTML = `
    <div class="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xs flex-shrink-0 mt-0.5">
      <i class="fa-solid fa-spinner fa-spin"></i>
    </div>
    <div class="chat-bubble-bot p-2.5 rounded-2xl rounded-tl-none text-slate-400 text-xs italic">
      Agent consulting society bylaws & lift schedules...
    </div>
  `;
  const msgContainer = document.getElementById('chat-messages');
  msgContainer.appendChild(typingRow);
  msgContainer.scrollTop = msgContainer.scrollHeight;

  try {
    const res = await fetch('/api/chat/tenant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: chatSessionId,
        message: message
      })
    });
    const data = await res.json();

    // Remove typing indicator
    const indicator = document.getElementById('chat-typing-indicator');
    if (indicator) indicator.remove();

    // Format bot reply with simple line break and bullet handling
    const formattedReply = formatMarkdown(data.reply);
    appendChatMessage('bot', formattedReply);

    // If ready to submit, display confirmation box
    const confirmBox = document.getElementById('chat-confirm-box');
    const confirmDetails = document.getElementById('chat-confirm-details');

    if (data.ready_to_submit && data.dossier) {
      lastDossier = data.dossier;
      confirmDetails.innerHTML = `
        <div class="grid grid-cols-2 gap-2 mt-1">
          <div><span class="text-slate-400">Flat:</span> <strong>${data.dossier.flat_id}</strong></div>
          <div><span class="text-slate-400">Type:</span> <strong>${data.dossier.move_type}</strong></div>
          <div><span class="text-slate-400">Date:</span> <strong>${data.dossier.shift_date}</strong></div>
          <div><span class="text-slate-400">Slot:</span> <strong>${data.dossier.slot_window}</strong></div>
          <div><span class="text-slate-400">Vehicle:</span> <strong>${data.dossier.vehicle_type} (${data.dossier.vehicle_no || 'TBD'})</strong></div>
          <div><span class="text-slate-400">Movers:</span> <strong>${data.dossier.mover_details || 'Standard'}</strong></div>
        </div>
      `;
      confirmBox.classList.remove('hidden');
    } else {
      confirmBox.classList.add('hidden');
    }

  } catch (err) {
    const indicator = document.getElementById('chat-typing-indicator');
    if (indicator) indicator.remove();
    appendChatMessage('bot', `<span class="text-rose-400">Network error communicating with Tenant Agent: ${err.message}</span>`);
  } finally {
    sendBtn.disabled = false;
  }
}

function handleQuickChip(text) {
  const inputEl = document.getElementById('chat-input');
  inputEl.value = text;
  handleChatSubmit(null);
}

async function submitFromChat() {
  if (!lastDossier) return;

  const submitBtn = document.getElementById('btn-submit-chat-req');
  const confirmBox = document.getElementById('chat-confirm-box');
  const badge = document.getElementById('orchestration-badge');
  const feed = document.getElementById('workflow-events-container');

  submitBtn.disabled = true;
  submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Holding Freight Lift & Submitting...`;

  try {
    const payload = {
      resident_id: (lastDossier && lastDossier.resident_id) || 'res-tenant-new',
      ...lastDossier,
      mode: 'step' // Human-in-the-loop step mode
    };
    const res = await fetch('/api/shift-requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Failed to submit shift request');
    }

    confirmBox.classList.add('hidden');

    if (data.events && data.events.length > 0) {
      renderWorkflowEvents(data.events);
    }

    badge.textContent = 'Awaiting Owner NOC';
    badge.className = 'px-2.5 py-0.5 rounded-full text-xs font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30';

    appendChatMessage('bot', `
      🎉 <strong>Shift Request #${data.request_id || ''} Created!</strong><br><br>
      • <strong>Freight Lift Lock:</strong> 24-Hour Hold Confirmed.<br>
      • <strong>Next Step:</strong> Pending tenancy NOC sign-off from Flat Owner <strong>Vikram Malhotra</strong>.<br><br>
      👉 <em>Switch to the <strong>Owner: Vikram</strong> persona in the top bar to review and grant NOC!</em>
    `);

    showToast('Shift request submitted! Notification sent to Flat Owner.', 'info');
    pollNotifications();

  } catch (err) {
    showToast(`Failed to submit request: ${err.message}`, 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Submit Request & Lock Service Elevator`;
  }
}

// ── 2. Direct Form Submission ──────────────────────────────────────

async function handleShiftSubmit(e) {
  e.preventDefault();
  const submitBtn = document.getElementById('btn-submit-shift');
  const badge = document.getElementById('orchestration-badge');
  const feed = document.getElementById('workflow-events-container');
  const gateCard = document.getElementById('gate-pass-card');

  submitBtn.disabled = true;
  submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Agents Coordinating...`;
  badge.textContent = 'Orchestrating';
  badge.className = 'px-2.5 py-0.5 rounded-full text-xs font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30';
  feed.innerHTML = '';
  gateCard.classList.add('hidden');

  const payload = {
    flat_id: document.getElementById('input-flat-id').value,
    resident_id: document.getElementById('input-resident-id').value,
    move_type: document.querySelector('input[name="move_type"]:checked').value,
    shift_date: document.getElementById('input-shift-date').value,
    slot_window: document.getElementById('input-slot-window').value,
    vehicle_type: document.getElementById('input-vehicle-type').value,
    vehicle_no: document.getElementById('input-vehicle-no').value,
    mover_details: document.getElementById('input-mover-details').value,
    mode: 'auto'
  };

  try {
    const res = await fetch('/api/shift-requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.events && data.events.length > 0) {
      renderWorkflowEvents(data.events);
    }

    if (data.final_state === 'GATE_PASS_ISSUED' && data.gate_pass) {
      badge.textContent = 'Approved & Issued';
      badge.className = 'px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';

      const gp = data.gate_pass;
      document.getElementById('gp-pass-title').textContent = `${payload.move_type.replace('_', ' ')} DIGITAL GATE PASS`;
      document.getElementById('gp-pass-id').textContent = gp.gate_pass_id || 'GP-ACTIVE';
      document.getElementById('gp-otp').textContent = gp.otp_code;
      document.getElementById('gp-slot').textContent = `${gp.valid_date} (${gp.valid_slot})`;
      document.getElementById('gp-vehicle').textContent = gp.vehicle_no || payload.vehicle_no;
      gateCard.classList.remove('hidden');
    } else {
      badge.textContent = data.final_state || 'Blocked';
      badge.className = 'px-2.5 py-0.5 rounded-full text-xs font-mono bg-rose-500/20 text-rose-300 border border-rose-500/30';
    }

    pollNotifications();

  } catch (err) {
    feed.innerHTML = `<div class="p-3 bg-rose-950/40 border border-rose-500/30 text-rose-300 rounded-xl">Error submitting request: ${err.message}</div>`;
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<i class="fa-solid fa-paper-plane"></i> Launch Multi-Agent Workflow`;
  }
}

function renderWorkflowEvents(events) {
  const feed = document.getElementById('workflow-events-container');
  feed.innerHTML = '';
  events.forEach(ev => {
    const item = document.createElement('div');
    item.className = 'p-3 rounded-xl border transition ';

    if (ev.step === 'INIT') {
      item.className += 'bg-slate-900 border-slate-800 text-slate-300';
      item.innerHTML = `<div class="font-semibold text-slate-200">🚀 ${ev.state}</div><div>${ev.message}</div>`;
    } else if (ev.step === 'TOOL_CALL') {
      item.className += 'bg-indigo-950/40 border-indigo-500/20 text-indigo-200 font-mono text-[11px]';
      item.innerHTML = `<div class="text-indigo-400 font-bold">🛠️ MCP Tool: ${ev.action} [${ev.agent}]</div><pre class="overflow-x-auto text-[10px] mt-1 text-indigo-300/80">${JSON.stringify(ev.payload, null, 2)}</pre>`;
    } else if (ev.step === 'FAILED') {
      item.className += 'bg-rose-950/40 border-rose-500/30 text-rose-300';
      item.innerHTML = `<div class="font-bold text-rose-400">❌ ${ev.state}</div><div>${ev.message}</div>`;
    } else if (ev.step === 'COMPLETED') {
      item.className += 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300';
      item.innerHTML = `<div class="font-bold text-emerald-400">✅ APPROVED: ${ev.state}</div><div>${ev.message}</div>`;
    } else {
      item.className += 'bg-slate-900/80 border-slate-700/60 text-slate-300';
      item.innerHTML = `<div class="font-semibold text-white">⚙️ ${ev.step} (${ev.state})</div><div>${ev.message}</div>`;
    }
    feed.appendChild(item);
  });
  feed.scrollTop = feed.scrollHeight;
}

// ── 3. Owner NOC Desk ──────────────────────────────────────────────

async function loadOwnerPending() {
  const container = document.getElementById('owner-pending-cards-container');
  if (!container) return;

  try {
    const res = await fetch('/api/requests');
    const requests = await res.json();
    const pending = requests.filter(r => r.owner_noc_status === 'PENDING' && r.status !== 'CANCELLED');

    if (pending.length === 0) {
      container.innerHTML = `
        <div class="p-6 text-center text-slate-400 bg-slate-900/40 border border-slate-800 rounded-xl space-y-1">
          <i class="fa-solid fa-circle-check text-emerald-400 text-lg"></i>
          <p class="font-semibold text-white">All Tenancy NOC Requests Cleared</p>
          <p class="text-xs text-slate-500">No move requests currently require owner clearance.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = pending.map(r => `
      <div class="p-5 bg-slate-900/90 border border-cyan-500/30 rounded-2xl space-y-3.5 shadow-lg">
        <div class="flex items-center justify-between border-b border-slate-800 pb-2.5">
          <div class="flex items-center gap-2.5">
            <span class="w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-400 flex items-center justify-center font-bold text-xs">
              ${r.flat_id}
            </span>
            <div>
              <h4 class="font-bold text-white text-sm">Shift Request #${r.id}</h4>
              <p class="text-[11px] text-slate-400">Incoming Resident: <span class="text-slate-200 font-semibold">${r.resident_name || r.resident_id}</span></p>
            </div>
          </div>
          <span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
            Pending Owner NOC
          </span>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs bg-slate-950 p-3 rounded-xl border border-slate-800/80">
          <div>
            <span class="text-slate-500 block text-[11px]">Move Type</span>
            <span class="font-semibold text-cyan-300">${r.move_type}</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Date & Slot</span>
            <span class="font-semibold text-white">${r.shift_date} (${r.slot_window})</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Vehicle</span>
            <span class="font-semibold text-white">${r.vehicle_type} (${r.vehicle_no || 'TBD'})</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Society Ledger</span>
            <span class="font-semibold text-emerald-400">✓ ₹0 Dues Verified</span>
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 pt-1">
          <button onclick="rejectRequest('${r.id}', 'Owner rejected tenancy NOC')" class="px-3.5 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 text-xs font-semibold transition">
            <i class="fa-solid fa-xmark"></i> Reject NOC
          </button>
          <button onclick="signOwnerNoc('${r.id}', '${r.flat_id}', '${r.move_type}', 'APPROVED')" class="px-4 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition shadow-md shadow-cyan-600/20">
            <i class="fa-solid fa-signature"></i> Grant Owner NOC
          </button>
        </div>
      </div>
    `).join('');

  } catch (err) {
    container.innerHTML = `<div class="p-4 text-center text-rose-400">Failed to load pending NOCs: ${err.message}</div>`;
  }
}

async function loadRequests() {
  const tbody = document.getElementById('owner-requests-tbody');
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" class="p-4 text-center text-slate-500">Loading requests...</td></tr>`;

  try {
    const res = await fetch('/api/requests');
    const requests = await res.json();

    if (requests.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="p-4 text-center text-slate-500">No shift requests found.</td></tr>`;
      return;
    }

    tbody.innerHTML = requests.map(r => {
      const isApproved = r.owner_noc_status === 'APPROVED';
      const isRejected = r.owner_noc_status === 'REJECTED';
      const badgeClass = isApproved 
        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' 
        : (isRejected ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30');

      return `
        <tr class="hover:bg-slate-900/50 transition">
          <td class="p-3 text-white font-bold">${r.id}</td>
          <td class="p-3">${r.flat_id} (${r.tower})</td>
          <td class="p-3"><span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">${r.move_type}</span></td>
          <td class="p-3">${r.shift_date} <span class="text-slate-400 text-[10px] block">${r.slot_window}</span></td>
          <td class="p-3"><span class="text-emerald-400 text-[11px]">✓ Cleared</span></td>
          <td class="p-3"><span class="px-2 py-0.5 rounded-full text-[10px] ${badgeClass}">${r.owner_noc_status}</span></td>
          <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] ${r.status === 'GATE_PASS_ISSUED' ? 'text-emerald-400 bg-emerald-500/10' : 'text-slate-300 bg-slate-800'}">${r.status}</span></td>
          <td class="p-3 text-right">
            ${r.owner_noc_status === 'PENDING' ? `
              <button onclick="signOwnerNoc('${r.id}', '${r.flat_id}', '${r.move_type}', 'APPROVED')" class="px-2 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-sans font-medium transition mr-1">Approve</button>
            ` : (r.status === 'OWNER_NOC_APPROVED' ? `
              <span class="text-[11px] text-purple-400 font-sans">Awaiting Admin</span>
            ` : `<span class="text-[11px] text-slate-500 font-sans">Processed</span>`)}
          </td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="p-4 text-center text-rose-400">Failed to load requests: ${err.message}</td></tr>`;
  }
}

async function signOwnerNoc(requestId, flatId, moveType, status) {
  try {
    const res = await fetch('/api/owner-noc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        flat_id: flatId,
        move_type: moveType,
        sign_off_status: status,
        remarks: `Owner portal verification: ${status}`
      })
    });
    const data = await res.json();

    if (data.status === 'APPROVED') {
      showToast(`Owner NOC granted for #${requestId}! Now in Admin Clearance Queue.`, 'success');
    } else {
      showToast(`Owner NOC rejected for #${requestId}.`, 'warning');
    }

    loadOwnerPending();
    loadRequests();
    pollNotifications();

  } catch (err) {
    showToast(`Failed to update NOC: ${err.message}`, 'error');
  }
}

// ── 4. Admin Clearance Desk & Bylaws Config ────────────────────────

async function loadAdminPending() {
  const container = document.getElementById('admin-pending-cards-container');
  if (!container) return;

  try {
    const res = await fetch('/api/requests');
    const requests = await res.json();
    const pending = requests.filter(r => r.status === 'OWNER_NOC_APPROVED');

    if (pending.length === 0) {
      container.innerHTML = `
        <div class="p-6 text-center text-slate-400 bg-slate-900/40 border border-slate-800 rounded-xl space-y-1">
          <i class="fa-solid fa-circle-check text-purple-400 text-lg"></i>
          <p class="font-semibold text-white">Society Clearance Queue Clear</p>
          <p class="text-xs text-slate-500">No requests currently awaiting admin approval.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = pending.map(r => `
      <div class="p-5 bg-slate-900/90 border border-purple-500/30 rounded-2xl space-y-3.5 shadow-lg">
        <div class="flex items-center justify-between border-b border-slate-800 pb-2.5">
          <div class="flex items-center gap-2.5">
            <span class="w-8 h-8 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center font-bold text-xs">
              ${r.flat_id}
            </span>
            <div>
              <h4 class="font-bold text-white text-sm">Society Clearance Dossier #${r.id}</h4>
              <p class="text-[11px] text-slate-400">Incoming Resident: <span class="text-slate-200 font-semibold">${r.resident_name || r.resident_id}</span></p>
            </div>
          </div>
          <span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30 animate-pulse">
            Awaiting Admin Clearance
          </span>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs bg-slate-950 p-3 rounded-xl border border-slate-800/80">
          <div>
            <span class="text-slate-500 block text-[11px]">Owner NOC</span>
            <span class="font-semibold text-emerald-400">✓ Verified Signed</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Scheduled Window</span>
            <span class="font-semibold text-white">${r.shift_date} (${r.slot_window})</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Moving Fee</span>
            <span class="font-semibold text-slate-200">₹2,000 (Shift Charge)</span>
          </div>
          <div>
            <span class="text-slate-500 block text-[11px]">Lift Deposit</span>
            <span class="font-semibold text-amber-300">₹5,000 (Refundable)</span>
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 pt-1">
          <button onclick="rejectRequest('${r.id}', 'Admin rejected society clearance')" class="px-3.5 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 text-xs font-semibold transition">
            <i class="fa-solid fa-xmark"></i> Reject Dossier
          </button>
          <button onclick="adminApproveRequest('${r.id}')" class="px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold transition shadow-md shadow-purple-600/20">
            <i class="fa-solid fa-stamp"></i> Sign Off & Issue Digital Gate Pass
          </button>
        </div>
      </div>
    `).join('');

  } catch (err) {
    container.innerHTML = `<div class="p-4 text-center text-rose-400">Failed to load admin queue: ${err.message}</div>`;
  }
}

async function adminApproveRequest(requestId) {
  try {
    const res = await fetch(`/api/requests/${requestId}/approve`, {
      method: 'POST'
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Gate Pass #${data.gate_pass_id} issued with OTP ${data.otp_code}!`, 'success');
      loadAdminPending();
      loadRequests();
      pollNotifications();
    } else {
      showToast(`Approval error: ${data.error || 'Failed'}`, 'error');
    }
  } catch (err) {
    showToast(`Error approving request: ${err.message}`, 'error');
  }
}

async function rejectRequest(requestId, reason) {
  try {
    const res = await fetch(`/api/requests/${requestId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Rejected by property management' })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Request #${requestId} rejected. Elevator hold released.`, 'warning');
      loadOwnerPending();
      loadAdminPending();
      loadRequests();
      pollNotifications();
    } else {
      showToast(`Rejection error: ${data.error || 'Failed'}`, 'error');
    }
  } catch (err) {
    showToast(`Error rejecting request: ${err.message}`, 'error');
  }
}

async function loadBylawsConfig() {
  try {
    const res = await fetch('/api/bylaws');
    const cfg = await res.json();

    const daysContainer = document.getElementById('allowed-days-container');
    const allDays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    daysContainer.innerHTML = allDays.map(day => `
      <label class="cursor-pointer border border-slate-700/80 rounded-xl p-2.5 flex items-center gap-2 hover:border-purple-500 transition has-[:checked]:border-purple-500 has-[:checked]:bg-purple-500/10 has-[:checked]:text-purple-300 text-xs">
        <input type="checkbox" name="allowed_days" value="${day}" ${cfg.allowed_days.map(d => d.toLowerCase()).includes(day.toLowerCase()) ? 'checked' : ''} class="accent-purple-500">
        ${day}
      </label>
    `).join('');

    document.getElementById('cfg-start-time').value = cfg.start_time;
    document.getElementById('cfg-end-time').value = cfg.end_time;
    document.getElementById('cfg-max-concurrent').value = cfg.max_concurrent_moves;
    document.getElementById('cfg-move-in-fee').value = cfg.move_in_fee;
    document.getElementById('cfg-move-out-fee').value = cfg.move_out_fee;
    document.getElementById('cfg-lift-deposit').value = cfg.lift_deposit;

  } catch (err) {
    console.error('Failed to load bylaws:', err);
  }
}

async function saveBylawsConfig() {
  const saveBtn = document.getElementById('btn-save-bylaws');
  saveBtn.disabled = true;
  saveBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving...`;

  const selectedDays = [];
  document.querySelectorAll('input[name="allowed_days"]:checked').forEach(cb => {
    selectedDays.push(cb.value);
  });

  const payload = {
    allowed_days: selectedDays,
    start_time: document.getElementById('cfg-start-time').value,
    end_time: document.getElementById('cfg-end-time').value,
    slot_duration_hours: 4,
    max_concurrent_moves: parseInt(document.getElementById('cfg-max-concurrent').value),
    advance_notice_hours: 24,
    move_in_fee: parseFloat(document.getElementById('cfg-move-in-fee').value),
    move_out_fee: parseFloat(document.getElementById('cfg-move-out-fee').value),
    lift_deposit: parseFloat(document.getElementById('cfg-lift-deposit').value),
    require_owner_noc: true
  };

  try {
    const res = await fetch('/api/bylaws', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    showToast('Society bylaws successfully updated and persisted!', 'success');
  } catch (err) {
    showToast(`Error saving bylaws: ${err.message}`, 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = `<i class="fa-solid fa-floppy-disk"></i> Save Bylaw Rules`;
  }
}

// ── 5. Resident Directory & Refresher ──────────────────────────────

async function loadDirectory() {
  const tbody = document.getElementById('directory-flats-tbody');
  tbody.innerHTML = `<tr><td colspan="6" class="p-4 text-center text-slate-500">Loading directory...</td></tr>`;

  try {
    const res = await fetch('/api/directory');
    const data = await res.json();

    tbody.innerHTML = data.flats.map(flat => {
      const isOccupiedTenant = flat.status === 'OCCUPIED_TENANT';
      const isVacant = flat.status === 'VACANT';
      const statusBadge = isOccupiedTenant 
        ? `<span class="px-2 py-0.5 rounded text-[10px] bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium">Occupied (Tenant)</span>`
        : (isVacant ? `<span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400">Vacant</span>` : `<span class="px-2 py-0.5 rounded text-[10px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-medium">Occupied (Owner)</span>`);

      const duesBadge = flat.maintenance_dues > 0 
        ? `<span class="text-rose-400 font-bold">₹${flat.maintenance_dues.toFixed(2)} Dues Pending</span>`
        : `<span class="text-emerald-400">✓ Cleared (₹0)</span>`;

      return `
        <tr class="hover:bg-slate-900/50 transition">
          <td class="p-3 text-white font-bold">${flat.id}</td>
          <td class="p-3">${flat.tower}</td>
          <td class="p-3">${statusBadge}</td>
          <td class="p-3 text-slate-300 font-medium">${flat.owner_name || 'N/A'}<br><span class="text-[10px] text-slate-500">${flat.owner_phone || ''}</span></td>
          <td class="p-3 text-slate-300 font-medium">${flat.tenant_name || '<em class="text-slate-600">None</em>'}<br><span class="text-[10px] text-slate-500">${flat.tenant_phone || ''}</span></td>
          <td class="p-3">${duesBadge}</td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="p-4 text-center text-rose-400">Failed to load directory: ${err.message}</td></tr>`;
  }
}

async function triggerDirectoryRefresh() {
  const btn = document.getElementById('btn-refresh-directory');
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-arrows-rotate fa-spin"></i> Refreshing...`;

  try {
    const res = await fetch('/api/directory/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flat_id: 'T1-101', action: 'REFRESH' })
    });
    await res.json();
    await loadDirectory();
    showToast('Resident Directory successfully refreshed and synchronized!', 'success');
  } catch (err) {
    showToast(`Directory sync error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> Refresh Directory ("Refresher")`;
  }
}

// ── 6. Gate Security Terminal & Keypad ─────────────────────────────

function appendOtp(digit) {
  const input = document.getElementById('input-security-otp');
  if (input.value.length < 10) {
    input.value += digit;
  }
}

function clearOtp() {
  const input = document.getElementById('input-security-otp');
  input.value = '';
}

async function handleSecurityVerify(e) {
  if (e && e.preventDefault) e.preventDefault();

  const input = document.getElementById('input-security-otp');
  const code = input.value.trim();
  const output = document.getElementById('security-verification-output');

  if (!code) {
    showToast('Please enter a 6-digit Gate Pass OTP', 'warning');
    return;
  }

  output.innerHTML = `<div class="p-4 text-center text-amber-300"><i class="fa-solid fa-spinner fa-spin mr-2"></i> Querying society gate pass database...</div>`;

  try {
    const res = await fetch('/api/security/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pass_code: code })
    });
    const data = await res.json();

    if (data.success) {
      output.innerHTML = `
        <div class="p-5 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-left space-y-3">
          <div class="flex items-center justify-between border-b border-emerald-500/20 pb-2.5">
            <span class="font-bold text-sm text-emerald-400 flex items-center gap-2">
              <i class="fa-solid fa-circle-check"></i> ENTRY GRANTED
            </span>
            <span class="text-xs font-mono bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded font-bold">
              ${data.gate_pass_id}
            </span>
          </div>

          <div class="grid grid-cols-2 gap-2 text-xs text-slate-300">
            <div><span class="text-slate-500">Resident:</span> <strong>${data.resident_name}</strong></div>
            <div><span class="text-slate-500">Flat:</span> <strong>${data.flat_id}</strong></div>
            <div><span class="text-slate-500">Move Type:</span> <strong>${data.move_type}</strong></div>
            <div><span class="text-slate-500">Gate Check-in:</span> <strong>${data.check_in_at}</strong></div>
          </div>

          <div class="p-2.5 rounded-lg bg-emerald-950/80 border border-emerald-500/30 text-[11px] text-emerald-300 flex items-center justify-between">
            <span><i class="fa-solid fa-database mr-1"></i> Directory Synced: <strong>${data.directory_updated}</strong></span>
            <button onclick="switchTab('directory')" class="underline hover:text-white font-semibold">View Registry →</button>
          </div>
        </div>
      `;
      showToast('Gate Pass Verified! Vehicle granted entry.', 'success');
      clearOtp();
      loadDirectory();
    } else {
      output.innerHTML = `
        <div class="p-5 rounded-xl bg-rose-950/40 border border-rose-500/40 text-left space-y-2">
          <div class="font-bold text-sm text-rose-400 flex items-center gap-2">
            <i class="fa-solid fa-circle-xmark"></i> ENTRY DENIED
          </div>
          <p class="text-xs text-rose-300">${data.error || 'Invalid or expired OTP token.'}</p>
        </div>
      `;
      showToast('Entry Denied: Invalid OTP', 'error');
    }

  } catch (err) {
    output.innerHTML = `<div class="p-4 text-center text-rose-400">Security verification error: ${err.message}</div>`;
  }
}

// ── 7. Notifications & Badge Polling ──────────────────────────────

async function pollNotifications() {
  try {
    const res = await fetch('/api/notifications?owner_id=res-owner-101');
    const data = await res.json();

    const ownerBadge = document.getElementById('badge-owner-pending');
    if (ownerBadge) {
      if (data.owner_pending_noc > 0) {
        ownerBadge.textContent = data.owner_pending_noc;
        ownerBadge.classList.remove('hidden');
      } else {
        ownerBadge.classList.add('hidden');
      }
    }

    const adminBadge = document.getElementById('badge-admin-pending');
    if (adminBadge) {
      if (data.admin_pending_clearance > 0) {
        adminBadge.textContent = data.admin_pending_clearance;
        adminBadge.classList.remove('hidden');
      } else {
        adminBadge.classList.add('hidden');
      }
    }

  } catch (err) {
    console.debug('Notification poll error:', err);
  }
}

// ── 8. MCP Tool Inspector ──────────────────────────────────────────

async function loadMcpTools() {
  const container = document.getElementById('mcp-tools-list');
  if (!container) return;

  try {
    const res = await fetch('/api/mcp/tools');
    const data = await res.json();

    container.innerHTML = data.tools.map(tool => `
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2 font-mono text-xs">
        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
          <span class="font-bold text-indigo-400">${tool.name}</span>
          <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 font-sans">MCP Tool</span>
        </div>
        <p class="text-slate-300 font-sans text-xs">${tool.description}</p>
        <pre class="bg-slate-950 p-2.5 rounded-lg border border-slate-800 text-[10px] text-slate-400 overflow-x-auto">${JSON.stringify(tool.parameters, null, 2)}</pre>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<div class="text-rose-400 text-center py-4">Failed to load MCP tools: ${err.message}</div>`;
  }
}

// ── 9. Utilities (Toasts, Formatting) ──────────────────────────────

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const bgClass = type === 'success' 
    ? 'bg-emerald-950 border-emerald-500/40 text-emerald-200' 
    : (type === 'error' ? 'bg-rose-950 border-rose-500/40 text-rose-200' : (type === 'warning' ? 'bg-amber-950 border-amber-500/40 text-amber-200' : 'bg-slate-900 border-slate-700 text-slate-200'));

  toast.className = `p-3 rounded-xl border shadow-xl text-xs max-w-sm flex items-center gap-2 pointer-events-auto transition duration-300 ${bgClass}`;
  toast.innerHTML = `
    <span>${message}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatMarkdown(text) {
  if (!text) return '';
  let formatted = escapeHtml(text);
  // Bold **text**
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Newlines to <br>
  formatted = formatted.replace(/\n/g, '<br>');
  return formatted;
}

// ── Initial Boot ───────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Set default shift date to next Saturday
  const d = new Date();
  d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7 || 7));
  const dateStr = d.toISOString().split('T')[0];
  const dateInput = document.getElementById('input-shift-date');
  if (dateInput) dateInput.value = dateStr;

  // Initial tab and notification poll
  switchPersona('tenant');
  pollNotifications();
  setInterval(pollNotifications, 5000);
});
