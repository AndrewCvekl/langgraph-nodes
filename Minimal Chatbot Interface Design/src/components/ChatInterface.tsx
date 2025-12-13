import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, Menu, User, Music, Mic, Guitar, Disc3, Radio, ChevronDown, Wrench } from 'lucide-react';
import logo from 'figma:asset/74207fe6a9b21f61a67fc904551a29b75945f28f.png';

type AssistantPayload =
  | { type: 'text'; text: string }
  | { type: 'embed'; provider?: string; url?: string; html?: string }
  | {
      type: 'invoice';
      invoice_id?: string | number;
      total?: number;
      lines?: Array<{ name?: string; qty?: number; unit_price?: number }>;
      transaction_id?: string;
    };

type InterruptPayload = {
  type: 'confirm' | 'input' | string;
  title?: string;
  text?: string;
  choices?: string[];
  placeholder?: string;
  context?: string;
};

type ApiResponse = {
  thread_id: string;
  assistant_messages: AssistantPayload[];
  interrupt?: InterruptPayload | null;
};

interface ToolUse {
  id: string;
  name: string;
  input: Record<string, any>;
  output?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  kind: 'text' | 'embed' | 'invoice' | 'tools';
  content?: string;
  payload?: AssistantPayload;
  tools?: ToolUse[];
}

export function ChatInterface() {
  const STORAGE_KEY = 'music_store_support_thread_id';

  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      kind: 'text',
      content: 'Hello! I\'m here to help. What would you like to know?',
    },
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const [expandedDetails, setExpandedDetails] = useState<Record<string, boolean>>({});
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [threadId, setThreadId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });

  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptPayload | null>(null);
  const [interruptInput, setInterruptInput] = useState('');
  const interruptResolveRef = useRef<((value: string) => void) | null>(null);
  const interruptInputRef = useRef<HTMLInputElement>(null);

  const loadingMessages = useMemo(
    () => ['Tuning...', 'Composing...', 'Orchestrating...', 'Harmonizing...', 'Mixing...'],
    [],
  );

  const loadingIcons = useMemo(() => [Guitar, Mic, Disc3, Radio, Music], []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  useEffect(() => {
    if (isTyping) {
      const interval = setInterval(() => {
        setLoadingMessageIndex((prev) => (prev + 1) % loadingMessages.length);
      }, 800);
      return () => clearInterval(interval);
    }
  }, [isTyping, loadingMessages.length]);

  useEffect(() => {
    try {
      if (threadId) {
        localStorage.setItem(STORAGE_KEY, threadId);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // ignore storage errors
    }
  }, [threadId]);

  // Focus the interrupt input when it appears (for smoother HITL UX).
  useEffect(() => {
    if (pendingInterrupt?.type === 'input') {
      // Let the modal render first
      const t = setTimeout(() => interruptInputRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [pendingInterrupt]);

  const defaultResumeValue = (payload: InterruptPayload): string => {
    if (payload.type === 'confirm') return 'No';
    if (payload.type === 'input') return '';
    return '';
  };

  const promptInterrupt = (payload: InterruptPayload): Promise<string> => {
    setInterruptInput(payload.placeholder ?? '');
    setPendingInterrupt(payload);
    return new Promise((resolve) => {
      interruptResolveRef.current = resolve;
    });
  };

  const resolveInterrupt = (value: string) => {
    setPendingInterrupt(null);
    const resolve = interruptResolveRef.current;
    interruptResolveRef.current = null;
    resolve?.(value);
  };

  const renderInterruptModal = () => {
    if (!pendingInterrupt) return null;

    const title = pendingInterrupt.title ?? 'Input Required';
    const bodyText = buildInterruptBubbleText(pendingInterrupt);
    const isConfirm = pendingInterrupt.type === 'confirm';
    const choices = pendingInterrupt.choices?.length ? pendingInterrupt.choices : ['Yes', 'No'];

    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 9999,
          background: 'rgba(0,0,0,0.35)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 16,
        }}
        // prevent clicks from falling through to the chat UI
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            width: 'min(560px, 100%)',
            background: 'white',
            borderRadius: 12,
            border: '1px solid rgba(0,0,0,0.1)',
            boxShadow: '0 24px 64px rgba(0,0,0,0.25)',
            padding: 16,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="space-y-2">
            <div className="text-gray-900" style={{ fontSize: 18, fontWeight: 600 }}>
              {title}
            </div>
            <div className="text-gray-700 whitespace-pre-wrap">{bodyText}</div>
          </div>

          {pendingInterrupt.type === 'input' && (
            <div className="mt-3">
              <input
                ref={interruptInputRef}
                value={interruptInput}
                onChange={(e) => setInterruptInput(e.target.value)}
                placeholder={pendingInterrupt.placeholder ?? ''}
                className="w-full border border-gray-200 rounded-lg px-4 py-3 outline-none"
              />
            </div>
          )}

          <div className="mt-4 flex flex-col sm:flex-row sm:justify-end gap-2">
            <button
              className="border border-gray-300 text-gray-900 rounded-lg px-4 py-3 hover:bg-gray-100 transition-colors"
              onClick={() => resolveInterrupt(defaultResumeValue(pendingInterrupt))}
            >
              Cancel
            </button>

            {isConfirm ? (
              <div className="flex gap-2">
                {choices.map((c) => (
                  <button
                    key={c}
                    className="border border-teal-700 text-teal-700 rounded-lg px-4 py-3 hover:bg-teal-50 transition-colors"
                    onClick={() => resolveInterrupt(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
            ) : (
              <button
                className="bg-teal-700 text-white rounded-lg px-4 py-3 hover:bg-teal-700 transition-colors"
                onClick={() => resolveInterrupt(interruptInput)}
              >
                Submit
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  const toggleDetails = (id: string) => {
    setExpandedDetails((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const toggleTool = (toolId: string) => {
    setExpandedTools((prev) => ({
      ...prev,
      [toolId]: !prev[toolId],
    }));
  };

  const buildInterruptBubbleText = (interrupt: InterruptPayload): string => {
    const parts: string[] = [];
    if (interrupt.context && interrupt.context.trim()) parts.push(interrupt.context.trim());
    if (interrupt.text && interrupt.text.trim()) parts.push(interrupt.text.trim());
    return parts.join('\n\n') || 'Input required.';
  };

  const inferToolUses = (payloads: AssistantPayload[], interrupt?: InterruptPayload | null): ToolUse[] => {
    const tools: ToolUse[] = [];

    for (const p of payloads) {
      if (p?.type === 'embed') {
        const provider = (p.provider ?? 'embed').toString();
        tools.push({
          id: `tool-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          name: `${provider}_embed`,
          input: {
            provider,
            url: (p as any).url,
            video_id: (p as any).video_id,
          },
          output: 'Prepared embedded media for the UI.',
        });
      }

      if (p?.type === 'invoice') {
        tools.push({
          id: `tool-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          name: 'payment_receipt',
          input: {
            invoice_id: (p as any).invoice_id,
            lines: (p as any).lines,
            total: (p as any).total,
          },
          output: (p as any).transaction_id ? `Transaction ${(p as any).transaction_id}` : 'Payment processed.',
        });
      }
    }

    if (interrupt) {
      const title = interrupt.title ?? 'Human approval';
      tools.push({
        id: `tool-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        name: 'human_in_the_loop',
        input: {
          type: interrupt.type,
          title,
          text: interrupt.text,
          choices: interrupt.choices,
          placeholder: interrupt.placeholder,
          context: interrupt.context,
        },
        output: 'Waiting for user input…',
      });
    }

    return tools;
  };

  const appendToolAccordionMessage = (toolUses: ToolUse[]) => {
    if (!toolUses.length) return;
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-tools-${Math.random().toString(16).slice(2)}`,
        role: 'assistant',
        kind: 'tools',
        tools: toolUses,
      },
    ]);
  };

  const appendAssistantPayloads = (payloads: AssistantPayload[]) => {
    const next: Message[] = payloads
      .map((p) => {
        const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        if (p.type === 'text') {
          return {
            id,
            role: 'assistant',
            kind: 'text',
            content: p.text ?? '',
            payload: p,
          };
        }
        if (p.type === 'embed') {
          return {
            id,
            role: 'assistant',
            kind: 'embed',
            payload: p,
          };
        }
        if (p.type === 'invoice') {
          return {
            id,
            role: 'assistant',
            kind: 'invoice',
            payload: p,
          };
        }
        return null;
      })
      .filter((x): x is Message => Boolean(x));

    if (next.length) {
      setMessages((prev) => [...prev, ...next]);
    }
  };

  const postJson = async <T,>(url: string, body: unknown): Promise<T> => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const j = await res.json();
        if (j?.detail) detail = String(j.detail);
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    return (await res.json()) as T;
  };

  const runGraphTurn = async (userText: string) => {
    setIsTyping(true);
    try {
      let resp = await postJson<ApiResponse>('/api/chat', {
        message: userText,
        thread_id: threadId ?? undefined,
      });

      setThreadId(resp.thread_id);
      appendToolAccordionMessage(inferToolUses(resp.assistant_messages ?? [], resp.interrupt ?? null));
      appendAssistantPayloads(resp.assistant_messages ?? []);

      while (resp.interrupt) {
        const hasText = (resp.assistant_messages ?? []).some((p) => p?.type === 'text' && Boolean((p as any).text));
        if (!hasText) {
          setMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-interrupt-text`,
              role: 'assistant',
              kind: 'text',
              content: buildInterruptBubbleText(resp.interrupt as InterruptPayload),
            },
          ]);
        }

        setIsTyping(false);
        const resumeValue = await promptInterrupt(resp.interrupt);
        setIsTyping(true);

        resp = await postJson<ApiResponse>('/api/resume', {
          thread_id: resp.thread_id,
          resume: resumeValue,
        });

        setThreadId(resp.thread_id);
        appendToolAccordionMessage(inferToolUses(resp.assistant_messages ?? [], resp.interrupt ?? null));
        appendAssistantPayloads(resp.assistant_messages ?? []);
      }
    } finally {
      setIsTyping(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      kind: 'text',
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    const userText = input;
    setInput('');

    try {
      await runGraphTurn(userText);
    } catch (e) {
      const err = e instanceof Error ? e.message : 'Unknown error';
      setMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-err`, role: 'assistant', kind: 'text', content: `Error: ${err}` },
      ]);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const resetConversation = () => {
    setThreadId(null);
    setPendingInterrupt(null);
    interruptResolveRef.current = null;
    setExpandedTools({});
    setExpandedDetails({});
    setMessages([
      {
        id: `${Date.now()}-hello`,
        role: 'assistant',
        kind: 'text',
        content: 'Hello! I\'m here to help. What would you like to know?',
      },
    ]);
  };

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <img src={logo} alt="Langchain" className="w-6 h-6" />
          <span className="text-gray-900">Langchain Music Store</span>
        </div>
        <button
          onClick={resetConversation}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          title="New chat"
        >
          <Menu className="w-5 h-5 text-gray-600" strokeWidth={1.5} />
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="space-y-6">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {message.role === 'assistant' && (
                <div className="flex-shrink-0 w-8 h-8 rounded-full border border-gray-300 flex items-center justify-center bg-white">
                  <Music className="w-4 h-4 text-teal-700" strokeWidth={1.5} />
                </div>
              )}
              <div className="max-w-[80%] space-y-2">
                {message.kind === 'tools' && message.role === 'assistant' && message.tools?.length ? (
                  <div className="space-y-2">
                    {message.tools.map((tool) => (
                      <div key={tool.id} className="border border-emerald-200 rounded-lg overflow-hidden bg-white">
                        <button
                          onClick={() => toggleTool(tool.id)}
                          className="w-full flex items-center justify-between px-4 py-3 bg-emerald-50 hover:bg-emerald-100 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <Wrench className="w-4 h-4 text-emerald-700" strokeWidth={1.5} />
                            <span className="text-emerald-900">{tool.name}</span>
                          </div>
                          <ChevronDown
                            className={`w-4 h-4 text-emerald-700 transition-transform ${
                              expandedTools[tool.id] ? 'rotate-180' : ''
                            }`}
                            strokeWidth={1.5}
                          />
                        </button>
                        {expandedTools[tool.id] && (
                          <div className="px-4 py-3 border-t border-emerald-200 bg-white">
                            <div className="space-y-2">
                              <div>
                                <p className="text-xs text-emerald-700 mb-1">Input:</p>
                                <pre className="text-xs text-gray-700 bg-gray-50 p-2 rounded overflow-x-auto">
                                  {JSON.stringify(tool.input, null, 2)}
                                </pre>
                              </div>
                              {tool.output && (
                                <div>
                                  <p className="text-xs text-emerald-700 mb-1">Output:</p>
                                  <pre className="text-xs text-gray-700 bg-gray-50 p-2 rounded overflow-x-auto">
                                    {tool.output}
                                  </pre>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}

                {message.kind === 'text' && (
                  <div
                    className={`rounded-lg px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-teal-700 text-white'
                        : 'bg-gray-100 text-gray-900'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  </div>
                )}

                {message.kind === 'embed' && message.role === 'assistant' && (
                  <div className="border border-emerald-200 rounded-lg overflow-hidden bg-white">
                    <button
                      onClick={() => toggleDetails(message.id)}
                      className="w-full flex items-center justify-between px-4 py-3 bg-emerald-50 hover:bg-emerald-100 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <Music className="w-4 h-4 text-emerald-700" strokeWidth={1.5} />
                        <span className="text-emerald-900">
                          {(message.payload as any)?.provider ? `${(message.payload as any).provider} embed` : 'Embedded media'}
                        </span>
                      </div>
                      <ChevronDown
                        className={`w-4 h-4 text-emerald-700 transition-transform ${
                          expandedDetails[message.id] ? 'rotate-180' : ''
                        }`}
                        strokeWidth={1.5}
                      />
                    </button>
                    <div className="px-4 py-3 border-t border-emerald-200 bg-white space-y-3">
                      {(() => {
                        const p: any = message.payload ?? {};
                        const provider = String(p.provider ?? '').toLowerCase();
                        const videoId = p.video_id ? String(p.video_id) : '';
                        if (provider === 'youtube' && videoId) {
                          return (
                            <div className="space-y-2">
                              <div className="relative w-full overflow-hidden rounded-md border border-gray-200" style={{ paddingTop: '56.25%' }}>
                                <iframe
                                  className="absolute inset-0 h-full w-full"
                                  src={`https://www.youtube.com/embed/${videoId}`}
                                  title="YouTube player"
                                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                  allowFullScreen
                                />
                              </div>
                              {Boolean(p.url) && (
                                <a className="text-sm text-teal-700 underline" href={p.url} target="_blank" rel="noreferrer">
                                  Open on YouTube
                                </a>
                              )}
                            </div>
                          );
                        }
                        return Boolean(p.url) ? (
                          <a className="text-sm text-teal-700 underline" href={p.url} target="_blank" rel="noreferrer">
                            Open link
                          </a>
                        ) : null;
                      })()}

                      {expandedDetails[message.id] && (
                        <pre className="text-xs text-gray-700 bg-gray-50 p-2 rounded overflow-x-auto">
                          {JSON.stringify(message.payload, null, 2)}
                        </pre>
                      )}
                    </div>
                  </div>
                )}

                {message.kind === 'invoice' && message.role === 'assistant' && (
                  <div className="border border-gray-200 rounded-lg bg-white p-4">
                    <div className="flex items-center justify-between">
                      <div className="text-gray-900">
                        Receipt{' '}
                        {(message.payload as any)?.invoice_id !== undefined
                          ? `#${(message.payload as any).invoice_id}`
                          : ''}
                      </div>
                      <button
                        onClick={() => toggleDetails(message.id)}
                        className="text-sm text-teal-700 hover:underline"
                      >
                        {expandedDetails[message.id] ? 'Hide' : 'Details'}
                      </button>
                    </div>

                    {Array.isArray((message.payload as any)?.lines) && (
                      <div className="mt-3 space-y-1 text-sm text-gray-700">
                        {(message.payload as any).lines.map((l: any, idx: number) => (
                          <div key={idx} className="flex justify-between gap-4">
                            <div className="truncate">
                              {l?.name ?? 'Item'} x{l?.qty ?? 1}
                            </div>
                            <div>${Number(l?.unit_price ?? 0).toFixed(2)}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="mt-3 flex justify-between text-gray-900">
                      <div>Total</div>
                      <div>${Number((message.payload as any)?.total ?? 0).toFixed(2)}</div>
                    </div>

                    {Boolean((message.payload as any)?.transaction_id) && (
                      <div className="mt-2 text-sm text-gray-600">
                        Transaction: {(message.payload as any).transaction_id}
                      </div>
                    )}

                    {expandedDetails[message.id] && (
                      <pre className="mt-3 text-xs text-gray-700 bg-gray-50 p-2 rounded overflow-x-auto">
                        {JSON.stringify(message.payload, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </div>
              {message.role === 'user' && (
                <div className="flex-shrink-0 w-8 h-8 rounded-full border border-gray-300 flex items-center justify-center bg-white">
                  <User className="w-4 h-4 text-gray-900" strokeWidth={1.5} />
                </div>
              )}
            </div>
          ))}

          {isTyping && (
            <div className="flex justify-start gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full border border-gray-300 flex items-center justify-center bg-white">
                <Music className="w-4 h-4 text-teal-700" strokeWidth={1.5} />
              </div>
              <div className="flex items-center gap-2">
                {(() => {
                  const IconComponent = loadingIcons[loadingMessageIndex];
                  return <IconComponent className="w-5 h-5 text-teal-700 animate-pulse" strokeWidth={1.5} />;
                })()}
                <p className="text-gray-500">{loadingMessages[loadingMessageIndex]}</p>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="relative flex items-end gap-3 bg-gray-50 rounded-xl border border-gray-200 focus-within:border-gray-300 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="Send a message..."
              rows={1}
              className="flex-1 bg-transparent px-4 py-3 resize-none outline-none placeholder:text-gray-400"
              style={{ minHeight: '52px', maxHeight: '200px' }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isTyping || Boolean(pendingInterrupt)}
              className="m-2 p-2 rounded-lg bg-white border border-teal-700 text-teal-700 hover:bg-teal-50 disabled:bg-gray-100 disabled:border-gray-300 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              <ArrowUp className="w-5 h-5 rotate-90" strokeWidth={1.5} />
            </button>
          </div>
          <p className="text-center text-gray-400 mt-3 text-sm">
            Press Enter to send. Click the menu icon to start a new chat.
          </p>
        </div>
      </div>
      {renderInterruptModal()}
    </div>
  );
}