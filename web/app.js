const BACKEND_URL = "http://127.0.0.1:8080";
const form = document.querySelector("#question-form");
const input = document.querySelector("#question-input");
const sendButton = document.querySelector("#send-button");
const welcome = document.querySelector("#welcome");
const messages = document.querySelector("#messages");
const newChat = document.querySelector("#new-chat");
const composer = document.querySelector("#composer-wrap");
const accountButton = document.querySelector("#account-button");
const loginDialog = document.querySelector("#login-dialog");
let backendToken = sessionStorage.getItem("supportpilot_token");
let displayName = sessionStorage.getItem("supportpilot_name");
let conversationId = null;
let devices = [];
let selectedTicketId = null;
const currentConversationKey = "supportpilot_conversation_id";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

function appendInlineMarkdown(parent, text) {
  const tokenPattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  let cursor = 0;
  for (const match of text.matchAll(tokenPattern)) {
    parent.append(document.createTextNode(text.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("**")) {
      parent.append(el("strong", "", token.slice(2, -2)));
    } else if (token.startsWith("`")) {
      parent.append(el("code", "", token.slice(1, -1)));
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      const link = el("a", "answer-link", linkMatch[1]);
      link.href = linkMatch[2];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      parent.append(link);
    }
    cursor = match.index + token.length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}

function renderMarkdown(markdown) {
  const container = el("div", "answer markdown-body");
  const normalized = String(markdown || "").replace(/\\n/g, "\n").replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  let list = null;

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      list = null;
      return;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const item = line.match(/^(?:[-*]|\d+\.)\s+(.+)$/);
    if (heading) {
      list = null;
      const node = el(`h${Math.min(heading[1].length + 2, 5)}`);
      appendInlineMarkdown(node, heading[2]);
      container.append(node);
    } else if (item) {
      const ordered = /^\d+\./.test(line);
      if (!list || list.tagName !== (ordered ? "OL" : "UL")) {
        list = document.createElement(ordered ? "ol" : "ul");
        container.append(list);
      }
      const node = document.createElement("li");
      appendInlineMarkdown(node, item[1]);
      list.append(node);
    } else {
      list = null;
      const paragraph = document.createElement("p");
      appendInlineMarkdown(paragraph, line);
      container.append(paragraph);
    }
  });
  return container;
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}

function updateAccount() {
  accountButton.textContent = backendToken ? displayName || "已登录" : "登录";
  accountButton.classList.toggle("authenticated", Boolean(backendToken));
}

function addUserMessage(text) {
  const wrapper = el("article", "message");
  wrapper.append(el("p", "message-label", "YOU"));
  wrapper.append(el("div", "user-message", text));
  messages.append(wrapper);
}

function addLoading(label = "正在执行受控流程") {
  document.querySelector("#loading-message")?.remove();
  const wrapper = el("article", "message assistant-message");
  wrapper.id = "loading-message";
  wrapper.append(el("p", "message-label", `SUPPORTPILOT · ${label}`));
  const dots = el("div", "loading");
  dots.append(el("i"), el("i"), el("i"));
  wrapper.append(dots);
  messages.append(wrapper);
}

function appendCitations(wrapper, citations) {
  if (!citations?.length) return;
  const list = el("div", "citations");
  citations.forEach((citation) => {
    const link = el("a", "citation");
    link.href = citation.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.append(el("span", "citation-id", citation.evidence_id));
    const copy = el("span");
    copy.append(el("strong", "", citation.title));
    const sourceLabel = citation.source_type === "engineering_practice" ? "工程实践" : "Redis 官方";
    copy.append(el("small", "", `${sourceLabel} · ${citation.section_path.join(" › ") || citation.source_path}`));
    link.append(copy, el("span", "citation-arrow", "↗"));
    list.append(link);
  });
  wrapper.append(list);
}

function appendToolEvents(wrapper, events) {
  if (!events?.length) return;
  const list = el("div", "tool-events");
  events.forEach((event) => {
    list.append(el("div", `tool-event ${event.status}`, `${event.tool} · ${event.status} · ${event.summary}`));
  });
  wrapper.append(list);
}

function appendTrace(wrapper, trace) {
  if (!trace) return;
  const stages = trace.stages_ms || {};
  const retrieval = ["bm25", "query_embedding", "dense_search", "rrf_fusion", "reranker"]
    .reduce((total, name) => total + (stages[name] || 0), 0);
  const parts = [
    `总耗时 ${(trace.total_ms / 1000).toFixed(2)}s`,
    `检索 ${retrieval.toFixed(0)}ms`,
    `重排 ${(stages.reranker || 0).toFixed(0)}ms`,
    `生成 ${((stages.llm_generation || 0) / 1000).toFixed(2)}s`,
  ];
  if (trace.prompt_tokens !== null && trace.prompt_tokens !== undefined) {
    parts.push(`Token ${trace.prompt_tokens}+${trace.completion_tokens || 0}`);
  }
  const summary = el("div", "trace-summary", parts.join(" · "));
  summary.title = `Request ID: ${trace.request_id}`;
  wrapper.append(summary);
}

function actionButton(label, action, primary = false) {
  const button = el("button", primary ? "primary" : "", label);
  button.type = "button";
  button.addEventListener("click", () => runAgentAction(action, label));
  return button;
}

function appendAgentActions(wrapper, data) {
  const actions = el("div", "agent-actions");
  if (data.required_action === "resolved_or_unresolved") {
    actions.append(actionButton("已解决", "resolved"), actionButton("仍未解决", "unresolved", true));
  } else if (data.required_action === "general_answer_or_stop") {
    actions.append(
      actionButton("查看通识回答", "general_answer", true),
      actionButton("结束对话", "resolved"),
    );
  } else if (data.required_action === "authorize_device") {
    if (!backendToken) {
      const login = el("button", "primary", "登录并选择设备");
      login.type = "button";
      login.addEventListener("click", () => loginDialog.showModal());
      actions.append(login);
    } else {
      const select = document.createElement("select");
      select.id = `device-select-${Date.now()}`;
      devices.forEach((device) => {
        const option = document.createElement("option");
        option.value = device.id;
        option.textContent = `${device.name} · ${device.serialNumber}`;
        select.append(option);
      });
      const authorize = el("button", "primary", "授权查询设备");
      authorize.type = "button";
      authorize.disabled = devices.length === 0;
      authorize.addEventListener("click", () => runAgentAction("authorize_device", "授权查询设备", select.value));
      actions.append(select, authorize);
    }
    actions.append(actionButton("转人工", "transfer"));
  } else if (data.required_action === "confirm_ticket") {
    const draft = data.ticket_draft;
    if (draft) {
      const draftCard = el("div", "resource-card");
      const copy = el("div");
      copy.append(el("h3", "", draft.title), el("p", "", `优先级：${draft.priority}`), el("p", "", draft.description));
      draftCard.append(copy, el("span", "status", "草稿"));
      wrapper.append(draftCard);
    }
    actions.append(actionButton("确认创建工单", "confirm_ticket", true), actionButton("转人工", "transfer"));
  }
  if (actions.childElementCount) wrapper.append(actions);
}

function addAgentResponse(data, includeActions = true) {
  document.querySelector("#loading-message")?.remove();
  conversationId = data.conversation_id;
  sessionStorage.setItem(currentConversationKey, conversationId);
  const wrapper = el("article", "message assistant-message");
  wrapper.append(el("p", "message-label", `SUPPORTPILOT · ${data.state}`));
  wrapper.append(renderMarkdown(data.message));
  if (data.device) {
    const meta = el("div", "meta-row");
    meta.append(el("span", "", `设备 ${data.device.name}`), el("span", "", `状态 ${data.device.status}`));
    wrapper.append(meta);
  }
  appendCitations(wrapper, data.citations);
  appendToolEvents(wrapper, data.tool_events);
  appendTrace(wrapper, data.trace);
  if (includeActions) appendAgentActions(wrapper, data);
  messages.append(wrapper);
}

async function agentHistoryFetch(path) {
  if (!backendToken) throw new Error("请先登录");
  const response = await fetch(path, { headers: { Authorization: `Bearer ${backendToken}` } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `历史对话服务返回 ${response.status}`);
  return body;
}

async function loadConversationList() {
  const list = document.querySelector("#history-list");
  if (!backendToken) {
    list.replaceChildren(el("p", "history-empty", "登录后显示最近对话"));
    return;
  }
  const conversations = await agentHistoryFetch("/api/agent/conversations");
  list.replaceChildren();
  if (!conversations.length) {
    list.append(el("p", "history-empty", "还没有历史对话"));
    return;
  }
  conversations.forEach((conversation) => {
    const active = conversation.id === conversationId ? " active" : "";
    const button = el("button", `history-item${active}`);
    button.type = "button";
    button.append(
      el("strong", "", conversation.title),
      el("small", "", new Date(`${conversation.updated_at}Z`).toLocaleString()),
    );
    button.addEventListener("click", () => restoreConversation(conversation.id));
    list.append(button);
  });
}

async function restoreConversation(id) {
  switchView("chat");
  const history = await agentHistoryFetch(`/api/agent/conversations/${id}`);
  conversationId = history.id;
  sessionStorage.setItem(currentConversationKey, conversationId);
  messages.replaceChildren();
  welcome.classList.add("hidden");
  history.turns.forEach((turn, index) => {
    addUserMessage(turn.user_message);
    addAgentResponse(turn.response, index === history.turns.length - 1);
  });
  await loadConversationList();
  window.scrollTo({ top: document.body.scrollHeight });
}

function addError(message) {
  document.querySelector("#loading-message")?.remove();
  const wrapper = el("article", "message assistant-message");
  wrapper.append(el("p", "message-label", "SUPPORTPILOT · 请求失败"));
  wrapper.append(el("p", "answer refusal", message));
  messages.append(wrapper);
}

async function agentTurn(payload) {
  const response = await fetch("/api/agent/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      conversation_id: conversationId,
      backend_token: backendToken,
    }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `AI 服务返回 ${response.status}`);
  return body;
}

async function agentStream(payload, onEvent) {
  const response = await fetch("/api/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      ...payload,
      conversation_id: conversationId,
      backend_token: backendToken,
    }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `流式回答服务返回 ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    frames.forEach((frame) => {
      const event = frame.split("\n").find((line) => line.startsWith("event: "))?.slice(7);
      const data = frame.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
      if (event && data) onEvent(event, JSON.parse(data));
    });
    if (done) break;
  }
}

function beginStreamingAnswer() {
  document.querySelector("#loading-message")?.remove();
  const wrapper = el("article", "message assistant-message streaming-message");
  wrapper.append(el("p", "message-label", "SUPPORTPILOT · 正在生成已校验回答"));
  const content = el("div", "answer streaming-answer", "");
  wrapper.append(content);
  messages.append(wrapper);
  return { wrapper, content };
}

async function ask(question) {
  const cleanQuestion = question.trim();
  if (!cleanQuestion || sendButton.disabled) return;
  if (!backendToken) {
    loginDialog.showModal();
    return;
  }
  if (conversationId) resetChat();
  welcome.classList.add("hidden");
  addUserMessage(cleanQuestion);
  addLoading("正在检索官方文档");
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  try {
    let streaming = null;
    let completed = null;
    await agentStream({ action: "ask", message: cleanQuestion }, (event, data) => {
      if (event === "status") {
        const label = document.querySelector("#loading-message .message-label");
        if (label) label.textContent = `SUPPORTPILOT · ${data.message}`;
      } else if (event === "answer_start") {
        streaming = beginStreamingAnswer();
      } else if (event === "answer_delta" && streaming) {
        streaming.content.textContent += data.text;
      } else if (event === "complete") {
        completed = data;
      } else if (event === "error") {
        throw new Error(data.message);
      }
    });
    streaming?.wrapper.remove();
    if (!completed) throw new Error("流式回答未返回完成事件");
    addAgentResponse(completed);
    await loadConversationList();
  } catch (error) {
    addError(`暂时无法完成回答：${error.message}`);
  } finally {
    sendButton.disabled = false;
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }
}

async function runAgentAction(action, label, deviceId = null) {
  document.querySelectorAll(".agent-actions button, .agent-actions select").forEach((control) => {
    control.disabled = true;
  });
  addUserMessage(label);
  addLoading(action === "authorize_device" ? "正在通过 Java 校验设备权限" : "正在执行状态流转");
  try {
    const data = await agentTurn({ action, device_id: deviceId });
    addAgentResponse(data);
    await loadConversationList();
    if (data.ticket) await loadTickets();
  } catch (error) {
    addError(error.message);
  }
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

async function backendFetch(path, options = {}) {
  if (!backendToken) throw new Error("请先登录");
  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}`, ...(options.headers || {}) },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || `Java 服务返回 ${response.status}`);
  return body;
}

async function loadDevices() {
  if (!backendToken) return;
  devices = await backendFetch("/api/devices");
  const list = document.querySelector("#device-list");
  list.replaceChildren();
  if (!devices.length) return list.append(el("div", "empty-state", "当前账号没有可访问设备。"));
  devices.forEach((device) => {
    const card = el("article", "resource-card");
    const copy = el("div");
    copy.append(el("h3", "", device.name), el("p", "", `序列号 ${device.serialNumber}`),
      el("p", "", `内网地址 ${device.internalIp}`), el("p", "", `最后在线 ${new Date(device.lastSeenAt).toLocaleString()}`));
    card.append(copy, el("span", "status", device.status));
    list.append(card);
  });
}

async function loadTickets() {
  if (!backendToken) return;
  const tickets = await backendFetch("/api/tickets");
  const list = document.querySelector("#ticket-list");
  list.replaceChildren();
  if (!tickets.length) return list.append(el("div", "empty-state", "还没有工单。完成受控排查后可以确认创建。"));
  tickets.forEach((ticket) => {
    const card = el("article", "resource-card");
    const copy = el("div");
    copy.append(el("h3", "", ticket.title), el("p", "", ticket.description),
      el("p", "", `${ticket.priority} · ${new Date(ticket.createdAt).toLocaleString()}`));
    const side = el("div", "resource-side");
    side.append(el("span", "status", ticket.status));
    const detail = el("button", "detail-button", "查看详情");
    detail.type = "button";
    detail.addEventListener("click", () => openTicket(ticket.id));
    side.append(detail);
    card.append(copy, side);
    list.append(card);
  });
}

const statusLabel = (status) => ({ OPEN: "待处理", IN_PROGRESS: "处理中", RESOLVED: "已解决", CLOSED: "已关闭" }[status] || status);

async function openTicket(ticketId) {
  selectedTicketId = ticketId;
  const detail = document.querySelector("#ticket-detail");
  detail.classList.remove("hidden");
  document.querySelector("#ticket-index").classList.add("hidden");
  detail.replaceChildren(el("div", "empty-state", "正在加载工单详情…"));
  try {
    renderTicketDetail(await backendFetch(`/api/tickets/${ticketId}`));
  } catch (error) {
    detail.replaceChildren(el("div", "empty-state", error.message));
  }
}

function renderTicketDetail(data) {
  const detail = document.querySelector("#ticket-detail");
  const ticket = data.ticket;
  detail.replaceChildren();
  const back = el("button", "back-button", "← 返回工单列表");
  back.type = "button";
  back.addEventListener("click", () => {
    selectedTicketId = null;
    detail.classList.add("hidden");
    document.querySelector("#ticket-index").classList.remove("hidden");
  });
  const heading = el("div", "ticket-detail-heading");
  const copy = el("div");
  copy.append(el("p", "eyebrow", `TICKET · ${ticket.id.slice(0, 8)}`), el("h2", "", ticket.title),
    el("p", "", `${data.deviceName} · ${ticket.priority} · ${new Date(ticket.createdAt).toLocaleString()}`));
  heading.append(copy, el("span", "status large", statusLabel(ticket.status)));
  const description = el("section", "detail-section");
  description.append(el("h3", "", "问题描述"), el("p", "", ticket.description));
  const timeline = el("section", "detail-section");
  timeline.append(el("h3", "", "状态历史"));
  const historyList = el("div", "timeline");
  data.history.forEach((item) => {
    const row = el("div", "timeline-item");
    row.append(el("span", "timeline-dot"), el("strong", "", statusLabel(item.toStatus)),
      el("small", "", new Date(item.createdAt).toLocaleString()), el("p", "", item.note || "无备注"));
    historyList.append(row);
  });
  timeline.append(historyList);
  detail.append(back, heading, description, timeline);
  if (data.allowedTransitions.length) {
    const workflow = el("section", "detail-section transition-panel");
    workflow.append(el("h3", "", "更新处理状态"));
    const note = document.createElement("textarea");
    note.className = "transition-note";
    note.maxLength = 500;
    note.rows = 2;
    note.placeholder = "填写本次状态变更说明…";
    const actions = el("div", "transition-actions");
    data.allowedTransitions.forEach((next) => {
      const button = el("button", "primary-action", `更新为${statusLabel(next)}`);
      button.type = "button";
      button.addEventListener("click", () => transitionTicket(next, note.value, button));
      actions.append(button);
    });
    workflow.append(note, actions);
    detail.append(workflow);
  }
}

async function transitionTicket(status, note, button) {
  if (!selectedTicketId) return;
  button.disabled = true;
  try {
    await backendFetch(`/api/tickets/${selectedTicketId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, note: note.trim() || `用户将工单更新为${statusLabel(status)}` }),
    });
    await loadTickets();
    await openTicket(selectedTicketId);
  } catch (error) {
    button.disabled = false;
    const message = el("p", "form-error", error.message);
    button.parentElement.before(message);
  }
}

function resetChat() {
  conversationId = null;
  sessionStorage.removeItem(currentConversationKey);
  messages.replaceChildren();
  welcome.classList.remove("hidden");
  input.value = "";
  resizeInput();
}

function switchView(view) {
  document.querySelectorAll(".app-view").forEach((item) => item.classList.add("hidden"));
  document.querySelector(`#${view}-view`).classList.remove("hidden");
  composer.classList.toggle("hidden", view !== "chat");
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  if (view !== "chat" && !backendToken) return loginDialog.showModal();
  if (view === "devices") loadDevices().catch((error) => addResourceError("device-list", error));
  if (view === "tickets") loadTickets().catch((error) => addResourceError("ticket-list", error));
  if (view !== "tickets") selectedTicketId = null;
}

function addResourceError(id, error) {
  const list = document.querySelector(`#${id}`);
  list.replaceChildren(el("div", "empty-state", error.message));
}

form.addEventListener("submit", (event) => { event.preventDefault(); ask(input.value); });
input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
});
document.querySelectorAll("[data-question]").forEach((button) => button.addEventListener("click", () => ask(button.dataset.question)));
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
newChat.addEventListener("click", () => { switchView("chat"); resetChat(); input.focus(); });
accountButton.addEventListener("click", () => {
  if (backendToken) {
    backendToken = null; displayName = null; devices = [];
    sessionStorage.removeItem("supportpilot_token"); sessionStorage.removeItem("supportpilot_name");
    resetChat(); updateAccount(); loadConversationList();
  } else loginDialog.showModal();
});
document.querySelector("#login-close").addEventListener("click", () => loginDialog.close());
document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#login-error");
  error.textContent = "";
  try {
    const response = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: document.querySelector("#login-email").value, password: document.querySelector("#login-password").value }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || "登录失败");
    backendToken = body.accessToken; displayName = body.displayName;
    sessionStorage.setItem("supportpilot_token", backendToken); sessionStorage.setItem("supportpilot_name", displayName);
    updateAccount(); loginDialog.close(); await loadDevices(); await loadConversationList();
  } catch (loginError) { error.textContent = loginError.message; }
});

updateAccount();
if (backendToken) {
  conversationId = sessionStorage.getItem(currentConversationKey);
  loadConversationList()
    .then(() => conversationId && restoreConversation(conversationId))
    .catch(() => {
      backendToken = null;
      displayName = null;
      conversationId = null;
      sessionStorage.removeItem("supportpilot_token");
      sessionStorage.removeItem("supportpilot_name");
      sessionStorage.removeItem(currentConversationKey);
      updateAccount();
      loadConversationList();
    });
}
if (backendToken) loadDevices().catch(() => {});
fetch("/health").then((response) => {
  if (!response.ok) throw new Error();
  document.querySelector(".status-dot").classList.add("online");
  document.querySelector("#service-status").textContent = "已连接";
}).catch(() => { document.querySelector("#service-status").textContent = "离线"; });
