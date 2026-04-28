import { useCallback, useEffect, useRef, useState } from 'react'
import { createClientWsUrl } from '../../clientApi'
import { fetchWithAuth } from '../../apiClient'
import { parseHealthEnvelope } from '../../protocolClient'
import type { ClientContext } from './useClientContext'

const ENDPOINT_WS_SCHEMA = 'meetyou.endpoint.ws.v4'

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

export function buildUiEndpointId(clientContext: ClientContext): string {
  return `desktop.${endpointSafeId(clientContext.clientId, 'desktop-app')}.ui`
}

export function buildEndpointHandshakeFrames(clientContext: ClientContext): Record<string, unknown>[] {
  const endpointId = buildUiEndpointId(clientContext)
  const workspaceId = clientContext.workspace.workspace_id
  return [
    {
      schema: ENDPOINT_WS_SCHEMA,
      type: 'endpoint.hello',
      message_id: messageId('ui-hello'),
      payload: {
        connection_id: `conn-${endpointSafeId(clientContext.session.session_id, 'ui-session')}-${Date.now()}`,
        provider: {
          provider_type: 'desktop',
          provider_id: endpointSafeId(clientContext.clientId, 'desktop-app'),
          display_name: '桌面应用',
          transport_profile: 'desktop_ui_bridge',
        },
        endpoints: [
          {
            endpoint_id: endpointId,
            endpoint_type: 'desktop_ui',
            roles: ['input', 'output'],
            workspace_ids: workspaceId ? [workspaceId] : [],
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
        subscription_id: `sub-${endpointSafeId(clientContext.threadId, 'thread')}`,
        target_type: 'thread',
        target_id: clientContext.threadId,
        last_seen_event_seq: 0,
      },
    },
  ]
}

export function useMeetYouSocket(
  baseUrl: string,
  clientContext: ClientContext | null,
  applyClientWsUpdate: (rawPayload: unknown) => void,
  dispatchTransport: any
) {
  const clientWsRef = useRef<WebSocket | null>(null)
  const clientReconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const [clientConnectionState, setClientConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

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

  const sendClientWsCommand = useCallback((payload: Record<string, unknown>) => {
    const ws = clientWsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const connectClientWs = useCallback(() => {
    if (!clientContext?.threadId) {
      return
    }
    if (
      clientWsRef.current?.readyState === WebSocket.OPEN ||
      clientWsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    clearTimeout(clientReconnectTimeoutRef.current)
    setClientConnectionState('connecting')

    void (async () => {
      const url = await createClientWsUrl(baseUrl, clientContext.threadId, {
        clientId: clientContext.clientId,
        sessionId: clientContext.session.session_id,
        workspaceId: clientContext.workspace.workspace_id,
        clientType: 'electron',
        displayName: '桌面应用',
      })
      if (clientWsRef.current?.readyState === WebSocket.OPEN || clientWsRef.current?.readyState === WebSocket.CONNECTING) {
        return
      }
      const ws = new WebSocket(url)
      clientWsRef.current = ws

      ws.onmessage = (event) => {
        if (clientWsRef.current !== ws) {
          return
        }

        try {
          applyClientWsUpdate(JSON.parse(event.data))
        } catch (error) {
          console.error('Client WS parse error:', error)
        }
      }

      ws.onopen = () => {
        if (clientWsRef.current !== ws) {
          ws.close()
          return
        }
        for (const frame of buildEndpointHandshakeFrames(clientContext)) {
          ws.send(JSON.stringify(frame))
        }
        setClientConnectionState('connected')
        void refreshHealth()
      }

      ws.onclose = () => {
        if (clientWsRef.current !== ws) {
          return
        }
        clientWsRef.current = null
        setClientConnectionState('disconnected')
        dispatchTransport({ type: 'set_connection_state', connectionState: 'disconnected' })
        clientReconnectTimeoutRef.current = setTimeout(() => {
          if (!clientWsRef.current) {
            connectClientWs()
          }
        }, 3000)
      }

      ws.onerror = (error) => {
        if (clientWsRef.current !== ws) {
          return
        }
        console.error('Client WS Error:', error)
      }
    })()
  }, [applyClientWsUpdate, baseUrl, clientContext, dispatchTransport, refreshHealth])

  useEffect(() => {
    connectClientWs()
  }, [connectClientWs])

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
      clearTimeout(clientReconnectTimeoutRef.current)
      const clientWs = clientWsRef.current
      clientWsRef.current = null
      clientWs?.close()
    }
  }, [])

  return {
    clientConnectionState,
    setClientConnectionState,
    sendClientWsCommand,
    refreshHealth,
  }
}
