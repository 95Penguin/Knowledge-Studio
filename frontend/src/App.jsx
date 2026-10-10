import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

const markdownPlugins = [remarkGfm, remarkMath];
const katexPlugins = [[rehypeKatex, { trust: false, throwOnError: false }]];

function MarkdownAnswer({ text }) {
  return <div className="answer-text markdown">
    <ReactMarkdown remarkPlugins={markdownPlugins} rehypePlugins={katexPlugins}>
      {text || ""}
    </ReactMarkdown>
  </div>;
}

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
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [showManageBase, setShowManageBase] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeRequestId = useRef(null);
  const turnsContainer = useRef(null);
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

  useEffect(() => {
    const container = turnsContainer.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [turns.length]);

  async function login(event) {
    event.preventDefault();
    try {
      const result = await api("/api/auth/login", {
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
      setShowManageBase(true);
      setShowUploadForm(false); setUploadFile(null); setSourceUrl("");
      await refreshBases();
    } catch (cause) { setError(cause.message); }
  }

  function startNewConversation(kbId = selectedBase) {
    activeRequestId.current = null;
    setSelectedBase(kbId); setCurrentConversation(""); setTurns([]);
    setDraft(""); setPhase(""); setError("");
    setEditingBase(false); setShowCreateBase(false);
    setShowManageBase(false);
    setShowUploadForm(false); setUploadFile(null); setSourceUrl("");
  }

  async function openConversation(conversationId) {
    try {
      const conversation = await api(`/api/knowledge/conversations/${conversationId}`, { headers: auth });
      activeRequestId.current = null;
      setCurrentConversation(conversation.id);
      setSelectedBase(conversation.knowledge_base_ids?.[0] || "");
      setTurns(conversation.turns || []); setDraft(""); setPhase(""); setError("");
      setEditingBase(false); setShowCreateBase(false);
      setShowManageBase(false);
      setShowUploadForm(false); setUploadFile(null); setSourceUrl("");
    } catch (cause) { setError(cause.message); }
  }

  function beginEditBase() {
    if (!currentBase) return;
    setBaseName(currentBase.name); setDescription(currentBase.description || "");
    setEditingBase(true); setShowCreateBase(false);
  }

  function openManageBase(kbId) {
    if (selectedBase !== kbId) startNewConversation(kbId);
    setShowManageBase(true);
    setShowUploadForm(false);
    setEditingBase(false);
    setError("");
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
    event.preventDefault();
    if (!uploadFile || !selectedBase) return;
    const form = new FormData();
    form.append("file", uploadFile);
    if (sourceUrl.trim()) form.append("source_url", sourceUrl.trim());
    setBusy(true); setError("");
    try {
      const result = await api(`/api/knowledge-bases/${selectedBase}/documents`, {
        method: "POST", headers: auth, body: form,
      });
      setPhase(`索引完成：${result.chunk_count} 个片段`);
      await Promise.all([refreshBases(), refreshDocuments()]);
      setShowUploadForm(false); setUploadFile(null); setSourceUrl("");
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  async function replaceDocument(event, document) {
    const file = event.target.files?.[0];
    if (!file || !selectedBase) return;
    const form = new FormData(); form.append("file", file);
    setBusy(true); setError("");
    try {
      const result = await api(`/api/knowledge-bases/${selectedBase}/documents/${document.id}`, {
        method: "PUT", headers: auth, body: form,
      });
      setPhase(`替换完成：${result.chunk_count} 个片段`);
      await Promise.all([refreshBases(), refreshDocuments()]);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); event.target.value = ""; }
  }

  async function deleteDocument(document) {
    if (!selectedBase || !window.confirm(`确定删除「${document.filename}」及其当前检索索引吗？`)) return;
    setBusy(true); setError("");
    try {
      await api(`/api/knowledge-bases/${selectedBase}/documents/${document.id}`, {
        method: "DELETE", headers: auth,
      });
      setPhase("文档已从知识库移除");
      await Promise.all([refreshBases(), refreshDocuments()]);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  async function ask(event, suggestedQuestion = "") {
    event?.preventDefault();
    const text = (suggestedQuestion || question).trim();
    if (!text || busy || !token) return;
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    activeRequestId.current = requestId;
    setTurns((items) => [...items, { clientId: requestId, question: text, answer: null }]);
    setQuestion(""); setDraft(""); setPhase("正在规划检索"); setBusy(true); setError("");
    try {
      let conversationId = currentConversation;
      if (!conversationId) {
        const created = await api("/api/knowledge/conversations", {
          method: "POST", headers: { ...auth, "Content-Type": "application/json" },
          body: JSON.stringify({ knowledge_base_ids: selectedBase ? [selectedBase] : [] }),
        });
        conversationId = created.id;
        if (activeRequestId.current === requestId) setCurrentConversation(conversationId);
      }
      const response = await fetch("/api/knowledge/stream", {
        method: "POST", headers: { ...auth, "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question: text,
          knowledge_base_ids: selectedBase ? [selectedBase] : [],
          conversation_id: conversationId }),
      });
      let completed = null;
      await readSse(response, (eventName, data) => {
        if (activeRequestId.current !== requestId) return;
        if (eventName === "status") setPhase(data.message);
        if (eventName === "answer_start") { setDraft(""); setPhase("正在生成回答"); }
        if (eventName === "answer_delta") setDraft((current) => current + data.text);
        if (eventName === "complete") completed = data;
        if (eventName === "error") throw new Error(data.message);
      });
      if (!completed) throw new Error("回答流缺少完成事件");
      if (activeRequestId.current === requestId) {
        setTurns((items) => items.map((turn) => turn.clientId === requestId
          ? { ...turn, answer: completed } : turn));
        setDraft(""); setPhase("");
      }
      await refreshConversations();
    } catch (cause) {
      if (activeRequestId.current === requestId) {
        setTurns((items) => items.map((turn) => turn.clientId === requestId
          ? { ...turn, answer: { status: "failed", answer: "回答失败，请重试。", citations: [] } }
          : turn));
        setDraft(""); setPhase(""); setError(cause.message);
      }
    } finally {
      if (activeRequestId.current === requestId) activeRequestId.current = null;
      setBusy(false);
    }
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
        {bases.map((base) => <div className={`base-entry ${selectedBase === base.id ? "active" : ""}`} key={base.id}>
          <button className="base-card" onClick={() => startNewConversation(base.id)}>
            <span className="base-icon">{base.name.slice(0, 1).toUpperCase()}</span><span><strong>{base.name}</strong><small>{base.document_count} 个文档 · {base.description || "暂无描述"}</small></span>
          </button>
          <button className="base-manage" onClick={() => openManageBase(base.id)} aria-label={`管理${base.name}`} title="管理知识库">管理</button>
        </div>)}
        {showCreateBase && <form onSubmit={createBase} className="stack base-form">
          <input placeholder="知识库名称" value={baseName} onChange={(event) => setBaseName(event.target.value)} required />
          <textarea placeholder="描述或适用范围" value={description} onChange={(event) => setDescription(event.target.value)} rows="2" />
          <div className="form-actions"><button type="button" className="secondary" onClick={() => setShowCreateBase(false)}>取消</button><button>创建</button></div>
        </form>}
        </section>

        <button className="account-row" onClick={() => {
          activeRequestId.current = null;
          sessionStorage.removeItem("kb_token"); sessionStorage.removeItem("kb_display_name");
          setToken(""); setDisplayName("当前用户"); setBases([]); setConversations([]);
          setSelectedBase(""); setCurrentConversation(""); setTurns([]); setShowManageBase(false);
        }}><span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span><span><strong>{displayName}</strong><small>退出登录</small></span></button>
      </>}
    </aside>
    <section className="chat">
      <header><div><strong>{currentBase?.name || "Redis 7.4 示例库"}</strong><p>{currentBase?.description || "展示混合检索、重排、引用和多轮问答"}</p></div></header>
      {showManageBase && currentBase && <div className="manage-backdrop" onClick={() => setShowManageBase(false)}>
        <section className="manage-panel" role="dialog" aria-modal="true" aria-label={`${currentBase.name}知识库管理`} onClick={(event) => event.stopPropagation()}>
          <div className="manage-heading"><div><h2>{currentBase.name}</h2><p>知识库管理 · {documents.length} 个文档</p></div>
            <button className="manage-close secondary" onClick={() => setShowManageBase(false)} aria-label="关闭管理面板">×</button></div>
          <div className="manage-actions"><button className="secondary" onClick={beginEditBase}>编辑信息</button>
            <button onClick={() => { setShowUploadForm((value) => !value); setEditingBase(false); }} disabled={busy}>上传文档</button></div>
          {editingBase && <form className="manage-form" onSubmit={updateBase}>
            <label>名称<input value={baseName} onChange={(event) => setBaseName(event.target.value)} required /></label>
            <label>描述<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <div className="manage-actions"><button type="button" className="secondary" onClick={() => setEditingBase(false)}>取消</button><button>保存</button></div>
          </form>}
          {showUploadForm && <form className="manage-form" onSubmit={upload}>
            <label>文件<input type="file" accept=".md,.txt,.html,.htm,.pdf" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} required /></label>
            <label>来源网址（可选）<input type="url" placeholder="仅记录来源，不会自动抓取" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></label>
            <div className="manage-actions"><button type="button" className="secondary" onClick={() => setShowUploadForm(false)}>取消</button>
              <button disabled={busy || !uploadFile}>{busy ? "处理中…" : "导入并建立索引"}</button></div>
          </form>}
          <h3>已上传文档</h3>
          {documents.length === 0 && <p className="manage-empty">暂无文档，上传后即可用于问答。</p>}
          <div className="manage-documents">{documents.map((document) => <div className="managed-document" key={document.id}>
            <div><strong title={document.filename}>{document.filename}</strong><small>{document.chunk_count} 个片段</small></div>
            <div className="manage-actions"><label className="document-action">替换<input type="file" accept=".md,.txt,.html,.htm,.pdf" onChange={(event) => replaceDocument(event, document)} disabled={busy} /></label>
              <button className="document-action" onClick={() => deleteDocument(document)} disabled={busy}>删除</button></div>
          </div>)}</div>
          {error && <p role="alert" className="error">{error}</p>}
        </section>
      </div>}
      <div className="turns" ref={turnsContainer}>
        {turns.length === 0 && <div className="empty"><h2>向知识库提问</h2></div>}
        {turns.map((turn, index) => <article className="turn" key={turn.clientId || `${turn.question}-${index}`}>
          <div className="user">{turn.question}</div>
          {turn.answer ? <div className={`answer ${turn.answer.status === "refused" || turn.answer.status === "failed" ? "refused" : ""}`}>
            <MarkdownAnswer text={turn.answer.answer} />
            {turn.answer.citations?.length > 0 && <div className="citations">{turn.answer.citations.map((citation) =>
              <div key={citation.evidence_id}><b>{citation.evidence_id}</b> · {citation.title} · {citation.section_path.join(" › ")}</div>)}</div>}
            {turn.answer.trace && <small>Trace {turn.answer.trace.request_id} · {turn.answer.trace.total_ms} ms</small>}
          </div> : <div className="answer pending-answer" role="status" aria-label={phase || "正在等待回答"}>
            {draft ? <MarkdownAnswer text={draft} /> : <span aria-hidden="true">…</span>}
          </div>}
        </article>)}
      </div>
      {latest?.suggested_questions?.length > 0 && <div className="suggestions">{latest.suggested_questions.map((item) =>
        <button key={item} onClick={() => ask(null, item)}>{item}</button>)}</div>}
      {error && !showManageBase && <p role="alert" className="error">{error}</p>}
      <form className="composer" onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入问题，支持连续追问…" rows="2" /><button disabled={busy || !token}>发送</button></form>
    </section>
  </main>;
}
