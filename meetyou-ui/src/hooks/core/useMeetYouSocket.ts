import { useCallback, useEffect, useRef, useState } from 'react'
import { createEndpointWsUrl } from '../../runtimeApi'
import { fetchWithAuth } from '../../apiClient'
import { parseHealthEnvelope } from '../../protocolClient'
import type { EndpointContext } from './useEndpointContext'

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
  const endpointReconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
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
    if (
      endpointWsRef.current?.readyState === WebSocket.OPEN ||
      endpointWsRef.current?.readyState === WebSocket.CONNECTING
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
      if (endpointWsRef.current?.readyState === WebSocket.OPEN || endpointWsRef.current?.readyState === WebSocket.CONNECTING) {
        return
      }
      const ws = new WebSocket(url)
      endpointWsRef.current = ws

      ws.onmessage = (event) => {
        if (endpointWsRef.current !== ws) {
          return
        }

        try {
          applyEndpointWsUpdate(JSON.parse(event.data))
        } catch (error) {
          console.error('解析端点实时消息失败:', error)
        }
      }

      ws.onopen = () => {
        if (endpointWsRef.current !== ws) {
          ws.close()
          return
        }
        for (const frame of buildEndpointHandshakeFrames(endpointContext)) {
          ws.send(JSON.stringify(frame))
        }
        setEndpointConnectionState('connected')
        void refreshHealth()
      }

      ws.onclose = () => {
        if (endpointWsRef.current !== ws) {
          return
        }
        endpointWsRef.current = null
        setEndpointConnectionState('disconnected')
        dispatchTransport({ type: 'set_connection_state', connectionState: 'disconnected' })
        endpointReconnectTimeoutRef.current = setTimeout(() => {
          if (!endpointWsRef.current) {
            connectEndpointWs()
          }
        }, 3000)
      }

      ws.onerror = (error) => {
        if (endpointWsRef.current !== ws) {
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
