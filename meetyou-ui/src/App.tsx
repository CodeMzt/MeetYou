import React, { useState, useEffect, useRef } from 'react';
import { Settings, Pin, PinOff, Send, X, Minus, ShieldAlert } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useMeetYou } from './hooks/useMeetYou';

export default function App() {
  const { messages, sendMessage, connected, confirmRequest, sendConfirmResponse } = useMeetYou('http://127.0.0.1:8000');
  
  const [inputVal, setInputVal] = useState('');
  const [isPinned, setIsPinned] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  
  // Configurable states
  const [opacity, setOpacity] = useState(0.95);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, confirmRequest]);

  // IPC handlers for window controls
  const handleClose = () => window.ipcRenderer?.send('window-close');
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize');
  
  const togglePin = () => {
    const next = !isPinned;
    setIsPinned(next);
    window.ipcRenderer?.send('window-toggle-top', next);
  };

  const handleSend = () => {
    if (!inputVal.trim() || !connected) return;
    sendMessage(inputVal);
    setInputVal('');
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="app-container" style={{ opacity }}>
      {/* Titlebar */}
      <div className="titlebar">
        <div className="titlebar-title">
          MeetYou
          <span className="status-dot" style={{ background: connected ? '#34c759' : '#ff3b30' }} title={connected ? '已连接' : '未连接'} />
        </div>
        <div className="actions">
          <button 
            className={`icon-btn ${isPinned ? 'active' : ''}`} 
            onClick={togglePin} 
            title={isPinned ? '取消置顶' : '置顶窗口'}
          >
            {isPinned ? <Pin size={16} /> : <PinOff size={16} />}
          </button>
          <button className="icon-btn" onClick={() => setShowSettings(!showSettings)} title="设置">
            <Settings size={16} />
          </button>
          <button className="icon-btn" onClick={handleMinimize} title="最小化">
            <Minus size={16} />
          </button>
          <button className="icon-btn" onClick={handleClose} title="关闭退出">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      <AnimatePresence>
        {showSettings && (
          <motion.div 
            className="settings-panel"
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.2 }}
          >
            <div className="setting-item">
              <label>窗口不透明度</label>
              <input 
                type="range" 
                min="0.3" max="1" step="0.05" 
                value={opacity} 
                onChange={e => setOpacity(Number(e.target.value))}
              />
            </div>
            <div className="setting-item">
              <label>连接状态</label>
              <span>{connected ? '已连接后端' : '断开'}</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Message List */}
      <div className="content-area">
        <AnimatePresence initial={false}>
          {messages.length === 0 && (
            <motion.div className="empty-state" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                {connected ? '随时可以开始对话' : '等待后端服务启动中...'}
              </div>
            </motion.div>
          )}

          {messages.map((msg, index) => (
            <motion.div 
              key={msg.id + index}
              className={`message ${msg.role}`}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 400, damping: 25 }}
            >
              <div className="message-inner">
                {msg.content}
                {msg.isStreaming && <span className="cursor-blink">▍</span>}
              </div>
            </motion.div>
          ))}

          {/* Confirm Request Modal / Bubble */}
          {confirmRequest && (
            <motion.div 
              className="confirm-modal"
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
            >
              <div className="confirm-header">
                <ShieldAlert size={16} color="#ff3b30" />
                <span>危险操作确认</span>
              </div>
              <div className="confirm-body">
                {confirmRequest.content}
              </div>
              <div className="confirm-actions">
                <button className="btn-reject" onClick={() => sendConfirmResponse(confirmRequest.requestId, false)}>拒绝</button>
                <button className="btn-accept" onClick={() => sendConfirmResponse(confirmRequest.requestId, true)}>允许</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="input-container">
        <input 
          className="chat-input"
          placeholder={connected ? "问点什么..." : "连接中..."}
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={!connected || !!confirmRequest}
          autoFocus
        />
        <button 
          className="send-btn" 
          onClick={handleSend}
          disabled={!inputVal.trim() || !connected || !!confirmRequest}
        >
          <Send size={16} />
        </button>
      </div>

      <style>{`
        .cursor-blink {
          display: inline-block;
          width: 8px;
          animation: blink 1s step-end infinite;
          margin-left: 2px;
          color: var(--accent-color);
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
        }
        .confirm-modal {
          margin-top: 10px;
          background: rgba(255, 59, 48, 0.1);
          border: 1px solid rgba(255, 59, 48, 0.3);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
          border-radius: var(--radius-md);
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .confirm-header {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #ff3b30;
          font-weight: 600;
          font-size: 14px;
        }
        .confirm-body {
          font-size: 13px;
          line-height: 1.5;
          color: var(--text-primary);
          word-break: break-all;
        }
        .confirm-actions {
          display: flex;
          gap: 10px;
          justify-content: flex-end;
          margin-top: 4px;
        }
        .btn-reject, .btn-accept {
          border: none;
          padding: 6px 14px;
          border-radius: 12px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: transform 0.1s;
        }
        .btn-reject:active, .btn-accept:active {
          transform: scale(0.95);
        }
        .btn-reject {
          background: rgba(128,128,128,0.2);
          color: var(--text-primary);
        }
        .btn-reject:hover { background: rgba(128,128,128,0.3); }
        .btn-accept {
          background: #ff3b30;
          color: white;
        }
        .btn-accept:hover { background: #d70015; }
      `}</style>
    </div>
  );
}
