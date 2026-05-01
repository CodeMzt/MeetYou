import { useCallback, useEffect, useRef, useState } from 'react'
import { createEndpointWsUrl } from '../../runtimeApi'
import { fetchWithAuth } from '../../apiClient'
import { parseHealthEnvelope } from '../../protocolClient'
import type { EndpointContext } from './useEndpointContext'

const ENDPOINT_WS_SCHEMA = 'meetyou.endpoint.ws.v4'
const ENDPOINT_WS_VERSION = 4
const ENDPOINT_PROTOCOL_FEATURES = [
  'tool_snapshot_optional',
  'connection_prompt',
  'feature_negotiation',
  'heartbeat_interval_negotiation',
  'hello_reject_reason',
]

function endpointSafeId(value: string, fallback: string): string {
  const normalized = String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return normalized || fallback
}

function messageId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function buildUiEndpointId(endpointContext: EndpointContext): string {
  return `desktop.${endpointSafeId(endpointContext.endpointId, 'desktop-app')}.ui`
}

export function buildEndpointHandshakeFrames(endpointContext: EndpointContext): Record<string, unknown>[] {
  const endpointId = buildUiEndpointId(endpointContext)
  const workspaceId = endpointContext.workspace.workspace_id
  return [
    {
      schema: ENDPOINT_WS_SCHEMA,
      type: 'endpoint.hello',
      message_id: messageId('ui-hello'),
      payload: {
        connection_id: `conn-${endpointSafeId(endpointContext.session.session_id, 'ui-session')}-${Date.now()}`,
        provider: {
          provider_type: 'desktop',
          provider_id: endpointSafeId(endpointContext.endpointId, 'desktop-app'),
          display_name: '桌面应用',
          transport_profile: 'desktop_ui_bridge',
          supports_markdown: true,
        },
        protocol: {
          schema: ENDPOINT_WS_SCHEMA,
          version: ENDPOINT_WS_VERSION,
          supported_schemas: [ENDPOINT_WS_SCHEMA],
          supported_versions: [ENDPOINT_WS_VERSION],
          features: ENDPOINT_PROTOCOL_FEATURES,
          required_features: [],
        },
        supports_markdown: true,
        endpoints: [
          {
            endpoint_id: endpointId,
            endpoint_type: 'desktop_ui',
            roles: ['input', 'output'],
            workspace_ids: workspaceId ? [workspaceId] : [],
            supports_markdown: true,
          },
        ],
      },
    },
    {
      schema: ENDPOINT_WS_SCHEMA,
      type: 'subscription.start',
      endpoint_id: endpointId,
      message_id: messageId('ui-subscribe'),
      payload: {
        subscription_id: `sub-${endpointSafeId(endpointContext.threadId, 'thread')}`,
        target_type: 'thread',
        target_id: endpointContext.threadId,
        last_seen_event_seq: 0,
      },
    },
  ]
}

export function useMeetYouSocket(
  baseUrl: string,
  endpointContext: EndpointContext | null,
  applyEndpointWsUpdate: (rawPayload: unknown) => void,
  dispatchTransport: any
) {
  const endpointWsRef = useRef<WebSocket | null>(null)
  const endpointWsContextKeyRef = useRef('')
  const endpointReconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const endpointReconnectAttemptRef = useRef(0)
  const [endpointConnectionState, setEndpointConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetchWithAuth(`${baseUrl}/desktop/health`)
      if (!response.ok) {
        return
      }
      const health = parseHealthEnvelope(await response.json())
      if (!health) {
        return
      }
      dispatchTransport({ type: 'health', health })
    } catch (error) {
      console.error('刷新健康状态失败:', error)
    }
  }, [baseUrl, dispatchTransport])

  const sendEndpointWsCommand = useCallback((payload: Record<string, unknown>) => {
    const ws = endpointWsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const connectEndpointWs = useCallback(() => {
    if (!endpointContext?.threadId) {
      return
    }
    const contextKey = `${endpointContext.threadId}:${endpointContext.session.session_id}`
    const currentWs = endpointWsRef.current
    if (
      currentWs &&
      endpointWsContextKeyRef.current !== contextKey &&
      (currentWs.readyState === WebSocket.OPEN || currentWs.readyState === WebSocket.CONNECTING)
    ) {
      endpointWsRef.current = null
      endpointWsContextKeyRef.current = ''
      currentWs.close()
    }
    if (
      endpointWsContextKeyRef.current === contextKey &&
      (endpointWsRef.current?.readyState === WebSocket.OPEN ||
        endpointWsRef.current?.readyState === WebSocket.CONNECTING)
    ) {
      return
    }

    clearTimeout(endpointReconnectTimeoutRef.current)
    setEndpointConnectionState('connecting')

    void (async () => {
      const url = await createEndpointWsUrl(baseUrl, endpointContext.threadId, {
        endpointId: endpointContext.endpointId,
        sessionId: endpointContext.session.session_id,
        workspaceId: endpointContext.workspace.workspace_id,
        endpointType: 'electron',
        displayName: '桌面应用',
      })
      if (
        endpointWsContextKeyRef.current === contextKey &&
        (endpointWsRef.current?.readyState === WebSocket.OPEN || endpointWsRef.current?.readyState === WebSocket.CONNECTING)
      ) {
        return
      }
      if (endpointWsRef.current?.readyState === WebSocket.OPEN || endpointWsRef.current?.readyState === WebSocket.CONNECTING) {
        const previousWs = endpointWsRef.current
        endpointWsRef.current = null
        endpointWsContextKeyRef.current = ''
        previousWs.close()
      }
      const ws = new WebSocket(url)
      endpointWsRef.current = ws
      endpointWsContextKeyRef.current = contextKey
      let helloAccepted = false
      let subscriptionAccepted = false
      let connectionReady = false

      const markReadyIfComplete = () => {
        if (connectionReady || !helloAccepted || !subscriptionAccepted) {
          return
        }
        connectionReady = true
        endpointReconnectAttemptRef.current = 0
        setEndpointConnectionState('connected')
        dispatchTransport({ type: 'set_connection_state', connectionState: 'connected' })
        void refreshHealth()
      }

      ws.onmessage = (event) => {
        if (endpointWsRef.current !== ws || endpointWsContextKeyRef.current !== contextKey) {
          return
        }

        try {
          const payload = JSON.parse(event.data)
          if (payload?.schema === ENDPOINT_WS_SCHEMA) {
            if (payload.type === 'endpoint.hello.ack') {
              const body = payload.payload && typeof payload.payload === 'object' ? payload.payload : {}
              if (body.accepted === false) {
                setEndpointConnectionState('disconnected')
                dispatchTransport({
                  type: 'error',
                  error: {
                    code: 'endpoint_hello_rejected',
                    category: 'dependency',
                    message: String(body.reject_reason?.message || 'Endpoint handshake rejected'),
                    retryable: false,
                    details: body.reject_reason && typeof body.reject_reason === 'object' ? body.reject_reason : {},
                    occurred_at: '',
                  },
                })
                ws.close()
                return
              }
              helloAccepted = true
              markReadyIfComplete()
              return
            }
            if (payload.type === 'subscription.ack') {
              const body = payload.payload && typeof payload.payload === 'object' ? payload.payload : {}
              if (body.active !== false) {
                subscriptionAccepted = true
                markReadyIfComplete()
              }
              return
            }
          }
          applyEndpointWsUpdate(payload)
        } catch (error) {
          console.error('解析端点实时消息失败:', error)
        }
      }

      ws.onopen = () => {
        if (endpointWsRef.current !== ws || endpointWsContextKeyRef.current !== contextKey) {
          ws.close()
          return
        }
        for (const frame of buildEndpointHandshakeFrames(endpointContext)) {
          ws.send(JSON.stringify(frame))
        }
      }

      ws.onclose = () => {
        if (endpointWsRef.current !== ws) {
          return
        }
        endpointWsRef.current = null
        if (endpointWsContextKeyRef.current === contextKey) {
          endpointWsContextKeyRef.current = ''
        }
        setEndpointConnectionState('disconnected')
        dispatchTransport({ type: 'set_connection_state', connectionState: 'disconnected' })
        const reconnectAttempt = endpointReconnectAttemptRef.current
        endpointReconnectAttemptRef.current = Math.min(reconnectAttempt + 1, 6)
        const baseDelayMs = Math.min(30000, 1000 * 2 ** reconnectAttempt)
        const jitterMs = Math.floor(Math.random() * 500)
        endpointReconnectTimeoutRef.current = setTimeout(() => {
          if (!endpointWsRef.current) {
            connectEndpointWs()
          }
        }, baseDelayMs + jitterMs)
      }

      ws.onerror = (error) => {
        if (endpointWsRef.current !== ws || endpointWsContextKeyRef.current !== contextKey) {
          return
        }
        console.error('端点实时连接错误:', error)
      }
    })()
  }, [applyEndpointWsUpdate, baseUrl, endpointContext, dispatchTransport, refreshHealth])

  useEffect(() => {
    connectEndpointWs()
  }, [connectEndpointWs])

  useEffect(() => {
    void refreshHealth()
    const timer = window.setInterval(() => {
      void refreshHealth()
    }, 10000)
    return () => {
      window.clearInterval(timer)
    }
  }, [refreshHealth])

  useEffect(() => {
    return () => {
      clearTimeout(endpointReconnectTimeoutRef.current)
      const endpointWs = endpointWsRef.current
      endpointWsRef.current = null
      endpointWsContextKeyRef.current = ''
      endpointWs?.close()
    }
  }, [])

  return {
    endpointConnectionState,
    setEndpointConnectionState,
    sendEndpointWsCommand,
    refreshHealth,
  }
}
