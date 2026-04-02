import { useCallback, useEffect, useRef, useState } from 'react';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoning?: string;
  isStreaming?: boolean;
}

export interface ConfirmRequestPayload {
  requestId: string;
  content: string;
  timeout?: number;
}

export function useMeetYou(baseUrl: string = 'http://127.0.0.1:8000') {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string>(
    `desktop-${Math.random().toString(36).substring(2, 9)}`,
  );
  const [sourceId] = useState('desktop-app');
  const [connected, setConnected] = useState(false);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequestPayload | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const seenEventIdsRef = useRef<Set<string>>(new Set());
  const seenEventOrderRef = useRef<string[]>([]);

  const wsUrl = baseUrl.replace(/^http/, 'ws');

  const rememberEventId = useCallback((eventId?: string) => {
    if (!eventId) return true;
    if (seenEventIdsRef.current.has(eventId)) return false;

    seenEventIdsRef.current.add(eventId);
    seenEventOrderRef.current.push(eventId);

    if (seenEventOrderRef.current.length > 2000) {
      const oldest = seenEventOrderRef.current.shift();
      if (oldest) {
        seenEventIdsRef.current.delete(oldest);
      }
    }

    return true;
  }, []);

  const handleStream = useCallback(
    (
      streamId: string,
      phase: string,
      content: string,
      role: string,
      channel: string = 'answer',
    ) => {
      setMessages((prev) => {
        const idx = prev.findIndex((message) => message.id === streamId);
        const next = [...prev];

        if (phase === 'start') {
          if (idx === -1) {
            next.push({
              id: streamId,
              role: role as Message['role'],
              content: channel === 'answer' ? content || '' : '',
              reasoning: channel === 'reasoning' ? content || '' : '',
              isStreaming: true,
            });
          }
          return next;
        }

        if (phase === 'chunk') {
          if (idx !== -1) {
            const current = next[idx];
            const updated: Message = {
              ...current,
              content: current.content,
              reasoning: current.reasoning,
              isStreaming: true,
            };
            if (channel === 'reasoning') {
              updated.reasoning = (current.reasoning || '') + (content || '');
            } else {
              updated.content = (current.content || '') + (content || '');
            }
            next[idx] = updated;
            return next;
          }

          next.push({
            id: streamId,
            role: role as Message['role'],
            content: channel === 'answer' ? content || '' : '',
            reasoning: channel === 'reasoning' ? content || '' : '',
            isStreaming: true,
          });
          return next;
        }

        if (phase === 'end' || phase === 'error') {
          if (idx !== -1) {
            const current = next[idx];
            const updated: Message = {
              ...current,
              content: current.content,
              reasoning: current.reasoning,
              isStreaming: false,
            };
            if (channel === 'reasoning') {
              updated.reasoning = (current.reasoning || '') + (content || '');
            } else {
              updated.content = (current.content || '') + (content || '');
            }
            next[idx] = updated;
          }
        }

        return next;
      });
    },
    [],
  );

  const connectWs = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    clearTimeout(reconnectTimeoutRef.current);

    const url = `${wsUrl}/ws?session_id=${sessionId}&source_id=${sourceId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) {
        ws.close();
        return;
      }
      setConnected(true);
      console.log('MeetYou WS Connected');
    };

    ws.onmessage = (e) => {
      if (wsRef.current !== ws) return;

      try {
        const data = JSON.parse(e.data);
        if (data.schema !== 'meetyou.ws.v1') return;

        if (data.kind === 'connection' && data.connection?.session_id) {
          if (data.connection.session_id !== sessionId) {
            setSessionId(data.connection.session_id);
          }
          return;
        }

        if (data.kind !== 'event') return;

        const evt = data.event;
        const stream = data.stream;
        const confirm = data.confirm;

        if (!rememberEventId(evt?.event_id)) return;

        if (evt.type === 'confirm_request') {
          setConfirmRequest({
            requestId: confirm?.request_id,
            content: evt.content,
            timeout: confirm?.timeout,
          });
          return;
        }

        if (evt.type === 'message' || evt.type === 'status' || evt.type === 'reasoning') {
          if (stream) {
            handleStream(stream.id, stream.phase, evt.content, evt.role, stream.channel);
            return;
          }

          setMessages((prev) => [
            ...prev,
            {
              id: evt.event_id || Date.now().toString(),
              role: evt.role || 'assistant',
              content: evt.type === 'reasoning' ? '' : evt.content,
              reasoning: evt.type === 'reasoning' ? evt.content : '',
              isStreaming: false,
            },
          ]);
        }
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;

      wsRef.current = null;
      setConnected(false);
      reconnectTimeoutRef.current = setTimeout(() => {
        if (!wsRef.current) {
          connectWs();
        }
      }, 3000);
    };

    ws.onerror = (err) => {
      if (wsRef.current !== ws) return;
      console.error('WS Error:', err);
    };
  }, [handleStream, rememberEventId, sessionId, sourceId, wsUrl]);

  useEffect(() => {
    connectWs();
    return () => {
      clearTimeout(reconnectTimeoutRef.current);
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [connectWs]);

  const sendMessage = async (text: string) => {
    const userMsgId = `user-${Date.now().toString()}`;
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: text, isStreaming: false },
    ]);

    try {
      const res = await fetch(`${baseUrl}/inputs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          session_id: sessionId,
          source_id: sourceId,
          role: 'user',
        }),
      });
      const data = await res.json();
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
      }
    } catch (err) {
      console.error('Failed to send message via HTTP:', err);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: 'system',
          content: '连接后端失败，请重试',
          isStreaming: false,
        },
      ]);
    }
  };

  const sendConfirmResponse = (requestId: string, accepted: boolean) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          action: 'confirm_response',
          request_id: requestId,
          accepted,
          metadata: { from: 'confirm-dialog' },
        }),
      );
    }
    setConfirmRequest(null);
  };

  return {
    messages,
    sendMessage,
    connected,
    confirmRequest,
    sendConfirmResponse,
    baseUrl,
  };
}
