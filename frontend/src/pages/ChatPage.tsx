import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Settings, User, Send, ChevronDown,
  File as FileIcon, Upload, Trash2, CheckCircle2, XCircle,
  Loader2, Database, AlertCircle, Zap, Brain, Sparkles, Copy, Check, BookOpen, X, Maximize2,
  LogOut, Shield, Plus, MessageSquare
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import cdacLogo from '../assets/C-DAC logo.png';
import { api } from '../services/api';
import { useAuth } from '../auth/AuthContext';
import AuthImage from '../components/AuthImage';

type Conversation = {
  id: string;
  title: string;
  model_used?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
};

type Mode = 'fast' | 'thinking';
type Source = { file: string; page?: number; chunk_type?: string };
type ImageSource = {
  file: string;
  page: number;
  img_id: string;
  score: number;
  caption: string;
  is_image: true;
};
type Message = {
  role: "user" | "assistant";
  content: string;
  timestamp?: number;
  mode?: Mode;
  isStreaming?: boolean;
  sources?: Source[];
  image_sources?: ImageSource[];
};

type UploadFile = {
  name: string;
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
};

const MODES: { id: Mode; label: string; desc: string; model: string }[] = [
  { id: 'fast',     label: 'Fast',     desc: 'Answers quickly',          model: 'gemma3n:e2b' },
  { id: 'thinking', label: 'Thinking', desc: 'Solves complex problems',  model: 'qwen3.5:2b'  },
];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={copy}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg hover:bg-blue-50 text-slate-600 hover:text-blue-500"
    >
      {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
    </button>
  );
}

// Image Zoom Modal Component (uses imgId since image requires auth)
function ImageZoomModal({
  isOpen,
  onClose,
  imgId,
  alt,
  caption,
  conversationId
}: {
  isOpen: boolean;
  onClose: () => void;
  imgId: string;
  alt: string;
  caption?: string;
  conversationId?: string;
}) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-md animate-fade-in p-8"
      onClick={onClose}
    >
      <div className="relative max-w-4xl max-h-[75vh] flex flex-col">
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
          title="Close (Esc)"
        >
          <X size={20} />
        </button>
        <div className="relative bg-white rounded-xl shadow-2xl overflow-hidden border-2 border-slate-200">
                          <AuthImage
                            imgId={imgId}
                            alt={alt}
                            conversationId={conversationId || undefined}
                            className="max-w-3xl max-h-[70vh] w-auto h-auto object-contain mx-auto"
                            onClick={(e) => e.stopPropagation()}
                          />
          {caption && (
            <div className="bg-slate-50 px-4 py-3 border-t border-slate-200">
              <p className="text-slate-700 text-sm text-center">{caption}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { user, logout } = useAuth();
  const [isSidebarOpen, setIsSidebarOpen]   = useState(true);
  const [messages, setMessages]             = useState<Message[]>([]);
  const [input, setInput]                   = useState("");
  const [isLoading, setIsLoading]           = useState(false);
  const [isThinking, setIsThinking]         = useState(false);

  const [mode, setMode]                           = useState<Mode>('fast');
  const [modeDropdownOpen, setModeDropdownOpen]   = useState(false);
  const selectedMode                              = MODES.find(m => m.id === mode)!;

  const [useReranker, setUseReranker]             = useState(true);
  const [pipelineState, setPipelineState]         = useState<any>({ indexed_files: [], bm25_ready: false });
  const [filesToUpload, setFilesToUpload]         = useState<File[]>([]);
  const [uploadProgress, setUploadProgress]       = useState<UploadFile[]>([]);
  const [uploading, setUploading]                 = useState(false);
  const [overallProgress, setOverallProgress]     = useState(0);

  // ── Document deletion state ──────────────────────────────────────────────────
  const [deletingDocs, setDeletingDocs]           = useState<Set<string>>(new Set());

  // ── Memory (user facts) ────────────────────────────────────────────────────
  const [memoryFacts, setMemoryFacts]             = useState<Record<string, string>>({});
  const [memoryCount, setMemoryCount]             = useState(0);
  const [memoryUpdated, setMemoryUpdated]         = useState<string | null>(null);

  // ── Session is derived from authenticated user ─────────────────────────────
  const sessionId = user?.id || "";

  // ── Conversation management ──────────────────────────────────────────────────
  const [conversations, setConversations]       = useState<Conversation[]>([]);
  const [conversationId, setConversationId]     = useState<string | null>(null);

  const fetchConversations = async () => {
    if (!sessionId) return;
    try {
      const res = await api.get('/conversations');
      const existingConvs: Conversation[] = res.data.conversations || [];
      // Find an existing empty conversation to reuse, or create a new one
      const emptyConv = existingConvs.find(c => (c.message_count || 0) === 0);
      let activeConv: Conversation;
      if (emptyConv) {
        activeConv = emptyConv;
      } else {
        const newRes = await api.post('/conversations');
        activeConv = newRes.data;
      }
      setConversations(existingConvs);
      setConversationId(activeConv.id);
      // Switch to this conversation
      setMessages([]);
      setFilesToUpload([]);
      setUploadProgress([]);
      await Promise.all([
        fetchPipelineStatus(activeConv.id),
        fetchHistory(activeConv.id),
        fetchMemory(),
      ]);
    } catch (e) { console.error(e); }
  };

  const createNewConversation = async () => {
    if (!sessionId) return;
    try {
      const res = await api.post('/conversations');
      const newConv: Conversation = res.data;
      setConversations(prev => [newConv, ...prev]);
      setConversationId(newConv.id);
      setMessages([]);
      setPipelineState({ indexed_files: [], bm25_ready: false });
      setFilesToUpload([]);
      setUploadProgress([]);
    } catch (e) { console.error(e); }
  };

  const switchConversation = (id: string) => {
    setConversationId(id);
    setMessages([]);
    setFilesToUpload([]);
    setUploadProgress([]);
    Promise.all([
      fetchPipelineStatus(id),
      fetchHistory(id),
      fetchMemory(),
    ]);
  };

  const deleteConversation = async (id: string) => {
    if (!confirm("Delete this conversation and all its documents?") || !sessionId) return;
    try {
      await api.delete(`/conversations/${id}`);
      setConversations(prev => prev.filter(c => c.id !== id));
      if (conversationId === id) {
        const remaining = conversations.filter(c => c.id !== id);
        if (remaining.length > 0) {
          switchConversation(remaining[0].id);
        } else {
          setConversationId(null);
          setMessages([]);
          setPipelineState({ indexed_files: [], bm25_ready: false });
        }
      }
    } catch (e) { console.error(e); }
  };

  // ── Image Zoom Modal ────────────────────────────────────────────────────────
  const [zoomImage, setZoomImage] = useState<{ src: string; alt: string; caption?: string } | null>(null);
  // Note: `src` here holds the img_id (used by AuthImage to fetch via authenticated API).

  const messagesEndRef  = useRef<HTMLDivElement>(null);
  const fileInputRef    = useRef<HTMLInputElement>(null);
  const dropdownRef     = useRef<HTMLDivElement>(null);
  const streamRef       = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── On mount: responsive handling ─────────────────────────────────────────
  useEffect(() => {
    const handleResize = () => setIsSidebarOpen(window.innerWidth >= 1024);
    window.addEventListener('resize', handleResize);
    handleResize();
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // ── On login: ensure a conversation exists ────────────────────────────────
  useEffect(() => {
    if (!sessionId) return;
    fetchConversations();
    fetchMemory();
  }, [sessionId]);

  // Reload status/history when conversation changes
  useEffect(() => {
    if (!sessionId || !conversationId) return;
    fetchPipelineStatus();
    fetchHistory();
  }, [conversationId]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
        setModeDropdownOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Handle Escape key for image zoom modal ────────────────────────────────
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && zoomImage) {
        setZoomImage(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [zoomImage]);

  // ── API calls ─────────────────────────────────────────────────────────────

  const fetchPipelineStatus = async (convId?: string) => {
    if (!sessionId) return;
    try {
      const params: any = {};
      const cid = convId || conversationId;
      if (cid) params.conversation_id = cid;
      const res = await api.get('/status', { params });
      setPipelineState({
        indexed_files: res.data.indexed_files || [],
        bm25_ready:    res.data.bm25_ready    || false,
      });
    } catch (e) { console.error(e); }
  };

  const fetchHistory = async (convId?: string) => {
    if (!sessionId) return;
    try {
      const params: any = {};
      const cid = convId || conversationId;
      if (cid) params.conversation_id = cid;
      const res = await api.get('/chat/history', { params });
      if (res.data.messages)
        setMessages(res.data.messages.map((m: any) => ({ ...m, timestamp: Date.now() })));
      if (res.data.conversation_id && !conversationId) {
        setConversationId(res.data.conversation_id);
      }
    } catch (e) {}
  };

  const fetchMemory = async () => {
    if (!sessionId) return;
    try {
      const res = await api.get('/memory');
      setMemoryFacts(res.data.facts || {});
      setMemoryCount(res.data.fact_count || 0);
      setMemoryUpdated(res.data.updated_at || null);
    } catch (e) { /* memory endpoint optional */ }
  };

  const clearMemoryFacts = async () => {
    if (!sessionId) return;
    try {
      await api.delete('/memory');
      setMemoryFacts({});
      setMemoryCount(0);
      setMemoryUpdated(null);
    } catch (e) { console.error(e); }
  };

  const streamMessage = useCallback((fullText: string, msgIndex: number) => {
    if (streamRef.current) clearInterval(streamRef.current);
    const words = fullText.split(' ');
    let i = 0;
    const chunkSize = 3;
    streamRef.current = setInterval(() => {
      i += chunkSize;
      const revealed = words.slice(0, i).join(' ');
      setMessages(prev => prev.map((m, idx) =>
        idx === msgIndex ? { ...m, content: revealed, isStreaming: i < words.length } : m
      ));
      if (i >= words.length) {
        clearInterval(streamRef.current!);
        setMessages(prev => prev.map((m, idx) =>
          idx === msgIndex ? { ...m, content: fullText, isStreaming: false } : m
        ));
      }
    }, 40);
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const newFiles = Array.from(e.target.files);
    setFilesToUpload(prev => {
      const existing = new Set(prev.map(f => f.name));
      return [...prev, ...newFiles.filter(f => !existing.has(f.name))];
    });
    setUploadProgress([]);
    e.target.value = '';
  };

  const removeQueuedFile = (name: string) => {
    setFilesToUpload(prev => prev.filter(f => f.name !== name));
    setUploadProgress(prev => prev.filter(f => f.name !== name));
  };

  const removeIndexedFile = async (filename: string) => {
    if (!sessionId) return;
    setDeletingDocs((prev) => new Set(prev).add(filename));
    try {
      const params: any = {};
      if (conversationId) params.conversation_id = conversationId;
      await api.delete(`/documents/${encodeURIComponent(filename)}`, { params });
    } catch (e) { console.error(e); }
    setDeletingDocs((prev) => { const next = new Set(prev); next.delete(filename); return next; });
    setPipelineState((prev: any) => ({
      ...prev,
      indexed_files: (prev.indexed_files || []).filter((f: string) => f !== filename),
    }));
    await fetchPipelineStatus();
  };

  const handleUpload = async () => {
    if (filesToUpload.length === 0 || uploading || !sessionId) return;
    setUploading(true);
    setOverallProgress(0);
    setUploadProgress(filesToUpload.map(f => ({ name: f.name, status: 'uploading' })));

    const formData = new FormData();
    filesToUpload.forEach(f => formData.append("files", f));
    if (conversationId) formData.append("conversation_id", conversationId);

    try {
      await api.post('/documents/upload', formData, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e) => {
          if (e.total) setOverallProgress(Math.round((e.loaded * 100) / e.total));
        },
      });
      setUploadProgress(prev => prev.map(f => ({ ...f, status: 'success' })));
      setOverallProgress(100);
      await fetchPipelineStatus();
      setFilesToUpload([]);
    } catch (e: any) {
      const msg = e?.response?.data?.detail || "Upload failed";
      setUploadProgress(prev => prev.map(f => ({ ...f, status: 'error', error: msg })));
    } finally {
      setUploading(false);
    }
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const userMsg = input.trim();
    const wordCount = userMsg ? userMsg.split(/\s+/).length : 0;
    if (!userMsg || isLoading || wordCount > 150 || !sessionId) return;

    setInput("");
    const now = Date.now();

    setMessages(prev => [
      ...prev,
      { role: "user",      content: userMsg, timestamp: now, mode },
      { role: "assistant", content: "",      timestamp: now, mode, isStreaming: false },
    ]);
    setIsLoading(true);
    if (mode === 'thinking') setIsThinking(true);

    try {
      const res = await api.post('/chat', {
        prompt:          userMsg,
        model:           selectedMode.model,
        use_reranker:    useReranker,
        conversation_id: conversationId,
      });

      const serverMessages: Message[] = res.data.messages;
      const lastAssistant = serverMessages[serverMessages.length - 1];
      const fullText      = lastAssistant?.content || "No response.";
      const sources: Source[]           = res.data.sources       || [];
      const image_sources: ImageSource[] = res.data.image_sources || [];

      setIsLoading(false);
      setIsThinking(false);

      setMessages(prev => {
        const updated = [...prev];
        const lastIdx = updated.length - 1;
        updated[lastIdx] = { ...updated[lastIdx], content: '', isStreaming: true, sources, image_sources };
        return updated;
      });

      setTimeout(() => {
        setMessages(prev => { streamMessage(fullText, prev.length - 1); return prev; });
      }, 50);

      // Refresh memory after each response (facts may have been extracted)
      setTimeout(() => fetchMemory(), 1200);

    } catch (e) {
      console.error(e);
      setIsLoading(false);
      setIsThinking(false);
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: "Sorry, I encountered an error. Please try again.",
          isStreaming: false,
        };
        return updated;
      });
    }
  };

  const clearChat = async () => {
    if (!confirm("Clear all conversation history?") || !sessionId) return;
    if (streamRef.current) clearInterval(streamRef.current);
    try {
      const formData = new FormData();
      if (conversationId) formData.append("conversation_id", conversationId);
      await api.post('/chat/clear', formData);
      setMessages([]);
    } catch (e) { console.error(e); }
  };

  // ── UI helpers (unchanged) ─────────────────────────────────────────────────

  const fileStatusIcon = (status: UploadFile['status']) => {
    switch (status) {
      case 'uploading': return <Loader2    size={14} className="text-blue-500 animate-spin" />;
      case 'success':   return <CheckCircle2 size={14} className="text-emerald-500" />;
      case 'error':     return <XCircle    size={14} className="text-red-400" />;
      default:          return <FileIcon   size={14} className="text-slate-600" />;
    }
  };

  const formatTime = (ts?: number) =>
    ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

  const hasFiles = filesToUpload.length > 0;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen w-full overflow-hidden font-sans app-bg">

      {/* Header */}
      <header className="h-[68px] flex-shrink-0 flex items-center justify-between px-6 z-30 header-surface border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 rounded-xl bg-white p-1.5 flex items-center justify-center shadow-lg shadow-blue-100 border border-blue-100/60">
            <img src={cdacLogo} alt="C-DAC Logo" className="w-full h-full object-contain" />
          </div>
          <div className="space-y-0.5">
            <h1 className="text-[16px] font-semibold tracking-tight text-slate-900 leading-tight">Samvaad</h1>
            <p className="text-[10px] uppercase tracking-widest text-blue-500 font-semibold leading-none">Buddhimaan Seva Pranali</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="flex items-center gap-1.5 text-xs text-slate-700 hover:text-red-500 transition-colors bg-slate-200 hover:bg-red-50 px-3 py-1.5 rounded-full border border-slate-300 hover:border-red-200"
            >
              <Trash2 size={12} /> Clear
            </button>
          )}
          <div className="flex items-center gap-2 p-1 pr-3 rounded-full border border-transparent ml-1">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-violet-500 flex items-center justify-center shadow-lg">
              <User size={14} className="text-white" />
            </div>
            <div className="hidden md:flex flex-col leading-tight">
              <span className="text-sm font-medium text-slate-800">{user?.full_name || 'User'}</span>
              <span className="text-[10px] text-slate-500 flex items-center gap-1">
                <Shield size={9} /> {user?.role || 'analyst'}
              </span>
            </div>
          </div>
          <button
            onClick={logout}
            title="Sign out"
            className="flex items-center gap-1.5 text-xs text-slate-700 hover:text-red-500 transition-colors bg-slate-100 hover:bg-red-50 px-3 py-1.5 rounded-full border border-slate-300 hover:border-red-200"
          >
            <LogOut size={12} /> <span className="hidden md:inline">Sign out</span>
          </button>
          <div className="h-5 w-px bg-slate-300 mx-1" />
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="p-2 rounded-lg hover:bg-slate-200 text-slate-600 hover:text-slate-800 transition-colors"
          >
            <Settings
              size={19}
              className={`transition-transform duration-500 ease-in-out ${isSidebarOpen ? 'rotate-90' : 'rotate-0'}`}
            />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Chat area */}
        <div className="flex-1 flex flex-col h-full relative min-w-0 overflow-hidden">
          <main className="flex-1 overflow-y-auto custom-scrollbar scroll-smooth pb-[200px]">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center max-w-4xl mx-auto px-4 min-h-full py-16 animate-fade-in">
                <h2 className="text-3xl font-bold mb-2 text-slate-900">How can I assist you?</h2>
                <p className="text-slate-700 text-sm mb-10 leading-relaxed">
                  Upload your organisation's documents and ask complex questions to retrieve hyper-accurate insights.
                </p>
                <div className="grid grid-cols-2 gap-3 w-full">
                  {[
                    { label: "Summarize Insights",  sub: "From the latest indexed files",  q: "What are the main insights from the recent document?", icon: "✦" },
                    { label: "Extract Tables",       sub: "Structured markdown data",        q: "Can you extract the data table from page 2?",           icon: "⊞" },
                    { label: "Compare Sections",     sub: "Side-by-side analysis",           q: "Compare the methodology and results sections.",          icon: "⇄" },
                    { label: "Key Findings",         sub: "Bullet-point summary",            q: "What are the key findings from all documents?",          icon: "◈" },
                  ].map(({ label, sub, q, icon }) => (
                    <div
                      key={label}
                      onClick={() => setInput(q)}
                      className="group suggestion-card p-4 rounded-2xl cursor-pointer text-left relative overflow-hidden transition-all"
                    >
                      <div className="absolute top-3 right-3 text-blue-300/50 text-xl group-hover:text-blue-400/80 transition-colors font-mono">{icon}</div>
                      <p className="text-sm font-semibold text-slate-800 group-hover:text-blue-700 transition-colors">{label}</p>
                      <p className="text-xs text-slate-600 mt-1">{sub}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="max-w-5xl mx-auto w-full flex flex-col gap-2 px-4 py-6">
                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} group`}
                    style={{ animation: 'slideUp 0.3s ease-out forwards', animationDelay: `${Math.min(idx * 0.02, 0.2)}s` }}
                  >
                    {msg.role === 'assistant' && (
                      <div className="flex-shrink-0 mr-3 mt-1">
                        <div className={`w-8 h-8 rounded-xl flex items-center justify-center shadow-lg ${
                          msg.mode === 'thinking'
                            ? 'bg-gradient-to-br from-violet-500 to-purple-600 shadow-violet-200'
                            : 'bg-gradient-to-br from-blue-500 to-blue-600 shadow-blue-200'
                        }`}>
                          {msg.mode === 'thinking' ? <Brain size={14} className="text-white" /> : <Zap size={14} className="text-white" />}
                        </div>
                      </div>
                    )}

                    <div className={`flex flex-col gap-1 max-w-[85%] ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                      {msg.role === 'user' ? (
                        <div className="relative">
                          <div className="px-5 py-3.5 rounded-2xl rounded-tr-sm bg-gradient-to-br from-blue-500 to-blue-600 text-white shadow-lg shadow-blue-200 border border-blue-400/20">
                            <p className="text-[15px] leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                          </div>
                          <p className="text-[10px] text-slate-600 mt-1 text-right">{formatTime(msg.timestamp)}</p>
                        </div>
                      ) : (
                        <div className="relative w-full">
                          {isLoading && idx === messages.length - 1 && (
                            <div className="px-5 py-4 rounded-2xl rounded-tl-sm assistant-bubble">
                              {isThinking ? (
                                <div className="flex items-center gap-3">
                                  <div className="relative">
                                    <Brain size={16} className="text-violet-500 animate-pulse" />
                                    <Sparkles size={10} className="text-violet-400 absolute -top-1 -right-1 animate-bounce" />
                                  </div>
                                  <div className="flex flex-col gap-0.5">
                                    <span className="text-sm text-violet-600 font-medium">Thinking…</span>
                                    <div className="flex gap-0.5">
                                      {[0,1,2,3,4].map(i => (
                                        <div key={i} className="w-1 h-1 rounded-full bg-violet-400"
                                          style={{ animation: `bounce 1.2s ease-in-out ${i * 0.15}s infinite` }} />
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-3">
                                  <div className="relative">
                                    <Zap size={16} className="text-blue-500 animate-pulse" />
                                    <Sparkles size={10} className="text-blue-400 absolute -top-1 -right-1 animate-bounce" />
                                  </div>
                                  <div className="flex flex-col gap-0.5">
                                    <span className="text-sm text-blue-600 font-medium">Answering…</span>
                                    <div className="flex gap-0.5">
                                      {[0,1,2,3,4].map(i => (
                                        <div key={i} className="w-1 h-1 rounded-full bg-blue-400"
                                          style={{ animation: `bounce 1.2s ease-in-out ${i * 0.15}s infinite` }} />
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              )}
                            </div>
                          )}

                          {(!isLoading || idx < messages.length - 1) && msg.content && (
                            <div className="relative group/msg">
                              <div className="px-5 py-4 rounded-2xl rounded-tl-sm assistant-bubble transition-colors shadow-lg">
                                <div className="markdown-body">
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm, remarkMath]}
                                    rehypePlugins={[rehypeKatex]}
                                  >
                                    {msg.content}
                                  </ReactMarkdown>
                                  {msg.isStreaming && (
                                    <span className="inline-block w-0.5 h-4 bg-blue-400 ml-0.5 align-middle animate-pulse" />
                                  )}
                                </div>
                              </div>
                              {!msg.isStreaming && (
                                <div className="flex flex-col gap-2 mt-1.5 ml-1">
                                  {/* Text sources */}
                                  {msg.sources && msg.sources.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                      <span className="text-[10px] text-slate-600 mr-1 flex items-center gap-0.5">
                                        <BookOpen size={10} /> Sources:
                                      </span>
                                      {msg.sources.map((s, si) => (
                                        <span key={si} className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border bg-slate-100 border-slate-300 text-slate-700 hover:text-blue-600 hover:border-blue-200 hover:bg-blue-50 transition-colors cursor-default">
                                          <FileIcon size={9} className={s.chunk_type === 'table' ? 'text-amber-500' : 'text-blue-400'} />
                                          <span className="max-w-[160px] truncate">{s.file}</span>
                                          {s.page !== undefined && s.page !== null && (
                                            <span className="text-slate-600 ml-0.5">pg.{s.page + 1}</span>
                                          )}
                                        </span>
                                      ))}
                                    </div>
                                  )}

                                  {/* Image sources */}
                                  {msg.image_sources && msg.image_sources.length > 0 && (
                                    <div className="mt-3">
                                      <p className="text-[11px] text-slate-600 font-semibold flex items-center gap-1.5 mb-2">
                                        <span>🖼</span> Relevant Figures:
                                      </p>
                                      <div className="flex flex-wrap gap-3 justify-center">
                                        {msg.image_sources.map((img, ii) => {
                                          const imgAlt = `Figure from ${img.file} p.${img.page + 1}`;
                                          return (
                                            <div
                                              key={ii}
                                              className="group/img flex flex-col rounded-xl overflow-hidden border-2 border-slate-300 bg-white shadow-md hover:shadow-lg hover:border-blue-400 hover:scale-105 transition-all cursor-pointer relative"
                                              style={{ width: '180px' }}
                                              onClick={() => setZoomImage({ src: img.img_id, alt: imgAlt, caption: img.caption })}
                                            >
                                              {/* Zoom icon overlay */}
                                              <div className="absolute top-2 right-2 opacity-0 group-hover/img:opacity-100 transition-opacity bg-blue-500 rounded-lg p-1.5 shadow-lg">
                                                <Maximize2 size={14} className="text-white" />
                                              </div>
                                              <div className="bg-slate-50 p-2 flex items-center justify-center" style={{ minHeight: '120px' }}>
                                                <AuthImage
                                                  imgId={img.img_id}
                                                  alt={imgAlt}
                                                  conversationId={conversationId || undefined}
                                                  className="w-full object-contain"
                                                  style={{ maxHeight: '110px' }}
                                                />
                                              </div>
                                              <div className="px-3 py-2 bg-white border-t border-slate-200">
                                                <p className="text-[10px] font-semibold text-blue-600 truncate">{img.file}</p>
                                                <p className="text-[10px] text-slate-500">Page {img.page + 1}</p>
                                                {img.caption && (
                                                  <p className="text-[9px] text-slate-600 mt-1.5 line-clamp-2 leading-relaxed">{img.caption}</p>
                                                )}
                                              </div>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}

                                  <div className="flex items-center gap-1">
                                    <CopyButton text={msg.content} />
                                    <p className="text-[10px] text-slate-600 ml-1">{formatTime(msg.timestamp)}</p>
                                    {msg.mode && (
                                      <span className={`text-[10px] px-2 py-0.5 rounded-full border ml-1 ${
                                        msg.mode === 'thinking'
                                          ? 'text-violet-600 border-violet-200 bg-violet-50'
                                          : 'text-blue-600 border-blue-200 bg-blue-50'
                                      }`}>
                                        {msg.mode === 'thinking' ? '🧠 Thinking' : '⚡ Fast'}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {msg.role === 'user' && (
                      <div className="flex-shrink-0 ml-3 mt-1">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-violet-500 flex items-center justify-center shadow-lg shadow-blue-200">
                          <User size={14} className="text-white" />
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </main>

          {/* Input bar */}
          <div className="absolute bottom-0 left-0 right-0 px-0 pb-3 pt-10 input-fade-bg pointer-events-none z-10">
            <div className="w-full max-w-5xl mx-auto pointer-events-auto">
              <form onSubmit={handleSend} className="relative group px-4">
                <div className="input-container rounded-2xl border border-slate-300 shadow-xl shadow-gray-200/80 bg-white">
                  <div className="flex items-end px-2 pt-2">
                    <input ref={fileInputRef} type="file" multiple accept=".pdf" onChange={handleFileSelect} className="hidden" />
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                      placeholder="Ask a question about your documents…"
                      className="flex-1 max-h-[180px] min-h-[44px] bg-transparent border-none resize-none focus:outline-none focus:ring-0 text-[15px] px-2 py-3 text-slate-900 font-medium placeholder-gray-400 custom-scrollbar leading-relaxed"
                      rows={Math.min(input.split('\n').length || 1, 6)}
                    />
                    <button
                      type="submit"
                      disabled={!input.trim() || isLoading || !sessionId || (input.trim() ? input.trim().split(/\s+/).length : 0) > 150}
                      className={`p-2.5 m-1.5 rounded-xl transition-all flex-shrink-0 ${
                        input.trim() && !isLoading && sessionId && (input.trim() ? input.trim().split(/\s+/).length : 0) <= 150
                          ? 'bg-blue-600 text-white shadow-lg shadow-blue-200 hover:bg-blue-500 cursor-pointer'
                          : 'bg-slate-200 text-slate-500 cursor-not-allowed'
                      }`}
                    >
                      <Send size={17} className={isLoading ? "animate-pulse" : ""} />
                    </button>
                  </div>

                  <div className="flex items-center justify-between px-3 pb-3 gap-2">
                    <div className="relative" ref={dropdownRef}>
                      <button
                        type="button"
                        onClick={() => setModeDropdownOpen(o => !o)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all ${
                          mode === 'fast'
                            ? 'bg-blue-50 border-blue-200 text-blue-600 hover:bg-blue-100'
                            : 'bg-violet-50 border-violet-200 text-violet-600 hover:bg-violet-100'
                        }`}
                      >
                        {mode === 'fast' ? <Zap size={11} /> : <Brain size={11} />}
                        {selectedMode.label}
                        <ChevronDown size={11} className={`transition-transform duration-200 ${modeDropdownOpen ? 'rotate-180' : ''}`} />
                      </button>

                      {modeDropdownOpen && (
                        <div className="absolute bottom-full mb-2 left-0 w-60 rounded-2xl border border-slate-300 shadow-xl z-50 overflow-hidden bg-white">
                          <div className="px-4 pt-3 pb-1.5">
                            <p className="text-[10px] uppercase tracking-widest text-slate-600 font-semibold">Select Mode</p>
                          </div>
                          {MODES.map(m => (
                            <button
                              key={m.id}
                              type="button"
                              onClick={() => { setMode(m.id); setModeDropdownOpen(false); }}
                              className={`w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-100 transition-colors text-left ${mode === m.id ? 'bg-blue-50/60' : ''}`}
                            >
                              <div className="flex items-center gap-3">
                                <div className={`p-2 rounded-xl ${m.id === 'fast' ? 'bg-blue-100' : 'bg-violet-100'}`}>
                                  {m.id === 'fast'
                                    ? <Zap  size={14} className="text-blue-500" />
                                    : <Brain size={14} className="text-violet-500" />}
                                </div>
                                <div>
                                  <p className="text-sm font-semibold text-slate-900">{m.label}</p>
                                </div>
                              </div>
                              {mode === m.id && (
                                <CheckCircle2 size={15} className={m.id === 'fast' ? 'text-blue-500' : 'text-violet-500'} />
                              )}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`text-xs font-semibold ${(input.trim() ? input.trim().split(/\s+/).length : 0) > 150 ? 'text-red-500' : 'text-slate-400'}`}>
                        {input.trim() ? input.trim().split(/\s+/).length : 0} / 150 words
                      </span>
                      <span className="text-slate-400 text-xs hidden sm:block">Enter ↵ to send · Shift+Enter for newline</span>
                    </div>
                  </div>
                </div>
              </form>
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className={`${isSidebarOpen ? 'w-[300px]' : 'w-0'} transition-all duration-300 ease-in-out flex-shrink-0 h-full sidebar-surface border-l border-slate-200 overflow-hidden z-20 relative`}>
          <div className="w-[300px] h-full flex flex-col overflow-y-auto custom-scrollbar pb-12">

            {/* Conversations */}
            <div className="p-5 border-b border-slate-300">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-[11px] uppercase tracking-widest text-slate-600 font-semibold flex items-center gap-1.5">
                  <MessageSquare size={11} /> Chats
                </h2>
                <button
                  onClick={createNewConversation}
                  className="text-blue-500 hover:text-blue-600 transition-colors p-1"
                  title="New Chat"
                >
                  <Plus size={14} />
                </button>
              </div>
              {conversations.length > 0 ? (
                <ul className="space-y-1 max-h-[180px] overflow-y-auto custom-scrollbar">
                  {conversations.map((c) => (
                    <li key={c.id}>
                      <button
                        onClick={() => switchConversation(c.id)}
                        className={`w-full flex items-center gap-2 text-xs px-3 py-2 rounded-lg transition-colors text-left ${
                          conversationId === c.id
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : 'text-slate-700 hover:bg-slate-100 border border-transparent'
                        }`}
                      >
                        <MessageSquare size={12} className="flex-shrink-0" />
                        <span className="truncate flex-1">{c.title}</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
                          className="text-slate-400 hover:text-red-500 transition-colors flex-shrink-0 p-0.5 rounded hover:bg-red-50"
                          title="Delete conversation"
                        >
                          <X size={12} />
                        </button>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500 text-center py-3">No conversations yet</p>
              )}
            </div>

            <div className="p-5 border-b border-slate-300">
              <h2 className="text-[11px] uppercase tracking-widest text-slate-600 font-semibold mb-3 flex items-center gap-1.5">
                <Settings size={11} /> Settings
              </h2>
              <div className="flex items-center justify-between bg-slate-100 p-3.5 rounded-xl border border-slate-300">
                <div>
                  <p className="text-sm font-medium text-slate-800">Reranker</p>
                  <p className="text-xs text-slate-600 mt-0.5">Slower but more accurate</p>
                </div>
                <button
                  onClick={() => setUseReranker(!useReranker)}
                  className={`w-11 h-6 rounded-full p-0.5 transition-colors duration-300 ${useReranker ? 'bg-blue-500' : 'bg-slate-400'}`}
                >
                  <div className={`w-5 h-5 bg-white rounded-full shadow-lg transition-transform duration-300 ${useReranker ? 'translate-x-5' : 'translate-x-0'}`} />
                </button>
              </div>
            </div>

            <div className="p-5 flex-1 flex flex-col gap-4">
              <h2 className="text-[11px] uppercase tracking-widest text-slate-600 font-semibold flex items-center gap-1.5">
                <Database size={11} /> Knowledge Base
              </h2>
              <label className="border-2 border-dashed border-slate-300 rounded-xl p-5 flex flex-col items-center justify-center bg-slate-100/50 hover:bg-blue-50/40 hover:border-blue-300 transition-all group cursor-pointer">
                <input type="file" multiple accept=".pdf" onChange={handleFileSelect} className="hidden" />
                <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center mb-2 group-hover:bg-blue-100 transition-colors">
                  <Upload size={18} className="text-blue-400 group-hover:text-blue-500" />
                </div>
                <p className="text-sm font-medium text-slate-800 text-center">Drop PDFs here</p>
                <p className="text-xs text-slate-600 mt-0.5">or click to browse</p>
              </label>

              {filesToUpload.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs text-slate-600">{filesToUpload.length} file(s) queued</p>
                  <div className="space-y-1 max-h-[120px] overflow-y-auto custom-scrollbar">
                    {filesToUpload.map((f) => {
                      const prog = uploadProgress.find(p => p.name === f.name);
                      return (
                        <div key={f.name} className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-slate-300">
                          <span className="flex-shrink-0">{prog ? fileStatusIcon(prog.status) : <FileIcon size={13} className="text-slate-600" />}</span>
                          <span className="text-xs text-slate-800 truncate flex-1">{f.name}</span>
                          {!uploading && !prog && (
                            <button onClick={() => removeQueuedFile(f.name)} className="text-slate-500 hover:text-red-400 transition-colors flex-shrink-0">
                              <XCircle size={13} />
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {uploading && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs text-slate-700">
                    <span>Uploading &amp; Indexing…</span>
                    <span>{overallProgress}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-500 to-violet-500 rounded-full transition-all duration-300"
                      style={{ width: `${overallProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {!uploading && uploadProgress.length > 0 && (
                <div className={`flex items-start gap-2 p-3 rounded-xl text-xs border ${
                  uploadProgress.every(f => f.status === 'success')
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                    : 'bg-red-50 border-red-200 text-red-600'
                }`}>
                  {uploadProgress.every(f => f.status === 'success')
                    ? <CheckCircle2 size={13} className="flex-shrink-0 mt-0.5" />
                    : <AlertCircle  size={13} className="flex-shrink-0 mt-0.5" />}
                  <span>
                    {uploadProgress.every(f => f.status === 'success')
                      ? `${uploadProgress.length} file(s) indexed successfully.`
                      : uploadProgress.find(f => f.error)?.error || "Upload failed."}
                  </span>
                </div>
              )}

              <button
                onClick={handleUpload}
                disabled={!hasFiles || uploading || !sessionId}
                className={`w-full text-sm font-semibold py-2.5 rounded-xl transition-all flex items-center justify-center gap-2 ${
                  hasFiles && !uploading && sessionId
                    ? 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-200 cursor-pointer'
                    : 'bg-slate-200 text-slate-600 cursor-not-allowed border border-slate-300'
                }`}
              >
                {uploading
                  ? <><Loader2 size={14} className="animate-spin" /> Processing…</>
                  : <><Upload size={14} /> Process &amp; Index</>
                }
              </button>

              {/* Indexed documents */}
              <div className="pt-4 border-t border-slate-300">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[11px] text-slate-600 font-semibold uppercase tracking-wider flex items-center gap-1">
                    <CheckCircle2 size={10} className="text-emerald-500" />
                    Indexed Documents
                  </p>
                  <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-semibold border border-blue-100">
                    {pipelineState?.indexed_files?.length || 0}
                  </span>
                </div>

                {pipelineState?.indexed_files?.length > 0 ? (
                  <ul className="space-y-1 max-h-[200px] overflow-y-auto custom-scrollbar">
                    {pipelineState.indexed_files.map((f: string) => (
                      <li key={f} className="group flex items-center gap-2 text-xs text-slate-800 py-1.5 px-2.5 rounded-lg hover:bg-red-50 hover:border-red-100 border border-transparent transition-colors">
                        <CheckCircle2 size={11} className="text-emerald-500 flex-shrink-0" />
                        <span className="truncate flex-1">{f}</span>
                        {deletingDocs.has(f) ? (
                          <div className="w-4 h-4 border-2 border-red-300 border-t-red-500 rounded-full animate-spin flex-shrink-0" />
                        ) : (
                          <button
                            onClick={() => removeIndexedFile(f)}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-500 hover:text-red-400 flex-shrink-0"
                            title="Remove document"
                          >
                            <X size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="flex flex-col items-center py-5 text-center">
                    <div className="w-10 h-10 rounded-xl bg-slate-200 flex items-center justify-center mb-2">
                      <Database size={16} className="text-slate-500" />
                    </div>
                    <p className="text-xs text-slate-600">No documents indexed yet.</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">Upload PDFs above to get started.</p>
                  </div>
                )}
              </div>

              {/* ── Memory panel ────────────────────────────── */}
              <div className="pt-4 border-t border-slate-300">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="text-[11px] text-slate-600 font-semibold uppercase tracking-wider flex items-center gap-1">
                      <Brain size={10} className="text-violet-500" />
                      User Memory
                    </p>
                    {memoryUpdated && (
                      <p className="text-[9px] text-slate-400 mt-0.5">
                        Updated {new Date(memoryUpdated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs bg-violet-50 text-violet-600 px-2 py-0.5 rounded-full font-semibold border border-violet-100">
                      {memoryCount}
                    </span>
                    {memoryCount > 0 && (
                      <button
                        onClick={clearMemoryFacts}
                        title="Clear memory"
                        className="text-slate-400 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={11} />
                      </button>
                    )}
                  </div>
                </div>

                {memoryCount > 0 ? (
                  <ul className="space-y-1 max-h-[160px] overflow-y-auto custom-scrollbar">
                    {Object.entries(memoryFacts).map(([key, val]) => (
                      <li key={key} className="flex items-start gap-2 text-[11px] py-1.5 px-2.5 rounded-lg bg-violet-50 border border-violet-100">
                        <span className="font-semibold text-violet-700 capitalize shrink-0">
                          {key.replace(/_/g, ' ')}:
                        </span>
                        <span className="text-slate-700 break-words">{val}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="flex flex-col items-center py-4 text-center">
                    <div className="w-8 h-8 rounded-xl bg-violet-50 flex items-center justify-center mb-1.5">
                      <Brain size={14} className="text-violet-400" />
                    </div>
                    <p className="text-[11px] text-slate-600">No user facts remembered yet.</p>
                    <p className="text-[10px] text-slate-500 mt-0.5">Facts are auto-extracted from your messages.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Sidebar Footer Disclaimer */}
            <div className="absolute bottom-0 left-0 right-0 bg-slate-50 border-t border-slate-200 py-2 px-5">
              <p className="text-center text-slate-400 text-[9px] leading-relaxed">
                AI-generated content<br/>Please validate before use
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Image Zoom Modal */}
      {zoomImage && (
        <ImageZoomModal
          isOpen={!!zoomImage}
          onClose={() => setZoomImage(null)}
          imgId={zoomImage.src}
          alt={zoomImage.alt}
          caption={zoomImage.caption}
          conversationId={conversationId || undefined}
        />
      )}
    </div>
  );
}