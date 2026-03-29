import { useState, useEffect, useRef, useCallback } from 'react';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  isStreaming?: boolean;
}

export interface ConfirmRequestPayload {
  requestId: string;
  content: string;
  timeout?: number;
}

export function useMeetYou(baseUrl: string = 'http://127.0.0.1:8000') {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string>(`desktop-${Math.random().toString(36).substring(2, 9)}`);
  const [sourceId] = useState('desktop-app');
  const [connected, setConnected] = useState(false);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequestPayload | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  const wsUrl = baseUrl.replace(/^http/, 'ws');

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    // Connect WebSocket
    const url = `${wsUrl}/ws?session_id=${sessionId}&source_id=${sourceId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      console.log('MeetYou WS Connected');
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.schema !== 'meetyou.ws.v1') return;

        if (data.kind === 'connection' && data.connection?.session_id) {
          // Update actual session ID if server assigns a specific one
          setSessionId(data.connection.session_id);
        }

        if (data.kind === 'event') {
          const evt = data.event;
          const stream = data.stream;
          const confirm = data.confirm;

          if (evt.type === 'confirm_request') {
            setConfirmRequest({
              requestId: confirm?.request_id,
              content: evt.content,
              timeout: confirm?.timeout
            });
            // Don't render confirm to message list, handle via modal
            return;
          }

          if (evt.type === 'message' || evt.type === 'status') {
             // Handle Streaming
             if (stream) {
               handleStream(stream.id, stream.phase, evt.content, evt.role);
             } else {
               // Non-streaming single message
               setMessages(prev => [...prev, {
                 id: evt.event_id || Date.now().toString(),
                 role: evt.role || 'assistant',
                 content: evt.content,
                 isStreaming: false
               }]);
             }
          }
        }
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto reconnect
      reconnectTimeoutRef.current = setTimeout(connectWs, 3000);
    };

    ws.onerror = (err) => {
      console.error('WS Error:', err);
    };
  }, [sessionId, sourceId, wsUrl]);

  useEffect(() => {
    connectWs();
    return () => {
      clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, [connectWs]);

  const handleStream = (streamId: string, phase: string, content: string, role: string) => {
    setMessages(prev => {
      const idx = prev.findIndex(m => m.id === streamId);
      const mArray = [...prev];

      if (phase === 'start') {
        if (idx === -1) {
          mArray.push({ id: streamId, role: role as any, content: content || '', isStreaming: true });
        }
      } else if (phase === 'chunk') {
        if (idx !== -1) {
          mArray[idx].content += (content || '');
          mArray[idx].isStreaming = true;
        } else {
          mArray.push({ id: streamId, role: role as any, content: content || '', isStreaming: true });
        }
      } else if (phase === 'end' || phase === 'error') {
        if (idx !== -1) {
          mArray[idx].content += (content || '');
          mArray[idx].isStreaming = false;
        }
      }
      return mArray;
    });
  };

  const sendMessage = async (text: string) => {
    // Optimistic UI for User message
    const userMsgId = 'user-' + Date.now().toString();
    setMessages(prev => [...prev, { id: userMsgId, role: 'user', content: text, isStreaming: false }]);

    try {
      const res = await fetch(`${baseUrl}/inputs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          session_id: sessionId,
          source_id: sourceId,
          role: 'user'
        })
      });
      const data = await res.json();
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
      }
    } catch (err) {
      console.error('Failed to send message via HTTP:', err);
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'system', content: '连接后端失败，请重试' }]);
    }
  };

  const sendConfirmResponse = (requestId: string, accepted: boolean) => {
    // "confirm_response" is sent via WS according to docs
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'confirm_response',
        request_id: requestId,
        accepted,
        metadata: { from: 'confirm-dialog' }
      }));
    }
    setConfirmRequest(null);
  };

  return {
    messages,
    sendMessage,
    connected,
    confirmRequest,
    sendConfirmResponse,
    baseUrl
  };
}
