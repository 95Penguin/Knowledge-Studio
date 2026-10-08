import React, { useEffect, useMemo, useState } from "react";

const JAVA_API = "http://127.0.0.1:8080";

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.message || `HTTP ${response.status}`);
  return body;
}

async function readSse(response, onEvent) {
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `SSE HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const event = frame.split("\n").find((line) => line.startsWith("event: "))?.slice(7);
      const data = frame.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
      if (event && data) onEvent(event, JSON.parse(data));
    }
    if (done) break;
  }
}

export default function App() {
  const [token, setToken] = useState(sessionStorage.getItem("kb_token") || "");
  const [displayName, setDisplayName] = useState(sessionStorage.getItem("kb_display_name") || "当前用户");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [bases, setBases] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [currentConversation, setCurrentConversation] = useState("");
  const [baseName, setBaseName] = useState("");
  const [description, setDescription] = useState("");
  const [showCreateBase, setShowCreateBase] = useState(false);
  const [editingBase, setEditingBase] = useState(false);
  const [selectedBase, setSelectedBase] = useState("");
  const [documents, setDocuments] = useState([]);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const auth = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  async function refreshBases() {
    if (token) setBases(await api("/api/knowledge-bases", { headers: auth }));
  }

  async function refreshConversations() {
    if (token) setConversations(await api("/api/knowledge/conversations", { headers: auth }));
  }

  async function refreshDocuments(kbId = selectedBase) {
    if (!kbId) return setDocuments([]);
    setDocuments(await api(`/api/knowledge-bases/${kbId}/documents`, { headers: auth }));
  }

  useEffect(() => {
    if (token) Promise.all([refreshBases(), refreshConversations()])
      .catch((cause) => setError(cause.message));
  }, [token]);

  useEffect(() => {
    refreshDocuments().catch((cause) => setError(cause.message));
  }, [selectedBase]);

  async function login(event) {
    event.preventDefault();
    try {
      const result = await api(`${JAVA_API}/api/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      sessionStorage.setItem("kb_token", result.accessToken);
      sessionStorage.setItem("kb_display_name", result.displayName || email);
      setDisplayName(result.displayName || email);
      setToken(result.accessToken); setError("");
    } catch (cause) { setError(cause.message); }
  }

  async function createBase(event) {
    event.preventDefault();
    try {
      const result = await api("/api/knowledge-bases", {
        method: "POST", headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ name: baseName, description }),
      });
      setBaseName(""); setDescription(""); setSelectedBase(result.id);
      setCurrentConversation(""); setTurns([]); setShowCreateBase(false);
      await refreshBases();
    } catch (cause) { setError(cause.message); }
  }

  function startNewConversation(kbId = selectedBase) {
    setSelectedBase(kbId); setCurrentConversation(""); setTurns([]);
    setDraft(""); setPhase(""); setError("");
    setEditingBase(false); setShowCreateBase(false);
  }

  async function openConversation(conversationId) {
    try {
      const conversation = await api(`/api/knowledge/conversations/${conversationId}`, { headers: auth });
      setCurrentConversation(conversation.id);
      setSelectedBase(conversation.knowledge_base_ids?.[0] || "");
      setTurns(conversation.turns || []); setDraft(""); setPhase(""); setError("");
      setEditingBase(false); setShowCreateBase(false);
    } catch (cause) { setError(cause.message); }
  }

  function beginEditBase() {
    if (!currentBase) return;
    setBaseName(currentBase.name); setDescription(currentBase.description || "");
    setEditingBase(true); setShowCreateBase(false);
  }

  async function updateBase(event) {
    event.preventDefault();
    try {
      await api(`/api/knowledge-bases/${selectedBase}`, {
        method: "PATCH", headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ name: baseName, description }),
      });
      setEditingBase(false); setBaseName(""); setDescription("");
      await refreshBases();
    } catch (cause) { setError(cause.message); }
  }

  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file || !selectedBase) return;
    const form = new FormData(); form.append("file", file); setBusy(true); setError("");
    try {
      const result = await api(`/api/knowledge-bases/${selectedBase}/documents`, {
        method: "POST", headers: auth, body: form,
      });
      setPhase(`索引完成：${result.chunk_count} 个片段`);
      await Promise.all([refreshBases(), refreshDocuments()]);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); event.target.value = ""; }
  }

  async function ask(event, suggestedQuestion = "") {
    event?.preventDefault();
    const text = (suggestedQuestion || question).trim();
    if (!text || busy || !token) return;
    const history = turns.flatMap((turn) => [turn.question, turn.answer?.answer || ""])
      .filter(Boolean).slice(-6);
    setQuestion(""); setDraft(""); setPhase("正在规划检索"); setBusy(true); setError("");
    try {
      let conversationId = currentConversation;
      if (!conversationId) {
        const created = await api("/api/knowledge/conversations", {
          method: "POST", headers: { ...auth, "Content-Type": "application/json" },
          body: JSON.stringify({ knowledge_base_ids: selectedBase ? [selectedBase] : [] }),
        });
        conversationId = created.id;
        setCurrentConversation(conversationId);
      }
      const response = await fetch("/api/knowledge/stream", {
        method: "POST", headers: { ...auth, "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question: text, history,
          knowledge_base_ids: selectedBase ? [selectedBase] : [],
          conversation_id: conversationId }),
      });
      let completed = null;
      await readSse(response, (eventName, data) => {
        if (eventName === "status") setPhase(data.message);
        if (eventName === "answer_start") { setDraft(""); setPhase("正在生成回答"); }
        if (eventName === "answer_delta") setDraft((current) => current + data.text);
        if (eventName === "complete") completed = data;
        if (eventName === "error") throw new Error(data.message);
      });
      if (!completed) throw new Error("回答流缺少完成事件");
      setTurns((items) => [...items, { question: text, answer: completed }]);
      setDraft(""); setPhase("");
      await refreshConversations();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  const currentBase = bases.find((base) => base.id === selectedBase);
  const latest = turns.at(-1)?.answer;

  return <main className="layout">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">K</span><div>
        <h1>Knowledge Studio</h1>
      </div></div>
      {!token ? <form onSubmit={login} className="stack login">
        <label>邮箱<input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required /></label>
        <label>密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required /></label>
        <button>登录</button>
      </form> : <>
        <button className="new-chat" onClick={() => startNewConversation()}>＋ 新建对话</button>

        <section className="sidebar-section history-section">
          <div className="section-title"><span>历史对话</span><small>{conversations.length}</small></div>
          <div className="history-list">
            {conversations.map((conversation) => <button key={conversation.id}
              className={`history-item ${currentConversation === conversation.id ? "active" : ""}`}
              onClick={() => openConversation(conversation.id)}>
              <strong>{conversation.title}</strong><small>{conversation.turn_count} 轮对话</small>
            </button>)}
          </div>
        </section>

        <section className="sidebar-section bases-section">
          <div className="section-title"><span>知识库</span><button className="icon-button"
            title="新建知识库" onClick={() => { setShowCreateBase((value) => !value); setEditingBase(false); setBaseName(""); setDescription(""); }}>＋</button></div>
        <button className={`base-card ${selectedBase === "" ? "active" : ""}`} onClick={() => startNewConversation("")}>
          <span className="base-icon">R</span><span><strong>Redis 7.4 示例库</strong><small>内置官方文档语料</small></span>
        </button>
        {bases.map((base) => <button key={base.id} className={`base-card ${selectedBase === base.id ? "active" : ""}`}
          onClick={() => startNewConversation(base.id)}>
          <span className="base-icon">{base.name.slice(0, 1).toUpperCase()}</span><span><strong>{base.name}</strong><small>{base.document_count} 个文档 · {base.description || "暂无描述"}</small></span>
        </button>)}
        {showCreateBase && <form onSubmit={createBase} className="stack base-form">
          <input placeholder="知识库名称" value={baseName} onChange={(event) => setBaseName(event.target.value)} required />
          <textarea placeholder="描述或适用范围" value={description} onChange={(event) => setDescription(event.target.value)} rows="2" />
          <div className="form-actions"><button type="button" className="secondary" onClick={() => setShowCreateBase(false)}>取消</button><button>创建</button></div>
        </form>}
        </section>

        <button className="account-row" onClick={() => {
          sessionStorage.removeItem("kb_token"); sessionStorage.removeItem("kb_display_name");
          setToken(""); setDisplayName("当前用户"); setBases([]); setConversations([]);
          setSelectedBase(""); setCurrentConversation(""); setTurns([]);
        }}><span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span><span><strong>{displayName}</strong><small>退出登录</small></span></button>
      </>}
    </aside>
    <section className="chat">
      <header><div><strong>{currentBase?.name || "Redis 7.4 示例库"}</strong><p>{currentBase?.description || "展示混合检索、重排、引用和多轮问答"}</p></div>
        {selectedBase && <div className="header-actions"><button className="secondary" onClick={beginEditBase}>编辑信息</button><label className="upload-button">上传文档<input type="file" accept=".md,.txt,.pdf" onChange={upload} disabled={busy} /></label></div>}
      </header>
      {editingBase && <form className="edit-panel" onSubmit={updateBase}>
        <input value={baseName} onChange={(event) => setBaseName(event.target.value)} placeholder="知识库名称" required />
        <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="知识库描述" />
        <button type="button" className="secondary" onClick={() => setEditingBase(false)}>取消</button><button>保存</button>
      </form>}
      {selectedBase && documents.length > 0 && <div className="document-strip">
        {documents.map((document) => <span key={document.id}>{document.filename} · {document.chunk_count} chunks</span>)}
      </div>}
      <div className="turns">
        {turns.length === 0 && <div className="empty"><h2>向知识库提问</h2></div>}
        {turns.map((turn, index) => <article className="turn" key={`${turn.question}-${index}`}>
          <div className="user">{turn.question}</div>
          <div className={`answer ${turn.answer.status === "refused" ? "refused" : ""}`}>
            <div className="answer-text">{turn.answer.answer}</div>
            {turn.answer.citations?.length > 0 && <div className="citations">{turn.answer.citations.map((citation) =>
              <div key={citation.evidence_id}><b>{citation.evidence_id}</b> · {citation.title} · {citation.section_path.join(" › ")}</div>)}</div>}
            {turn.answer.trace && <small>Trace {turn.answer.trace.request_id} · {turn.answer.trace.total_ms} ms</small>}
          </div>
        </article>)}
        {draft && <div className="answer answer-text streaming">{draft}</div>}
        {phase && <p className="phase">{phase}</p>}
      </div>
      {latest?.suggested_questions?.length > 0 && <div className="suggestions">{latest.suggested_questions.map((item) =>
        <button key={item} onClick={() => ask(null, item)}>{item}</button>)}</div>}
      {error && <p role="alert" className="error">{error}</p>}
      <form className="composer" onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入问题，支持连续追问…" rows="2" /><button disabled={busy || !token}>发送</button></form>
    </section>
  </main>;
}
